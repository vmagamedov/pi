from .utils import cached_property, SequenceMap
from .docker import Docker


class Environ:
    docker: Docker

    def __init__(self, meta, images, services):
        self._meta = meta
        self.images = SequenceMap(images, lambda i: i.name)
        self.services = SequenceMap(services, lambda i: i.name)

    @property
    def namespace(self):
        return self._meta.namespace or 'default'

    @property
    def network(self):
        return 'pi-{}'.format(self.namespace)

    @cached_property
    def docker(self):
        return Docker()
