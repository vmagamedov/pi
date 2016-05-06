import os
import io
import re
import sys
import json
import math
import socket
import select
import hashlib
import pathlib
import threading
import itertools
import functools
import collections
import logging.config
from datetime import datetime
from operator import attrgetter
from contextlib import closing

from requests import ConnectionError

import toml

import click
from click.core import Command, Option
from click.types import IntParamType, StringParamType

from .client import Client, APIError
from .client import echo_download_progress, echo_build_progress
from .console import raw_stdin, COLORS


_CFG_DIR = '~/.pi'

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


def docker_client(domain, port):
    return Client('tcp://{0}:{1}'.format(domain, port))


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
        docker = docker_client(*kwargs.pop('docker_host'))
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
        volume_bindings[host_path] = {'bind': dest_path, 'mode': mode}

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
    except APIError as e:
        click.echo(e.explanation)
        return

    try:
        try:
            client.start(container,
                         binds=volume_bindings,
                         port_bindings=port_bindings,
                         links=link_bindings)
        except APIError as e:
            click.echo(e.explanation)
            return

        width, height = click.get_terminal_size()
        client.resize(container, width, height)

        process_exit = threading.Event()

        attach_params = {'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream': 1}

        with closing(client.attach_socket_raw(container, attach_params)) as sock:
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

    def invoke(self, ctx):
        kwargs = ctx.params.copy()
        host = kwargs.pop('docker_host')
        image = kwargs.pop('docker_image')

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

        client = docker_client(*host)
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
                    line = '{_red}{0} {_reset}'.format('*', **COLORS)
                else:
                    line = '{_green}{0} {_reset}'.format('*', **COLORS)
            else:
                line = '  '
            name, version = tag.name.rsplit(':', 1)
            line += name + ':'
            line += '{_cyan}{0}{_reset}'.format(version, **COLORS)
            if tag.id:
                line += '{_darkgray} ID:{id} {size} {created}{_reset}'.format(
                    id=tag.id,
                    name=tag.name,
                    size=_format_size(tag.size),
                    created=tag.created.strftime('%Y-%m-%d %H:%M'),
                    **COLORS
                )
            click.echo(line)


def _match_image_alias(ctx, value):
    alias = IMAGE_ALIAS.get(value)
    if alias is not None:
        return alias()
    return value


@pi_image.command('pull', cls=DockerCommand)
@click.argument('docker-image', callback=_match_image_alias)
def image_pull(docker, docker_image):
    echo_download_progress(docker.pull(docker_image, stream=True))


@pi_image.command('push', cls=DockerCommand)
@click.argument('docker-image', callback=_match_image_alias)
def image_push(docker, docker_image):
    echo_download_progress(docker.push(docker_image, stream=True))


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


@build.command('env', cls=DockerCommand)
@click.option('--docker-file', default=ENV_DOCKER_FILE, show_default=True)
@click.option('--docker-image', default=ENV_IMAGE_TAG)
@click.option('--no-cache', is_flag=True)
def build_env(docker, docker_file, docker_image, no_cache):
    df_obj = _read_docker_files(docker_file.split(','))
    output = docker.build(tag=docker_image, fileobj=df_obj, nocache=no_cache,
                          rm=True, stream=True)
    echo_build_progress(docker, output)


@pi.command('test', cls=DockerShellCommand, default_image=ENV_IMAGE_TAG)
def pi_test(runner):
    runner(['python3.4', '-c', 'print("Hello")'])
