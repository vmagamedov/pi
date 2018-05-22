import sys

from functools import partial

from .._requires import click
from .._requires import jinja2

from ..run import run
from ..types import CommandType, LocalPath, Mode
from ..images import docker_image
from ..environ import async_cmd
from ..console import config_tty
from ..network import ensure_network
from ..resolve import resolve
from ..services import ensure_running

from .common import ProxyCommand


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


def _get_short_help(description):
    lines = description.splitlines()
    return lines[0]


def _render_template(template, params):
    t = jinja2.Template(template)
    return t.render(params)


class _ParameterCreator:
    TYPES_MAP = {
        'str': click.STRING,
        'int': click.INT,
        'bool': click.BOOL,
    }

    def visit(self, param):
        return param.accept(self)

    def visit_argument(self, param):
        cli_type = self.TYPES_MAP[param.type or 'str']
        return click.Argument([param.name], type=cli_type,
                              default=param.default)

    def visit_option(self, param):
        opt_decl = ('-' if len(param.name) == 1 else '--') + param.name
        cli_type = self.TYPES_MAP[param.type or 'str']
        return click.Option([opt_decl], type=cli_type,
                            default=param.default)


def _required_services(env, obj, *, _seen=None, _all=None):
    """
    Yields required services in order for their start, without duplicates
    """
    if _seen is None or _all is None:
        _seen = set()
        _all = set()
    if obj.requires:
        for name in obj.requires:
            if name in _all:
                continue

            try:
                service = env.services.get(name)
            except KeyError:
                raise TypeError('Service "{}" is not defined'.format(name))
            if name in _seen:
                raise TypeError('Service "{}" has circular reference'
                                .format(name))
            _seen.add(name)
            yield from _required_services(env, service, _seen=_seen, _all=_all)
            _seen.discard(name)

            yield service
            _all.add(name)


async def _start_services(env, command):
    services = list(_required_services(env, command))
    await ensure_running(env.client, env.namespace, services)


async def _callback(command, env, **params):
    await resolve(
        env.client,
        env.images,
        env.services,
        command,
        loop=env.loop,
        pull=True,
        build=True,
    )
    await _start_services(env, command)
    await ensure_network(env.client, env.network)

    di = docker_image(env.images, command.image)
    volumes = [LocalPath('.', '.', Mode.RW)]

    if isinstance(command.run, str):
        command_run = ['sh', '-c', _render_template(command.run, params)]
    else:
        assert isinstance(command.run, list), type(command.run)
        assert not command.params
        command_run = command.run + params['args']

    volumes.extend(command.volumes or [])

    with config_tty() as (fd, tty):
        exit_code = await run(
            env.client, fd, tty, di, command_run,
            loop=env.loop,
            init=True,
            volumes=volumes,
            ports=command.ports,
            environ=command.environ,
            work_dir='.',
            network=env.network,
            network_alias=command.network_name,
        )
        sys.exit(exit_code)


def create_command(name, command):
    short_help = None
    if command.description is not None:
        short_help = _get_short_help(command.description)

    callback = partial(_callback, command)
    callback = async_cmd(callback)
    callback = click.pass_obj(callback)

    if isinstance(command.run, str):
        params_creator = _ParameterCreator()
        params = [params_creator.visit(param)
                  for param in (command.params or [])]
        return click.Command(name, params=params, callback=callback,
                             help=command.description,
                             short_help=short_help)
    else:
        return ProxyCommand(name, callback=callback,
                            help=command.description,
                            short_help=short_help)


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
        cli_command = create_command(command_name, command)
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
