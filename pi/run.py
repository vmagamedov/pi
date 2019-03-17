import sys
import os.path
import logging
import asyncio

from ._requires import click

from .http import HTTPError
from .utils import sh_to_list


log = logging.getLogger(__name__)


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


async def resize(docker, id_):
    # TODO: maybe set also $LINES and $COLUMNS variables, add SIGWINCH handler
    width, height = click.get_terminal_size()
    try:
        await docker.resize(id_, params={'w': str(width), 'h': str(height)})
    except HTTPError as e:
        log.debug('Failed to resize terminal: %s', e)


class StdIOProtocol(asyncio.Protocol):
    transport: asyncio.Transport

    def __init__(self, http_proto=None):
        self.http_proto = http_proto

    def connection_made(self, transport):
        self.transport = transport

    def pause_writing(self):
        self.http_proto.transport.pause_reading()

    def resume_writing(self):
        self.http_proto.transport.resume_reading()

    def data_received(self, data):
        self.http_proto.transport.write(data)


async def attach(docker, id_, *, loop):
    stdin_proto = StdIOProtocol()
    await loop.connect_read_pipe(lambda: stdin_proto, sys.stdin)
    stdin_proto.transport.pause_reading()

    stdout_proto = StdIOProtocol()
    await loop.connect_write_pipe(lambda: stdout_proto, sys.stdout)

    async with docker.attach(
        id_, stdin_proto, stdout_proto,
        params={'logs': '1', 'stream': '1',
                'stdin': '1', 'stdout': '1', 'stderr': '1'}
    ) as http_proto:
        stdin_proto.http_proto = http_proto
        stdout_proto.http_proto = http_proto

        stdin_proto.transport.resume_reading()
        await http_proto.wait_closed()


async def run(client, docker, tty, image, command, *, loop, init=None,
              volumes=None, ports=None, environ=None, work_dir=None,
              network=None, network_alias=None):
    c = await start(docker, image, command, init=init, tty=tty,
                    volumes=volumes,
                    ports=ports, environ=environ, work_dir=work_dir,
                    network=network, network_alias=network_alias)
    if c is None:
        return
    try:
        await resize(docker, c['Id'])
        await attach(docker, c['Id'], loop=loop)
        exit_code = await client.wait(c)
        return exit_code['StatusCode']

    finally:
        await docker.remove_container(c['Id'],
                                      params={'v': 'true', 'force': 'true'})
