import sys
import socket
import os.path
import logging
from asyncio import Queue, CancelledError

from ._requires import click

from .client import APIError, NotFound
from .actors import receive, send, MessageType, terminate


log = logging.getLogger(__name__)

BYTES = MessageType('BYTES')


def input(self, fd, dst):
    q = Queue()

    def cb():
        q.put_nowait(os.read(fd, 32))

    self.loop.add_reader(fd, cb)
    try:
        while True:
            data = yield from q.get()
            if not data:
                break
            yield from send(dst, BYTES, data)
    finally:
        self.loop.remove_reader(fd)


def output(self):
    while True:
        type_, value = yield from receive(self)
        if type_ is BYTES:
            sys.stdout.write(value.decode('utf-8', 'replace'))
            sys.stdout.flush()
        else:
            raise TypeError(type_)


def socket_reader(self, sock, dst):
    while True:
        data = yield from self.loop.sock_recv(sock, 4096)
        if not data:
            break
        yield from send(dst, BYTES, data)


def socket_writer(self, sock):
    while True:
        type_, value = yield from receive(self)
        if type_ is BYTES:
            yield from self.loop.sock_sendall(sock, value)
        else:
            raise TypeError(type_)


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


def start(self, client, image, command, *, entrypoint=None,
          volumes=None, ports=None, work_dir=None, hosts=None, label=None):
    volumes = volumes or []
    container_volumes = _VolumeBinds.translate_volumes(volumes)
    container_volume_binds = _VolumeBinds.translate_binds(volumes)

    ports = ports or []
    container_ports = [(e.port, e.proto) for e in ports]
    container_port_binds = _port_binds(ports)

    work_dir = os.path.abspath(work_dir) if work_dir is not None else None
    labels = [label] if label is not None else []

    try:
        c = yield from self.exec(client.create_container,
                                 image=image.name,
                                 command=command,
                                 stdin_open=True,
                                 tty=True,
                                 ports=container_ports,
                                 volumes=container_volumes,
                                 entrypoint=entrypoint,
                                 working_dir=work_dir,
                                 labels=labels,
                                 host_config=client.create_host_config(
                                     binds=container_volume_binds,
                                     port_bindings=container_port_binds,
                                     extra_hosts=hosts
                                 ))
    except APIError as e:
        click.echo(e.explanation)
        return
    try:
        yield from self.exec(client.start, c)
    except APIError as e:
        click.echo(e.explanation)
        yield from self.exec(client.remove_container, c, v=True, force=True)
    else:
        return c


def resize(self, client, container):
    width, height = click.get_terminal_size()
    try:
        yield from self.exec(client.resize, container, height, width)
    except NotFound as e:
        log.debug('Failed to resize terminal: %s', e)


def attach(self, client, container, input_fd, *, wait_exit=3):
    params = {'logs': 1, 'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream': 1}
    with (yield from self.exec(client.attach_socket, container, params)) \
            as sock_io:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM,
                             fileno=sock_io.fileno())
        sock.setblocking(False)

        socket_writer_proc = self.spawn(socket_writer, sock)
        input_proc = self.spawn(input, input_fd, socket_writer_proc)

        output_proc = self.spawn(output)
        socket_reader_proc = self.spawn(socket_reader, sock, output_proc)

        exit_code = None
        try:
            exit_code = yield from self.exec(client.wait, container)
        except CancelledError:
            yield from self.exec(client.stop, container, timeout=wait_exit)
            yield from terminate(socket_reader_proc)

        yield from terminate(output_proc)
        yield from terminate(input_proc)
        yield from terminate(socket_reader_proc)
        yield from terminate(socket_writer_proc)
        return exit_code


def run(self, client, input_fd, image, command, *,
        volumes=None, ports=None, work_dir=None, hosts=None,
        wait_exit=3):
    c = yield from start(self, client, image, command, volumes=volumes,
                         ports=ports, work_dir=work_dir, hosts=hosts)
    if c is None:
        return
    try:
        yield from resize(self, client, c)
        exit_code = yield from attach(self, client, c, input_fd,
                                      wait_exit=wait_exit)
        if exit_code is None:
            exit_code = yield from self.exec(client.wait, c)
        return exit_code

    finally:
        yield from self.exec(client.remove_container, c, v=True, force=True)
