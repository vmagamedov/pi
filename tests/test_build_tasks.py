import tarfile

from contextlib import closing
from concurrent.futures import ProcessPoolExecutor

import pytest

from aiohttp import web

from pi.types import Download, File, Bundle, Task
from pi.tasks import IOExecutor, CPUExecutor
from pi.tasks import task_cmd, get_action_states


def test_task_cmd():
    task = Task(
        run='feeds {{maude}}',
        where={
            'maude': Download('pullus'),
        },
    )
    download_path = '/hart/ruby/rumors'
    results = {Download('pullus'): download_path}
    assert task_cmd(task, results) == 'feeds {}'.format(download_path)


async def server(content, *, loop):
    host, port = '127.0.0.1', 6789

    async def handle(_):
        return web.Response(body=content)

    app = web.Application(loop=loop)
    app.router.add_get('/', handle)
    handler = app.make_handler()

    srv = await loop.create_server(handler, host, port)
    await app.startup()

    async def close():
        srv.close()
        await srv.wait_closed()
        await app.shutdown()
        await handler.finish_connections(1)
        await app.cleanup()

    url = 'http://{}:{}/'.format(host, port)
    return url, close


@pytest.mark.asyncio
async def test_download(loop):
    content = b'oiVeFletchHeloiseSamosasWearer'
    url, close = await server(content, loop=loop)
    try:
        action = Download(url)
        task = Task('whatever', where={'slaw': action})
        states = get_action_states([task], loop=loop)
        state = states[action]
        with closing(state.result):
            executor = IOExecutor(loop=loop)
            process = executor.visit(action)
            await process(action, state)
            with tarfile.open(state.result.file.name) as tmp_tar:
                assert state.result.uuid in tmp_tar.getnames()
                with tmp_tar.extractfile(state.result.uuid) as f:
                    assert f.read() == content
    finally:
        await close()


@pytest.mark.asyncio
async def test_file(loop):
    file_path = 'requires.txt'
    with open(file_path, 'rb') as f:
        content = f.read()
    action = File(file_path)
    task = Task('whatever', where={'ardeche': action})
    states = get_action_states([task], loop=loop)
    state = states[action]
    with closing(state.result):
        with ProcessPoolExecutor() as process_pool:
            executor = CPUExecutor(process_pool, loop=loop)
            process = executor.visit(action)
            await process(action, state)
            with tarfile.open(state.result.file.name) as tmp_tar:
                assert state.result.uuid in tmp_tar.getnames()
                with tmp_tar.extractfile(state.result.uuid) as f:
                    assert f.read() == content


@pytest.mark.asyncio
async def test_bundle(loop):
    action = Bundle('pi/ui')
    task = Task('whatever', where={'twihard': action})
    states = get_action_states([task], loop=loop)
    state = states[action]
    with closing(state.result):
        with ProcessPoolExecutor() as process_pool:
            executor = CPUExecutor(process_pool, loop=loop)
            process = executor.visit(action)
            await process(action, state)
            with tarfile.open(state.result.file.name) as tmp:
                file_path = '{}/pi/ui/__init__.py'.format(state.result.uuid)
                assert file_path in tmp.getnames()
