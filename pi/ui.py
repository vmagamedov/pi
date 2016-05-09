import socket
import asyncio

import click

from .run import printer, input, output
from .utils import cached_property
from .client import get_client
from .actors import spawn, terminate
from .console import raw_stdin


class Context(object):

    @cached_property
    def client(self):
        return get_client()


@click.group()
@click.pass_context
def ui(ctx):
    ctx.obj = Context()


def _coro1(fd, *, loop):
    printer_proc = spawn(printer, loop=loop)
    input_proc = spawn(input, [fd, printer_proc], loop=loop)
    yield from asyncio.sleep(3)
    yield from terminate(input_proc)
    yield from terminate(printer_proc)
    print('-- terminated')


@ui.command()
def coro1():
    loop = asyncio.get_event_loop()
    with raw_stdin() as fd:
        loop.run_until_complete(_coro1(fd, loop=loop))


def _coro2(sock, *, loop):
    printer_proc = spawn(printer, loop=loop)
    output_proc = spawn(output, [sock, printer_proc], loop=loop)
    yield from asyncio.sleep(3)
    yield from terminate(output_proc)
    yield from terminate(printer_proc)
    print('-- terminated')


@ui.command()
@click.argument('container')
@click.pass_context
def coro2(ctx, container):
    loop = asyncio.get_event_loop()
    with ctx.obj.client.attach_socket(container) as sock_io:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM,
                             fileno=sock_io.fileno())
        sock.setblocking(False)
        loop.run_until_complete(_coro2(sock, loop=loop))
