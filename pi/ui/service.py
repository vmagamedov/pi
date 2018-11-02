import sys

from .._requires import click
from .._requires.tabulate import tabulate

from ..run import start
from ..utils import search_container, sh_to_list
from ..images import docker_image
from ..environ import async_cmd
from ..network import ensure_network
from ..console import pretty
from ..services import get_volumes, service_label

from .common import ExtGroup


@click.command('start', help='Start service')
@click.argument('name')
@click.pass_obj
@async_cmd
async def service_start(env, name):
    service = env.services.get(name, None)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        sys.exit(-1)

    label = service_label(env.namespace, service)
    containers = await env.client.containers(all=True)
    container = next(search_container(label, containers), None)
    if container is not None:
        if container['State'] == 'running':
            click.echo('Service is already running')
        elif container['State'] == 'exited':
            await env.client.start(container)
            click.echo('Started previously stopped service')
        else:
            raise NotImplementedError(container['State'])
    else:
        exec_ = sh_to_list(service.exec) if service.exec else None
        args = sh_to_list(service.args) if service.args else None
        di = docker_image(env, service.image)
        await ensure_network(env.client, env.network)

        await start(env.client, di, args,
                    entrypoint=exec_,
                    volumes=get_volumes(service.volumes),
                    ports=service.ports,
                    environ=service.environ,
                    network=env.network,
                    network_alias=service.network_name or service.name,
                    label=label)
        click.echo('Service started')


@click.command('stop', help='Stop service')
@click.argument('name')
@click.pass_obj
@async_cmd
async def service_stop(env, name):
    service = env.services.get(name, None)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        sys.exit(-1)

    label = service_label(env.namespace, service)
    all_containers = await env.client.containers(all=True)
    containers = list(search_container(label, all_containers))
    if not containers:
        click.echo('Service was not started')
        sys.exit(-1)

    for container in containers:
        if container['State'] == 'running':
            await env.client.stop(container, timeout=3)
        await env.client.remove_container(container, v=True, force=True)
    click.echo('Service stopped')


@click.command('status', help='Display services status')
@click.pass_obj
@async_cmd
async def service_status(env):
    containers = await env.client.containers(all=True)

    running = set()
    exited = set()
    images = {}
    for container in containers:
        if container['State'] == 'exited':
            exited.update(container['Labels'])
        elif container['State'] == 'running':
            running.update(container['Labels'])
        for label in container['Labels']:
            images[label] = container['Image']

    rows = []
    for service in env.services:
        label = service_label(env.namespace, service)
        if label in running:
            status = pretty('{_green}running{_r}')
            image = images[label]
        elif label in exited:
            status = pretty('{_red}stopped{_r}')
            image = images[label]
        else:
            status = None
            image = None

        di = docker_image(env.images, service.image)

        if image is not None and image != di.name:
            image += ' (obsolete)'

        rows.append([service.name, status, image])
    click.echo(tabulate(rows, headers=['Service name', 'Status',
                                       'Docker image']))


def _service_ext_help(ctx, formatter):
    if ctx.obj.services:
        with formatter.section('Services'):
            formatter.write_dl([(service.name, service.description or '')
                                for service in ctx.obj.services])
    else:
        with formatter.section('Services'):
            formatter.write_text('--- not defined ---')


def create_service_cli():
    service_group = ExtGroup('service', help='Services status and management',
                             ext_help=_service_ext_help)
    service_group.add_command(service_start)
    service_group.add_command(service_stop)
    service_group.add_command(service_status)

    cli = click.Group()
    cli.add_command(service_group)
    return cli
