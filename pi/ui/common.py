import sys
import signal
import asyncio

from .._requires import click


SIGNALS = (signal.SIGINT, signal.SIGTERM)


class ExtGroup(click.Group):

    def __init__(self, *args, ext_help=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ext_help = ext_help

    def parse_args(self, ctx, args):
        if not args:
            click.echo(ctx.get_help(), color=ctx.color)
            ctx.exit()
        return super().parse_args(ctx, args)

    def format_help_text(self, ctx, formatter):
        super().format_help_text(ctx, formatter)
        if self.ext_help is not None:
            self.ext_help(ctx, formatter)


def _exit_handler(sig_num):
    msg = 'Interrupted!' if sig_num == signal.SIGINT else 'Terminated!'
    click.echo(msg, file=sys.stderr, nl=True)
    raise SystemExit(128 + sig_num)


async def _invoke(callback, *args, **kwargs):
    loop = asyncio.get_running_loop()
    for sig_num in SIGNALS:
        loop.add_signal_handler(sig_num, _exit_handler, sig_num)
    try:
        return await callback(*args, **kwargs)
    finally:
        for sig_num in SIGNALS:
            loop.remove_signal_handler(sig_num)


def _async(callback):
    def wrapper(*args, **kwargs):
        return asyncio.run(_invoke(callback, *args, **kwargs))
    return wrapper


class AsyncCommand(click.Command):

    def __init__(self, *args, callback, **kwargs):
        super().__init__(*args, callback=_async(callback), **kwargs)


class AsyncProxyCommand(AsyncCommand):

    def parse_args(self, ctx, args):
        ctx.args = args

    def invoke(self, ctx):
        if self.callback is not None:
            ctx.invoke(self.callback, args=ctx.args)
