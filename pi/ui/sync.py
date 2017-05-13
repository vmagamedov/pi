from .._requires.click import command, pass_obj, Group, Option

from ..environ import async_cmd

from .. import sync


@command('start', help='Start synchronization')
@pass_obj
@async_cmd
async def sync_start(env):
    port = await sync.start_server(env)
    await sync.start_client(port, loop=env.loop)


@command('stop', help='Stop synchronization')
@pass_obj
@async_cmd
async def sync_stop(env):
    print('stop')


@async_cmd
async def _sync_status(env):
    """
    remote volume: pi-sync-deadbeef
    remote unison: started
    local unison: started
    volume size: 3.14G
    """
    print('status')


def _sync_status_callback(ctx, param, value):
    if value and not ctx.resilient_parsing:
        _sync_status(ctx.obj)
        ctx.exit()


def create_sync_cli():
    params = [
        Option(['-s', '--status'], is_flag=True, is_eager=True,
                     expose_value=False, callback=_sync_status_callback,
                     help='Display services status'),
        # click.Argument(['name']),
    ]

    service_group = Group('sync', params=params,
                          help='Synchronization')
    service_group.add_command(sync_start)
    service_group.add_command(sync_stop)

    cli = Group()
    cli.add_command(service_group)
    return cli
