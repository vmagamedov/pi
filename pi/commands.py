import shlex

from ._requires import click
from ._requires import jinja2

from .run import run
from .types import CommandType, LocalPath, Mode
from .actors import init
from .console import config_tty


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


def execute(client, image, command, *, volumes=None, ports=None,
            work_dir=None, raw_input=False):
    with config_tty(raw_input) as fd:
        return init(run, client, fd, image, command,
                    volumes=volumes, ports=ports, work_dir=work_dir)


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


class _CommandCreator:

    def __init__(self, name):
        self.name = name

    def _get_volumes(self, command):
        if command.volumes is not None:
            return command.volumes
        else:
            return [LocalPath('.', '.', Mode.RW)]

    def _get_work_dir(self, command):
        if command.volumes is None:
            return '.'
        else:
            return '/'

    def visit(self, command):
        return command.accept(self)

    def visit_shellcommand(self, command):
        params_creator = _ParameterCreator()
        params = [params_creator.visit(param)
                  for param in (command.params or [])]

        @click.pass_context
        def cb(ctx, **kw):
            docker_image = ctx.obj.require_image(command.image)
            code = render_template(command.shell, kw)
            exit_code = execute(ctx.obj.client, docker_image,
                                ['sh', '-c', code],
                                volumes=self._get_volumes(command),
                                ports=command.ports,
                                work_dir=self._get_work_dir(command),
                                raw_input=command.raw_input)
            ctx.exit(exit_code)

        short_help = None
        if command.description is not None:
            short_help = get_short_help(command.description)
        return click.Command(self.name, params=params, callback=cb,
                             help=command.description,
                             short_help=short_help)

    def visit_subcommand(self, command):
        if isinstance(command.call, str):
            call = shlex.split(command.call)
        else:
            call = command.call

        @click.pass_context
        def cb(ctx, args):
            docker_image = ctx.obj.require_image(command.image)
            exit_code = execute(ctx.obj.client, docker_image,
                                call + args,
                                volumes=self._get_volumes(command),
                                ports=command.ports,
                                work_dir=self._get_work_dir(command),
                                raw_input=command.raw_input)
            ctx.exit(exit_code)

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
