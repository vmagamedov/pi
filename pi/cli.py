from ._requires import click

from .types import Meta
from .config import read_config
from .images import create_images_cli, construct_layers
from .context import Context
from .commands import create_commands_cli


def build_cli():
    config = read_config()

    meta = Meta()
    for obj in config:
        if isinstance(obj, Meta):
            meta = obj

    commands_cli = create_commands_cli(config)
    layers = construct_layers(config)
    images_cli = create_images_cli(layers)

    cli = click.CommandCollection(sources=[images_cli, commands_cli],
                                  help=meta.description)
    cli(obj=Context(layers))
