#!/usr/bin/env python3
import sys
import logging

from urllib.parse import quote, unquote


log = logging.getLogger('fsmonitor')


def send(cmd, *args):
    msg = ' '.join((cmd,) + tuple(map(quote, args)))
    log.debug('send: %r', msg)
    print(msg, file=sys.stdout)


def recv():
    sys.stdout.flush()
    line = sys.stdin.readline()
    log.debug('recv: %r', line)
    if not line.endswith('\n'):
        raise EOFError
    cmd, *args = line.strip().split(' ')
    return cmd, tuple(map(unquote, args))


def version(num):
    if num != '1':
        send('ERROR', ('Unexpected version number: {!r}'
                       .format(num)))
    send('VERSION', '1')


def start(replica, fspath, path=''):
    # TODO: subscribe to file changes
    send('OK')
    while True:
        cmd, args = recv()
        if cmd == 'DIR':
            send('OK')
        elif cmd == 'LINK':
            send('ERROR', 'Links are not supported')
        elif cmd == 'DONE':
            break
        else:
            send('ERROR', ('Unexpected command during replica start: {}'
                           .format(cmd)))


def wait():
    pass


def changes():
    pass


def reset():
    pass


MAP = {
    'VERSION': version,
    'START': start,
    'WAIT': wait,
    'CHANGES': changes,
    'RESET': reset,
}


def main():
    while True:
        cmd, args = recv()
        action = MAP.get(cmd)
        if not action:
            raise NotImplementedError(cmd)
        action(*args)

    # send('VERSION', '1')
    # try:
    #     cmd, (version,) = recv()
    #     print('>>>', cmd, version, file=sys.stderr)
    #     if cmd != 'VERSION':
    #         send('ERROR', 'Unexpected VERSION command: {!r}'.format(cmd))
    #         return
    #     if version != '1':
    #         send('ERROR', 'Unexpected version number: {!r}'.format(version))
    #     while True:
    #         cmd, args = recv()
    #         print('>>>', cmd, args, file=sys.stderr)
    # except EOFError:
    #     pass


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
