import sys
from collections import defaultdict


def _f(s):
    sys.stdout.write(s)
    sys.stdout.flush()


def _move(from_, to):
    count = to - from_
    if count > 0:
        _down(count)
    elif count < 0:
        _up(-count)


def _up(count):
    _f(f'{chr(27)}[{count}A')


def _down(count):
    _f(f'{chr(27)}[{count}B')


def _erase():
    _f(f'{chr(27)}[2K\r')


class Status:
    def __init__(self):
        self._idx = []
        self._steps = defaultdict(list)
        self._titles = {}
        self._current = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()

    def _move(self, to):
        _move(self._current, to)
        self._current = to

    def add_task(self, title):
        self._move(len(self._idx))

        key = object()
        self._titles[key] = title
        self._idx.append(key)
        _f(title)

        # new line
        _f('\n')
        self._current += 1
        return key

    def add_step(self, task_key, title):
        after_key = self._steps[task_key][-1] if task_key in self._steps else task_key

        pos = self._idx.index(after_key) + 1

        key = object()
        self._idx.insert(pos, key)
        self._steps[task_key].append(key)
        self._titles[key] = title

        self._move(pos)
        _erase()
        _f(title)
        for i in range(pos + 1, len(self._idx)):
            self._move(i)
            _erase()
            _f(self._titles[self._idx[i]])

        # new line
        _f('\n')
        self._current += 1
        return key

    def update(self, key, title):
        self._move(self._idx.index(key))
        _erase()
        _f(title)
        self._titles[key] = title

    def finish(self):
        self._move(len(self._idx))
        _erase()
