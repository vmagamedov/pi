from .._requires import click

from ..types import Meta
from ..config import read_config
from ..images import construct_layers
from ..services import get_services
from ..context import Context

from .image import create_images_cli
from .custom import create_commands_cli
from .service import create_service_cli


def build_cli():
    config = read_config()

    meta = Meta()
    for obj in config:
        if isinstance(obj, Meta):
            meta = obj

    layers = construct_layers(config)
    images_cli = create_images_cli(layers)

    services = get_services(config)
    services_cli = create_service_cli()

    commands_cli = create_commands_cli(config)

    cli = click.CommandCollection(sources=[images_cli, services_cli,
                                           commands_cli],
                                  help=meta.description)
    cli(obj=Context(meta, layers, services))
