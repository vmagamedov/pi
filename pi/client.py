import http.client
import urllib.parse

import docker.errors
from docker import AutoVersionClient


APIError = docker.errors.APIError


class Client(AutoVersionClient):

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
