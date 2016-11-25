import sys

from .._requires import click
from .._requires.tabulate import tabulate

from ..run import start
from ..utils import search_container, sh_to_list
from ..types import DockerImage
from ..images import get_docker_image
from ..context import async_cmd
from ..network import ensure_network
from ..console import pretty
from ..services import get_volumes, service_label


@click.pass_obj
@async_cmd
def _start_callback(ctx, name):
    service = ctx.services.get(name, None)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        sys.exit(-1)

    label = service_label(ctx.namespace, service)
    containers = yield from ctx.client.containers(all=True)
    container = next(search_container(label, containers), None)
    if container is not None:
        if container['State'] == 'running':
            click.echo('Service is already running')
        elif container['State'] == 'exited':
            yield from ctx.client.start(container)
            click.echo('Started previously stopped service')
        else:
            raise NotImplementedError(container['State'])
    else:
        exec_ = sh_to_list(service.exec) if service.exec else None
        args = sh_to_list(service.args) if service.args else None
        docker_image = get_docker_image(ctx.layers, service.image)
        yield from ensure_network(ctx.client, ctx.network)

        yield from start(ctx.client, docker_image, args,
                         entrypoint=exec_,
                         volumes=get_volumes(service.volumes),
                         ports=service.ports,
                         environ=service.environ,
                         network=ctx.network,
                         network_alias=service.name,
                         label=label)
        click.echo('Service started')


@click.pass_obj
@async_cmd
def _stop_callback(ctx, name):
    service = ctx.services.get(name, None)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        sys.exit(-1)

    label = service_label(ctx.namespace, service)
    all_containers = yield from ctx.client.containers(all=True)
    containers = list(search_container(label, all_containers))
    if not containers:
        click.echo('Service was not started')
        sys.exit(-1)

    for container in containers:
        if container['State'] == 'running':
            yield from ctx.client.stop(container, timeout=3)
        yield from ctx.client.remove_container(container, v=True, force=True)
    click.echo('Service stopped')


@click.pass_obj
@async_cmd
def _status_callback(ctx):
    containers = yield from ctx.client.containers(all=True)

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
    for service in ctx.services:
        label = service_label(ctx.namespace, service)
        if label in running:
            status = pretty('{_green}running{_r}')
            image = images[label]
        elif label in exited:
            status = pretty('{_red}stopped{_r}')
            image = images[label]
        else:
            status = None
            image = None

        if isinstance(service.image, DockerImage):
            docker_image = service.image
        else:
            docker_image = ctx.layers.get(service).docker_image()

        if image is not None and image != docker_image.name:
            image += ' (obsolete)'

        rows.append([service.name, status, image])
    click.echo(tabulate(rows, headers=['Service name', 'Status',
                                       'Docker image']))


def create_service_cli():
    service_group = click.Group('service')
    service_group.add_command(
        click.Command('start', params=[click.Argument(['name'])],
                      callback=_start_callback, help='Start service')
    )
    service_group.add_command(
        click.Command('stop', params=[click.Argument(['name'])],
                      callback=_stop_callback, help='Stop service')
    )
    service_group.add_command(
        click.Command('status', callback=_status_callback,
                      help='Services status')
    )
    cli = click.Group()
    cli.add_command(service_group)
    return cli
