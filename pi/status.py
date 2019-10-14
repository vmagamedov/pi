import sys
from collections import defaultdict


class Status:
    def __init__(self, *, output=sys.stdout):
        self._idx = []
        self._steps = defaultdict(list)
        self._titles = {}
        self._current = 0
        self._output = output

    def _up(self, count):
        self._output.write(f'{chr(27)}[{count}A')

    def _down(self, count):
        self._output.write(f'{chr(27)}[{count}B')

    def _erase(self):
        self._output.write(f'{chr(27)}[2K\r')

    def _move(self, to):
        count = to - self._current
        if count > 0:
            self._down(count)
        elif count < 0:
            self._up(-count)
        self._current = to

    def _newline(self):
        self._output.write('\n')
        self._current += 1

    def _refresh(self, key):
        self._move(self._idx.index(key))
        self._erase()
        self._output.write(self._titles[key])

    def add_task(self, title):
        self._move(len(self._idx))
        self._newline()

        key = object()
        self._idx.append(key)
        self._titles[key] = title
        self._refresh(key)

        self._output.flush()
        return key

    def add_step(self, task_key, title):
        if task_key in self._steps:
            append_after = self._steps[task_key][-1]
        else:
            append_after = task_key

        insert_pos = self._idx.index(append_after) + 1

        key = object()
        self._idx.insert(insert_pos, key)
        self._steps[task_key].append(key)
        self._titles[key] = title

        # rerender
        for key in self._idx[insert_pos:]:
            self._refresh(key)
        self._newline()

        self._output.flush()
        return key

    def update(self, key, title):
        self._titles[key] = title
        self._refresh(key)
        self._output.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._move(len(self._idx))
        self._erase()
        self._output.flush()
