import click

from .utils import cached_property
from .client import get_client


class Context(object):

    @cached_property
    def client(self):
        return get_client()


@click.group()
@click.pass_context
def ui(ctx):
    ctx.obj = Context()
