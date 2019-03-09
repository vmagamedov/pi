import asyncio

from typing import cast
from contextlib import asynccontextmanager

from .utils import Wrapper
from ._requires import h11


class Stream:

    def __init__(self, connection: h11.Connection,
                 transport: asyncio.Transport):
        self.connection = connection
        self.transport = transport

        self._response = None
        self._response_waiter = asyncio.Event()
        self._data = []
        self._data_size = 0
        self._data_waiter = asyncio.Event()

        self._wrapper = Wrapper()

    async def send_request(self, method, path, headers, *, end_stream=True):
        data = self.connection.send(h11.Request(method=method, target=path,
                                                headers=headers))
        self.transport.write(data)
        if end_stream:
            await self.end()

    async def send_data(self, data):
        pass

    async def recv_response(self):
        with self._wrapper:
            await self._response_waiter.wait()
            return self._response

    async def recv_data(self, *, content_length=None):
        with self._wrapper:
            while True:
                await self._data_waiter.wait()
                if (
                    content_length is not None
                    and self._data_size < content_length
                ):
                    self._data_waiter.clear()
                else:
                    data = b''.join(self._data)
                    del self._data[:]
                    self._data_size = 0
                    return data

    async def end(self):
        data = self.connection.send(h11.EndOfMessage())
        self.transport.write(data)

    def __response__(self, response: h11.Response):
        self._response = response
        self._response_waiter.set()

    def __data__(self, data: h11.Data):
        self._data.append(data.data)
        self._data_size += len(data.data)
        self._data_waiter.set()

    def __end__(self):
        self._data.append(b'')
        self._data_waiter.set()

    def __terminated__(self):
        self._wrapper.cancel(Exception('Connection closed'))


class HTTPProtocol(asyncio.Protocol):
    connection = None
    transport: asyncio.Transport = None
    stream: Stream = None

    def connection_made(self, transport):
        self.connection = h11.Connection(h11.CLIENT)
        self.transport = transport
        self.stream = Stream(self.connection, self.transport)

    def data_received(self, data: bytes):
        self.connection.receive_data(data)
        while True:
            event = self.connection.next_event()
            event_type = type(event)
            if event_type is h11.Response:
                self.stream.__response__(event)
            elif event_type is h11.Data:
                self.stream.__data__(event)
            elif event_type is h11.EndOfMessage:
                self.stream.__end__()
            elif event is h11.NEED_DATA:
                break

    def connection_lost(self, exc):
        self.stream.__terminated__()
        self.transport.close()


@asynccontextmanager
async def connect():
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_unix_connection(
        HTTPProtocol,
        '/var/run/docker.sock',
    )
    try:
        yield cast(HTTPProtocol, protocol).stream
    finally:
        transport.close()
