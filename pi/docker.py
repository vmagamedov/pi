import json
from contextlib import asynccontextmanager

from urllib.parse import urlencode

from .http import connect


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
        _ok_statuses = frozenset({200, 201})
    async with connect() as stream:
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
        if response.status_code in _ok_statuses:
            return await _recv_json(stream, response)
        else:
            raise response.error()


async def _get_json(path, *, _ok_statuses=None):
    return await _request_json('GET', path, _ok_statuses=_ok_statuses)


async def _post_json(path, data=None, *, _ok_statuses=None):
    return await _request_json('POST', path, data=data,
                               _ok_statuses=_ok_statuses)


async def images():
    return await _get_json('/images/json')


async def create_container(spec, *, params=None):
    uri = '/containers/create'
    if params:
        uri += '?' + urlencode(params)
    return await _post_json(uri, spec)


async def resize(id_, *, params=None):
    assert isinstance(id_, str), id_
    uri = '/containers/{id}/resize'.format(id=id_)
    if params:
        uri += '?' + urlencode(params)
    async with connect() as stream:
        await stream.send_request('POST', uri, [
            ('Host', 'localhost'),
        ])
        response = await stream.recv_response()
        if response.status_code == 200:
            pass
        else:
            raise response.error()


async def start(id_, *, params=None):
    assert isinstance(id_, str), id_
    uri = '/containers/{id}/start'.format(id=id_)
    if params:
        uri += '?' + urlencode(params)
    async with connect() as stream:
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


async def exec_create(id_, spec):
    assert isinstance(id_, str), id_
    uri = '/containers/{id}/exec'.format(id=id_)
    return await _post_json(uri, spec)


@asynccontextmanager
async def exec_start(id_, spec, stdin_proto, stdout_proto):
    assert isinstance(id_, str), id_
    uri = '/exec/{id}/start'.format(id=id_)
    async with connect(stdin_proto=stdin_proto, stdout_proto=stdout_proto) as stream:
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


async def exec_inspect(id_):
    assert isinstance(id_, str), id_
    uri = '/exec/{id}/json'.format(id=id_)
    return await _get_json(uri)


@asynccontextmanager
async def attach(id_, stdin_proto, stdout_proto, *, params=None):
    assert isinstance(id_, str), id_
    uri = '/containers/{id}/attach'.format(id=id_)
    if params:
        uri += '?' + urlencode(params)
    async with connect(stdin_proto=stdin_proto, stdout_proto=stdout_proto) as stream:
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


async def remove_container(id_, *, params=None):
    assert isinstance(id_, str), id_
    uri = '/containers/{id}'.format(id=id_)
    if params:
        uri += '?' + urlencode(params)
    async with connect() as stream:
        await stream.send_request('DELETE', uri, [
            ('Host', 'localhost'),
        ])
        response = await stream.recv_response()
        if response.status_code == 204:
            pass
        else:
            raise response.error()
