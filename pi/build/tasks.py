import os
import uuid
import tarfile
import hashlib
import tempfile
import unicodedata

from pathlib import Path
from asyncio import coroutine, wait, Queue, Event, gather, FIRST_EXCEPTION

from concurrent.futures import ProcessPoolExecutor

from .._requires import attr
from .._requires import jinja2
from .._requires import requests

from ..types import Tasks, ActionType
from ..utils import terminate


@attr.s
class Task:
    run = attr.ib()
    name = attr.ib(default=None)
    where = attr.ib(default=attr.Factory(dict))


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


def compile_task(task: Task, ctx):
    t = jinja2.Template(task.run)
    return t.render(ctx)


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


@coroutine
def wait_actions(states, *, loop):
    if states:
        yield from gather(*[state.complete.wait() for state in states.values()],
                          loop=loop)


class ActionDispatcher:

    def __init__(self, states, io_queue, cpu_queue):
        self.states = states
        self.io_queue = io_queue
        self.cpu_queue = cpu_queue

    @classmethod
    @coroutine
    def dispatch(cls, states, io_queue, cpu_queue):
        dispatcher = cls(states, io_queue, cpu_queue)
        for action in states:
            yield from dispatcher.visit(action)

    def visit(self, obj):
        return obj.accept(self)

    @coroutine
    def visit_download(self, obj):
        yield from self.io_queue.put((obj, self.states[obj]))

    @coroutine
    def visit_bundle(self, obj):
        yield from self.cpu_queue.put((obj, self.states[obj]))


class IOExecutor:

    def __init__(self, *, loop):
        self.loop = loop

    def visit(self, action):
        return action.accept(self)

    @coroutine
    def download(self, action, state):
        try:
            yield from self.loop.run_in_executor(
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

    @coroutine
    def bundle(self, action, state):
        try:
            yield from self.loop.run_in_executor(
                self.process_pool,
                bundle, action.path, state.result.file.name, state.result.uuid
            )
        except Exception as err:
            state.error = str(err)
        finally:
            state.complete.set()

    def visit_bundle(self, obj):
        return self.bundle


@coroutine
def worker(queue, executor):
    while True:
        action, state = yield from queue.get()
        process = executor.visit(action)
        yield from process(action, state)


@coroutine
def pool(queue, executor, concurrency=2, *, loop):
    pending = [loop.create_task(worker(queue, executor))
               for _ in range(concurrency)]
    try:
        # fast exit on first error
        _, pending = yield from wait(pending, loop=loop,
                                     return_when=FIRST_EXCEPTION)
    finally:
        for task in pending:
            yield from terminate(task, loop=loop)


@coroutine
def run(client, task, results, *, loop):
    ctx = {key: value if not isinstance(value, ActionType) else results[value]
           for key, value in task.where.items()}
    print('run:', compile_task(task, ctx))


def _sh(client, container, cmd):
    exec_id = yield from client.exec_create(container, cmd)
    yield from client.exec_start(exec_id)


@coroutine
def build(client, layer, tasks: Tasks, *, loop):
    if layer.parent:
        from_ = layer.parent.docker_image()
    else:
        from_ = layer.image.from_

    task_items = [Task(**d) for d in tasks.items]

    io_queue = Queue()
    io_executor = IOExecutor(loop=loop)

    process_pool = ProcessPoolExecutor()
    cpu_queue = Queue()
    cpu_executor = CPUExecutor(process_pool, loop=loop)

    states = get_action_states(task_items, loop=loop)
    submitted_states = set()

    io_pool_task = loop.create_task(pool(io_queue, io_executor, loop=loop))
    cpu_pool_task = loop.create_task(pool(cpu_queue, cpu_executor, loop=loop))

    c = yield from client.create_container(
        from_.name, '/bin/sh', detach=True, tty=True,
    )
    try:
        yield from client.start(c)
        yield from _sh(client, c, ['mkdir', '/.pi'])

        yield from ActionDispatcher.dispatch(states, io_queue, cpu_queue)

        for task in task_items:
            task_states = {action: states[action]
                           for action in iter_actions(task)}

            yield from wait_actions(task_states, loop=loop)

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
                        yield from client.put_archive(c, '/.pi', tar)
                    submitted_states.add(action)

            yield from run(client, task, task_results, loop=loop)

        yield from _sh(client, c, ['rm', '-rf', '/.pi'])
        yield from client.pause(c)
        yield from client.commit(
            c,
            layer.image.repository,
            layer.version(),
        )
        yield from client.unpause(c)
        return True

    finally:
        yield from terminate(io_pool_task, loop=loop)
        yield from terminate(cpu_pool_task, loop=loop)
        process_pool.shutdown()
        for state in states.values():
            state.result.close()
        yield from client.remove_container(c, v=True, force=True)
