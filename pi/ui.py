import signal
import asyncio

import click

from .run import run
from .utils import cached_property
from .client import get_client
from .actors import spawn, Terminator
from .console import raw_stdin


class Context(object):

    @cached_property
    def client(self):
        return get_client()


@click.group()
@click.pass_context
def ui(ctx):
    ctx.obj = Context()


@ui.command()
@click.pass_context
def coro(ctx):
    loop = asyncio.get_event_loop()
    with raw_stdin() as fd:
        run_proc = spawn(run, [ctx.obj.client, fd], loop=loop)

        terminator = Terminator([signal.SIGINT], [run_proc], loop=loop)
        terminator.install()

        loop.run_forever()
