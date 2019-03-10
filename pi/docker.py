import json

from .http import connect


async def _request_json(method, path):
    async with connect() as stream:
        await stream.send_request(method, path, [
            ('Host', 'localhost'),
            ('Connection', 'close'),
        ])
        response = await stream.recv_response()
        assert response.status_code == 200, response

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


async def _get_json(path):
    return await _request_json('GET', path)


async def images():
    return await _get_json('/images/json')
