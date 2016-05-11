import click

from .config import read_config
from .images import build_images_cli
from .context import DockerMixin
from .commands import build_commands_cli


class Context(DockerMixin):
    pass


@click.command()
@click.pass_context
def ping(ctx):
    from .run import run
    from .actors import init
    from .console import raw_stdin

    with raw_stdin() as fd:
        init(run, ctx.obj.client, fd)


def build_cli():
    config = read_config()
    images_cli = build_images_cli(config)
    commands_cli = build_commands_cli(config)

    # temp
    images_cli.add_command(ping)

    cli = click.CommandCollection(sources=[images_cli, commands_cli])
    cli(obj=Context())
