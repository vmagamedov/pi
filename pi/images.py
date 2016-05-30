from functools import partial

import click

from .layers import DockerfileLayer, AnsibleTasksLayer, Image
from .client import echo_download_progress, echo_build_progress


BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


class Builder(object):

    def __init__(self, ctx):
        self.ctx = ctx

    def visit(self, layer):
        return layer.accept(self)

    def visit_dockerfile(self, layer):
        self.ctx.obj.image_build_dockerfile(layer.image(), layer.file_name,
                                            echo_build_progress)


def _build_image(ctx, *, name):
    layers = ctx.obj.layers_path(name)
    for layer in layers:
        image = layer.image()
        if not ctx.obj.layer_exists(image):
            if not ctx.obj.maybe_pull(image, echo_download_progress):
                Builder(ctx).visit(layer)
        else:
            click.echo('Already exists: {}'
                       .format(layer.image().name))


def build_images_cli(layers):
    cli = click.Group()
    image_group = click.Group('image')

    build_help = BUILD_NO_IMAGES if not layers else None
    build_group = click.Group('build', help=build_help)
    for layer in layers:
        callback = partial(_build_image, name=layer.name)
        callback = click.pass_context(callback)
        cmd = click.Command(layer.name, callback=callback)
        build_group.add_command(cmd)
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
