import os
import tarfile
import tempfile
import unicodedata

from pathlib import Path
from asyncio import coroutine, wait, CancelledError, Queue, Event, ensure_future
from asyncio import FIRST_COMPLETED, FIRST_EXCEPTION
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor

import pytest

from aiohttp import web

from pi._requires import attr
from pi._requires import jinja2
from pi._requires import requests

from pi.types import Download, Dir
from pi.utils import terminate


def compile_task(task):
    template = task['run']
    params = task['where']
    t = jinja2.Template(template)
    return t.render(params)


class DownloadsVisitor:

    def __init__(self):
        self.downloads = []
        self._seen = set()

    def visit(self, obj):
        return obj.accept(self)

    def visit_task(self, obj):
        for value in obj.get('where', {}).values():
            self.visit(value)

    def visit_download(self, obj):
        if obj not in self._seen:
            self.downloads.append(obj)
            self._seen.add(obj)


class DirsVisitor:

    def __init__(self):
        self.dirs = []
        self._seen = set()

    def visit(self, obj):
        return obj.accept(self)

    def visit_task(self, obj):
        for value in obj.get('where', {}).values():
            self.visit(value)

    def visit_dir(self, obj):
        if obj not in self._seen:
            self.dirs.append(obj)
            self._seen.add(obj)


@attr.s
class Progress:
    url = attr.ib()
    complete = attr.ib()
    temp_file = attr.ib()
    value = attr.ib(0)
    error = attr.ib(None)


def _download(state):
    downloaded = 0
    response = requests.get(state.url)
    response.raise_for_status()
    for chunk in response.iter_content(64 * 1024):
        state.temp_file.write(chunk)
        downloaded += len(chunk)
        state.value = downloaded


def _download_worker(input_queue, *, loop):
    while True:
        state = yield from input_queue.get()
        try:
            yield from loop.run_in_executor(None, _download, state)
        except Exception as e:
            state.error = str(e)
            raise
        finally:
            state.complete.set()


@coroutine
def _download_workers(input_queue, concurrency, *, loop):
    pending = [loop.create_task(_download_worker(input_queue, loop=loop))
               for _ in range(concurrency)]
    try:
        # fast exit on first error
        _, pending = yield from wait(pending, loop=loop,
                                     return_when=FIRST_EXCEPTION)
    finally:
        for task in pending:
            yield from terminate(task, loop=loop)


@contextmanager
def download_states(tasks, *, loop):
    downloads_visitor = DownloadsVisitor()
    for task in tasks:
        downloads_visitor.visit_task(task)
    states = [Progress(d.url, Event(loop=loop), tempfile.NamedTemporaryFile())
              for d in downloads_visitor.downloads]
    try:
        yield states
    finally:
        for state in states:
            state.temp_file.close()


@coroutine
def download(states, concurrency=2, *, loop):
    input_queue = Queue(loop=loop)
    for state in states:
        yield from input_queue.put(state)

    download_task = loop.create_task(_download_workers(input_queue, concurrency,
                                                       loop=loop))
    pending = {download_task}.union({ensure_future(state.complete.wait(),
                                                   loop=loop)
                                     for state in states})
    try:
        while True:
            done, pending = yield from wait(pending, loop=loop,
                                            return_when=FIRST_COMPLETED)
            if download_task in done or pending == {download_task}:
                break
    finally:
        for task in pending:
            yield from terminate(task, loop=loop)


@attr.s
class DirState:
    path = attr.ib()
    complete = attr.ib()
    temp_file = attr.ib()
    error = attr.ib(None)


def _packer(state_path, state_temp_file):
    dir_path = Path(state_path).resolve()  # FIXME: raises FileNotFoundError
    assert dir_path.is_dir(), dir_path

    cur_path = Path('.').resolve()
    assert cur_path in dir_path.parents, dir_path

    rel_path = dir_path.relative_to(cur_path)

    def filter_(path_):
        # TODO: ability to exclude (.gitignore? .hgignore?)
        return True

    with open(state_temp_file, 'wb+') as tmp:
        with tarfile.open(mode='w:tar', fileobj=tmp) as tar:
            for path, _, names in os.walk(str(rel_path)):
                if not filter_(path):
                    continue

                arc_path = unicodedata.normalize('NFC', path)
                tar.addfile(tar.gettarinfo(path, arc_path))
                for name in names:
                    file_path = os.path.join(path, name)
                    if not filter_(file_path):
                        continue

                    arc_file_path = unicodedata.normalize('NFC', file_path)
                    with open(file_path, 'rb') as f:
                        tar.addfile(tar.gettarinfo(file_path, arc_file_path,
                                                   fileobj=f),
                                    fileobj=f)


@contextmanager
def dir_states(tasks, *, loop):
    dirs_visitor = DirsVisitor()
    for task in tasks:
        dirs_visitor.visit_task(task)
    states = [DirState(d.path, Event(loop=loop), tempfile.NamedTemporaryFile())
              for d in dirs_visitor.dirs]
    try:
        yield states
    finally:
        for state in states:
            state.temp_file.close()


@coroutine
def pack(states, *, loop, pool):
    pending = [loop.run_in_executor(pool, _packer, state.path,
                                    state.temp_file.name)
               for state in states]

    states_map = dict(zip(pending, states))
    try:
        while True:
            done, pending = yield from wait(pending,
                                            return_when=FIRST_COMPLETED)
            for task in done:
                state = states_map[task]
                error = task.exception()
                if error:
                    state.error = error
                state.complete.set()
            if not pending:
                break
    finally:
        for task in pending:
            yield from terminate(task, loop=loop)


def test_simple():
    task = {
        'run': 'feeds {{maude}}',
        'where': {
            'maude': 'pullus',
        },
    }
    assert compile_task(task) == 'feeds pullus'


def test_download():
    task = {
        'where': {
            'adiabat': Download('thorow'),
        },
    }
    downloads_visitor = DownloadsVisitor()
    downloads_visitor.visit_task(task)
    assert downloads_visitor.downloads == [Download('thorow')]


@pytest.mark.asyncio
def test_real_download(event_loop):
    task = {
        'where': {
            'adiabat': Download('http://localhost:6789/'),
        },
    }

    @coroutine
    def handle(request):
        return web.Response(body=b'oiVeFletchHeloiseSamosasWearer')

    app = web.Application(loop=event_loop)
    app.router.add_get('/', handle)
    handler = app.make_handler()

    server = yield from event_loop.create_server(handler, 'localhost', 6789)
    yield from app.startup()
    try:
        with download_states([task], loop=event_loop) as states:
            yield from download(states, loop=event_loop)
            f = states[0].temp_file
            f.seek(0)
            assert f.read() == b'oiVeFletchHeloiseSamosasWearer'
    finally:
        server.close()
        yield from server.wait_closed()
        yield from app.shutdown()
        yield from handler.finish_connections(1)
        yield from app.cleanup()


@pytest.mark.asyncio
def test_dir(event_loop):
    task = {
        'where': {
            'slaw': Dir('pi/ui'),
        },
    }
    with ProcessPoolExecutor(1) as pool:
        with dir_states([task], loop=event_loop) as states:
            yield from pack(states, loop=event_loop, pool=pool)

            state, = states
            assert state.complete.is_set()
            with tarfile.open(state.temp_file.name) as tmp:
                assert 'pi/ui/__init__.py' in tmp.getnames()
