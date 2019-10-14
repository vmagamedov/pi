import sys
from collections import defaultdict


class Status:
    def __init__(self):
        self._idx = []
        self._steps = defaultdict(list)
        self._titles = {}
        self._current = 0
        self._file = sys.stdout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()

    def _write(self, s):
        self._file.write(s)
        self._file.flush()

    def _up(self, count):
        self._write(f'{chr(27)}[{count}A')

    def _down(self, count):
        self._write(f'{chr(27)}[{count}B')

    def _erase(self):
        self._write(f'{chr(27)}[2K\r')

    def _move(self, to):
        count = to - self._current
        if count > 0:
            self._down(count)
        elif count < 0:
            self._up(-count)
        self._current = to

    def _newline(self):
        self._write('\n')
        self._current += 1

    def add_task(self, title):
        self._move(len(self._idx))

        key = object()
        self._titles[key] = title
        self._idx.append(key)
        self._write(title)

        self._newline()
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

        self._move(insert_pos)
        self._erase()
        self._write(title)
        for i in range(insert_pos + 1, len(self._idx)):
            self._move(i)
            self._erase()
            self._write(self._titles[self._idx[i]])

        self._newline()
        return key

    def update(self, key, title):
        self._move(self._idx.index(key))
        self._erase()
        self._write(title)
        self._titles[key] = title

    def finish(self):
        self._move(len(self._idx))
        self._erase()
