import asyncio

from operator import attrgetter

from .utils import cached_property, SequenceMap


class Context:

    def __init__(self, meta, layers, services):
        self._meta = meta
        self.loop = asyncio.get_event_loop()
        self.layers = SequenceMap(layers, attrgetter('name'))
        self.services = SequenceMap(services, attrgetter('name'))

    @property
    def namespace(self):
        return self._meta.namespace or 'pi'

    @property
    def network(self):
        if self._meta.namespace:
            return 'pi-{}'.format(self._meta.namespace)
        else:
            return 'pi'

    @cached_property
    def client(self):
        from .client import get_client

        return get_client()

    @cached_property
    def async_client(self):
        from .client import AsyncClient

        return AsyncClient(loop=asyncio.get_event_loop())

    def layers_path(self, name):
        path = []
        parent = self.layers.get(name)
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
