import shlex

import click
import jinja2

from .run import run
from .actors import init
from .console import raw_stdin


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


def parse_attrs(attrs):
    d = dict(i.split('=') for i in attrs.split())
    type_ = TYPES_MAP[d.pop('type', 'str')]
    default = d.pop('default', None)
    assert not d, d
    return {'type': type_, 'default': default}


def get_short_help(help):
    lines = help.splitlines()
    return lines[0]


def render_template(template, params):
    t = jinja2.Template(template)
    return t.render(params)


def execute(client, command):
    with raw_stdin() as fd:
        init(run, client, fd, command)
    return 0  # TODO: return real exit code


def create_proxy_command(name, prefix, help):
    if isinstance(prefix, str):
        prefix = shlex.split(prefix)

    @click.pass_context
    def cb(ctx, args):
        exit_code = execute(ctx.obj.client, prefix + args)
        ctx.exit(exit_code)

    short_help = get_short_help(help) if help else None
    return ProxyCommand(name, callback=cb,
                        help=help, short_help=short_help)


def create_shell_command(name, args, options, template, help):
    params = []
    for arg in args:
        (arg_name, attrs), = arg.items()
        arg_kwargs = parse_attrs(attrs)
        params.append(click.Argument([arg_name], **arg_kwargs))
    for opt in options:
        (opt_name, attrs), = opt.items()
        opt_kwargs = parse_attrs(attrs)
        opt_decl = ('-' if len(opt_name) == 1 else '--') + opt_name
        params.append(click.Option([opt_decl], **opt_kwargs))

    @click.pass_context
    def cb(ctx, **kw):
        code = render_template(template, kw)
        command = ['/bin/bash', '-c', code]
        exit_code = execute(ctx.obj.client, command)
        ctx.exit(exit_code)

    short_help = get_short_help(help) if help else None
    return click.Command(name, params=params, callback=cb,
                         help=help, short_help=short_help)


def create_command(name, data):
    data = data.copy()
    image = data.pop('image', None)
    help = data.pop('help', None)
    if image is None:
        raise ValueError('Image not specified ({})'.format(name))
    if 'shell' in data:
        args = data.pop('arguments', [])
        options = data.pop('options', [])
        template = data.pop('shell')
        command = create_shell_command(name, args, options, template, help)
    elif 'call' in data:
        prefix = data.pop('call')
        if not isinstance(prefix, (str, list)):
            raise TypeError('"call" value should be a list or string')
        command = create_proxy_command(name, prefix, help)
    else:
        raise ValueError('Command "{}" has nothing to call')
    if data:
        raise ValueError('Unknown values: {}'.format(list(data.keys())))
    return command


def build_commands_cli(config):
    groups_set = set()
    commands_map = dict()

    commands_data = config.get('commands', {})
    for command_path, command_data in commands_data.items():
        command_parts = tuple(command_path.split('.'))
        group_parts, command_name = command_parts[:-1], command_parts[-1]
        assert command_parts not in groups_set
        assert group_parts not in commands_map
        if group_parts:
            groups_set.add(group_parts)
        commands_map[command_parts] = command_data

    groups, mapping = create_groups(groups_set)

    commands = []
    for command_parts, command_data in commands_map.items():
        group_parts, command_name = command_parts[:-1], command_parts[-1]
        command = create_command(command_name, command_data)
        if group_parts in mapping:
            mapping[group_parts].add_command(command)
        else:
            commands.append(command)

    cli = click.Group()
    for group in groups:
        cli.add_command(group)
    for command in commands:
        cli.add_command(command)
    return cli
