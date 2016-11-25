import sys

from asyncio import coroutine

from .._requires import click
from .._requires import jinja2

from .._res import DUMB_INIT_LOCAL_PATH

from ..run import run
from ..types import CommandType, LocalPath, Mode
from ..utils import sh_to_list
from ..images import get_docker_image
from ..context import async_cmd
from ..console import config_tty
from ..network import ensure_network
from ..resolve import resolve
from ..services import ensure_running


DUMB_INIT_REMOTE_PATH = '/.pi-dumb-init'


class ProxyCommand(click.MultiCommand):

    def parse_args(self, ctx, args):
        ctx.args = args

    def invoke(self, ctx):
        if self.callback is not None:
            ctx.invoke(self.callback, ctx.args)


def create_groups(groups_parts):
    groups = []
    mapping = {}
    for parts in groups_parts:
        parent = None
        key = tuple()
        for part in parts:
            key += (part,)
            if key not in mapping:
                group = mapping[key] = click.Group(part)
                if parent is None:
                    groups.append(group)
                else:
                    parent.add_command(group)
                parent = group
            else:
                parent = mapping[key]
    return groups, mapping


TYPES_MAP = {
    'str': click.STRING,
    'int': click.INT,
    'bool': click.BOOL,
}


def get_short_help(description):
    lines = description.splitlines()
    return lines[0]


def render_template(template, params):
    t = jinja2.Template(template)
    return t.render(params)


class _ParameterCreator:

    def visit(self, param):
        return param.accept(self)

    def visit_argument(self, param):
        cli_type = TYPES_MAP[param.type or 'str']
        return click.Argument([param.name], type=cli_type,
                              default=param.default)

    def visit_option(self, param):
        opt_decl = ('-' if len(param.name) == 1 else '--') + param.name
        cli_type = TYPES_MAP[param.type or 'str']
        return click.Option([opt_decl], type=cli_type,
                            default=param.default)


def get_volumes(volumes):
    if volumes is not None:
        return volumes
    else:
        return [LocalPath('.', '.', Mode.RW)]


def get_work_dir(volumes):
    return '.' if volumes is None else '/'


@coroutine
def _resolve(ctx, command, *, loop):
    yield from resolve(
        ctx.client,
        ctx.layers,
        ctx.services,
        command,
        loop=loop,
        pull=True,
        build=True,
    )


@coroutine
def _start_services(ctx, command):
    services = [ctx.services.get(name)
                for name in command.requires or []]
    yield from ensure_running(ctx.client, ctx.namespace, services)


class _CommandCreator:

    def __init__(self, name):
        self.name = name

    def visit(self, command):
        return command.accept(self)

    def visit_shellcommand(self, command):
        params_creator = _ParameterCreator()
        params = [params_creator.visit(param)
                  for param in (command.params or [])]

        @click.pass_obj
        @async_cmd
        def cb(ctx, **kw):
            yield from _resolve(ctx, command, loop=ctx.loop)
            docker_image = get_docker_image(ctx.layers, command.image)
            yield from _start_services(ctx, command)
            yield from ensure_network(ctx.client, ctx.network)

            volumes = get_volumes(command.volumes)
            volumes.append(LocalPath(DUMB_INIT_LOCAL_PATH,
                                     DUMB_INIT_REMOTE_PATH))

            cmd = [DUMB_INIT_REMOTE_PATH, 'sh', '-c',
                   render_template(command.eval, kw)]

            with config_tty(command.raw_input) as fd:
                exit_code = yield from run(
                    ctx.client, fd, docker_image, cmd,
                    loop=ctx.loop,
                    volumes=volumes,
                    ports=command.ports,
                    environ=command.environ,
                    work_dir=get_work_dir(command.volumes),
                    network=ctx.network,
                    network_alias=command.network_name,
                )
                sys.exit(exit_code)

        short_help = None
        if command.description is not None:
            short_help = get_short_help(command.description)
        return click.Command(self.name, params=params, callback=cb,
                             help=command.description,
                             short_help=short_help)

    def visit_subcommand(self, command):
        exec_ = sh_to_list(command.exec)

        @click.pass_obj
        @async_cmd
        def cb(ctx, args):
            yield from _resolve(ctx, command, loop=ctx.loop)
            docker_image = get_docker_image(ctx.layers, command.image)
            yield from _start_services(ctx, command)
            yield from ensure_network(ctx.client, ctx.network)

            cmd = exec_ + args
            with config_tty(command.raw_input) as fd:
                exit_code = yield from run(
                    ctx.client, fd, docker_image, cmd,
                    loop=ctx.loop,
                    volumes=get_volumes(command.volumes),
                    ports=command.ports,
                    environ=command.environ,
                    work_dir=get_work_dir(command.volumes),
                    network=ctx.network,
                    network_alias=command.network_name,
                )
                sys.exit(exit_code)

        short_help = None
        if command.description is not None:
            short_help = get_short_help(command.description)
        return ProxyCommand(self.name, callback=cb,
                            help=command.description, short_help=short_help)


def create_commands_cli(config):
    groups_set = set()
    commands_map = dict()

    commands = [i for i in config if isinstance(i, CommandType)]
    for command in commands:
        command_path = tuple(command.name.split())
        group_parts, command_name = command_path[:-1], command_path[-1]
        assert command_path not in groups_set
        assert group_parts not in commands_map
        if group_parts:
            groups_set.add(group_parts)
        commands_map[command_path] = command

    groups, mapping = create_groups(groups_set)

    cli_commands = []
    for command_path, command in commands_map.items():
        group_parts, command_name = command_path[:-1], command_path[-1]
        cli_command = _CommandCreator(command_name).visit(command)
        if group_parts in mapping:
            mapping[group_parts].add_command(cli_command)
        else:
            cli_commands.append(cli_command)

    cli = click.Group()
    for group in groups:
        cli.add_command(group)
    for cli_command in cli_commands:
        cli.add_command(cli_command)
    return cli
