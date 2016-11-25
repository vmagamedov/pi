import asyncio

from operator import attrgetter

from .utils import cached_property, SequenceMap, async_func


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

        return AsyncClient(loop=self.loop)


def async_cmd(func):

    @async_func()
    def async_wrapper(ctx, *args, loop, **kwargs):
        yield from func(ctx, *args, **kwargs)

    def sync_wrapper(ctx, *args, **kwargs):
        async_wrapper(ctx, *args, loop=ctx.loop, **kwargs)

    return sync_wrapper
