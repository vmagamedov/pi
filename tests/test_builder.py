import tempfile

from asyncio import coroutine, wait, CancelledError, Queue, Event, ensure_future
from asyncio import FIRST_COMPLETED, FIRST_EXCEPTION, get_event_loop
from contextlib import contextmanager

import pytest

from aiohttp import web

from pi._requires import attr
from pi._requires import jinja2
from pi._requires import requests

from pi.types import Download
from pi.utils import terminate


def compile_task(task):
    template = task['run']
    params = task['where']
    t = jinja2.Template(template)
    return t.render(params)


class DownloadsVisitor:

    def __init__(self):
        self.downloads = set()

    def visit(self, obj):
        return obj.accept(self)

    def visit_task(self, obj):
        for value in obj.get('where', {}).values():
            self.visit(value)

    def visit_download(self, obj):
        self.downloads.add(obj)


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
    tasks = [loop.create_task(_download_worker(input_queue, loop=loop))
             for _ in range(concurrency)]
    try:
        _, pending = yield from wait(tasks, loop=loop,
                                     return_when=FIRST_EXCEPTION)
    except CancelledError:
        for task in tasks:
            yield from terminate(task, loop=loop)
    else:
        # fast exit on first error
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


def test_simple():
    task = {
        'name': 'freo pella beganne chalet unweave',
        'run': 'feeds {{maude}}',
        'where': {
            'maude': 'pullus',
        },
    }
    assert compile_task(task) == 'feeds pullus'


def test_download():
    task = {
        'name': 'begem daysail macking noni zombie',
        'run': 'aligner {{maude}}',
        'where': {
            'adiabat': Download('thorow'),
        },
    }
    downloads_visitor = DownloadsVisitor()
    downloads_visitor.visit_task(task)
    assert downloads_visitor.downloads == {Download('thorow')}


@pytest.mark.asyncio
@coroutine
def test_real_download(event_loop):
    task = {
        'name': 'begem-daysail-macking-noni-zombie',
        'run': 'aligner {{maude}}',
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


if __name__ == '__main__':
    loop = get_event_loop()
    loop.run_until_complete(test_real_download(loop))
