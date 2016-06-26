from itertools import chain
from functools import partial

from ._requires import click

from .run import run
from .types import DockerImage, Image
from .layers import Layer
from .client import echo_download_progress, echo_build_progress
from .actors import init
from .console import pretty
from .console import raw_stdin


BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


class Builder(object):

    def __init__(self, layer, ctx):
        self.layer = layer
        self.from_ = layer.parent.docker_image() if layer.parent else None
        self.ctx = ctx

    def visit(self, obj):
        return obj.accept(self)

    def visit_dockerfile(self, obj):
        return self.ctx.obj.image_build_dockerfile(
            self.layer.docker_image(),
            obj.file_name,
            self.from_,
            echo_build_progress,
        )

    def visit_ansibletasks(self, obj):
        return self.ctx.obj.image_build_ansibletasks(
            self.layer.image.repository,
            self.layer.version(),
            obj.tasks,
            self.from_,
        )


def _build_image(ctx, *, name):
    layers = ctx.obj.layers_path(name)
    for layer in layers:
        docker_image = layer.docker_image()
        if not ctx.obj.image_exists(docker_image):
            if not ctx.obj.image_pull(docker_image, echo_download_progress):
                if not Builder(layer, ctx).visit(layer.image.provision_with):
                    ctx.exit(1)
        else:
            click.echo('Already exists: {}'
                       .format(docker_image.name))


@click.command('list')
@click.pass_context
def image_list(ctx):
    images = ctx.obj.client.images()
    tags = set(chain.from_iterable(i['RepoTags'] for i in images))
    for name in sorted(ctx.obj.layers.keys()):
        image_name = ctx.obj.layers[name].docker_image().name
        if image_name in tags:
            click.echo(pretty('\u2714 {_green}{}{_r}: {}', name, image_name))
        else:
            click.echo(pretty('\u2717 {_red}{}{_r}: {}', name, image_name))


@click.command('pull')
@click.argument('name')
@click.pass_context
def image_pull(ctx, name):
    if name in ctx.obj.layers:
        image = ctx.obj.layers[name].docker_image()
    else:
        image = DockerImage(name)
    if not ctx.obj.image_pull(image, echo_download_progress):
        click.echo('Unable to pull image {}'.format(image.name))
        ctx.exit(1)


@click.command('push')
@click.argument('name')
@click.pass_context
def image_push(ctx, name):
    if name in ctx.obj.layers:
        image = ctx.obj.layers[name].docker_image()
    else:
        image = DockerImage(name)
    if not ctx.obj.image_push(image, echo_download_progress):
        click.echo('Unable to push image {}'.format(image.name))
        ctx.exit(1)


@click.command('shell')
@click.argument('name')
@click.pass_context
def image_shell(ctx, name):
    if name in ctx.obj.layers:
        image = ctx.obj.layers[name].docker_image()
    else:
        image = DockerImage(name)
    with raw_stdin() as fd:
        ctx.exit(init(run, ctx.obj.client, fd, image, '/bin/bash'))


def create_images_cli(layers):
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

    image_group.add_command(image_list)
    image_group.add_command(image_pull)
    image_group.add_command(image_push)
    image_group.add_command(image_shell)

    cli.add_command(image_group)
    return cli


def resolve_deps(deps):
    while deps:
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


def construct_layers(config):
    deps = {}
    layers = {}
    image_by_name = {}

    images = [i for i in config if isinstance(i, Image)]
    for image in images:
        if image.from_ is not None:
            if not isinstance(image.from_, DockerImage):
                deps[image.name] = image.from_
                image_by_name[image.name] = image
                continue
        layers[image.name] = Layer(image, parent=None)

    # check missing parents
    missing = {name for name, parent_name in deps.items()
               if parent_name not in deps and parent_name not in layers}
    if missing:
        raise TypeError('These images has missing parent images: {}'
                        .format(', '.join(sorted(missing))))

    for name, parent_name in resolve_deps(deps):
        image = image_by_name[name]
        parent = layers[parent_name]
        layers[name] = Layer(image, parent=parent)

    return list(layers.values())
