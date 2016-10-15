from operator import attrgetter
from functools import partial
from collections import Counter, defaultdict, namedtuple

from ._requires import click

from .run import run
from .types import DockerImage, Image, LocalPath, Mode
from .utils import format_size
from .build import Builder
from .layers import Layer
from .client import echo_download_progress
from .actors import init
from .console import pretty
from .console import config_tty


BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


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
                builder = Builder(ctx.obj.client, ctx.obj.async_client, layer,
                                  loop=ctx.obj.loop)
                build_coro = builder.visit(layer.image.provision_with)
                if not ctx.obj.loop.run_until_complete(build_coro):
                    ctx.exit(1)
        else:
            click.echo('Already exists: {}'
                       .format(docker_image.name))


@click.command('list', help='List known images')
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
    for layer in sorted(ctx.obj.layers, key=attrgetter('name')):
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


@click.command('pull', help='Pull image version')
@click.argument('name')
@click.pass_context
def image_pull(ctx, name):
    mapping = {l.name: l for l in ctx.obj.layers}
    if name in mapping:
        image = mapping[name].docker_image()
    else:
        image = DockerImage(name)
    if not ctx.obj.image_pull(image, echo_download_progress):
        click.echo('Unable to pull image {}'.format(image.name))
        ctx.exit(1)


@click.command('push', help='Push image version')
@click.argument('name')
@click.pass_context
def image_push(ctx, name):
    mapping = {l.name: l for l in ctx.obj.layers}
    if name in mapping:
        image = mapping[name].docker_image()
    else:
        image = DockerImage(name)
    if not ctx.obj.image_push(image, echo_download_progress):
        click.echo('Unable to push image {}'.format(image.name))
        ctx.exit(1)


@click.command('shell', help='Inspect image using shell')
@click.argument('name')
@click.option('-v', '--volume', multiple=True,
              help='Mount volume: "/host" or "/host:/container" or '
                   '"/host:/container:rw"')
@click.pass_context
def image_shell(ctx, name, volume):
    mapping = {l.name: l for l in ctx.obj.layers}
    if name in mapping:
        image = mapping[name].docker_image()
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


_Tag = namedtuple('_Tag', 'value created')


@click.command('gc', help='Delete old image versions')
@click.option('-c', '--count', type=click.INT, default=2, show_default=True,
              help='How much versions to leave')
@click.pass_context
def image_gc(ctx, count):
    if count < 0:
        click.echo('Count should be more or equal to 0')
        ctx.exit(-1)
    known_repos = {l.image.repository for l in ctx.obj.layers}
    repo_tags_used = {c['Image'] for c in ctx.obj.client.containers(all=True)}

    by_repo = defaultdict(list)
    to_delete = []

    for image in ctx.obj.client.images():
        repo_tags = set(image['RepoTags'])
        if repo_tags == {'<none>:<none>'}:
            to_delete.append(image['Id'])
            continue
        repo_tags.difference_update(repo_tags_used)
        for repo_tag in repo_tags:
            repo, _, tag = repo_tag.partition(':')
            if repo in known_repos:
                by_repo[repo].append(_Tag(tag, image['Created']))

    for repo, tags in by_repo.items():
        latest_tags = sorted(tags, key=attrgetter('created'), reverse=True)
        for tag in latest_tags[count:]:
            to_delete.append('{}:{}'.format(repo, tag.value))

    for image in to_delete:
        ctx.obj.client.remove_image(image)
        click.echo('Removed: {}'.format(image))


def create_images_cli(layers):
    cli = click.Group()
    image_group = click.Group('image')

    if layers:
        build_help = 'Build image version'
    else:
        build_help = BUILD_NO_IMAGES
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
    image_group.add_command(image_gc)

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
