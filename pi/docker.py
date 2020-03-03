import os
import json
from contextlib import asynccontextmanager

from urllib.parse import urlencode

from .http import connect_unix, connect_tcp
from .auth import read_config, server_name, resolve_auth, encode_header
from .utils import cached_property


CHUNK_SIZE = 65535

_TCP_PROTO = 'tcp://'
_UNIX_PROTO = 'unix://'
_DOCKER_HOST = os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
if _DOCKER_HOST.startswith(_TCP_PROTO):
    _HOST, _, _PORT_STR = _DOCKER_HOST[len(_TCP_PROTO):].partition(':')
    _PORT = int(_PORT_STR)

    def connect_docker(**kwargs):
        return connect_tcp(_HOST, _PORT, **kwargs)
elif _DOCKER_HOST.startswith(_UNIX_PROTO):
    _PATH = _DOCKER_HOST[len(_UNIX_PROTO):]

    def connect_docker(**kwargs):
        return connect_unix(_PATH, **kwargs)
else:
    raise RuntimeError(f'Invalid DOCKER_HOST environ variable: {_DOCKER_HOST}')


async def _recv_json(stream, response):
    content_type = response.headers.get(b'content-type')
    assert content_type == b'application/json', response

    if b'content-length' in response.headers:
        content_length = response.headers[b'content-length']
        data = await stream.recv_data(content_length=int(content_length))
    elif b'transfer-encoding' in response.headers:
        transfer_encoding = response.headers[b'transfer-encoding']
        assert transfer_encoding == b'chunked', response
        chunks = [c async for c in stream.recv_data_chunked()]
        data = b''.join(chunks)
    else:
        assert False, response

    return json.loads(data.decode('utf-8'))


async def _request_json(method, path, data=None, *, _ok_statuses=None):
    if _ok_statuses is None:
        _ok_statuses = frozenset({200, 201, 204})
    async with connect_docker() as stream:
        headers = [
            ('Host', 'localhost'),
            ('Connection', 'close'),
        ]
        if data is not None:
            json_data = json.dumps(data).encode('utf-8')
            headers.append(('Content-Type', 'application/json'))
            headers.append(('Content-Length', str(len(json_data))))
        await stream.send_request(method, path, headers,
                                  end_stream=(data is None))
        if data is not None:
            await stream.send_data(json_data)
        response = await stream.recv_response()
        if response.status_code == 204:
            return None
        if response.status_code in _ok_statuses:
            return await _recv_json(stream, response)
        else:
            raise response.error()


async def _get_json(path, *, _ok_statuses=None):
    return await _request_json('GET', path, _ok_statuses=_ok_statuses)


async def _post_json(path, data=None, *, _ok_statuses=None):
    return await _request_json('POST', path, data=data,
                               _ok_statuses=_ok_statuses)


async def _delete_json(path, *, _ok_statuses=None):
    return await _request_json('DELETE', path, _ok_statuses=_ok_statuses)


class Docker:

    @cached_property
    def _docker_config(self):
        return read_config()

    async def _auth_header(self, image_name):
        registry = server_name(image_name)
        auth = await resolve_auth(self._docker_config, registry)
        if auth is not None:
            auth_header = encode_header(auth)
            return auth_header
        else:
            return None

    async def images(self):
        return await _get_json('/images/json')

    async def create_container(self, spec, *, params=None):
        uri = '/containers/create'
        if params:
            uri += '?' + urlencode(params)
        return await _post_json(uri, spec)

    async def resize(self, id_, *, params=None):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/resize'.format(id=id_)
        if params:
            uri += '?' + urlencode(params)
        async with connect_docker() as stream:
            await stream.send_request('POST', uri, [
                ('Host', 'localhost'),
            ])
            response = await stream.recv_response()
            if response.status_code == 200:
                pass
            else:
                raise response.error()

    async def start(self, id_, *, params=None):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/start'.format(id=id_)
        if params:
            uri += '?' + urlencode(params)
        async with connect_docker() as stream:
            await stream.send_request('POST', uri, [
                ('Host', 'localhost'),
            ])
            response = await stream.recv_response()
            if response.status_code == 204:
                pass
            elif response.status_code == 304:
                pass
            else:
                raise response.error()

    async def exec_create(self, id_, spec):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/exec'.format(id=id_)
        return await _post_json(uri, spec)

    @asynccontextmanager
    async def exec_start(self, id_, spec, stdin_proto, stdout_proto):
        assert isinstance(id_, str), id_
        uri = '/exec/{id}/start'.format(id=id_)
        async with connect_docker(
            stdin_proto=stdin_proto, stdout_proto=stdout_proto
        ) as stream:
            json_data = json.dumps(spec).encode('utf-8')
            await stream.send_request('POST', uri, [
                ('Host', 'localhost'),
                ('Content-Type', 'application/json'),
                ('Content-Length', str(len(json_data))),
                ('Connection', 'Upgrade'),
                ('Upgrade', 'tcp'),
            ], end_stream=False)
            await stream.send_data(json_data)
            response = await stream.recv_response()
            if response.status_code == 101:
                yield stream.protocol
            else:
                raise response.error()

    async def exec_inspect(self, id_):
        assert isinstance(id_, str), id_
        uri = '/exec/{id}/json'.format(id=id_)
        return await _get_json(uri)

    @asynccontextmanager
    async def attach(self, id_, stdin_proto, stdout_proto, *, params=None):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/attach'.format(id=id_)
        if params:
            uri += '?' + urlencode(params)
        async with connect_docker(
            stdin_proto=stdin_proto, stdout_proto=stdout_proto
        ) as stream:
            await stream.send_request('POST', uri, [
                ('Host', 'localhost'),
                ('Connection', 'Upgrade'),
                ('Upgrade', 'tcp'),
            ])
            response = await stream.recv_response()
            if response.status_code == 101:
                yield stream.protocol
            else:
                raise response.error()

    async def remove_container(self, id_, *, params=None):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}'.format(id=id_)
        if params:
            uri += '?' + urlencode(params)
        async with connect_docker() as stream:
            await stream.send_request('DELETE', uri, [
                ('Host', 'localhost'),
            ])
            response = await stream.recv_response()
            if response.status_code == 204:
                pass
            else:
                raise response.error()

    async def create_image(self, *, params=None):
        uri = '/images/create'
        if params:
            uri += '?' + urlencode(params)
        headers = [('Host', 'localhost')]
        if 'fromImage' in params:
            auth_header = await self._auth_header(params['fromImage'])
            if auth_header:
                headers.append(('X-Registry-Auth', auth_header))

        async with connect_docker() as stream:
            await stream.send_request('POST', uri, headers)
            response = await stream.recv_response()
            if response.status_code == 200:
                async for chunk in stream.recv_data_chunked():
                    yield chunk
            else:
                raise response.error()

    async def push(self, name, *, params):
        uri = '/images/{name}/push'.format(name=name)
        if params:
            uri += '?' + urlencode(params)
        headers = [('Host', 'localhost')]
        auth_header = await self._auth_header(name)
        if auth_header:
            headers.append(('X-Registry-Auth', auth_header))

        async with connect_docker() as stream:
            await stream.send_request('POST', uri, headers)
            response = await stream.recv_response()
            if response.status_code == 200:
                async for chunk in stream.recv_data_chunked():
                    yield chunk
            else:
                raise response.error()

    async def containers(self, *, params):
        uri = '/containers/json'
        if params:
            uri += '?' + urlencode(params)
        return await _get_json(uri)

    async def remove_image(self, name):
        uri = '/images/{name}'.format(name=name)
        return await _delete_json(uri)

    async def wait(self, id_):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/wait'.format(id=id_)
        return await _post_json(uri)

    async def stop(self, id_, *, params):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/stop'.format(id=id_)
        if params:
            uri += '?' + urlencode(params)
        await _post_json(uri)

    async def pause(self, id_):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/pause'.format(id=id_)
        await _post_json(uri)

    async def commit(self, *, params):
        uri = '/commit'
        if params:
            uri += '?' + urlencode(params)
        return await _post_json(uri)

    async def unpause(self, id_):
        assert isinstance(id_, str), id_
        uri = '/containers/{id}/unpause'.format(id=id_)
        await _post_json(uri)

    async def create_network(self, *, data):
        uri = '/networks/create'
        return await _post_json(uri, data=data)

    async def put_archive(self, id_, arch, *, params):
        uri = '/containers/{id}/archive'.format(id=id_)
        if params:
            uri += '?' + urlencode(params)
        headers = [
            ('Host', 'localhost'),
            ('transfer-encoding', 'chunked'),
        ]
        async with connect_docker() as stream:
            await stream.send_request('PUT', uri, headers, end_stream=False)
            while True:
                chunk = arch.read(CHUNK_SIZE)
                if len(chunk) == CHUNK_SIZE:
                    await stream.send_data(chunk, end_stream=False)
                else:
                    if chunk:
                        await stream.send_data(chunk)
                    else:
                        await stream.end()
                    break
            response = await stream.recv_response()
            if response.status_code != 200:
                raise response.error()
