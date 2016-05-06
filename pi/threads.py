import os
import sys
import select
import logging
import threading

from .console import raw_stdin


log = logging.getLogger(__name__)


class _Thread(threading.Thread):
    exit_code = None

    def run(self):
        try:
            super(_Thread, self).run()
        except SystemExit as exc:
            self.exit_code = exc.code
            raise


def _spawn(func, args=(), kwargs=None):
    thread = _Thread(target=func, args=args, kwargs=kwargs)
    thread.start()
    return thread


def _container_input(tty_fd, sock, exit_event):
    timeout = 0
    while True:
        if exit_event.is_set():
            break
        if any(select.select([tty_fd], [], [], timeout)):
            data = os.read(tty_fd, 32)
            sock.sendall(data)
            timeout = 0
        else:
            timeout = .2
    log.debug('input thread exited')


def _container_output(sock, exit_event):
    while True:
        try:
            data = sock.recv(4096)
        except IOError as e:
            log.debug('connection broken: %s', e)
            break
        if not data:
            break
        sys.stdout.write(data.decode('utf-8', 'replace'))
        sys.stdout.flush()
    exit_event.set()
    log.debug('output thread exited')


def spawn_input_thread(tty_fd, sock, exit_event):
    return _spawn(_container_input, [tty_fd, sock, exit_event])


def spawn_output_thread(sock, process_exit):
    return _spawn(_container_output, [sock, process_exit])


def start(func, args, ignore_cbrake=False):
    exit_event = threading.Event()
    with raw_stdin(not ignore_cbrake) as tty_fd:
        kwargs = dict(_exit_event=exit_event, _tty_fd=tty_fd)
        thread = _spawn(func, args, kwargs)
        try:
            while True:
                # using timeout to avoid main process blocking
                thread.join(.2)
                if not thread.is_alive():
                    break
        finally:
            log.debug('exiting...')
            exit_event.set()
            thread.join()
            log.debug('main thread exited')
        return thread.exit_code
