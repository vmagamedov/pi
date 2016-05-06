import click
import jinja2


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


def create_proxy_command(name, prefix):

    def cb(args):
        print('PROXY: {!r} with {!r}'.format(prefix, args))

    return ProxyCommand(name, callback=cb)


def create_shell_command(name, args, options, template):
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

    def cb(**kw):
        print('SHELL: {!r}'.format(render_template(template, kw)))

    return click.Command(name, params=params, callback=cb)


def create_command(name, data):
    data = data.copy()
    image = data.pop('image', None)
    if image is None:
        raise ValueError('Image not specified ({})'.format(name))
    if 'shell' in data:
        args = data.pop('args', [])
        options = data.pop('options', [])
        template = data.pop('shell')
        command = create_shell_command(name, args, options, template)
    elif 'call' in data:
        prefix = data.pop('call')
        command = create_proxy_command(name, prefix)
    else:
        raise ValueError('Command "{}" has nothing to call')
    if data:
        raise ValueError('Unknown values: {}'.format(list(data.keys())))
    return command


def create_commands(config):
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

    return groups + commands


def render_template(template, params):
    t = jinja2.Template(template)
    return t.render(params)
