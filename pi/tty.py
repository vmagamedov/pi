import sys
import tty
import termios
from contextlib import contextmanager


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
