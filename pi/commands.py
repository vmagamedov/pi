import click


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


def create_command(name, data):
    args = data.get('args', [])
    options = data.get('options', [])

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
        print(kw)

    return click.Command(name, params=params, callback=cb)


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