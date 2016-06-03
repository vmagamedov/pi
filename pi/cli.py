import click

from .config import read_config
from .images import create_images_cli, construct_layers
from .context import Context
from .commands import create_commands_cli


def build_cli():
    config = read_config()
    commands_cli = create_commands_cli(config)

    layers = construct_layers(config)
    images_cli = create_images_cli(layers)

    cli = click.CommandCollection(sources=[images_cli, commands_cli])
    cli(obj=Context(layers))
