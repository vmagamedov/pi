from ._requires import click
from ._requires.tabulate import tabulate

from .run import start
from .types import Service, DockerImage
from .actors import init
from .console import pretty
from .commands import get_volumes


def _search(label, containers):
    for container in containers:
        if label in container['Labels']:
            yield container


@click.pass_context
def _start_callback(ctx, name):
    service = ctx.obj.services.get(name)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        ctx.exit(-1)

    label = 'pi-{}'.format(service.name)
    container = next(_search(label, ctx.obj.client.containers(all=True)), None)
    if container is not None:
        if container['State'] == 'running':
            click.echo('Service is already running')
        elif container['State'] == 'exited':
            ctx.obj.client.start(container)
            click.echo('Started previously stopped service')
        else:
            raise NotImplementedError(container['State'])
    else:
        docker_image = ctx.obj.require_image(service.image)
        init(start, ctx.obj.client, docker_image, None, label=label,
             volumes=get_volumes(service.volumes), ports=service.ports)
        click.echo('Service started')


@click.pass_context
def _stop_callback(ctx, name):
    service = ctx.obj.services.get(name)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        ctx.exit(-1)

    label = 'pi-{}'.format(service.name)
    containers = list(_search(label, ctx.obj.client.containers(all=True)))
    if not containers:
        click.echo('Service was not started')
        ctx.exit(-1)

    for container in containers:
        if container['State'] == 'running':
            ctx.obj.client.stop(container, timeout=3)
        ctx.obj.client.remove_container(container, v=True, force=True)
    click.echo('Service stopped')


@click.pass_context
def _status_callback(ctx):
    containers = ctx.obj.client.containers(all=True)

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
    for service in ctx.obj.services.values():
        label = 'pi-{}'.format(service.name)
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
            docker_image = ctx.obj.layers[service.image].docker_image()

        if image is not None and image != docker_image.name:
            image += ' (obsolete)'

        rows.append([service.name, status, image])
    click.echo(tabulate(rows, headers=['Service name', 'Status',
                                       'Docker image']))


def get_services(config):
    # TODO: validate services definition (different ports)
    return [i for i in config if isinstance(i, Service)]


def create_service_cli(services):
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
