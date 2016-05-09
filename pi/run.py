import os
import sys
import logging
from asyncio import Queue

import click

from .client import APIError
from .actors import receive, send, MessageType


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


INPUT = MessageType('INPUT')
OUTPUT = MessageType('OUTPUT')


def printer(self):
    while True:
        type_, value = yield from receive(self)
        if type_ in {INPUT, OUTPUT}:
            sys.stdout.write(value)
            sys.stdout.flush()
        else:
            raise TypeError(type_)


def input(self, fd, dst):
    q = Queue()

    def cb():
        q.put_nowait(os.read(fd, 32))

    self.loop.add_reader(fd, cb)
    try:
        while True:
            data = yield from q.get()
            yield from send(dst, INPUT, data.decode('utf-8'))
    finally:
        self.loop.remove_reader(fd)


def output(self, sock, dst):
    while True:
        data = yield from self.loop.sock_recv(sock, 4096)
        if not data:
            break
        yield from send(dst, OUTPUT, data.decode('utf-8'))
