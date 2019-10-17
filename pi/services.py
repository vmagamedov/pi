from .utils import search_container
from .types import Service, LocalPath, Mode


def service_label(namespace: str, service: Service):
    return '{}-{}'.format(namespace, service.name)


async def ensure_running(docker, namespace, services):
    containers = await docker.containers(params={'all': 'true'})
    for service in services:
        label = service_label(namespace, service)
        container = next(search_container(label, containers), None)
        if container is None:
            # TODO: Create container
            raise RuntimeError('Service {} is not running'
                               .format(service.name))
        if container['State'] != 'running':
            await docker.start(container['Id'])


def get_volumes(volumes):
    if volumes is not None:
        return volumes
    else:
        return [LocalPath('.', '.', Mode.RW)]


def get_services(config):
    # TODO: validate services definition (different ports)
    return [i for i in config if isinstance(i, Service)]
