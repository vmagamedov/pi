import logging
from enum import Enum
from asyncio import Queue, coroutine
from itertools import chain
from collections import defaultdict

from ._requires import attr

from .types import DockerImage, Dockerfile
from .build import Builder


log = logging.getLogger(__name__)


@attr.s
class Dep:
    image = attr.ib()
    docker_image = attr.ib()


class ImagesCollector:

    def __init__(self, layers, services):
        self._layers_map = {l.name: l for l in layers}
        self._services_map = {s.name for s in services}
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
        pass

    def add(self, image):
        if isinstance(image, DockerImage):
            self._images.add(Dep(None, image))
        else:
            layer = self._layers_map[image]
            self._images.add(Dep(layer.image, layer.docker_image()))
            if layer.image.from_ is not None:
                self.add(layer.image.from_)

    def visit_service(self, obj):
        self.add(obj.image)

    def visit_shellcommand(self, obj):
        self.add(obj.image)
        for service in (obj.requires or []):
            self.visit(service)

    def visit_subcommand(self, obj):
        self.add(obj.image)
        for service in (obj.requires or []):
            self.visit(service)


class Result(Enum):
    pull_done = 1
    pull_failed = 2
    build_done = 3
    build_failed = 4


@coroutine
def pull_worker(queue, result_queue):
    while True:
        dep = yield from queue.get()
        print('pull >>>', dep)
        yield from result_queue.put((Result.pull_failed, dep))


@coroutine
def build_worker(client, async_client, layers, queue, result_queue, *, loop):
    while True:
        dep = yield from queue.get()
        try:
            layer = {l.name: l for l in layers}[dep.image.name]
            builder = Builder(client, async_client, layer, loop=loop)
            result = yield from builder.visit(dep.image.provision_with)
        except Exception:
            log.exception('Failed to build image')
            yield from result_queue.put((Result.build_failed, dep))
        else:
            status = Result.build_done if result else Result.build_failed
            yield from result_queue.put((status, dep))


def build_deps_map(plain_deps):
    deps_set = set(plain_deps)
    images_mapping = {d.image.name: d for d in plain_deps if d.image is not None}

    deps = defaultdict(set)

    for dep in plain_deps:
        if dep.image is not None:
            if isinstance(dep.image.from_, str):
                parent = images_mapping[dep.image.from_]
            elif isinstance(dep.image.from_, DockerImage):
                parent = Dep(None, dep.image.from_)
            elif dep.image.from_ is None and isinstance(dep.image.provision_with,
                                                        Dockerfile):
                parent = None
            else:
                raise TypeError(repr(dep.image.from_))
        else:
            parent = None

        if parent is not None and parent in deps_set:
            deps[dep].add(parent)
        else:
            deps.setdefault(dep, set())

    return dict(deps)


@coroutine
def check(client, dependencies):
    available_images = yield from client.images()
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


@coroutine
def resolve(client, async_client, layers, services, obj, *, loop,
            pull=False, build=False, fail_fast=False):
    deps = ImagesCollector.collect(layers, services, obj)
    missing = yield from check(async_client, deps)
    if not missing or not (pull or build):
        return missing

    failed = []
    deps_map = build_deps_map(missing)
    in_work = set()

    # check existence of all images

    pull_queue = Queue()
    build_queue = Queue()
    result_queue = Queue()

    puller_task = loop.create_task(pull_worker(pull_queue, result_queue))
    builder_task = loop.create_task(build_worker(client, async_client, layers,
                                                 build_queue, result_queue,
                                                 loop=loop))
    try:
        while deps_map or in_work:
            # enqueue all tasks with resolved dependencies
            batch = [k for k, v in deps_map.items() if not v]
            init_queue = pull_queue if pull else build_queue
            for item in batch:
                mark_working(deps_map, in_work, item)
                yield from init_queue.put(item)

            result, image = yield from result_queue.get()

            if result is Result.pull_done:
                mark_done(deps_map, in_work, image)

            elif result is Result.pull_failed:
                if build:
                    yield from build_queue.put(image)
                else:
                    failed.extend(mark_failed(deps_map, in_work, image))
                    if fail_fast:
                        deps_map.clear()

            elif result is Result.build_done:
                mark_done(deps_map, in_work, image)

            elif result is Result.build_failed:
                failed.extend(mark_failed(deps_map, in_work, image))
                if fail_fast:
                    deps_map.clear()

    finally:
        puller_task.cancel()
        builder_task.cancel()
    return failed
