import sys
import math
import shlex
import asyncio

from collections import Sequence


class MessageType:

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return '<MSG[{}]>'.format(self._name)


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

    def __len__(self):
        return len(self._items)


def sh_to_list(args):
    if isinstance(args, str):
        return shlex.split(args)
    else:
        assert isinstance(args, Sequence)
        return args


async def terminate(task, *, wait=1):
    task.cancel()
    try:
        await asyncio.wait_for(task, wait)
    except asyncio.CancelledError:
        pass


if sys.version_info > (3, 7):
    _current_task = asyncio.current_task
else:
    _current_task = asyncio.Task.current_task


class Wrapper:
    """Special wrapper for coroutines to wake them up in case of some error.

    Example:

    .. code-block:: python

        w = Wrapper()

        async def blocking_call():
            with w:
                await asyncio.sleep(10)

        # and somewhere else:
        w.cancel(NoNeedToWaitError('With explanation'))

    """
    _error = None

    cancelled = None

    def __init__(self):
        self._tasks = set()

    def __enter__(self):
        if self._error is not None:
            raise self._error

        task = _current_task()
        if task is None:
            raise RuntimeError('Called not inside a task')

        self._tasks.add(task)

    def __exit__(self, exc_type, exc_val, exc_tb):
        task = _current_task()
        assert task
        self._tasks.discard(task)
        if self._error is not None:
            raise self._error

    def cancel(self, error):
        self._error = error
        for task in self._tasks:
            task.cancel()
        self.cancelled = True
