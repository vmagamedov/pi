import sys
import tty
import termios
import logging.config

from contextlib import contextmanager


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


@contextmanager
def config_tty():
    fd = sys.stdin.fileno()
    if sys.stdin.isatty() and sys.stdout.isatty():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            yield fd, True
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    else:
        yield fd, False


def configure_logging(debug):
    log = logging.getLogger('pi')
    if debug:
        logging.config.dictConfig({
            'version': 1,
            'formatters': {'standard': {
                'format': '{asctime} {levelname} {name}: {message}',
                'style': '{',
                'datefmt': '%H:%M:%S',
            }},
            'handlers': {'default': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'standard',
                'stream': 'ext://sys.stderr',
            }},
            'loggers': {log.name: {
                'handlers': ['default'],
                'level': 'DEBUG',
            }},
        })
    else:
        log.disabled = True


def pretty(string, *args, **kwargs):
    kwargs.update(AUTO_COLORS)
    return string.format(*args, **kwargs) + AUTO_COLORS['_r']
