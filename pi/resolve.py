import logging

from asyncio import Queue
from itertools import chain
from collections import defaultdict

from ._requires import attr

from .utils import MessageType, terminate
from .types import DockerImage
from .images import pull as pull_image
from .images import build as build_image


log = logging.getLogger(__name__)


@attr.s
class Dep:
    image = attr.ib()
    docker_image = attr.ib()


class ImagesCollector:

    def __init__(self, layers, services):
        self._layers = layers
        self._services = services
        self._images = set()

    @classmethod
    def collect(cls, layers, services, obj):
        self = cls(layers, services)
        self.visit(obj)
        return list(self._images)

    def visit(self, obj):
        return obj.accept(self)

    def visit_meta(self, obj):
        pass

    def visit_image(self, obj):
        self.add(obj.name)

    def add(self, image):
        if isinstance(image, DockerImage):
            self._images.add(Dep(None, image))
        else:
            layer = self._layers.get(image)
            self._images.add(Dep(layer.image, layer.docker_image()))
            if layer.image.from_ is not None:
                self.add(layer.image.from_)

    def visit_service(self, obj):
        self.add(obj.image)

    def visit_command(self, obj):
        self.add(obj.image)
        for service_name in (obj.requires or []):
            self.visit(self._services.get(service_name))


PULL_DONE = MessageType('PULL_DONE')
PULL_FAILED = MessageType('PULL_FAILED')
BUILD_DONE = MessageType('BUILD_DONE')
BUILD_FAILED = MessageType('BUILD_FAILED')


async def pull_worker(client, queue, result_queue):
    while True:
        dep = await queue.get()
        try:
            result = await pull_image(client, dep.docker_image)
        except Exception:
            log.exception('Failed to pull image')
            await result_queue.put((PULL_FAILED, dep))
        else:
            status = PULL_DONE if result else PULL_FAILED
            await result_queue.put((status, dep))


async def build_worker(client, layers, queue, result_queue, *, loop):
    while True:
        dep = await queue.get()
        try:
            layer = layers.get(dep.image.name)
            result = await build_image(client, layer, dep.image.tasks,
                                       loop=loop)
        except Exception:
            log.exception('Failed to build image')
            await result_queue.put((BUILD_FAILED, dep))
        else:
            status = BUILD_DONE if result else BUILD_FAILED
            await result_queue.put((status, dep))


def build_deps_map(plain_deps):
    deps_set = set(plain_deps)
    image_to_dep_map = {d.image.name: d for d in plain_deps
                        if d.image is not None}

    deps = defaultdict(set)

    for dep in plain_deps:
        if dep.image is not None:
            if isinstance(dep.image.from_, str):
                if dep.image.from_ in image_to_dep_map:
                    parent = image_to_dep_map[dep.image.from_]
                else:
                    parent = None  # image already exists
            elif isinstance(dep.image.from_, DockerImage):
                from_dep = Dep(None, dep.image.from_)
                if from_dep in deps_set:
                    parent = from_dep
                else:
                    parent = None  # image already exists
            else:
                raise TypeError(repr(dep.image.from_))
        else:
            parent = None

        if parent is not None and parent in deps_set:
            deps[dep].add(parent)
        else:
            deps.setdefault(dep, set())

    return dict(deps)


async def check(client, dependencies):
    available_images = await client.images()
    repo_tags = set(chain.from_iterable(i['RepoTags']
                                        for i in available_images))
    missing = [d for d in dependencies
               if d.docker_image.name not in repo_tags]
    return missing


def mark_working(deps_map, in_work, item):
    deps_map.pop(item)
    in_work.add(item)


def mark_done(deps_map, in_work, item):
    deps_map.pop(item, None)
    for v in deps_map.values():
        v.discard(item)
    in_work.discard(item)


def mark_failed(deps_map, in_work, item):
    failed = [item]
    deps_map.pop(item, None)
    for k, v in list(deps_map.items()):
        if item in v:
            failed.extend(mark_failed(deps_map, in_work, k))
    in_work.discard(item)
    return failed


async def resolve(client, layers, services, obj, *, loop,
                  pull=False, build=False, fail_fast=False):
    deps = ImagesCollector.collect(layers, services, obj)
    missing = await check(client, deps)
    if not missing or not (pull or build):
        return missing

    failed = []
    deps_map = build_deps_map(missing)
    in_work = set()

    # check existence of all images

    pull_queue = Queue()
    build_queue = Queue()
    result_queue = Queue()

    puller_task = loop.create_task(
        pull_worker(client, pull_queue, result_queue)
    )
    builder_task = loop.create_task(
        build_worker(client, layers, build_queue, result_queue, loop=loop)
    )
    try:
        while deps_map or in_work:
            # enqueue all tasks with resolved dependencies
            batch = [k for k, v in deps_map.items() if not v]
            init_queue = pull_queue if pull else build_queue
            for item in batch:
                mark_working(deps_map, in_work, item)
                await init_queue.put(item)

            result, image = await result_queue.get()

            if result is PULL_DONE:
                mark_done(deps_map, in_work, image)

            elif result is PULL_FAILED:
                if build:
                    await build_queue.put(image)
                else:
                    failed.extend(mark_failed(deps_map, in_work, image))
                    if fail_fast:
                        deps_map.clear()

            elif result is BUILD_DONE:
                mark_done(deps_map, in_work, image)

            elif result is BUILD_FAILED:
                failed.extend(mark_failed(deps_map, in_work, image))
                if fail_fast:
                    deps_map.clear()

    finally:
        await terminate(puller_task, loop=loop)
        await terminate(builder_task, loop=loop)
    return failed
