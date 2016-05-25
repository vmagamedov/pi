import os
import sys
import socket
import logging
from asyncio import Queue, CancelledError

import click

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


def run(self, client, input_fd, image, command):
    try:
        c = yield from self.exec(client.create_container,
                                 image=image,
                                 command=command,
                                 tty=True,
                                 stdin_open=True)
    except APIError as e:
        click.echo(e.explanation)
        return
    try:
        try:
            yield from self.exec(client.start, c)
        except APIError as e:
            click.echo(e.explanation)
            return

        width, height = click.get_terminal_size()
        yield from self.exec(client.resize, c, width, height)

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
                yield from terminate(socket_reader_proc)

            yield from terminate(output_proc)
            yield from terminate(input_proc)
            yield from terminate(socket_writer_proc)

    finally:
        yield from self.exec(client.remove_container, c, v=True, force=True)
