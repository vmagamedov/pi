import sys
import json
import logging

from asyncio import coroutine
from functools import partial

from ._requires.docker import Client, errors
from ._requires.docker.utils import kwargs_from_env


APIError = errors.APIError
NotFound = errors.NotFound

log = logging.getLogger(__name__)


def echo_download_progress(output):
    error = False
    last_id = None
    for line in output:
        log.debug(line)
        chunks = line.decode('utf-8').splitlines()
        for chunk in chunks:
            progress = json.loads(chunk)

            error = error or 'error' in progress

            progress_id = progress.get('id')
            if last_id:
                if progress_id == last_id:
                    sys.stdout.write('\x1b[2K\r')
                elif not progress_id or progress_id != last_id:
                    sys.stdout.write('\n')
            last_id = progress_id

            if progress_id:
                sys.stdout.write('{}: '.format(progress_id))
            sys.stdout.write(progress.get('status') or
                             progress.get('error') or '')

            progress_bar = progress.get('progress')
            if progress_bar:
                sys.stdout.write(' ' + progress_bar)

            if not progress_id:
                sys.stdout.write('\n')
            sys.stdout.flush()
    if last_id:
        sys.stdout.write('\n')
        sys.stdout.flush()
    return not error


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
