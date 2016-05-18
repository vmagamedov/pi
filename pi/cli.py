import click

from .config import read_config
from .images import build_images_cli
from .context import DockerMixin
from .commands import build_commands_cli


class Context(DockerMixin):
    pass


def build_cli():
    config = read_config()
    images_cli = build_images_cli(config)
    commands_cli = build_commands_cli(config)

    cli = click.CommandCollection(sources=[images_cli, commands_cli])
    cli(obj=Context())
