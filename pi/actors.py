from asyncio import Queue, coroutine, wait, wait_for, CancelledError, Event
from functools import partial


class MessageType:

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return '<MSG[{}]>'.format(self._name)


class Addr:
    task = None

    def __init__(self, *, loop):
        self.loop = loop
        self.mailbox = Queue()

    def spawn(self, fn, *args, **kwargs):
        return spawn(fn, list(args), kwargs, loop=self.loop)

    def exec(self, fn, *args, **kwargs):
        return self.loop.run_in_executor(None, partial(fn, *args, **kwargs))

    def wait(self, processes):
        return wait([a.task for a in processes], loop=self.loop)


def spawn(func, args=None, kwargs=None, *, loop):
    addr = Addr(loop=loop)

    args = args[:] if args is not None else []
    args.insert(0, addr)

    kwargs = kwargs.copy() if kwargs is not None else {}

    task = loop.create_task(func(*args, **kwargs))
    addr.task = task
    return addr


@coroutine
def terminate(addr):
    addr.task.cancel()
    try:
        yield from wait_for(addr.task, 1, loop=addr.loop)
    except CancelledError:
        pass


def send(addr, type_, value):
    yield from addr.mailbox.put((type_, value))


def receive(addr):
    return (yield from addr.mailbox.get())


class Terminator:

    def __init__(self, signals, processes, *, loop):
        self._signals = signals
        self._processes = processes
        self._loop = loop
        self._exit_event = Event()

    def install(self):
        for sig_num in self._signals:
            self._loop.add_signal_handler(sig_num, self._signal_handler)
        self._loop.create_task(self._watcher())

    def _exit(self):
        try:
            for p in self._processes:
                yield from terminate(p)
        finally:
            self._loop.call_soon(self._loop.stop)

    def _signal_handler(self):
        self._exit_event.set()
        self._loop.create_task(self._exit())

    def _watcher(self):
        yield from wait([p.task for p in self._processes],
                        loop=self._loop)
        if not self._exit_event.is_set():
            self._loop.call_soon(self._loop.stop)
