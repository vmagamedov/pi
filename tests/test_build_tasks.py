import tarfile
import hashlib

from asyncio import coroutine
from contextlib import closing
from unittest.mock import Mock
from concurrent.futures import ProcessPoolExecutor

import pytest

from aiohttp import web

from pi.types import Download, Bundle
from pi.build.tasks import ActionState, compile_task, Task, get_action_states
from pi.build.tasks import Result, IOExecutor, CPUExecutor


def test_compile_task():
    task = Task(
        run='feeds {{maude}}',
        where={
            'maude': Download('pullus'),
        },
    )

    mock = Mock()
    mock.name = 'pullus'

    states = {Download('pullus'): ActionState(None, Result(mock))}

    name = hashlib.sha1(mock.name.encode('utf-8')).hexdigest()
    assert compile_task(task, states) == 'feeds {}'.format(name)


def server(content, *, loop):
    host, port = 'localhost', 6789

    @coroutine
    def handle(_):
        return web.Response(body=content)

    app = web.Application(loop=loop)
    app.router.add_get('/', handle)
    handler = app.make_handler()

    srv = yield from loop.create_server(handler, host, port)
    yield from app.startup()

    @coroutine
    def close():
        srv.close()
        yield from srv.wait_closed()
        yield from app.shutdown()
        yield from handler.finish_connections(1)
        yield from app.cleanup()

    url = 'http://{}:{}/'.format(host, port)
    return url, close


@pytest.mark.asyncio
def test_download(loop):
    content = b'oiVeFletchHeloiseSamosasWearer'
    url, close = yield from server(content, loop=loop)
    try:
        action = Download(url)
        task = Task('whatever', where={'slaw': action})
        states = get_action_states([task], loop=loop)
        state = states[action]
        with closing(state.result):
            executor = IOExecutor(loop=loop)
            process = executor.visit(action)
            yield from process(action, state)
            state.result.file.seek(0)
            assert state.result.file.read() == content
    finally:
        yield from close()


@pytest.mark.asyncio
def test_bundle(loop):
    action = Bundle('pi/ui')
    task = Task('whatever', where={'twihard': action})
    states = get_action_states([task], loop=loop)
    state = states[action]
    with closing(state.result):
        with ProcessPoolExecutor() as process_pool:
            executor = CPUExecutor(process_pool, loop=loop)
            process = executor.visit(action)
            yield from process(action, state)
            with tarfile.open(state.result.file.name) as tmp:
                assert 'pi/ui/__init__.py' in tmp.getnames()
