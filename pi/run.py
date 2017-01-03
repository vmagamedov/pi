import sys
import signal
import socket
import os.path
import logging

from asyncio import Queue, CancelledError, Event, coroutine
from asyncio import TimeoutError as AIOTimeoutError, wait_for

from ._requires import click

from .utils import terminate
from .client import APIError, NotFound


log = logging.getLogger(__name__)


@coroutine
def stdin_reader(fd, in_queue, *, loop):
    eof = Event(loop=loop)

    def cb():
        data = os.read(fd, 32)
        if not data:
            eof.set()
        in_queue.put_nowait(data)

    loop.add_reader(fd, cb)
    try:
        yield from eof.wait()
    finally:
        loop.remove_reader(fd)


@coroutine
def stdout_writer(out_queue):
    while True:
        data = yield from out_queue.get()
        sys.stdout.write(data.decode('utf-8', 'replace'))
        sys.stdout.flush()


@coroutine
def socket_reader(sock, out_queue, *, loop):
    while True:
        data = yield from loop.sock_recv(sock, 4096)
        if not data:
            break
        yield from out_queue.put(data)


@coroutine
def socket_writer(sock, in_queue, *, loop):
    while True:
        data = yield from in_queue.get()
        yield from loop.sock_sendall(sock, data)


class _VolumeBinds:

    @classmethod
    def translate_binds(cls, volumes):
        self = cls()
        return dict(self.visit(vol) for vol in volumes)

    @classmethod
    def translate_volumes(cls, volumes):
        return [os.path.abspath(vol.to) for vol in volumes]

    def visit(self, obj):
        return obj.accept(self)

    def visit_RO(self, obj):
        return 'ro'

    def visit_RW(self, obj):
        return 'rw'

    def visit_localpath(self, obj):
        from_ = os.path.abspath(obj.from_)
        to = os.path.abspath(obj.to)
        # FIXME: implement proper errors reporting
        assert os.path.exists(from_),\
            'Local path does not exists: {}'.format(from_)
        return from_, {'bind': to, 'mode': self.visit(obj.mode)}

    def visit_namedvolume(self, obj):
        to = os.path.abspath(obj.to)
        return obj.name, {'bind': to, 'mode': self.visit(obj.mode)}


def _port_binds(ports):
    return {'{}/{}'.format(e.port, e.proto): {'HostPort': e.as_,
                                              'HostIp': e.addr}
            for e in ports}


@coroutine
def start(client, image, command, *, entrypoint=None,
          volumes=None, ports=None, environ=None, work_dir=None,
          network=None, network_alias=None, label=None):
    volumes = volumes or []
    container_volumes = _VolumeBinds.translate_volumes(volumes)
    container_volume_binds = _VolumeBinds.translate_binds(volumes)

    ports = ports or []
    container_ports = [(e.port, e.proto) for e in ports]
    container_port_binds = _port_binds(ports)

    work_dir = os.path.abspath(work_dir) if work_dir is not None else None
    labels = [label] if label is not None else []

    host_config = client.create_host_config(
        binds=container_volume_binds,
        port_bindings=container_port_binds,
        network_mode=network,
    )
    networking_config = None
    if network_alias is not None:
        networking_config = client.create_networking_config(endpoints_config={
            network: {'Aliases': [network_alias]},
        })
    try:
        c = yield from client.create_container(
            image=image.name,
            command=command,
            stdin_open=True,
            tty=True,
            ports=container_ports,
            environment=environ,
            volumes=container_volumes,
            entrypoint=entrypoint,
            working_dir=work_dir,
            labels=labels,
            host_config=host_config,
            networking_config=networking_config,
        )
    except APIError as e:
        click.echo(e.explanation)
        return
    try:
        yield from client.start(c)
    except APIError as e:
        click.echo(e.explanation)
        yield from client.remove_container(c, v=True, force=True)
    else:
        return c


@coroutine
def resize(client, container):
    width, height = click.get_terminal_size()
    try:
        yield from client.resize(container, height, width)
    except NotFound as e:
        log.debug('Failed to resize terminal: %s', e)


@coroutine
def attach(client, container, input_fd, *, loop, wait_exit=10):
    params = {'logs': 1, 'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream': 1}
    with (yield from client.attach_socket(container, params)) as sock_io:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM,
                             fileno=sock_io.fileno())
        sock.setblocking(False)

        container_input = Queue(loop=loop)
        socket_writer_task = loop.create_task(
            socket_writer(sock, container_input, loop=loop))
        stdin_reader_task = loop.create_task(
            stdin_reader(input_fd, container_input, loop=loop))

        container_output = Queue(loop=loop)
        stdout_writer_task = loop.create_task(
            stdout_writer(container_output))
        socket_reader_task = loop.create_task(
            socket_reader(sock, container_output, loop=loop))

        exit_code = None
        try:
            exit_code = yield from client.wait(container)
        except CancelledError:
            yield from client.kill(container, signal.SIGINT)
            try:
                yield from wait_for(socket_reader_task, wait_exit, loop=loop)
            except AIOTimeoutError:
                yield from client.kill(container, signal.SIGKILL)

        yield from terminate(stdout_writer_task, loop=loop)
        yield from terminate(stdin_reader_task, loop=loop)
        yield from terminate(socket_reader_task, loop=loop)
        yield from terminate(socket_writer_task, loop=loop)
        return exit_code


@coroutine
def run(client, input_fd, image, command, *, loop,
        volumes=None, ports=None, environ=None, work_dir=None, network=None,
        network_alias=None, wait_exit=3):
    c = yield from start(client, image, command, volumes=volumes,
                         ports=ports, environ=environ, work_dir=work_dir,
                         network=network, network_alias=network_alias)
    if c is None:
        return
    try:
        yield from resize(client, c)
        exit_code = yield from attach(client, c, input_fd, loop=loop,
                                      wait_exit=wait_exit)
        if exit_code is None:
            exit_code = yield from client.wait(c)
        return exit_code

    finally:
        yield from client.remove_container(c, v=True, force=True)
