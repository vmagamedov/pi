import click

from .layers import DockerfileLayer, AnsibleTasksLayer, Image

BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


def _build_with_docker_file_cmd(name, file_name):

    def cb():
        print('Building image using {}'.format(file_name))

    return click.Command(name, callback=cb)


def _build_with_ansible_playbook_cmd(name, from_, file_name):

    def cb():
        print('Building image from {!r} using playbook {!r}'
              .format(from_, file_name))

    return click.Command(name, callback=cb)


def _build_with_ansible_tasks_cmd(name, from_, ansible_tasks):

    def cb():
        print('Building image from {!r} using ansible tasks:\n{!r}'
              .format(from_, ansible_tasks))

    return click.Command(name, callback=cb)


def create_build_command(name, data):
    data = data.copy()
    data.pop('repository')

    if 'from' in data:
        from_ = data.pop('from')

        if 'ansible-tasks' in data:
            ansible_tasks = data.pop('ansible-tasks')
            cmd = _build_with_ansible_tasks_cmd(name, from_, ansible_tasks)
        elif 'ansible-playbook' in data:
            ansible_playbook = data.pop('ansible-playbook')
            cmd = _build_with_ansible_playbook_cmd(name, from_,
                                                   ansible_playbook)
        else:
            raise ValueError('Image "{}" has nothing to build'.format(name))

    elif 'docker-file' in data:
        docker_file = data.pop('docker-file', None)
        cmd = _build_with_docker_file_cmd(name, docker_file)

    else:
        raise ValueError('Base image is not defined for "{}"'.format(name))
    if data:
        raise ValueError('Unknown values: {}'.format(list(data.keys())))
    return cmd


def build_images_cli(config):
    commands = []
    images_data = config.get('images', {})
    for image_name, image_data in images_data.items():
        commands.append(create_build_command(image_name, image_data))

    cli = click.Group()
    image_group = click.Group('image')

    build_help = BUILD_NO_IMAGES if not commands else None
    build_group = click.Group('build', help=build_help)
    for command in commands:
        build_group.add_command(command)
    image_group.add_command(build_group)

    cli.add_command(image_group)
    return cli


def construct_layer(name, data, parent):
    data = data.copy()
    repository = data.pop('repository')
    if 'docker-file' in data:
        dockerfile = data.pop('docker-file')
        layer = DockerfileLayer(name, repository, dockerfile)
    elif 'ansible-tasks' in data:
        data.pop('from', None)
        ansible_tasks = data.pop('ansible-tasks')
        layer = AnsibleTasksLayer(name, repository, ansible_tasks,
                                  parent=parent)
    else:
        raise ValueError('Image type is undefined: {}'.format(name))
    if data:
        raise ValueError('Unknown values: {}'.format(list(data.keys())))
    return layer


def resolve_deps(deps):
    while True:
        resolved = set()
        for name, parent_name in deps.items():
            if parent_name not in deps:
                resolved.add(name)
        if not resolved:
            raise TypeError('Images hierarchy build error, '
                            'circular dependency found in these images: {}'
                            .format(', '.join(sorted(deps.keys()))))
        for name in resolved:
            yield name, deps[name]
        deps = {k: v for k, v in deps.items() if k not in resolved}
        if not deps:
            return


def construct_layers(config):
    deps = {}
    layers = {}
    data_by_name = {}

    for name, data in config.get('images', {}).items():
        if 'from' in data:
            from_ = data['from']
            if not isinstance(from_, Image):
                deps[name] = from_
                data_by_name[name] = data
                continue
        layers[name] = construct_layer(name, data, None)

    # check missing parents
    missing = {name for name, parent_name in deps.items()
               if parent_name not in deps and parent_name not in layers}
    if missing:
        raise TypeError('These images has missing parent images: {}'
                        .format(', '.join(sorted(missing))))

    for name, parent_name in resolve_deps(deps):
        data = data_by_name[name]
        parent = layers[parent_name]
        layers[name] = construct_layer(name, data, parent)

    return list(layers.values())
