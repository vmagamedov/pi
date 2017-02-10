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


class SingleMultiCommand(click.Command):

    def __init__(self, *args, ext_help=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ext_help = ext_help

    def parse_args(self, ctx, args):
        if not args:
            click.echo(ctx.get_help(), color=ctx.color)
            ctx.exit()
        return super().parse_args(ctx, args)

    def format_help_text(self, ctx, formatter):
        super().format_help_text(ctx, formatter)
        if self.ext_help is not None:
            self.ext_help(ctx, formatter)


@click.pass_obj
@async_cmd
async def _service_start(ctx, name):
    service = ctx.services.get(name, None)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        sys.exit(-1)

    label = service_label(ctx.namespace, service)
    containers = await ctx.client.containers(all=True)
    container = next(search_container(label, containers), None)
    if container is not None:
        if container['State'] == 'running':
            click.echo('Service is already running')
        elif container['State'] == 'exited':
            await ctx.client.start(container)
            click.echo('Started previously stopped service')
        else:
            raise NotImplementedError(container['State'])
    else:
        exec_ = sh_to_list(service.exec) if service.exec else None
        args = sh_to_list(service.args) if service.args else None
        docker_image = get_docker_image(ctx.layers, service.image)
        await ensure_network(ctx.client, ctx.network)

        await start(ctx.client, docker_image, args,
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
async def _service_stop(ctx, name):
    service = ctx.services.get(name, None)
    if service is None:
        click.echo('Unknown service name: {}'.format(name))
        sys.exit(-1)

    label = service_label(ctx.namespace, service)
    all_containers = await ctx.client.containers(all=True)
    containers = list(search_container(label, all_containers))
    if not containers:
        click.echo('Service was not started')
        sys.exit(-1)

    for container in containers:
        if container['State'] == 'running':
            await ctx.client.stop(container, timeout=3)
        await ctx.client.remove_container(container, v=True, force=True)
    click.echo('Service stopped')


@async_cmd
async def _service_status(ctx):
    containers = await ctx.client.containers(all=True)

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


def _service_ext_help(ctx, formatter):
    if ctx.obj.services:
        with formatter.section('Services'):
            formatter.write_dl([(service.name, service.description or '')
                                for service in ctx.obj.services])
    else:
        with formatter.section('Services'):
            formatter.write_text('--- not defined ---')
    with formatter.section('Actions'):
        formatter.write_text('start')
        formatter.write_text('stop')


def _service_status_callback(ctx, param, value):
    if value and not ctx.resilient_parsing:
        _service_status(ctx.obj)
        ctx.exit()


@click.pass_context
def _service_callback(ctx, name, action):
    if action == 'start':
        _service_start(name)
    elif action == 'stop':
        _service_stop(name)
    else:
        click.echo('Invalid action: {}'.format(action))
        ctx.exit(1)


def create_service_cli():
    params = [
        click.Option(['-s', '--status'], is_flag=True, is_eager=True,
                     expose_value=False, callback=_service_status_callback,
                     help='Display services status'),
        click.Argument(['name']),
        click.Argument(['action']),
    ]
    help_ = 'Services status and management'
    service_command = SingleMultiCommand('service', params=params,
                                         callback=_service_callback,
                                         help=help_, ext_help=_service_ext_help)
    cli = click.Group()
    cli.add_command(service_command)
    return cli
