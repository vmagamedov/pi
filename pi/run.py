import sys
import socket
import os.path
import logging
from asyncio import Queue, CancelledError

from ._requires import click

from .client import APIError
from .actors import receive, send, MessageType, terminate

log = logging.getLogger(__name__)

LC_CTYPE = 'en_US.UTF-8'


def docker_run(client, docker_image, command, environ, user, work_dir, volumes,
               ports, links, _exit_event, _tty_fd):
    if _tty_fd is not None:
        environ = dict(environ or {}, LC_CTYPE=LC_CTYPE)

    container_volumes = []
    volume_bindings = {}
    for host_path, dest_path, mode in volumes:
        container_volumes.append(dest_path)
        volume_bindings[host_path] = {'bind': dest_path, 'mode': mode}

    container_ports = []
    port_bindings = {}
    for ext_ip, ext_port, int_port in ports:
        container_ports.append(int_port)
        port_bindings[int_port] = (ext_ip, ext_port)

    link_bindings = [(v, k) for k, v in links.items()]

    try:
        container = client.create_container(
            docker_image,
            command=command,
            environment=environ,
            user=user,
            tty=True,
            stdin_open=True,
            ports=container_ports,
            volumes=container_volumes,
            working_dir=work_dir or None,
        )
    except APIError as e:
        click.echo(e.explanation)
        return

    try:
        try:
            client.start(container,
                         binds=volume_bindings,
                         port_bindings=port_bindings,
                         links=link_bindings)
        except APIError as e:
            click.echo(e.explanation)
            return

        width, height = click.get_terminal_size()
        client.resize(container, width, height)
        while True:
            if _exit_event.wait(.2):
                client.stop(container, timeout=5)
                break
        exit_code = client.wait(container)
        if exit_code >= 0:
            sys.exit(exit_code)
    finally:
        client.remove_container(container, v=True, force=True)
        log.debug('run thread exited')


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


def run(self, client, input_fd, image, command, *,
        volumes=None, ports=None, work_dir=None,
        wait_exit=3):
    volumes = volumes or []
    container_volumes = _VolumeBinds.translate_volumes(volumes)
    container_volume_binds = _VolumeBinds.translate_binds(volumes)

    ports = ports or []
    container_ports = [(e.port, e.proto) for e in ports]
    container_port_binds = _port_binds(ports)

    work_dir = os.path.abspath(work_dir) if work_dir is not None else None

    try:
        c = yield from self.exec(client.create_container,
                                 image=image.name,
                                 command=command,
                                 stdin_open=True,
                                 tty=True,
                                 ports=container_ports,
                                 volumes=container_volumes,
                                 working_dir=work_dir)
    except APIError as e:
        click.echo(e.explanation)
        return
    try:
        try:
            yield from self.exec(client.start, c,
                                 binds=container_volume_binds,
                                 port_bindings=container_port_binds)
        except APIError as e:
            click.echo(e.explanation)
            return

        width, height = click.get_terminal_size()
        yield from self.exec(client.resize, c, height, width)

        params = {'logs': 1, 'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream': 1}
        with (yield from self.exec(client.attach_socket, c, params)) as sock_io:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM,
                                 fileno=sock_io.fileno())
            sock.setblocking(False)

            socket_writer_proc = self.spawn(socket_writer, sock)
            input_proc = self.spawn(input, input_fd, socket_writer_proc)

            output_proc = self.spawn(output)
            socket_reader_proc = self.spawn(socket_reader, sock, output_proc)

            try:
                yield from self.wait([socket_reader_proc])
            except CancelledError:
                yield from self.exec(client.stop, c, timeout=wait_exit)
                yield from terminate(socket_reader_proc)

            yield from terminate(output_proc)
            yield from terminate(input_proc)
            yield from terminate(socket_writer_proc)

        exit_code = yield from self.exec(client.wait, c)
        return exit_code

    finally:
        yield from self.exec(client.remove_container, c, v=True, force=True)
