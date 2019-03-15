import json

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


async def _request_json(method, path):
    async with connect() as stream:
        await stream.send_request(method, path, [
            ('Host', 'localhost'),
            ('Connection', 'close'),
        ])
        response = await stream.recv_response()
        assert response.status_code == 200, response
        return await _recv_json(stream, response)


async def _get_json(path):
    return await _request_json('GET', path)


async def images():
    return await _get_json('/images/json')


async def create_container(spec, *, params=None):
    uri = '/containers/create'
    if params:
        uri += '?' + urlencode(params)
    async with connect() as stream:
        data = json.dumps(spec).encode('utf-8')
        await stream.send_request('POST', uri, [
            ('Host', 'localhost'),
            ('Content-Type', 'application/json'),
            ('Content-Length', str(len(data))),
        ], end_stream=False)
        await stream.send_data(data)
        response = await stream.recv_response()
        if response.status_code == 201:
            return await _recv_json(stream, response)
        else:
            raise response.error()


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
