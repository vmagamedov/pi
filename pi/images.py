import json
import hashlib

from .http import HTTPError
from .types import DockerImage, Image, ActionType


class Hasher:

    def visit(self, obj):
        return obj.accept(self)

    def visit_image(self, obj):
        yield obj.repository.encode('utf-8')
        for task in obj.tasks:
            yield from self.visit(task)

    def visit_task(self, obj):
        yield obj.run.encode('utf-8')
        for value in obj.where.values():
            if isinstance(value, ActionType):
                yield from self.visit(value)
            else:
                yield str(value).encode('utf-8')

    def visit_download(self, obj):
        yield obj.url.encode('utf-8')

    def visit_file(self, obj):
        with open(obj.path, 'rb') as f:
            while True:
                chunk = f.read(2**16)
                if not chunk:
                    break
                else:
                    yield chunk

    def visit_bundle(self, obj):
        yield obj.path.encode('utf-8')


def image_hashes(images_map, images, *, _cache=None):
    _cache = _cache or {}

    hasher = Hasher()
    hashes = []
    for image in images:
        if image.name in _cache:
            hashes.append(_cache[image.name])
            continue

        if isinstance(image.from_, DockerImage):
            parent_hashable = image.from_.name
        else:
            parent = images_map.get(image.from_)
            parent_hashable, = image_hashes(images_map, [parent],
                                            _cache=_cache)

        h = hashlib.sha1()
        h.update(parent_hashable.encode('utf-8'))
        for chunk in hasher.visit(image):
            h.update(chunk)
        hex_digest = _cache[image.name] = h.hexdigest()
        hashes.append(hex_digest)
    return hashes


def image_versions(images_map, images):
    hashes = image_hashes(images_map, images)
    return [h[:12] for h in hashes]


def docker_image(images_map, image):
    if isinstance(image, str):
        image = images_map.get(image)
        version, = image_versions(images_map, [image])
        return DockerImage.from_image(image, version)
    elif isinstance(image, DockerImage):
        return image
    else:
        raise TypeError(repr(image))


def resolve_deps(deps):
    while deps:
        resolved = set()
        for name, parent_name in deps.items():
            if parent_name not in deps:
                resolved.add(name)
        if not resolved:
            raise TypeError('Images hierarchy build error, '
                            'circular dependency found in these images: {}'
                            .format(', '.join(sorted(deps.keys()))))
        for name in resolved:
            yield name, deps[name]
        deps = {k: v for k, v in deps.items() if k not in resolved}


def get_images(config):
    return [i for i in config if isinstance(i, Image)]


def _process_pull_progress(status, image):
    key = status.add_task('=> Pulling image {}'.format(image))
    steps = {}
    while True:
        event = yield
        if event.get('status', '').startswith('Pulling from '):
            continue
        if 'id' in event:
            title = '  [{}] '.format(event['id']) + event['status']
            if 'progress' in event:
                title += ': ' + event['progress']
            if event['id'] in steps:
                status.update(steps[event['id']], title)
            else:
                steps[event['id']] = status.add_step(key, title)


def _process_push_progress(status, image):
    key = status.add_task('=> Pushing image {}'.format(image))
    steps = {}
    while True:
        event = yield
        if 'id' in event:
            title = '  [{}] '.format(event['id']) + event['status']
            if 'progress' in event:
                title += ': ' + event['progress']
            if event['id'] in steps:
                status.update(steps[event['id']], title)
            else:
                steps[event['id']] = status.add_step(key, title)


async def pull(docker, docker_image_: DockerImage, *, status):
    repository, _, tag = docker_image_.name.partition(':')
    params = {'fromImage': repository, 'tag': tag}
    try:
        gen = _process_pull_progress(status, docker_image_.name)
        gen.send(None)
        async for chunk in docker.create_image(params=params):
            for doc in chunk.decode('utf-8').splitlines():
                gen.send(json.loads(doc))
    except HTTPError:
        return False
    else:
        return True


async def push(docker, docker_image_, *, status):
    name, _, tag = docker_image_.name.partition(':')
    params = {'tag': tag}
    try:
        gen = _process_push_progress(status, docker_image_.name)
        gen.send(None)
        async for chunk in docker.push(name, params=params):
            for doc in chunk.decode('utf-8').splitlines():
                gen.send(json.loads(doc))
    except HTTPError:
        return False
    else:
        return True
