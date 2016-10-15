import re
import sys
import json
import logging

from asyncio import coroutine


from ._requires.docker import Client, errors


APIError = errors.APIError

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


def echo_build_progress(client, output):
    error = False
    latest_container = None
    try:
        for line in output:
            log.debug(line)
            # FIXME: There is a bug in docker or docker-py: possibility
            # of more than one chunks in one line.
            chunks = line.decode('utf-8').splitlines()
            for chunk in chunks:
                status = json.loads(chunk)
                if 'stream' in status:
                    sys.stdout.write(status['stream'])
                    match = re.search(u'Running in ([0-9a-f]+)',
                                      status['stream'])
                    if match:
                        latest_container = match.group(1)
                elif 'error' in status:
                    error = True
                    sys.stdout.write(status['error'])
        return not error
    except BaseException as original_exc:
        try:
            if latest_container is not None:
                sys.stdout.write('Stopping current container {}...'
                                 .format(latest_container))
                client.stop(latest_container, 5)
                client.remove_container(latest_container)
        except Exception:
            log.exception('Failed to delete current container')
        finally:
            raise original_exc


def get_client():
    return Client.from_env()


class AsyncClient:

    def __init__(self, *, loop):
        self._client = Client.from_env()
        self._loop = loop

    @coroutine
    def _exec(self, func, *args):
        result = yield from self._loop.run_in_executor(None, func, *args)
        return result

    def images(self):
        return self._exec(self._client.images)
