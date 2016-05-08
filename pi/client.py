import re
import sys
import json
import logging
import http.client
import urllib.parse

import docker.errors
from docker import Client as _Client


APIError = docker.errors.APIError

log = logging.getLogger(__name__)


class Client(_Client):

    def attach_socket_raw(self, container, params=None):
        """Returns real writable socket, usable to send stdin"""
        if params is None:
            params = {'stdout': 1, 'stderr': 1, 'stream': 1}

        if isinstance(container, dict):
            container = container['Id']

        url = self._url('/containers/{0}/attach'.format(container))
        netloc = urllib.parse.urlsplit(self.base_url).netloc
        conn = http.client.HTTPConnection(netloc)
        conn.request('POST', url, urllib.parse.urlencode(params), {
            'Content-Type': 'application/x-www-form-urlencoded',
        })
        resp = http.client.HTTPResponse(conn.sock, method='POST')
        resp.begin()
        return conn.sock


def echo_download_progress(output):
    last_id = None
    for line in output:
        log.debug(line)
        progress = json.loads(line.decode('utf-8'))

        progress_id = progress.get('id')
        if last_id:
            if progress_id == last_id:
                sys.stdout.write('\x1b[2K\r')
            elif not progress_id or progress_id != last_id:
                sys.stdout.write('\n')
        last_id = progress_id

        if progress_id:
            sys.stdout.write('{}: '.format(progress_id))
        sys.stdout.write(progress.get('status') or progress.get('error') or '')

        progress_bar = progress.get('progress')
        if progress_bar:
            sys.stdout.write(' ' + progress_bar)

        if not progress_id:
            sys.stdout.write('\n')
        sys.stdout.flush()
    if last_id:
        sys.stdout.write('\n')
        sys.stdout.flush()


def echo_build_progress(client, output):
    latest_container = None
    try:
        for line in output:
            log.debug(line)
            status = json.loads(line.decode('utf-8'))
            if 'stream' in status:
                sys.stdout.write(status['stream'])
                match = re.search(u'Running in ([0-9a-f]+)', status['stream'])
                if match:
                    latest_container = match.group(1)
            elif 'error' in status:
                sys.stdout.write(status['error'])
    except BaseException as original_exc:
        try:
            if latest_container is not None:
                sys.stdout.write('Stopping current container {}...'
                                 .format(latest_container))
                client.stop(latest_container, 5)
                client.remove_container(latest_container)
        except:
            log.exception('Failed to delete current container')
        finally:
            raise original_exc


def get_client():
    return Client('http+unix:///var/tmp/docker.sock')
