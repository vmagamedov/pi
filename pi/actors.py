from asyncio import Queue, coroutine, wait, wait_for, CancelledError
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


def terminator(processes, *, loop):
    def coro(self):
        for p in processes:
            yield from terminate(p)
        loop.call_soon(loop.stop)

    def callback():
        print('Terminating...')
        spawn(coro, loop=loop)
    return callback
