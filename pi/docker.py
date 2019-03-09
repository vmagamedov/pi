import asyncio

from .http import connect


class DockerClient:

    async def _request_json(self):
        pass

    async def _request_stream(self):
        pass

    async def images(self):
        async with connect() as stream:
            await stream.send_request('GET', '/info', [
                ('Host', 'localhost'),
                ('Connection', 'close'),
            ])
            response = await stream.recv_response()
            print(response.status_code)
            print(response.headers)
            data = []
            while True:
                chunk = await stream.recv_data()
                if chunk:
                    data.append(chunk)
                else:
                    break
            print(b''.join(data))


async def test():
    client = DockerClient()
    await client.images()


if __name__ == '__main__':
    asyncio.run(test())
