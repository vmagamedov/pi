from asyncio import coroutine
from functools import partial

from ._requires.docker import Client, errors
from ._requires.docker.utils import kwargs_from_env


APIError = errors.APIError
NotFound = errors.NotFound


def get_client():
    return Client(version='auto', **kwargs_from_env())


class AsyncClient:

    def __init__(self, *, loop):
        self._client = Client(version='auto', **kwargs_from_env())
        self._loop = loop

    @coroutine
    def _exec(self, func, *args, **kwargs):
        wrapper = partial(func, *args, **kwargs)
        result = yield from self._loop.run_in_executor(None, wrapper)
        return result

    def images(self, *args, **kwargs):
        return self._exec(self._client.images, *args, **kwargs)

    def build(self, *args, **kwargs):
        return self._exec(self._client.build, *args, **kwargs)

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
