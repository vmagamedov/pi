import asyncio

import click

from .run import printer, input
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


def _coro(fd, *, loop):
    printer_proc = spawn(printer, loop=loop)
    input_proc = spawn(input, [fd, printer_proc], loop=loop)
    yield from asyncio.sleep(3)
    yield from terminate(input_proc)
    yield from terminate(printer_proc)
    print('-- terminated')


@ui.command()
def coro():
    loop = asyncio.get_event_loop()
    with raw_stdin() as fd:
        loop.run_until_complete(_coro(fd, loop=loop))
