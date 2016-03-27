_CFG_DIR = '~/.pi'

_COLORS = {
    '_red': '\x1b[38;5;1m',
    '_green': '\x1b[38;5;2m',
    '_yellow': '\x1b[38;5;3m',
    '_magenta': '\x1b[38;5;5m',
    '_cyan': '\x1b[38;5;6m',
    '_darkgray': '\x1b[38;5;8m',
    '_reset': '\x1b[0m',
}


def bootstrap_pi_env():
    import sys
    if sys.version_info < (3, 4, 0):
        print('PI requires Python version >= 3.4')
        return 1

    try:
        import ensurepip
    except ImportError:
        print('Seems like your Python distribution is not complete,'
              ' "ensurepip" library is missing. Here is possible cause:'
              ' https://bugs.launchpad.net/bugs/1290847')
        return 1

    import os
    import venv
    import stat
    import pathlib
    import textwrap

    cfg_dir = pathlib.Path(os.path.expanduser(_CFG_DIR))
    env_dir = cfg_dir / 'env'
    bin_dir = cfg_dir / 'bin'
    x_mode = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

    print('Creating virtual environment in {0}...'.format(env_dir))
    venv.create(str(env_dir), clear=True, with_pip=True)
    print('Installing requirements...')
    os.system('{pip} install -q click==1.1 docker-py==0.3.1 toml.py==0.1.2'
              .format(pip=str(env_dir / 'bin' / 'pip')))
    pi_src = """
    #!{python}

    import sys
    sys.path.append('.')

    try:
        from pi import pi
    except ImportError:
        print("You're probably running pi outside of the project working "
              "directory")
        sys.exit(1)
    else:
        pi()
    """.format(python=env_dir / 'bin' / 'python')
    not bin_dir.exists() and bin_dir.mkdir()
    pi_path = bin_dir / 'pi'
    with pi_path.open('w+') as f:
        f.write(textwrap.dedent(pi_src).strip() + '\n')
    pi_path.chmod(pi_path.stat().st_mode | x_mode)
    print(
        '{_green}\u2714 TODO:{_reset}'
        ' Please add "{_yellow}{bin_dir}{_reset}"'
        ' to the {_magenta}PATH{_reset} variable in your OS environment'
        .format(bin_dir=bin_dir, **_COLORS)
    )


if __name__ == '__main__':
    import sys
    sys.exit(bootstrap_pi_env())


import os
import io
import re
import tty
import sys
import pwd
import json
import uuid
import math
import queue
import socket
import select
import termios
import hashlib
import pathlib
import tarfile
import platform
import tempfile
import threading
import itertools
import functools
import subprocess
import collections
import unicodedata
import http.client
import urllib.parse
import logging.config
import concurrent.futures
from datetime import datetime
from operator import attrgetter
from contextlib import closing, contextmanager

from requests import ConnectionError

import toml

from docker.client import Client as _DockerClient
from docker.client import APIError as DockerAPIError

import click
from click.core import Command, Option
from click.types import IntParamType, StringParamType, BOOL, INT


CFG_DIR = pathlib.Path(os.path.expanduser(_CFG_DIR))

CUR_DIR = pathlib.Path('.').resolve()

PYTHON_MODULE_REGEX = r'^[a-zA-Z0-9]+\.py$|^[a-zA-Z0-9]+$'

LC_CTYPE = 'en_US.UTF-8'

log = logging.getLogger('pi')


class FileType(StringParamType):
    pass

FILE = FileType()


class AddrType(StringParamType):
    name = 'domain:port'

    def convert(self, value, param, ctx):
        value = super(AddrType, self).convert(value, param, ctx)
        if not value:
            self.fail('empty', param, ctx)
        if ':' in value:
            domain, port = value.rsplit(':')
        else:
            self.fail('unknown format', param, ctx)
        try:
            port = int(port)
        except ValueError:
            self.fail('invalid port number', param, ctx)
        else:
            return (domain, port)

ADDR = AddrType()


class BindType(AddrType):
    name = 'ip:port'

BIND = BindType()


class PortType(IntParamType):
    pass

PORT = PortType()


class JSONType(StringParamType):
    name = 'json'

    def __init__(self, collection_type):
        self.collection_type = collection_type

    def convert(self, value, param, ctx):
        value = super(JSONType, self).convert(value, param, ctx)
        if not value:
            self.fail('empty', param, ctx)
        try:
            obj = json.loads(value)
        except ValueError:
            self.fail('invalid JSON value', param, ctx)
        if not isinstance(obj, self.collection_type):
            self.fail('invalid JSON type', param, ctx)
        return obj


ListJSON = JSONType(list)
DictJSON = JSONType(dict)


class LinkType(StringParamType):
    name = 'link'

    def convert(self, value, param, ctx):
        value = super(LinkType, self).convert(value, param, ctx)
        if not value:
            self.fail('empty', param, ctx)
        parts = value.split(':')
        if len(parts) == 1:
            name, = parts
            alias = name
        elif len(parts) == 2:
            name, alias = parts
        else:
            self.fail('unknown format', param, ctx)
        return name, alias

LINK = LinkType()


class VolumeType(StringParamType):
    name = 'volume'

    def convert(self, value, param, ctx):
        value = super(VolumeType, self).convert(value, param, ctx)
        if not value:
            self.fail('empty', param, ctx)
        parts = value.split(':')
        if len(parts) == 2:
            src, dst = parts
            mode = 'ro'
        elif len(parts) == 3:
            src, dst, mode = parts
            if mode not in {'ro', 'rw'}:
                self.fail('unknown mode', param, ctx)
        else:
            self.fail('unknown format', param, ctx)
        return src, dst, mode

VOLUME = VolumeType()


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


def _format_size(value):
    units = {0: 'B', 1: 'kB', 2: 'MB', 3: 'GB', 4: 'TB', 5: 'PB'}

    pow_ = 0
    while value >= 1000:
        value = float(value) / 1000
        pow_ += 1

    precision = 3 - int(math.floor(math.log10(value))) if value > 1 else 0
    unit = units.get(pow_, None) or '10^{} B'.format(pow_)
    size = (
        '{{value:.{precision}f}}'
        .format(precision=precision)
        .format(value=value, unit=unit)
        .rstrip('.0')
    )
    return '{} {}'.format(size, unit)


@contextmanager
def _raw_stdin(cbreak=True):
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


class DockerClient(_DockerClient):

    def __init__(self, domain, port):
        base_url = 'tcp://{0}:{1}'.format(domain, port)
        super(DockerClient, self).__init__(base_url, version='1.12')

    def _stream_helper(self, response):
        fp = response.raw._fp.fp
        # with closing(response.raw):
        try:
            while True:
                size = int(fp.readline().strip(), 16)
                if not size:
                    break
                yield fp.read(size + 2)[:-2]
        except:
            # interrupted read, closing connection
            response.raw.close()
            raise
        else:
            # this will release connection
            response.close()

    def attach_socket(self, container, params=None, ws=False):
        if params is None:
            params = {'stdout': 1, 'stderr': 1, 'stream': 1}

        if isinstance(container, dict):
            container = container['Id']

        url = self._url('/containers/{0}/attach'.format(container))
        netloc = urllib.parse.urlsplit(self.base_url).netloc
        conn = http.client.HTTPConnection(netloc)
        conn.request('POST', url, urllib.parse.urlencode(params), {
            'Content-Type': 'application/x-www-form-urlencoded',
        })
        resp = http.client.HTTPResponse(conn.sock, method='POST')
        resp.begin()
        return conn.sock

    def resize(self, container, width, height):
        if isinstance(container, dict):
            container = container['Id']

        params = urllib.parse.urlencode({'w': width, 'h': height})

        res = self._post(self._url('/containers/{0}/resize?{1}'
                                   .format(container, params)))
        self._raise_for_status(res)

    def push(self, repository, tag=None, stream=False):
        from docker.auth import auth
        from docker.utils import utils

        if not tag:
            repository, tag = utils.parse_repository_tag(repository)
        registry, repo_name = auth.resolve_repository_name(repository)
        if repo_name.count(':') == 1:
            repository, tag = repository.rsplit(':', 1)

        params = {'tag': tag}

        url = self._url('/images/{0}/push'.format(repository))
        response = self._post_json(url, None, params=params, stream=stream)
        if stream:
            return self._stream_helper(response)
        else:
            return self._result(response)

    def remove_container(self, container, v=False, force=False):
        if isinstance(container, dict):
            container = container.get('Id')
        params = {'v': v, 'force': force}
        res = self._delete(self._url("/containers/" + container),
                           params=params)
        self._raise_for_status(res)

    def build_context(self, context, tag, nocache=False, rm=False,
                      timeout=None):
        response = self._post(
            self._url('/build'),
            data=context,
            params={
                't': tag,
                'remote': None,
                'q': False,
                'nocache': nocache,
                'rm': rm
            },
            headers={'Content-Type': 'application/tar'},
            stream=True,
            timeout=timeout,
        )
        return self._stream_helper(response)


def _lines_writer(output_queue):
    chunks = []
    while True:
        data = yield
        if not data:
            break
        parts = data.split(b'\n')
        if len(parts) > 1:
            output_queue.append(b''.join(chunks + parts[0:1]))
            chunks[:] = []
            for part in parts[1:-1]:
                output_queue.append(part)
        if parts[-1]:
            chunks.append(parts[-1])


def _read_line(sock):
    result = []
    writer = _lines_writer(result)
    writer.send(None)  # gen start
    while not result:
        data = sock.recv(4096)
        if data is None:
            break
        writer.send(data)
    else:
        assert len(result) == 1
        return result[0]


def _assert_watchman_error(result):
    if 'error' in result:
        click.echo('Watchman error: {0}'.format(result['error']))
        sys.exit()


class expr(object):

    @classmethod
    def or_(cls, *exprs):
        return ['anyof'] + list(exprs)

    @classmethod
    def and_(cls, *exprs):
        return ['allof'] + list(exprs)

    @classmethod
    def not_(cls, expr):
        return ['not', expr]

    @classmethod
    def ext(cls, extension):
        return cls.and_(['type', 'f'], ['suffix', extension])

    @classmethod
    def dirname(cls, name, depth__eq=None, depth__ge=None):
        if depth__eq is not None:
            return ['dirname', name, ['depth', 'eq', depth__eq]]
        elif depth__ge is not None:
            return ['dirname', name, ['depth', 'ge', depth__ge]]
        else:
            return ['dirname', name]


def watchman(path, expr, queue, exit_event):
    try:
        raw_result = subprocess.check_output(['watchman', 'get-sockname'])
    except OSError as e:
        click.echo('Can\'t call "watchman" service, make sure that Watchman '
                   'is installed on your system')
        log.debug('Watchman call error: %s', e)
        return

    result = json.loads(raw_result.decode('utf-8'))
    if result['version'] < '3.1':
        click.echo('{_red}Please upgrade Watchman to the version >= 3.1'
                   'in order to use "reload" feature{_reset}'.format(**_COLORS))
        return

    error = result.get('error')
    if error is not None:
        click.echo('{_red}Can\'t watch files for changes. '
                   'Please resolve issue specified below:{_reset}\n{}'
                   .format(error, **_COLORS))
        return

    with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as sock:
        sock.connect(result['sockname'])

        sock.sendall(json.dumps(['watch', path]).encode('utf-8') + b'\n')
        _assert_watchman_error(json.loads(_read_line(sock).decode('utf-8')))

        sock.sendall(json.dumps(['clock', path]).encode('utf-8') + b'\n')
        clock_response = json.loads(_read_line(sock).decode('utf-8'))
        _assert_watchman_error(clock_response)
        clock = clock_response['clock']

        query = {
            'since': clock,
            'expression': expr,
            'fields': ['name'],
        }

        sock.sendall(json.dumps(['subscribe', path, uuid.uuid4().hex, query])
                     .encode('utf-8') + b'\n')
        _assert_watchman_error(json.loads(_read_line(sock).decode('utf-8')))

        lines_queue = collections.deque()
        lines_writer = _lines_writer(lines_queue)
        lines_writer.send(None)  # gen start
        while True:
            if exit_event.is_set():
                break
            if any(select.select([sock], [], [], .2)):
                data = sock.recv(4096)
                lines_writer.send(data)
                while True:
                    try:
                        line = lines_queue.popleft()
                    except IndexError:
                        break
                    else:
                        result = json.loads(line.decode('utf-8'))
                        _assert_watchman_error(result)
                        queue.put(result['files'])

    log.debug('watchman thread exited')


def reloader(reload_conf, func, args, kwargs):
    exit_event = kwargs.pop('_exit_event')

    files_queue = queue.Queue()
    files_queue.put([])  # for the first run

    func_exit_event = threading.Event()

    path = reload_conf['path']
    expr = reload_conf['expr']

    watch_thread = _spawn(watchman, [path, expr, files_queue, exit_event])

    func_thread = None
    while True:
        # signal from the outside to exit
        if exit_event.is_set():
            if func_thread is not None and func_thread.is_alive():
                func_exit_event.set()
                func_thread.join()
            watch_thread.join()
            break

        # we have changes, optionally kill and start new process
        try:
            files_queue.get(True, .2)
        except queue.Empty:
            continue
        else:
            if func_thread is not None and func_thread.is_alive():
                func_exit_event.set()
                func_thread.join()
            func_exit_event.clear()
            func_thread = _spawn(func, args, dict(kwargs,
                                                  _exit_event=func_exit_event))
            continue


def start(func, args, reload_conf=None, ignore_cbrake=False):
    exit_event = threading.Event()
    with _raw_stdin(not ignore_cbrake) as tty_fd:
        kwargs = dict(_exit_event=exit_event, _tty_fd=tty_fd)
        if reload_conf is not None:
            thread = _spawn(reloader, [reload_conf, func, args, kwargs])
        else:
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


def _is_up_or_exit(client):
    try:
        client.version()
    except ConnectionError:
        click.echo("Can't connect to the Docker daemon ('docker -d'), please "
                   "check that it is running and reachable at the {0} address"
                   .format(client.base_url))
        sys.exit(1)


def _missing_links(client, names):
    if not len(names):
        return []
    running = {name.lstrip('/')
               for name in itertools.chain(*(c['Names']
                                             for c in client.containers()))}
    return list(set(names) - running)


class DockerCommand(Command):

    def __init__(self, **kwargs):
        super(DockerCommand, self).__init__(**kwargs)
        self.params.append(Option(
            ['--docker-host'],
            type=ADDR,
            default='localhost:4243',
            show_default=True,
            help='Docker API endpoint',
            required=True,
        ))

    def invoke(self, ctx):
        kwargs = ctx.params.copy()
        docker = DockerClient(*kwargs.pop('docker_host'))
        _is_up_or_exit(docker)
        ctx.invoke(self.callback, docker, **kwargs)


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


def docker_run(client, docker_image, command, environ, user, work_dir, volumes,
               ports, links, _exit_event, _tty_fd):
    if _tty_fd is not None:
        environ = dict(environ or {}, LC_CTYPE=LC_CTYPE)

    container_volumes = []
    volume_bindings = {}
    for host_path, dest_path, mode in volumes:
        container_volumes.append(dest_path)
        volume_bindings[host_path] = '{0}:{1}'.format(dest_path, mode)

    container_ports = []
    port_bindings = {}
    for ext_ip, ext_port, int_port in ports:
        container_ports.append(int_port)
        port_bindings[int_port] = (ext_ip, ext_port)

    link_bindings = [(v, k) for k, v in links.items()]

    try:
        container = client.create_container(
            docker_image,
            command=command,
            environment=environ,
            user=user,
            tty=True,
            stdin_open=True,
            ports=container_ports,
            volumes=container_volumes,
            working_dir=work_dir or None,
        )
    except DockerAPIError as e:
        click.echo(e.explanation)
        return

    try:
        try:
            client.start(container, volume_bindings, port_bindings,
                         links=link_bindings)
        except DockerAPIError as e:
            click.echo(e.explanation)
            return

        width, height = click.get_terminal_size()
        client.resize(container, width, height)

        process_exit = threading.Event()

        attach_params = {'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream': 1}

        with closing(client.attach_socket(container, attach_params)) as sock:
            input_thread = _spawn(_container_input, [_tty_fd, sock, _exit_event])
            output_thread = _spawn(_container_output, [sock, process_exit])
            while True:
                if _exit_event.wait(.2):
                    client.stop(container, timeout=5)
                    try:
                        # just to be sure that output thread will exit normally
                        sock.shutdown(socket.SHUT_RDWR)
                    except IOError:
                        pass
                    break
                if process_exit.is_set():
                    _exit_event.set()
                    break
            input_thread.join()
            output_thread.join()
        exit_code = client.wait(container)
        if exit_code >= 0:
            sys.exit(exit_code)
    finally:
        client.remove_container(container, v=True, force=True)
        log.debug('run thread exited')


class DockerShellCommand(Command):

    def __init__(self, **kwargs):
        self.default_image = kwargs.pop('default_image', None)
        self.reload_conf = kwargs.pop('reload_conf', None)
        self.ignore_cbrake = kwargs.pop('ignore_cbrake', False)
        super(DockerShellCommand, self).__init__(**kwargs)
        self.params.append(Option(
            ['--docker-host'],
            type=ADDR,
            default='localhost:4243',
            show_default=True,
            help='Docker API endpoint',
        ))
        self.params.append(Option(
            ['--docker-image'],
            default=self.default_image,
            help='Docker image',
            required=True,
        ))
        if self.reload_conf is not None:
            self.params.append(Option(['--reload'], is_flag=True))

    def invoke(self, ctx):
        kwargs = ctx.params.copy()
        host = kwargs.pop('docker_host')
        image = kwargs.pop('docker_image')
        reload_ = kwargs.pop('reload', False) if self.reload_conf else None

        user = (conf2(ctx, 'env.user', None) or
                '{0}:{1}'.format(os.getuid(), os.getgid()))
        bind_all = conf2(ctx, 'env.bind_all', False)
        work_dir = conf2(ctx, 'env.work_dir', None) or os.getcwd()

        current = ctx
        path = [current]
        while current.parent:
            current = current.parent
            path.append(current)

        links = {}
        for ctx_ in reversed(path):
            links.update(conf(ctx_, '.links', {}))
            links.update(conf2(ctx_, '.links', {}))

        volumes = [[work_dir, work_dir, 'rw']]
        for ctx_ in reversed(path):
            volumes.extend(conf(ctx_, '.volumes', []))
            volumes.extend(conf2(ctx_, '.volumes', []))

        ports = []

        for param in self.params:
            if isinstance(param.type, FileType) and param.name in kwargs:
                value = kwargs[param.name]
                if not value.startswith('/'):
                    kwargs[param.name] = work_dir.rstrip('/') + '/' + value
            elif isinstance(param.type, BindType):
                bind_addr = kwargs.get(param.name)
                if bind_addr is not None:
                    ip, port = bind_addr
                    if bind_all:
                        ip = '0.0.0.0'
                    ports.append((ip, port, port))
                    kwargs[param.name] = ('0.0.0.0', port)
            elif isinstance(param.type, PortType):
                port = kwargs.get(param.name)
                if port is not None:
                    ip = '0.0.0.0' if bind_all else '127.0.0.1'
                    ports.append((ip, port, port))

        reload_conf = self.reload_conf if reload_ else None

        client = DockerClient(*host)
        _is_up_or_exit(client)

        missing = _missing_links(client, links.values())
        if missing:
            click.echo('Linked containers are not running: {0}'
                       .format(', '.join(missing)))
            ctx.exit(1)

        def runner(command, environ=None):
            exit_code = start(
                docker_run,
                [client, image, command, environ, user, work_dir, volumes,
                 ports, links],
                reload_conf=reload_conf,
                ignore_cbrake=self.ignore_cbrake,
            )
            if exit_code:
                ctx.exit(exit_code)

        ctx.invoke(self.callback, runner, **kwargs)


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#
#                                    CLI                                       #
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#


@click.group()
@click.option('--debug', is_flag=True)
@click.pass_context
def pi(ctx, debug):
    ctx.obj = {}
    for file_path in [CUR_DIR / 'pi.conf', CFG_DIR / 'pi.conf']:
        if file_path.exists():
            with file_path.open() as cfg:
                try:
                    ctx.obj = toml.loads(cfg.read())
                except toml.TomlSyntaxError as e:
                    click.echo("Config parsing error: {0}; {1}"
                               .format(file_path, e))
                    ctx.exit(1)
            break
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


_undefined = object()


def conf(ctx, path, default=_undefined):
    if path.startswith('.'):
        parts = ctx.command_path.split()[1:] + path.lstrip('.').split('.')
    else:
        parts = path.split('.')

    obj = ctx.obj
    for key in parts:
        try:
            obj = obj[key]
        except (LookupError, TypeError):
            if default is _undefined:
                raise LookupError('missing config value')
            return default
    return obj


def conf2(ctx, path, default=_undefined):
    if path.startswith('.'):
        parts = ctx.command_path.split() + [path.lstrip('.')]
    else:
        parts = path.split('.')

    obj = ctx.obj
    for key in parts:
        try:
            obj = obj[key]
        except (LookupError, TypeError):
            if default is _undefined:
                raise LookupError('missing config value')
            return default
    return obj


@pi.group('image')
def pi_image():
    pass


def _tag_from_hash(docker_files, image_name):
    h = hashlib.sha1()
    for docker_file in docker_files:
        with open(docker_file, 'rb') as f:
            h.update(f.read())
    return '{name}:{tag}'.format(name=image_name, tag=h.hexdigest()[:12])


# def _tag_from_hg_id(image_name):
#     app_version = subprocess.check_output(['hg', 'id', '--id']).strip()
#     return '{name}:{tag}'.format(name=image_name, tag=app_version)


ENV_IMAGE = 'reg.local/test/env'
ENV_DOCKER_FILE = 'Dockerfile.env'

ENV_IMAGE_TAG = functools.partial(
    _tag_from_hash,
    docker_files=[ENV_DOCKER_FILE],
    image_name=ENV_IMAGE,
)

IMAGE_ALIAS = {
    'env': ENV_IMAGE_TAG,
}

Tag = collections.namedtuple('Tag', 'id, name, size, created, current, missing')


@pi_image.command('list', cls=DockerCommand)
def image_list(docker):
    repos = [
        (ENV_IMAGE, ENV_IMAGE_TAG()),
    ]
    for image_name, current_image_tag in repos:
        tags = []
        for image in docker.images(image_name):
            for tag in image['RepoTags']:
                tags.append(Tag(
                    id=image['Id'][:12],
                    name=tag,
                    size=image['VirtualSize'],
                    created=datetime.fromtimestamp(image['Created']),
                    current=(tag == current_image_tag),
                    missing=False,
                ))
        tags.sort(key=attrgetter('created'), reverse=True)
        if current_image_tag not in {tag.name for tag in tags}:
            tags.insert(0, Tag(id=None, name=current_image_tag, size=None,
                               created=None, current=True, missing=True))

        for tag in tags:
            if tag.current:
                if tag.missing:
                    line = '{_red}{0} {_reset}'.format('*', **_COLORS)
                else:
                    line = '{_green}{0} {_reset}'.format('*', **_COLORS)
            else:
                line = '  '
            name, version = tag.name.rsplit(':', 1)
            line += name + ':'
            line += '{_cyan}{0}{_reset}'.format(version, **_COLORS)
            if tag.id:
                line += '{_darkgray} ID:{id} {size} {created}{_reset}'.format(
                    id=tag.id,
                    name=tag.name,
                    size=_format_size(tag.size),
                    created=tag.created.strftime('%Y-%m-%d %H:%M'),
                    **_COLORS
                )
            click.echo(line)


def _match_image_alias(ctx, value):
    alias = IMAGE_ALIAS.get(value)
    if alias is not None:
        return alias()
    return value


def _echo_streamed_progress(output):
    last_id = None
    for line in output:
        log.debug(line)
        progress = json.loads(line.decode('utf-8'))

        progress_id = progress.get('id')
        if last_id:
            if progress_id == last_id:
                sys.stdout.write('\x1b[2K\r')
            elif not progress_id or progress_id != last_id:
                sys.stdout.write('\n')
        last_id = progress_id

        if progress_id:
            sys.stdout.write('{}: '.format(progress_id))
        sys.stdout.write(progress.get('status') or progress.get('error') or '')

        progress_bar = progress.get('progress')
        if progress_bar:
            sys.stdout.write(' ' + progress_bar)

        if not progress_id:
            sys.stdout.write('\n')
        sys.stdout.flush()
    if last_id:
        sys.stdout.write('\n')
        sys.stdout.flush()


@pi_image.command('pull', cls=DockerCommand)
@click.argument('docker-image', callback=_match_image_alias)
def image_pull(docker, docker_image):
    _echo_streamed_progress(docker.pull(docker_image, stream=True))


@pi_image.command('push', cls=DockerCommand)
@click.argument('docker-image', callback=_match_image_alias)
def image_push(docker, docker_image):
    _echo_streamed_progress(docker.push(docker_image, stream=True))


@pi_image.command('shell', cls=DockerCommand)
@click.argument('docker-image', callback=_match_image_alias)
@click.option('--link', type=LINK, multiple=True,
              help='Link another container (name or name:alias)')
@click.option('--volume', type=VOLUME, multiple=True,
              help='Mount volume from host into container '
                   '(/host:/container or /host:/container:rw)')
def image_shell(docker, docker_image, link, volume):
    links = {alias: name for name, alias in link}
    missing = _missing_links(docker, links.values())
    if missing:
        click.echo('Linked containers are not running: {0}'
                   .format(', '.join(missing)))
        sys.exit(1)

    start(docker_run,
          [docker, docker_image, ['/bin/bash'], None, None, None, volume, [],
           links],
          ignore_cbrake=True)


@pi.group()
def build():
    pass


def _read_docker_files(docker_files):
    df = io.BytesIO()
    for file_name in docker_files:
        with open(file_name, 'rb') as f:
            df.write(f.read())
    df.seek(0)
    return df


def _build_progress(docker, output):
    latest_container = None
    try:
        for line in output:
            log.debug(line)
            status = json.loads(line.decode('utf-8'))
            if 'stream' in status:
                click.echo(status['stream'], nl=False)
                match = re.search(u'Running in ([0-9a-f]+)', status['stream'])
                if match:
                    latest_container = match.group(1)
            elif 'error' in status:
                click.echo(status['error'])
    except BaseException as original_exc:
        try:
            if latest_container is not None:
                click.echo('Stopping current container {}...'
                           .format(latest_container))
                docker.stop(latest_container, 5)
                docker.remove_container(latest_container)
        except:
            log.exception('Failed to delete current container')
        finally:
            raise original_exc


@build.command('env', cls=DockerCommand)
@click.option('--docker-file', default=ENV_DOCKER_FILE, show_default=True)
@click.option('--docker-image', default=ENV_IMAGE_TAG)
@click.option('--no-cache', is_flag=True)
def build_env(docker, docker_file, docker_image, no_cache):
    df_obj = _read_docker_files(docker_file.split(','))
    output = docker.build(tag=docker_image, fileobj=df_obj, nocache=no_cache,
                          rm=True, stream=True)
    _build_progress(docker, output)


@pi.command('test', cls=DockerShellCommand, default_image=ENV_IMAGE_TAG)
def pi_test(runner):
    runner(['python3.4', '-c', 'print("Hello")'])
