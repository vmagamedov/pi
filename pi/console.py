import sys
import tty
import termios
from contextlib import contextmanager


COLORS = {
    '_red': '\x1b[38;5;1m',
    '_green': '\x1b[38;5;2m',
    '_yellow': '\x1b[38;5;3m',
    '_magenta': '\x1b[38;5;5m',
    '_cyan': '\x1b[38;5;6m',
    '_darkgray': '\x1b[38;5;8m',
    '_reset': '\x1b[0m',
}


@contextmanager
def raw_stdin(cbreak=True):
    if sys.stdin.isatty():
        fd = sys.stdin.fileno()
        dev_tty = None
    else:
        dev_tty = open('/dev/tty')
        fd = dev_tty.fileno()
    old = termios.tcgetattr(fd)
    try:
        if cbreak:
            tty.setcbreak(fd)
        else:
            tty.setraw(fd)
        yield fd
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if dev_tty is not None:
            dev_tty.close()
