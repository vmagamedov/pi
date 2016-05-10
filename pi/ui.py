import signal
import asyncio

import click

from .run import run
from .utils import cached_property
from .client import get_client
from .actors import spawn, terminator
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
        loop.add_signal_handler(signal.SIGINT,
                                terminator([run_proc], loop=loop))

        # FIXME: handle Ctrl+C and normal exit properly
        # run_proc.task.add_done_callback(lambda f: loop.stop())
        loop.run_forever()
        # loop.run_until_complete(run_proc.task)
