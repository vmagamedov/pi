import stat
import os.path
import platform

from ._res import DUMB_INIT_LOCAL_PATH


async def ensure_home():
    abs_path = os.path.expanduser('~/.pi')
    try:
        mode = os.stat(abs_path)[stat.ST_MODE]
    except FileNotFoundError:
        os.mkdir(abs_path)
    else:
        if not stat.S_ISDIR(mode):
            raise RuntimeError('{!r} is not a directory'.format(abs_path))
    return abs_path


async def ensure_bin():
    home_path = await ensure_home()
    abs_path = os.path.join(home_path, 'bin')
    try:
        mode = os.stat(abs_path)[stat.ST_MODE]
    except FileNotFoundError:
        os.mkdir(abs_path)
    else:
        if not stat.S_ISDIR(mode):
            raise RuntimeError('{!r} is not a directory'.format(abs_path))
    return abs_path


async def ensure_dumb_init():
    if platform.system() != 'Darwin':
        return DUMB_INIT_LOCAL_PATH

    bin_path = await ensure_bin()
    abs_path = os.path.join(bin_path, 'dumb-init-v1.2.1')
    try:
        mode = os.stat(abs_path)[stat.ST_MODE]
    except FileNotFoundError:
        os.link(DUMB_INIT_LOCAL_PATH, abs_path)
    else:
        if not stat.S_ISREG(mode):
            raise RuntimeError('{!r} is not a file'.format(abs_path))
    return abs_path
