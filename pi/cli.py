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
    import signal
    import asyncio
    from .run import run
    from .actors import spawn, Terminator
    from .console import raw_stdin

    loop = asyncio.get_event_loop()
    with raw_stdin() as fd:
        run_proc = spawn(run, [ctx.obj.client, fd], loop=loop)

        terminator = Terminator([signal.SIGINT], [run_proc], loop=loop)
        terminator.install()

        loop.run_forever()


def build_cli():
    config = read_config()
    images_cli = build_images_cli(config)
    commands_cli = build_commands_cli(config)

    # temp
    images_cli.add_command(ping)

    cli = click.CommandCollection(sources=[images_cli, commands_cli])
    cli(obj=Context())
