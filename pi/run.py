import sys
import signal
import socket
import os.path
import logging

from asyncio import Queue, CancelledError, Event
from asyncio import TimeoutError as AIOTimeoutError, wait_for

from ._requires import click

from .http import HTTPError
from .utils import terminate, sh_to_list
from .client import NotFound


log = logging.getLogger(__name__)


async def stdin_reader(fd, in_queue, *, loop):
    eof = Event(loop=loop)

    def cb():
        data = os.read(fd, 32)
        if not data:
            eof.set()
        in_queue.put_nowait(data)

    loop.add_reader(fd, cb)
    try:
        await eof.wait()
    finally:
        loop.remove_reader(fd)


async def stdout_writer(out_queue):
    while True:
        data = await out_queue.get()
        sys.stdout.write(data.decode('utf-8', 'replace'))
        sys.stdout.flush()


async def socket_reader(sock, out_queue, *, loop):
    while True:
        data = await loop.sock_recv(sock, 4096)
        if not data:
            break
        await out_queue.put(data)


async def socket_writer(sock, in_queue, *, loop):
    while True:
        data = await in_queue.get()
        await loop.sock_sendall(sock, data)


class _VolumeBinds:

    def visit(self, obj):
        return obj.accept(self)

    def visit_RO(self, _):
        return 'ro'

    def visit_RW(self, _):
        return 'rw'

    def visit_localpath(self, obj):
        from_ = os.path.abspath(obj.from_)
        to = os.path.abspath(obj.to)
        # FIXME: implement proper errors reporting
        assert os.path.exists(from_),\
            'Local path does not exists: {}'.format(from_)
        return '{}:{}:{}'.format(from_, to, self.visit(obj.mode))

    def visit_namedvolume(self, obj):
        to = os.path.abspath(obj.to)
        return '{}:{}:{}'.format(obj.name, to, self.visit(obj.mode))


def _volumes(volumes):
    return {os.path.abspath(vol.to): {} for vol in volumes}


def _volume_binds(volumes):
    transformer = _VolumeBinds()
    return [transformer.visit(v) for v in volumes]


def _exposed_ports(ports):
    return {'{}/{}'.format(p.port, p.proto): {} for p in ports}


def _port_binds(ports):
    return {'{}/{}'.format(e.port, e.proto): {'HostPort': e.as_,
                                              'HostIp': e.addr}
            for e in ports}


async def start(docker, image, command, *, init=None, tty=True,
                entrypoint=None, volumes=None, ports=None, environ=None,
                work_dir=None, network=None, network_alias=None, label=None):
    spec = {
        'Image': image.name,
        'Cmd': sh_to_list(command),
        'OpenStdin': True,
        'Tty': tty,
    }
    if ports:
        spec['ExposedPorts'] = _exposed_ports(ports)
    if environ:
        spec['Env'] = ['{}={}'.format(k, v) for k, v in (environ.items() or ())]
    if volumes:
        spec['Volumes'] = _volumes(volumes)
    if entrypoint is not None:
        spec['Entrypoint'] = entrypoint
    if work_dir:
        spec['WorkingDir'] = os.path.abspath(work_dir)
    if label:
        spec['Labels'] = {label: ''}

    host_config = {}
    if init:
        host_config['Init'] = True
    if volumes:
        host_config['Binds'] = _volume_binds(volumes)
    if ports:
        host_config['PortBindings'] = _port_binds(ports)
    if network:
        host_config['NetworkMode'] = network
    if host_config:
        spec['HostConfig'] = host_config

    networking_config = {}
    if network and network_alias:
        networking_config['EndpointsConfig'] = {
            network: {'Aliases': [network_alias]},
        }
    if networking_config:
        spec['NetworkingConfig'] = networking_config

    try:
        c = await docker.create_container(spec)
    except HTTPError as e:
        click.echo(e)
        return
    try:
        await docker.start(c['Id'])
    except HTTPError as e:
        click.echo(e)
        await docker.remove_container(c['Id'], params={
            'v': 'true', 'force': 'true',
        })
    else:
        return c


async def resize(client, container):
    width, height = click.get_terminal_size()
    try:
        await client.resize(container, height, width)
    except NotFound as e:
        log.debug('Failed to resize terminal: %s', e)


async def attach(client, container, stdin_fd, *, loop, wait_exit=10):
    params = {'logs': 1, 'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream': 1}
    async with client.attach_socket(container, params) as sock_io:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM,
                             fileno=sock_io.fileno())
        sock.setblocking(False)

        container_input = Queue(loop=loop)
        socket_writer_task = loop.create_task(
            socket_writer(sock, container_input, loop=loop))
        stdin_reader_task = loop.create_task(
            stdin_reader(stdin_fd, container_input, loop=loop))

        container_output = Queue(loop=loop)
        stdout_writer_task = loop.create_task(
            stdout_writer(container_output))
        socket_reader_task = loop.create_task(
            socket_reader(sock, container_output, loop=loop))

        exit_code = None
        try:
            exit_code = await client.wait(container)
        except CancelledError:
            await client.kill(container, signal.SIGINT)
            try:
                await wait_for(socket_reader_task, wait_exit, loop=loop)
            except AIOTimeoutError:
                await client.kill(container, signal.SIGKILL)

        await terminate(stdout_writer_task, loop=loop)
        await terminate(stdin_reader_task, loop=loop)
        await terminate(socket_reader_task, loop=loop)
        await terminate(socket_writer_task, loop=loop)
        return exit_code


async def run(client, docker, stdin_fd, tty, image, command, *, loop, init=None,
              volumes=None, ports=None, environ=None, work_dir=None,
              network=None, network_alias=None, wait_exit=3):
    c = await start(docker, image, command, init=init, tty=tty,
                    volumes=volumes,
                    ports=ports, environ=environ, work_dir=work_dir,
                    network=network, network_alias=network_alias)
    if c is None:
        return
    try:
        await resize(client, c)
        exit_code = await attach(client, c, stdin_fd, loop=loop,
                                 wait_exit=wait_exit)
        if exit_code is None:
            exit_code = await client.wait(c)
        return exit_code['StatusCode']

    finally:
        await docker.remove_container(c['Id'],
                                      params={'v': 'true', 'force': 'true'})
