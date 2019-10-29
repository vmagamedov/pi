import ssl
import socket
import asyncio
from asyncio import Event

from typing import cast, NamedTuple
from contextlib import asynccontextmanager

from .utils import Wrapper
from ._requires import h11


if hasattr(socket, 'TCP_NODELAY'):
    _sock_type_mask = 0xf if hasattr(socket, 'SOCK_NONBLOCK') else 0xffffffff

    def _set_nodelay(sock):
        if (
            sock.family in {socket.AF_INET, socket.AF_INET6}
            and sock.type & _sock_type_mask == socket.SOCK_STREAM
            and sock.proto == socket.IPPROTO_TCP
        ):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
else:
    def _set_nodelay(sock):
        pass


class HTTPError(Exception):

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Response(NamedTuple):
    status_code: int
    headers: dict
    reason: bytes

    def error(self):
        try:
            reason = self.reason.decode('ascii')
        except UnicodeDecodeError:
            reason = repr(self.reason)
        raise HTTPError(reason)


class Stream:

    def __init__(self, protocol, connection: h11.Connection,
                 transport: asyncio.Transport):
        self.protocol = protocol  # FIXME: circular reference
        self.connection = connection
        self.transport = transport

        self._response = None
        self._response_waiter = asyncio.Event()
        self._data = []
        self._data_size = 0
        self._data_waiter = asyncio.Event()
        self._eof = False

        self._wrapper = Wrapper()

    async def send_request(self, method, path, headers, *, end_stream=True):
        data = self.connection.send(h11.Request(method=method, target=path,
                                                headers=headers))
        self.transport.write(data)
        if end_stream:
            await self.end()

    async def send_data(self, data, *, end_stream=True):
        data = self.connection.send(h11.Data(data=data))
        self.transport.write(data)
        if end_stream:
            await self.end()

    async def recv_response(self):
        with self._wrapper:
            await self._response_waiter.wait()
            return Response(self._response.status_code,
                            dict(self._response.headers),
                            self._response.reason)

    async def recv_data(self, content_length):
        with self._wrapper:
            while True:
                await self._data_waiter.wait()
                if self._data_size < content_length:
                    self._data_waiter.clear()
                else:
                    assert self._eof
                    assert self._data_size == content_length
                    return b''.join(self._data)

    async def recv_data_chunked(self):
        with self._wrapper:
            while True:
                await self._data_waiter.wait()
                for chunk in self._data:
                    yield chunk
                del self._data[:]
                if self._eof:
                    break
                else:
                    self._data_waiter.clear()

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
        self._eof = True
        self._data_waiter.set()

    def __terminated__(self):
        if not self._eof:
            self._wrapper.cancel(Exception('Connection closed'))


class HTTPProtocol(asyncio.Protocol):
    connection = None
    transport: asyncio.Transport = None
    stream: Stream = None

    hijacked = False

    def __init__(self, *, stdin_proto=None, stdout_proto=None):
        self._stdin_proto = stdin_proto
        self._stdout_proto = stdout_proto
        self._closed = Event()

    def connection_made(self, transport):
        sock = transport.get_extra_info('socket')
        if sock is not None:
            _set_nodelay(sock)

        self.connection = h11.Connection(h11.CLIENT)
        self.transport = transport
        self.stream = Stream(self, self.connection, self.transport)

    def pause_writing(self):
        if self.hijacked:
            assert self._stdin_proto
            self._stdin_proto.transport.pause_reading()

    def resume_writing(self):
        if self.hijacked:
            assert self._stdin_proto
            self._stdin_proto.transport.resume_reading()

    def data_received(self, data: bytes):
        if self.hijacked:
            assert self._stdout_proto
            self._stdout_proto.transport.write(data)
        else:
            self.connection.receive_data(data)
            while True:
                event = self.connection.next_event()
                # print(event)
                event_type = type(event)
                # print(event_type)
                if event_type is h11.Response:
                    self.stream.__response__(event)
                elif event_type is h11.InformationalResponse:
                    self.stream.__response__(event)
                    if event.status_code == 101:
                        self.hijacked = True
                elif event_type is h11.Data:
                    self.stream.__data__(event)
                elif event_type is h11.EndOfMessage:
                    self.stream.__end__()
                elif event is h11.NEED_DATA:
                    break
                elif event is h11.PAUSED:
                    break

    def connection_lost(self, exc):
        if not self.hijacked:
            self.stream.__terminated__()
        self.transport.close()
        self._closed.set()

    async def wait_closed(self):
        return await self._closed.wait()


@asynccontextmanager
async def connect_unix(*, stdin_proto=None, stdout_proto=None):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_unix_connection(
        lambda: HTTPProtocol(stdin_proto=stdin_proto,
                             stdout_proto=stdout_proto),
        '/var/run/docker.sock',
    )
    try:
        yield cast(HTTPProtocol, protocol).stream
    finally:
        transport.close()


@asynccontextmanager
async def connect_tcp(host, port, *, secure=False):
    loop = asyncio.get_running_loop()
    ssl_context = ssl.create_default_context() if secure else None
    transport, protocol = await loop.create_connection(
        HTTPProtocol, host, port, ssl=ssl_context,
    )
    try:
        yield cast(HTTPProtocol, protocol).stream
    finally:
        transport.close()
