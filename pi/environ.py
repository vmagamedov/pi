import asyncio

from operator import attrgetter

from .utils import cached_property, SequenceMap, async_func


class Environ:

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
        from .client import AsyncClient

        return AsyncClient(loop=self.loop)


def async_cmd(func):

    @async_func()
    async def async_wrapper(env, *args, loop, **kwargs):
        await func(env, *args, **kwargs)

    def sync_wrapper(env, *args, **kwargs):
        async_wrapper(env, *args, loop=env.loop, **kwargs)

    return sync_wrapper
