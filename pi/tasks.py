import io
import os
import sys
import math
import uuid
import tarfile
import logging
import hashlib
import asyncio
import tempfile
import unicodedata
from typing import Optional
from pathlib import Path
from asyncio import wait, Queue, Event, gather, FIRST_EXCEPTION, WriteTransport
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from concurrent.futures import ProcessPoolExecutor

from ._requires import jinja2

from .run import StdIOProtocol
from .http import connect_tcp
from .types import ActionType
from .utils import terminate
from .images import docker_image, image_versions


log = logging.getLogger(__name__)


@dataclass
class Result:
    file: tempfile.NamedTemporaryFile
    uuid: str = field(default_factory=lambda: uuid.uuid4().hex)

    def value(self):
        return hashlib.sha1(self.file.name.encode('utf-8')).hexdigest()

    def close(self):
        self.file.close()


@dataclass
class ActionState:
    complete: Event
    result: Result
    error: Optional[str] = None


async def _download(url, output, *, _max_redirects=5):
    redirects = 0
    initial_url = url
    initial_secure = None
    while redirects < _max_redirects:
        url_parts = urlsplit(url)

        secure = True if url_parts.scheme == 'https' else False
        if redirects == 0:
            initial_secure = secure
        if initial_secure is True and secure is False:
            raise Exception(f'Redirect to insecure url: {url}')

        host, _, port = url_parts.netloc.partition(':')
        if not port:
            port = 443 if url_parts.scheme == 'https' else 80
        else:
            port = int(port)
        path = url_parts.path
        if url_parts.query:
            path += '?' + url_parts.query

        async with connect_tcp(host, port, secure=secure) as stream:
            await stream.send_request('GET', path, [
                ('host', url_parts.netloc),
            ])
            response = await stream.recv_response()
            if response.status_code in {301, 302}:
                url = response.headers[b'location'].decode('ascii')
                redirects += 1
                continue
            elif response.status_code != 200:
                response.error()
            async for chunk in stream.recv_data_chunked():
                output.write(chunk)
            break
    else:
        raise Exception(f'More than {_max_redirects} redirects: {initial_url}')


async def download(url, file_name, destination):
    with tempfile.NamedTemporaryFile() as tmp:
        with tarfile.open(file_name, mode='w:tar') as tar:
            await _download(url, tmp)
            tmp.seek(0)
            tar.addfile(tar.gettarinfo(arcname=destination, fileobj=tmp),
                        fileobj=tmp)


def file_(path, file_name, destination):
    file_path = Path(path).resolve()
    assert file_path.is_file(), file_path

    cur_path = Path('.').resolve()
    assert cur_path in file_path.parents, file_path

    with open(str(file_path), 'rb') as f:
        with tarfile.open(file_name, mode='w:tar') as tar:
            tar.addfile(tar.gettarinfo(arcname=destination, fileobj=f),
                        fileobj=f)


def bundle(action_path, file_name, destination):
    dir_path = Path(action_path).resolve()  # FIXME: raises FileNotFoundError
    assert dir_path.is_dir(), dir_path

    cur_path = Path('.').resolve()
    assert cur_path in dir_path.parents, dir_path

    def _arc_path(path_):
        return os.path.join(destination, unicodedata.normalize('NFC', path_))

    with tarfile.open(file_name, mode='w:tar') as tar:
        for abs_path, _, names in os.walk(str(dir_path)):
            rel_path = Path(abs_path).relative_to(dir_path)
            if rel_path != Path('.'):
                tar.addfile(tar.gettarinfo(abs_path, _arc_path(str(rel_path))))

            for name in names:
                file_abs_path = os.path.join(abs_path, name)
                file_rel_path = str(rel_path.joinpath(name))
                with open(file_abs_path, 'rb') as f:
                    tar.addfile(
                        tar.gettarinfo(arcname=_arc_path(str(file_rel_path)),
                                       fileobj=f),
                        fileobj=f,
                    )


def iter_actions(task):
    for value in task.where.values():
        if isinstance(value, ActionType):
            yield value


def get_action_states(tasks):
    actions = {}
    for task in tasks:
        for action in iter_actions(task):
            if action in actions:
                continue
            result = Result(tempfile.NamedTemporaryFile())
            actions[action] = ActionState(Event(), result)
    return actions


async def wait_actions(states):
    if states:
        await gather(*[state.complete.wait() for state in states.values()])


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

    async def visit_file(self, obj):
        await self.cpu_queue.put((obj, self.states[obj]))

    async def visit_bundle(self, obj):
        await self.cpu_queue.put((obj, self.states[obj]))


class IOExecutor:

    def visit(self, action):
        return action.accept(self)

    async def download(self, action, state):
        try:
            await download(
                action.url,
                state.result.file.name,
                state.result.uuid,
            )
        except Exception as err:
            log.debug('Download action failed: %r', action, exc_info=True)
            state.error = str(err)
            raise
        finally:
            state.complete.set()

    def visit_download(self, obj):
        return self.download


class CPUExecutor:

    def __init__(self, process_pool):
        self.process_pool = process_pool

    def visit(self, action):
        return action.accept(self)

    async def file(self, action, state):
        try:
            await asyncio.get_running_loop().run_in_executor(
                self.process_pool,
                file_, action.path, state.result.file.name, state.result.uuid
            )
        except Exception as err:
            log.debug('File action failed: %r', action, exc_info=True)
            state.error = str(err)
        finally:
            state.complete.set()

    async def bundle(self, action, state):
        try:
            await asyncio.get_running_loop().run_in_executor(
                self.process_pool,
                bundle, action.path, state.result.file.name, state.result.uuid
            )
        except Exception as err:
            log.debug('Bundle action failed: %r', action, exc_info=True)
            state.error = str(err)
        finally:
            state.complete.set()

    def visit_file(self, obj):
        return self.file

    def visit_bundle(self, obj):
        return self.bundle


async def worker(queue, executor):
    while True:
        action, state = await queue.get()
        process = executor.visit(action)
        await process(action, state)


async def pool(queue, executor, concurrency=2):
    loop = asyncio.get_running_loop()
    pending = [loop.create_task(worker(queue, executor))
               for _ in range(concurrency)]
    try:
        # fast exit on first error
        _, pending = await wait(pending, return_when=FIRST_EXCEPTION)
    finally:
        for task in pending:
            await terminate(task)


def task_cmd(task, results):
    ctx = {key: value if not isinstance(value, ActionType) else results[value]
           for key, value in task.where.items()}
    t = jinja2.Template(task.run)
    return t.render(ctx)


class WriteBuffer(WriteTransport):

    def __init__(self):
        super().__init__()
        self._buffer = io.BytesIO()

    def write(self, data):
        self._buffer.write(data)

    def dump(self):
        return self._buffer.getvalue()


async def _exec(docker, id_, cmd):
    if isinstance(cmd, str):
        cmd = ['/bin/sh', '-c', cmd]

    stdout_buffer = WriteBuffer()
    stdout_proto = StdIOProtocol()
    stdout_proto.connection_made(stdout_buffer)

    exec_ = await docker.exec_create(id_, {
        'Cmd': cmd,
        'AttachStdout': True,
        'AttachStderr': True,
    })
    async with docker.exec_start(
        exec_['Id'], {}, None, stdout_proto
    ) as http_proto:
        await http_proto.wait_closed()
    info = await docker.exec_inspect(exec_['Id'])
    exit_code = info['ExitCode']
    if exit_code:
        # FIXME: proper output
        print(stdout_buffer.dump().decode('utf-8', 'backslashreplace'),
              file=sys.stderr)
    return exit_code


async def build_image(docker, images_map, image, *, status):
    loop = asyncio.get_running_loop()
    version, = image_versions(images_map, [image])
    from_ = docker_image(images_map, image.from_)

    task_key = status.add_task('=> Building image {}:{} ({})'
                               .format(image.repository, version, image.name))

    io_queue = Queue()
    io_executor = IOExecutor()

    process_pool = ProcessPoolExecutor()
    cpu_queue = Queue()
    cpu_executor = CPUExecutor(process_pool)

    states = get_action_states(image.tasks)
    submitted_states = set()

    io_pool_task = loop.create_task(pool(io_queue, io_executor))
    cpu_pool_task = loop.create_task(pool(cpu_queue, cpu_executor))

    c = await docker.create_container({
        'Image': from_.name,
        'Cmd': '/bin/sh',
        'Tty': True,
        'AttachStdout': False,
        'AttachStderr': False,
    })
    try:
        await docker.start(c['Id'])
        exit_code = await _exec(docker, c['Id'], ['mkdir', '/.pi'])
        if exit_code:
            return False

        await ActionDispatcher.dispatch(states, io_queue, cpu_queue)

        total = len(image.tasks)
        padding = math.ceil(math.log10(total + 1))

        for i, task in enumerate(image.tasks, 1):
            task_states = {action: states[action]
                           for action in iter_actions(task)}

            await wait_actions(task_states)

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
                        await docker.put_archive(c['Id'], tar, params={
                            'path': '/.pi',
                        })
                    submitted_states.add(action)

            cmd = task_cmd(task, task_results)
            current_index = '{{:{}d}}'.format(padding).format(i)
            status.add_step(
                task_key, '[{}/{}] {}'.format(current_index, total, cmd),
            )
            exit_code = await _exec(docker, c['Id'], cmd)
            if exit_code:
                return False

        exit_code = await _exec(docker, c['Id'], ['rm', '-rf', '/.pi'])
        if exit_code:
            return False

        await docker.pause(c['Id'])
        await docker.commit(params={
            'container': c['Id'],
            'repo': image.repository,
            'tag': version,
        })
        await docker.unpause(c['Id'])
        return True

    finally:
        await terminate(io_pool_task)
        await terminate(cpu_pool_task)
        process_pool.shutdown()
        for state in states.values():
            state.result.close()
        await docker.remove_container(c['Id'],
                                      params={'v': 'true', 'force': 'true'})
