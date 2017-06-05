import sys

from operator import attrgetter
from collections import defaultdict
from collections import Counter, namedtuple

from ..run import run
from ..types import DockerImage, Mode, LocalPath
from ..utils import format_size
from ..images import pull as pull_image, push as push_image, docker_image
from ..images import image_versions
from ..console import pretty, config_tty
from ..environ import async_cmd
from ..resolve import resolve

from .._requires import click

from .common import ProxyCommand, ExtGroup


BUILD_NO_IMAGES = 'There are no images to build in the pi.yaml file'


@click.command('build', help='Build image')
@click.pass_obj
@async_cmd
async def image_build(env):
    name = click.get_current_context().meta['image_name']
    image = env.images.get(name)
    failed = await resolve(
        env.client,
        env.images,
        env.services,
        image,
        loop=env.loop,
        pull=True,
        build=True,
    )
    if failed:
        click.echo('Failed to build image {}'.format(name))
        sys.exit(1)


def _get_image(images_map, name):
    try:
        image = images_map.get(name)
    except KeyError:
        return DockerImage(name)
    else:
        return docker_image(images_map, image.name)


@click.command('pull', help='Pull image version')
@click.pass_obj
@async_cmd
async def image_pull(env):
    name = click.get_current_context().meta['image_name']
    image = _get_image(env.images, name)
    success = await pull_image(env.client, image)
    if not success:
        click.echo('Unable to pull image {}'.format(image.name))
        sys.exit(1)


@click.command('push', help='Push image version')
@click.pass_obj
@async_cmd
async def image_push(env):
    name = click.get_current_context().meta['image_name']
    image = _get_image(env.images, name)
    success = await push_image(env.client, image)
    if not success:
        click.echo('Unable to push image {}'.format(image.name))
        sys.exit(1)


@click.pass_obj
@async_cmd
async def _image_run(env, args):
    name = click.get_current_context().meta['image_name']
    image = _get_image(env.images, name)
    volumes = [LocalPath('.', '.', Mode.RW)]

    with config_tty() as (fd, tty):
        exit_code = await run(env.client, fd, tty, image, args,
                              loop=env.loop, volumes=volumes,
                              work_dir='.')
        sys.exit(exit_code)


_Tag = namedtuple('_Tag', 'value created')


@click.pass_obj
@async_cmd
async def image_gc(env, count):
    if count < 0:
        click.echo('Count should be more or equal to 0')
        sys.exit(-1)
    known_repos = {i.repository for i in env.images}
    containers = await env.client.containers(all=True)
    repo_tags_used = {c['Image'] for c in containers}

    by_repo = defaultdict(list)
    to_delete = []

    images = await env.client.images()
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
        await env.client.remove_image(image)
        click.echo('Removed: {}'.format(image))


async def get_images_info(env):
    available = set()
    counts = Counter()
    sizes = {}
    images = await env.client.images()
    for image in images:
        available.update(image['RepoTags'])
        for repo_tag in image['RepoTags']:
            repo, _ = repo_tag.split(':')
            counts[repo] += 1
            sizes[repo_tag] = image['VirtualSize']
    return available, counts, sizes


@async_cmd
async def _image_list(env):
    from .._requires.tabulate import tabulate

    available, counts, sizes = await get_images_info(env)
    images = sorted(env.images, key=lambda i: i.name)
    versions = image_versions(env.images, images)

    rows = []
    for image, version in zip(images, versions):
        di = DockerImage.from_image(image, version)
        if di.name in available:
            pretty_name = pretty('\u2714 {_green}{}{_r}', image.name)
        else:
            pretty_name = pretty('\u2717 {_red}{}{_r}', image.name)
        size = sizes.get(di.name, 0)
        pretty_size = format_size(size) if size else None
        count = counts.get(image.repository, None)
        rows.append([pretty_name, di.name, pretty_size, count])

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
    if ctx.obj.images:
        with formatter.section('Images'):
            formatter.write_dl([(image.name,
                                 image.description or '')
                                for image in ctx.obj.images])
    else:
        with formatter.section('Images'):
            formatter.write_text('--- not defined ---')


def create_images_cli():
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
