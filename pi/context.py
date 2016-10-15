import asyncio

from .utils import cached_property, search_container
from .types import DockerImage


class Context:

    def __init__(self, layers, services):
        self.loop = asyncio.get_event_loop()
        self.layers = layers
        self.services = services
        self._layers_map = {l.name: l for l in layers}
        self._services_map = {s.name: s for s in services}

    @cached_property
    def client(self):
        from .client import get_client

        return get_client()

    @cached_property
    def async_client(self):
        from .client import AsyncClient

        return AsyncClient(loop=asyncio.get_event_loop())

    def require_image(self, image):
        if not isinstance(image, DockerImage):
            layer = self._layers_map[image]
            image = layer.docker_image()
        # check and autoload image
        return image

    def ensure_running(self, service_names):
        mapping = {s.name: s for s in self.services}
        services = [mapping[name] for name in service_names]
        containers = self.client.containers(all=True)
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

    def layers_path(self, name):
        path = []
        parent = self._layers_map[name]
        while parent is not None:
            path.append(parent)
            parent = path[-1].parent
        return tuple(reversed(path))

    def image_exists(self, image):
        from .client import APIError

        try:
            self.client.inspect_image(image.name)
        except APIError as e:
            if e.response.status_code == 404:
                return False
            raise
        else:
            return True

    def image_pull(self, image, printer):
        from .client import APIError

        try:
            output = self.client.pull(image.name, stream=True)
        except APIError as e:
            if e.response.status_code == 404:
                return False
            raise
        else:
            # NOTE: `printer` is also responsible in detecting errors
            return printer(output)

    def image_push(self, image, printer):
        output = self.client.push(image.name, stream=True)
        # NOTE: `printer` is also responsible in detecting errors
        return printer(output)
