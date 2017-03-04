import sys

from operator import attrgetter
from collections import defaultdict
from collections import Counter, namedtuple

from ..run import run
from ..types import DockerImage, Mode, LocalPath
from ..utils import format_size
from ..images import pull as pull_image, push as push_image
from ..console import pretty, config_tty
from ..context import async_cmd
from ..resolve import resolve

from .._requires import click

from .common import ProxyCommand, ExtGroup


BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


@click.command('build', help='Build image')
@click.pass_obj
@async_cmd
async def image_build(ctx):
    name = click.get_current_context().meta['image_name']
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


def _get_image(layers, name):
    try:
        layer = layers.get(name)
    except KeyError:
        return DockerImage(name)
    else:
        return layer.docker_image()


@click.command('pull', help='Pull image version')
@click.pass_obj
@async_cmd
async def image_pull(ctx):
    name = click.get_current_context().meta['image_name']
    image = _get_image(ctx.layers, name)
    success = await pull_image(ctx.client, image)
    if not success:
        click.echo('Unable to pull image {}'.format(image.name))
        sys.exit(1)


@click.command('push', help='Push image version')
@click.pass_obj
@async_cmd
async def image_push(ctx):
    name = click.get_current_context().meta['image_name']
    image = _get_image(ctx.layers, name)
    success = await push_image(ctx.client, image)
    if not success:
        click.echo('Unable to push image {}'.format(image.name))
        sys.exit(1)


@click.pass_obj
@async_cmd
async def _image_run(ctx, args):
    name = click.get_current_context().meta['image_name']
    image = _get_image(ctx.layers, name)
    volumes = [LocalPath('.', '.', Mode.RW)]

    with config_tty() as (fd, tty):
        exit_code = await run(ctx.client, fd, tty, image, args,
                              loop=ctx.loop, volumes=volumes,
                              work_dir='.')
        sys.exit(exit_code)


_Tag = namedtuple('_Tag', 'value created')


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


@async_cmd
async def _image_list(ctx):
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


def _image_list_callback(ctx, param, value):
    if value and not ctx.resilient_parsing:
        _image_list(ctx.obj)
        ctx.exit()


def _image_gc_callback(ctx, param, value):
    if value and not ctx.resilient_parsing:
        image_gc(value)
        ctx.exit()


def _image_callback(name):
    click.get_current_context().meta['image_name'] = name


def _image_ext_help(ctx, formatter):
    if ctx.obj.layers:
        with formatter.section('Images'):
            formatter.write_dl([(layer.name, layer.image.description or '')
                                for layer in ctx.obj.layers])
    else:
        with formatter.section('Images'):
            formatter.write_text('--- not defined ---')


def create_images_cli(layers):
    params = [
        click.Option(['-l', '--list'], is_flag=True, is_eager=True,
                     expose_value=False, callback=_image_list_callback,
                     help='Display services status'),
        click.Option(['--gc'], type=click.INT, is_eager=True,
                     expose_value=False, callback=_image_gc_callback,
                     help='Delete old image versions'),
        click.Argument(['name']),
    ]

    image_run = ProxyCommand('run', callback=_image_run,
                             help='Run command in container')

    image_group = ExtGroup('image', params=params,
                           callback=_image_callback,
                           help='Images creation and delivery',
                           ext_help=_image_ext_help)

    image_group.add_command(image_run)
    image_group.add_command(image_pull)
    image_group.add_command(image_push)
    image_group.add_command(image_build)

    cli = click.Group()
    cli.add_command(image_group)
    return cli
