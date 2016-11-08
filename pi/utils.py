import math
import shlex
import asyncio

from collections import Sequence


def format_size(value):
    units = {0: 'B', 1: 'kB', 2: 'MB', 3: 'GB', 4: 'TB', 5: 'PB'}

    pow_ = 0
    while value >= 1000:
        value = float(value) / 1000
        pow_ += 1

    precision = 3 - int(math.floor(math.log10(value))) if value > 1 else 0
    unit = units.get(pow_, None) or '10^{} B'.format(pow_)
    size = (
        '{{value:.{precision}f}}'
        .format(precision=precision)
        .format(value=value, unit=unit)
        .rstrip('.0')
    )
    return '{} {}'.format(size, unit)


class cached_property(object):

    def __init__(self, func):
        self.__doc__ = getattr(func, '__doc__')
        self.func = func

    def __get__(self, obj, cls):
        if obj is None:
            return self
        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


class ImmutableDict(dict):
    _hash = None

    def __hash__(self):
        if self._hash is None:
            self._hash = hash(frozenset(self.items()))
        return self._hash

    def _immutable(self):
        raise TypeError("{} object is immutable"
                        .format(self.__class__.__name__))

    __delitem__ = __setitem__ = _immutable
    clear = pop = popitem = setdefault = update = _immutable


def search_container(label, containers):
    for container in containers:
        if label in container['Labels']:
            yield container


_unknown = object()


class SequenceMap:

    def __init__(self, items, key):
        self._items = list(items)
        self._items_map = {key(i): i for i in items}

    def get(self, key, default=_unknown):
        value = self._items_map.get(key, default)
        if value is _unknown:
            raise KeyError('Key {!r} not found'.format(key))
        return value

    def __iter__(self):
        return iter(self._items)


def sh_to_list(args):
    if isinstance(args, str):
        return shlex.split(args)
    else:
        assert isinstance(args, Sequence)
        return args


def async_func(func):
    func = asyncio.coroutine(func)

    def wrapper(*args, loop, **kwargs):
        task = loop.create_task(func(*args, loop=loop, **kwargs))
        try:
            loop.run_until_complete(task)
        except KeyboardInterrupt as err:
            task.cancel()
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass
            raise err
        except BaseException:
            raise task.exception()

    return wrapper
