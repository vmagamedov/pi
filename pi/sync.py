import os
import plistlib
import socket
import asyncio

from ._requires.docker.errors import NotFound

from ._res import PATH


async def start_server(env):
    uid = 'pi-sync-deadbeef'
    try:
        vol = await env.client.inspect_volume(uid)
    except NotFound:
        vol = await env.client.create_volume(uid)
        print('Created Docker volume: {}'.format(uid))

    try:
        c = await env.client.inspect_container(uid)
    except NotFound:
        c = await env.client.create_container(
            name=uid,
            detach=True,
            image='eugenmayer/unison:latest',
            ports={'5000/tcp': {}},
            environment={
                'VOLUME': '/data',
                'OWNER_UID': 1000,
                # 'MAX_INOTIFY_WATCHES': 65536,
            },
            volumes=['/data'],
            labels=[uid],
            host_config=env.client.create_host_config(
                binds={vol['Name']: {'bind': '/data',
                                     'mode': 'rw'}},
                port_bindings={'5000/tcp': {'HostPort': 0,
                                            'HostIp': '127.0.0.1'}},
            ),
        )
        print('Created Unison container')
        await env.client.start(c)
        print('Started Unison server')
        c = await env.client.inspect_container(uid)
    else:
        if c['State'] != 'running':
            await env.client.start(c)
            print('Started Unison server')
            c = await env.client.inspect_container(uid)

    port = int(c['NetworkSettings']['Ports']['5000/tcp'][0]['HostPort'])
    return port


async def _wait_sock(port, *, loop):
    with socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM) as sock:
        sock.setblocking(False)
        while True:
            try:
                await loop.sock_connect(sock, ('127.0.0.1', port))
            except BaseException as e:
                print(e)
                await asyncio.sleep(1, loop=loop)
            else:
                sock.shutdown(socket.SHUT_RDWR)
                return


async def start_client(port, agent=True, *, loop):
    await _wait_sock(port, loop=loop)

    server_url = 'socket://localhost:{}'.format(port)

    args = [
        'unison',
        '-prefer', '.',
        '-silent',
        # '-batch',
        '-repeat', 'watch',
        '.',  # source
        server_url,  # destination
    ]
    env = dict(os.environ,
               PATH='{}:{}'.format(PATH, os.environ['PATH']))
    if agent:
        job = {
            'Label': 'com.github.vmagamedov.pi.sync.deadbeef',
            'ProgramArguments': args,
            'RunAtLoad': False,
            'OnDemand': True,
        }
        print(plistlib.dumps(job).decode('utf-8'))
    else:
        print('Starting Unison client for {}'.format(server_url))
        process = await asyncio.create_subprocess_exec(*args,
                                                       env=env, loop=loop)
        await process.wait()

    # print(plistlib.dumps(jobs).decode('utf-8'))
    # find ~/Library/LaunchAgents/
