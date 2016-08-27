import math


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
