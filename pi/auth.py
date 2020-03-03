import re
import json
import base64
import codecs
import os.path
import asyncio
import subprocess


_PREFIX = 'docker-credential-'


def read_config():
    path = os.path.expanduser('~/.docker/config.json')
    if not os.path.exists(path):
        return {}
    with codecs.open(path, encoding='utf-8') as f:
        json_data = f.read()
    return json.loads(json_data)


async def _read_creds(creds_store, server):
    if not re.match(r'^\w+$', creds_store, re.ASCII):
        raise ValueError('Invalid credsStore: {!r}'.format(creds_store))

    proc = await asyncio.create_subprocess_exec(
        _PREFIX + creds_store, 'get',
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(server.encode('ascii'))
    if proc.returncode != 0:
        return None
    else:
        data = json.loads(stdout)
        return {
            'Username': data['Username'],
            'Password': data['Secret'],
            'ServerAddress': server,
        }


def _decode_auth(auth_data, server):
    auth_data_decoded = base64.b64decode(auth_data).decode('utf-8')
    username, _, password = auth_data_decoded.partition(':')
    return {
        'Username': username,
        'Password': password,
        'ServerAddress': server,
    }


async def resolve_auth(config, server):
    config_auths = config.get('auths')
    if config_auths is None:
        return None

    server_auth = config_auths.get(server)
    if server_auth is not None:
        auth_data = server_auth.get('auth')
        if auth_data is not None:
            return _decode_auth(auth_data, server)

    creds_store = config.get('credsStore')
    if creds_store is not None:
        return await _read_creds(creds_store, server)

    return None


def server_name(image_name):
    registry, _, name = image_name.partition('/')
    if not name:
        return 'docker.io'
    else:
        return registry


def encode_header(auth):
    json_data = json.dumps(auth)
    return base64.urlsafe_b64encode(json_data.encode('ascii'))
