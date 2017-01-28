import sys

from operator import attrgetter
from functools import partial
from collections import defaultdict
from collections import Counter, namedtuple

from ..run import run
from ..types import DockerImage, Mode, LocalPath
from ..utils import format_size
from ..images import Puller, Pusher
from ..console import pretty, config_tty
from ..context import async_cmd
from ..resolve import resolve

from .._requires import click


BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


async def _build_image(ctx, *, name):
    image = ctx.layers.get(name).image
    failed = await resolve(
        ctx.client,
        ctx.layers,
        ctx.services,
        image,
        loop=ctx.loop,
        pull=True,
        build=True,
    )
    if failed:
        click.echo('Failed to build image {}'.format(name))
        sys.exit(1)


@click.command('list', help='List known images')
@click.pass_obj
@async_cmd
async def image_list(ctx):
    from .._requires.tabulate import tabulate

    available = set()
    counts = Counter()
    sizes = {}
    images = await ctx.client.images()
    for image in images:
        available.update(image['RepoTags'])
        for repo_tag in image['RepoTags']:
            repo, _ = repo_tag.split(':')
            counts[repo] += 1
            sizes[repo_tag] = image['VirtualSize']

    rows = []
    for layer in sorted(ctx.layers, key=attrgetter('name')):
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


def _get_image(layers, name):
    try:
        layer = layers.get(name)
    except KeyError:
        return DockerImage(name)
    else:
        return layer.docker_image()


@click.command('pull', help='Pull image version')
@click.argument('name')
@click.pass_obj
@async_cmd
async def image_pull(ctx, name):
    image = _get_image(ctx.layers, name)
    success = await Puller(ctx.client, loop=ctx.loop).visit(image)
    if not success:
        click.echo('Unable to pull image {}'.format(image.name))
        sys.exit(1)


@click.command('push', help='Push image version')
@click.argument('name')
@click.pass_obj
@async_cmd
async def image_push(ctx, name):
    image = _get_image(ctx.layers, name)
    success = await Pusher(ctx.client, loop=ctx.loop).visit(image)
    if not success:
        click.echo('Unable to push image {}'.format(image.name))
        sys.exit(1)


@click.command('shell', help='Inspect image using shell')
@click.argument('name')
@click.option('-v', '--volume', multiple=True,
              help='Mount volume: "/host" or "/host:/container" or '
                   '"/host:/container:rw"')
@click.pass_obj
@async_cmd
async def image_shell(ctx, name, volume):
    image = _get_image(ctx.layers, name)

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
        exit_code = await run(ctx.client, fd, image, '/bin/sh',
                              loop=ctx.loop, volumes=volumes)
        sys.exit(exit_code)


_Tag = namedtuple('_Tag', 'value created')


@click.command('gc', help='Delete old image versions')
@click.option('-c', '--count', type=click.INT, default=2, show_default=True,
              help='How much versions to leave')
@click.pass_obj
@async_cmd
async def image_gc(ctx, count):
    if count < 0:
        click.echo('Count should be more or equal to 0')
        sys.exit(-1)
    known_repos = {l.image.repository for l in ctx.layers}
    containers = await ctx.client.containers(all=True)
    repo_tags_used = {c['Image'] for c in containers}

    by_repo = defaultdict(list)
    to_delete = []

    images = await ctx.client.images()
    for image in images:
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
        await ctx.client.remove_image(image)
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
        callback = async_cmd(callback)
        callback = click.pass_obj(callback)
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
