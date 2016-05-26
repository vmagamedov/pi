import click

from .layers import DockerfileLayer


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


def construct_layers(config):
    return [DockerfileLayer('env', 'reg.local/env', 'Dockerfile.env')]
