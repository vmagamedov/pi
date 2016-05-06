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
