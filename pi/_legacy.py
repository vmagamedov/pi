import os
import io
import sys
import json
import hashlib
import pathlib
import itertools
import functools
import collections
import logging.config
from datetime import datetime
from operator import attrgetter

from requests import ConnectionError

import toml

import click
from click.core import Command, Option
from click.types import IntParamType, StringParamType

from .run import docker_run
from .utils import format_size
from .client import Client
from .client import echo_download_progress, echo_build_progress
from .threads import start
from .console import COLORS, configure_logging


_CFG_DIR = '~/.pi'

CFG_DIR = pathlib.Path(os.path.expanduser(_CFG_DIR))

CUR_DIR = pathlib.Path('.').resolve()

PYTHON_MODULE_REGEX = r'^[a-zA-Z0-9]+\.py$|^[a-zA-Z0-9]+$'

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
    configure_logging(debug)


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
                    size=format_size(tag.size),
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
