from .utils import search_container
from .types import Service, LocalPath, Mode


def ensure_running(client, services):
    containers = client.containers(all=True)
    hosts = {}
    for service in services:
        label = 'pi-{}'.format(service.name)
        container = next(search_container(label, containers), None)
        if container is None:
            raise RuntimeError('Service {} is not running'
                               .format(service.name))
        if container['State'] != 'running':
            assert False, 'TODO: auto-start'
        ip = container['NetworkSettings']['Networks']['bridge']['IPAddress']
        hosts[service.name] = ip
    return hosts


def get_volumes(volumes):
    if volumes is not None:
        return volumes
    else:
        return [LocalPath('.', '.', Mode.RW)]


def get_services(config):
    # TODO: validate services definition (different ports)
    return [i for i in config if isinstance(i, Service)]
