import sys
import socket
import logging
import threading
from contextlib import closing

import click

from .client import APIError
from .threads import spawn_input_thread, spawn_output_thread


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

        process_exit = threading.Event()

        attach_params = {'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream': 1}

        with closing(client.attach_socket_raw(container, attach_params)) as sock:
            input_thread = spawn_input_thread(_tty_fd, sock, _exit_event)
            output_thread = spawn_output_thread(sock, process_exit)
            while True:
                if _exit_event.wait(.2):
                    client.stop(container, timeout=5)
                    try:
                        # just to be sure that output thread will exit normally
                        sock.shutdown(socket.SHUT_RDWR)
                    except IOError:
                        pass
                    break
                if process_exit.is_set():
                    _exit_event.set()
                    break
            input_thread.join()
            output_thread.join()
        exit_code = client.wait(container)
        if exit_code >= 0:
            sys.exit(exit_code)
    finally:
        client.remove_container(container, v=True, force=True)
        log.debug('run thread exited')
