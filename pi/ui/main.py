import logging

from .._requires import click

from ..types import Meta
from ..config import read_config
from ..images import get_images
from ..environ import Environ
from ..console import configure_logging
from ..services import get_services

from .image import create_images_cli
from .custom import create_commands_cli
from .service import create_service_cli


log = logging.getLogger(__name__)


class UI(click.CommandCollection):

    def __init__(self, config, meta, core, custom, **kwargs):
        params = [click.Option(['--debug'], is_flag=True,
                               help='Run in debug mode')]
        super().__init__(sources=(core + custom), callback=self.callback,
                         params=params, help=meta.description, **kwargs)
        self._meta = meta
        self._config = config
        self._core = core
        self._custom = custom

    def callback(self, debug):
        configure_logging(debug)

        ctx = click.get_current_context()
        images = get_images(self._config)
        services = get_services(self._config)
        ctx.obj = Environ(self._meta, images, services)
        log.debug('Environment configured')

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
            click_commands = [self.get_command(ctx, c) for c in commands]
            rows = []
            if any(isinstance(c, click.MultiCommand) for c in click_commands):
                for cmd in click_commands:
                    prefix = '+' if isinstance(cmd, click.MultiCommand) else ' '
                    rows.append((prefix + ' ' + cmd.name, cmd.short_help or ''))
            else:
                for cmd in click_commands:
                    rows.append((cmd.name, cmd.short_help or ''))
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

    images_cli = create_images_cli()
    services_cli = create_service_cli()
    commands_cli = create_commands_cli(config)

    return UI(config, meta, [images_cli, services_cli], [commands_cli])
