import os
import math
import uuid
import tarfile
import hashlib
import tempfile
import unicodedata

from pathlib import Path
from asyncio import wait, Queue, Event, gather, FIRST_EXCEPTION

from concurrent.futures import ProcessPoolExecutor

from ._requires import attr
from ._requires import jinja2
from ._requires import requests

from .types import ActionType
from .utils import terminate


class ResultBase:

    def value(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


@attr.s
class Result(ResultBase):
    file = attr.ib()
    uuid = attr.ib(default=attr.Factory(lambda: uuid.uuid4().hex))

    def value(self):
        return hashlib.sha1(self.file.name.encode('utf-8')).hexdigest()

    def close(self):
        self.file.close()


@attr.s
class SimpleResult(ResultBase):
    content = attr.ib()

    def value(self):
        return self.content

    def close(self):
        pass


@attr.s
class ActionState:
    complete = attr.ib()
    result = attr.ib()
    error = attr.ib(default=None)


def download(url, file_name, destination):
    with tempfile.NamedTemporaryFile() as tmp:
        with tarfile.open(file_name, mode='w:tar') as tar:
            # downloaded = 0
            response = requests.get(url)
            response.raise_for_status()
            for chunk in response.iter_content(64 * 1024):
                tmp.write(chunk)
                # downloaded += len(chunk)
            tmp.seek(0)
            tar.addfile(tar.gettarinfo(arcname=destination, fileobj=tmp),
                        fileobj=tmp)


def bundle(action_path, file_name, destination):
    dir_path = Path(action_path).resolve()  # FIXME: raises FileNotFoundError
    assert dir_path.is_dir(), dir_path

    cur_path = Path('.').resolve()
    assert cur_path in dir_path.parents, dir_path

    rel_path = dir_path.relative_to(cur_path)

    def filter_(path_):
        # TODO: ability to exclude (.gitignore? .hgignore?)
        return True

    def _arc_path(path_):
        return os.path.join(destination, unicodedata.normalize('NFC', path_))

    with tarfile.open(file_name, mode='w:tar') as tar:
        for path, _, names in os.walk(str(rel_path)):
            if not filter_(path):
                continue

            tar.addfile(tar.gettarinfo(path, _arc_path(path)))
            for name in names:
                file_path = os.path.join(path, name)
                if not filter_(file_path):
                    continue

                with open(file_path, 'rb') as f:
                    tar.addfile(tar.gettarinfo(arcname=_arc_path(file_path),
                                               fileobj=f),
                                fileobj=f)


def iter_actions(task):
    for value in task.where.values():
        if isinstance(value, ActionType):
            yield value


def get_action_states(tasks, *, loop):
    actions = {}
    for task in tasks:
        for action in iter_actions(task):
            if action in actions:
                continue
            result = Result(tempfile.NamedTemporaryFile())
            actions[action] = ActionState(Event(loop=loop), result)
    return actions


async def wait_actions(states, *, loop):
    if states:
        await gather(*[state.complete.wait() for state in states.values()],
                     loop=loop)


class ActionDispatcher:

    def __init__(self, states, io_queue, cpu_queue):
        self.states = states
        self.io_queue = io_queue
        self.cpu_queue = cpu_queue

    @classmethod
    async def dispatch(cls, states, io_queue, cpu_queue):
        dispatcher = cls(states, io_queue, cpu_queue)
        for action in states:
            await dispatcher.visit(action)

    def visit(self, obj):
        return obj.accept(self)

    async def visit_download(self, obj):
        await self.io_queue.put((obj, self.states[obj]))

    async def visit_bundle(self, obj):
        await self.cpu_queue.put((obj, self.states[obj]))


class IOExecutor:

    def __init__(self, *, loop):
        self.loop = loop

    def visit(self, action):
        return action.accept(self)

    async def download(self, action, state):
        try:
            await self.loop.run_in_executor(
                None,
                download, action.url, state.result.file.name, state.result.uuid
            )
        except Exception as err:
            state.error = str(err)
            raise
        finally:
            state.complete.set()

    def visit_download(self, obj):
        return self.download


class CPUExecutor:

    def __init__(self, process_pool, *, loop):
        self.process_pool = process_pool
        self.loop = loop

    def visit(self, action):
        return action.accept(self)

    async def bundle(self, action, state):
        try:
            await self.loop.run_in_executor(
                self.process_pool,
                bundle, action.path, state.result.file.name, state.result.uuid
            )
        except Exception as err:
            state.error = str(err)
        finally:
            state.complete.set()

    def visit_bundle(self, obj):
        return self.bundle


async def worker(queue, executor):
    while True:
        action, state = await queue.get()
        process = executor.visit(action)
        await process(action, state)


async def pool(queue, executor, concurrency=2, *, loop):
    pending = [loop.create_task(worker(queue, executor))
               for _ in range(concurrency)]
    try:
        # fast exit on first error
        _, pending = await wait(pending, loop=loop,
                                return_when=FIRST_EXCEPTION)
    finally:
        for task in pending:
            await terminate(task, loop=loop)


def task_cmd(task, results):
    ctx = {key: value if not isinstance(value, ActionType) else results[value]
           for key, value in task.where.items()}
    t = jinja2.Template(task.run)
    return t.render(ctx)


async def _exec(client, container, cmd):
    if isinstance(cmd, str):
        cmd = ['/bin/sh', '-c', cmd]
    exec_id = await client.exec_create(container, cmd)
    output = await client.exec_start(exec_id)
    info = await client.exec_inspect(exec_id)
    exit_code = info['ExitCode']
    if exit_code:
        print(output.decode('utf-8'))  # FIXME: proper output
    return exit_code


async def build(client, layer, tasks, *, loop):
    if layer.parent:
        from_ = layer.parent.docker_image()
    else:
        from_ = layer.image.from_

    io_queue = Queue()
    io_executor = IOExecutor(loop=loop)

    process_pool = ProcessPoolExecutor()
    cpu_queue = Queue()
    cpu_executor = CPUExecutor(process_pool, loop=loop)

    states = get_action_states(tasks, loop=loop)
    submitted_states = set()

    io_pool_task = loop.create_task(pool(io_queue, io_executor, loop=loop))
    cpu_pool_task = loop.create_task(pool(cpu_queue, cpu_executor, loop=loop))

    c = await client.create_container(
        from_.name, '/bin/sh', detach=True, tty=True,
    )
    try:
        await client.start(c)
        exit_code = await _exec(client, c, ['mkdir', '/.pi'])
        if exit_code:
            return False

        await ActionDispatcher.dispatch(states, io_queue, cpu_queue)

        total = len(tasks)
        padding = math.ceil(math.log10(total + 1))

        for i, task in enumerate(tasks, 1):
            task_states = {action: states[action]
                           for action in iter_actions(task)}

            await wait_actions(task_states, loop=loop)

            errors = {action: state.error
                      for action, state in task_states.items()
                      if state.error is not None}
            if errors:
                raise Exception(repr(errors))

            task_results = {action: '/.pi/{}'.format(state.result.uuid)
                            for action, state in task_states.items()}

            for action, state in task_states.items():
                if action not in submitted_states:
                    with open(state.result.file.name, 'rb') as tar:
                        await client.put_archive(c, '/.pi', tar)
                    submitted_states.add(action)

            cmd = task_cmd(task, task_results)
            current_index = '{{:{}d}}'.format(padding).format(i)
            print('[{}/{}] {}'.format(current_index, total, cmd))
            exit_code = await _exec(client, c, cmd)
            if exit_code:
                return False

        exit_code = await _exec(client, c, ['rm', '-rf', '/.pi'])
        if exit_code:
            return False

        await client.pause(c)
        await client.commit(
            c,
            layer.image.repository,
            layer.version(),
        )
        await client.unpause(c)
        return True

    finally:
        await terminate(io_pool_task, loop=loop)
        await terminate(cpu_pool_task, loop=loop)
        process_pool.shutdown()
        for state in states.values():
            state.result.close()
        await client.remove_container(c, v=True, force=True)