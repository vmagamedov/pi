import sys
import tty
import termios
import logging.config

from contextlib import contextmanager

from . import __name__ as __root_logger__


COLORS = {
    '_red': '\x1b[38;5;1m',
    '_green': '\x1b[38;5;2m',
    '_yellow': '\x1b[38;5;3m',
    '_magenta': '\x1b[38;5;5m',
    '_cyan': '\x1b[38;5;6m',
    '_darkgray': '\x1b[38;5;8m',
    '_r': '\x1b[0m',
}

NO_COLORS = {k: '' for k in COLORS}

AUTO_COLORS = COLORS if sys.stdout.isatty() else NO_COLORS

LOG_FORMAT = '{asctime} {levelname} {name}: {message}'

LOG_STYLE = '{'

DATE_FORMAT = '%H:%M:%S'


@contextmanager
def config_tty():
    fd = sys.stdin.fileno()
    if sys.stdin.isatty() and sys.stdout.isatty():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            # fixes new-lines in raw mode
            fixed_mode = termios.tcgetattr(fd)
            fixed_mode[tty.OFLAG] |= tty.OPOST
            termios.tcsetattr(fd, termios.TCSAFLUSH, fixed_mode)
            yield fd, True
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    else:
        yield fd, False


def configure_logging(debug):
    log = logging.getLogger(__root_logger__)
    if debug:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT,
                                               LOG_STYLE))
        log.setLevel(logging.DEBUG)
        log.addHandler(handler)
    else:
        log.disabled = True


def pretty(string, *args, **kwargs):
    kwargs.update(AUTO_COLORS)
    return string.format(*args, **kwargs) + AUTO_COLORS['_r']
