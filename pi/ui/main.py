from functools import partial

from .._requires import click

from ..types import Meta
from ..config import read_config
from ..images import construct_layers
from ..context import Context
from ..services import get_services

from .image import create_images_cli
from .custom import create_commands_cli
from .service import create_service_cli


class UI(click.CommandCollection):

    def __init__(self, core, custom, **kwargs):
        super().__init__(sources=(core + custom), **kwargs)
        self._core = core
        self._custom = custom

    def _list_core_commands(self, ctx):
        rv = set()
        for source in self._core:
            rv.update(source.list_commands(ctx))
        return sorted(rv)

    def _list_custom_commands(self, ctx):
        rv = set()
        for source in self._custom:
            rv.update(source.list_commands(ctx))
        return sorted(rv)

    def format_commands(self, ctx, formatter):

        def get_rows(commands):
            rows = []
            for sub_command in commands:
                cmd = self.get_command(ctx, sub_command)
                prefix = '+' if isinstance(cmd, click.MultiCommand) else ' '
                rows.append((prefix + ' ' + sub_command, cmd.short_help or ''))
            return rows

        core = get_rows(self._list_core_commands(ctx))
        custom = get_rows(self._list_custom_commands(ctx))
        if core:
            with formatter.section('Core commands'):
                formatter.write_dl(core)
        if custom:
            with formatter.section('Custom commands'):
                formatter.write_dl(custom)


def build_ui():
    config = read_config()

    meta = Meta()
    for obj in config:
        if isinstance(obj, Meta):
            meta = obj

    layers = construct_layers(config)
    services = get_services(config)

    images_cli = create_images_cli(layers)
    services_cli = create_service_cli()
    commands_cli = create_commands_cli(config)

    ui = UI([images_cli, services_cli], [commands_cli], help=meta.description)
    return partial(ui, obj=Context(meta, layers, services))
