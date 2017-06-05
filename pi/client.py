import json
import socket

from functools import partial
from contextlib import contextmanager
from collections import deque

from ._requires.docker import APIClient, errors
from ._requires.docker.utils import kwargs_from_env


APIError = errors.APIError
NotFound = errors.NotFound


class ChunkedReader:

    def __init__(self, sock, *, loop):
        self.sock = sock
        self.loop = loop
        self.chunk_size = None
        self.tail = b''
        self.chunks = deque()
        self.complete = False

    async def read(self):
        while not self.chunks:
            if self.complete:
                raise RuntimeError('Stream is already consumed')
            data = await self.loop.sock_recv(self.sock, 4096)
            if not data:
                raise IOError('Incomplete response')
            self.tail += data
            while True:
                if self.chunk_size is None:
                    parts = self.tail.split(b'\r\n', 1)
                    if len(parts) == 2:
                        chunk_size_hex, self.tail = parts
                        self.chunk_size = int(chunk_size_hex, 16)
                    else:
                        break
                else:
                    if len(self.tail) >= self.chunk_size + 2:
                        self.chunks.append(self.tail[:self.chunk_size])
                        self.tail = self.tail[self.chunk_size + 2:]
                        if self.chunk_size == 0:
                            self.complete = True
                        self.chunk_size = None
                        continue
        return self.chunks.popleft()


class DockerStreamDecoder:

    def __init__(self, reader):
        self.reader = reader

    async def read(self):
        chunk = await self.reader.read()
        if chunk:
            return map(json.loads, chunk.decode('utf-8').strip().split('\r\n'))
        else:
            return []


class _Client(APIClient):

    def __init__(self, *args, loop, **kwargs):
        super().__init__(*args, **kwargs)
        self.loop = loop

    @contextmanager
    def _stream_ctx(self, response, decode=False):
        with self._get_raw_response_socket(response) as sock_io:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM,
                                 fileno=sock_io.fileno())
            sock.setblocking(False)
            reader = ChunkedReader(sock, loop=self.loop)
            if decode:
                reader = DockerStreamDecoder(reader)
            yield reader

    def _stream_helper(self, response, decode=False):
        if response.raw._fp.chunked:
            return self._stream_ctx(response, decode=decode)
        else:
            raise APIError('Error', response)


class _AsyncContextManagerAdapter:

    def __init__(self, func):
        self._func = func

    async def __aenter__(self):
        self._ctx = await self._func()
        return self._ctx.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._ctx.__exit__(exc_type, exc_val, exc_tb)


class AsyncClient:

    def __init__(self, *, loop):
        self._client = _Client(version='auto', loop=loop, **kwargs_from_env())
        self._loop = loop

    def create_host_config(self, *args, **kwargs):
        return self._client.create_host_config(*args, **kwargs)

    def create_networking_config(self, *args, **kwargs):
        return self._client.create_networking_config(*args, **kwargs)

    async def _exec(self, func, *args, **kwargs):
        wrapper = partial(func, *args, **kwargs)
        result = await self._loop.run_in_executor(None, wrapper)
        return result

    def images(self, *args, **kwargs):
        return self._exec(self._client.images, *args, **kwargs)

    def build(self, *args, stream=False, **kwargs):
        def proc():
            return self._exec(self._client.build, *args,
                              stream=stream, **kwargs)
        return _AsyncContextManagerAdapter(proc) if stream else proc()

    def create_container(self, *args, **kwargs):
        return self._exec(self._client.create_container, *args, **kwargs)

    def start(self, *args, **kwargs):
        return self._exec(self._client.start, *args, **kwargs)

    def remove_container(self, *args, **kwargs):
        return self._exec(self._client.remove_container, *args, **kwargs)

    def put_archive(self, *args, **kwargs):
        return self._exec(self._client.put_archive, *args, **kwargs)

    def exec_create(self, *args, **kwargs):
        return self._exec(self._client.exec_create, *args, **kwargs)

    def exec_start(self, *args, **kwargs):
        return self._exec(self._client.exec_start, *args, **kwargs)

    def exec_inspect(self, *args, **kwargs):
        return self._exec(self._client.exec_inspect, *args, **kwargs)

    def pause(self, *args, **kwargs):
        return self._exec(self._client.pause, *args, **kwargs)

    def commit(self, *args, **kwargs):
        return self._exec(self._client.commit, *args, **kwargs)

    def unpause(self, *args, **kwargs):
        return self._exec(self._client.unpause, *args, **kwargs)

    def pull(self, *args, **kwargs):
        return self._exec(self._client.pull, *args, **kwargs)

    def push(self, *args, **kwargs):
        return self._exec(self._client.push, *args, **kwargs)

    def stop(self, *args, **kwargs):
        return self._exec(self._client.stop, *args, **kwargs)

    def kill(self, *args, **kwargs):
        return self._exec(self._client.kill, *args, **kwargs)

    def resize(self, *args, **kwargs):
        return self._exec(self._client.resize, *args, **kwargs)

    def attach_socket(self, *args, **kwargs):
        def proc():
            return self._exec(self._client.attach_socket, *args, **kwargs)
        return _AsyncContextManagerAdapter(proc)

    def wait(self, *args, **kwargs):
        return self._exec(self._client.wait, *args, **kwargs)

    def containers(self, *args, **kwargs):
        return self._exec(self._client.containers, *args, **kwargs)

    def create_network(self, *args, **kwargs):
        return self._exec(self._client.create_network, *args, **kwargs)

    def remove_image(self, *args, **kwargs):
        return self._exec(self._client.remove_image, *args, **kwargs)
