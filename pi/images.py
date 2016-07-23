from operator import attrgetter
from functools import partial
from collections import Counter

from ._requires import click

from .run import run
from .types import DockerImage, Image, LocalPath, Mode
from .utils import format_size
from .layers import Layer
from .client import echo_download_progress, echo_build_progress
from .actors import init
from .console import pretty
from .console import config_tty


BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


class Builder(object):

    def __init__(self, layer, ctx):
        self.layer = layer
        self.ctx = ctx
        if layer.parent:
            from_ = layer.parent.docker_image()
        else:
            from_ = layer.image.from_
        self.from_ = from_

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

    # check if base image exists
    base_image = layers[0].image.from_
    if base_image is not None:
        if not ctx.obj.image_exists(base_image):
            if not ctx.obj.image_pull(base_image, echo_download_progress):
                ctx.exit(1)

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
    from ._requires.tabulate import tabulate

    available = set()
    counts = Counter()
    sizes = {}
    for image in ctx.obj.client.images():
        available.update(image['RepoTags'])
        for repo_tag in image['RepoTags']:
            repo, _ = repo_tag.split(':')
            counts[repo] += 1
            sizes[repo_tag] = image['VirtualSize']

    rows = []
    for layer in sorted(ctx.obj.layers.values(), key=attrgetter('name')):
        image_name = layer.docker_image().name
        if image_name in available:
            pretty_name = pretty('\u2714 {_green}{}{_r}', layer.name)
        else:
            pretty_name = pretty('\u2717 {_red}{}{_r}', layer.name)
        size = sizes.get(image_name, 0)
        pretty_size = format_size(size) if size else None
        count = counts.get(layer.image.repository, None)
        rows.append([pretty_name, image_name, pretty_size, count])

    click.echo(tabulate(rows, headers=['  Image name', 'Docker image',
                                       'Size', 'Versions']))


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
@click.option('-v', '--volume', multiple=True,
              help='Mount volume: "/host" or "/host:/container" or '
                   '"/host:/container:rw"')
@click.pass_context
def image_shell(ctx, name, volume):
    if name in ctx.obj.layers:
        image = ctx.obj.layers[name].docker_image()
    else:
        image = DockerImage(name)

    volumes = []
    for v in volume:
        parts = v.split(':')
        if len(parts) == 1:
            from_, = to, = parts
            mode = Mode.RO
        elif len(parts) == 2:
            from_, to = parts
            mode = Mode.RO
        elif len(parts) == 3:
            from_, to, mode_raw = parts
            mode = {'ro': Mode.RO, 'rw': Mode.RW}[mode_raw]
        else:
            raise TypeError('More values than expected: {!r}'.format(v))
        volumes.append(LocalPath(from_, to, mode))

    with config_tty(raw_input=True) as fd:
        ctx.exit(init(run, ctx.obj.client, fd, image, '/bin/sh',
                      volumes=volumes))


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
