import sys
import hashlib

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


async def _echo_download_progress(output):
    error = False
    last_id = None
    while True:
        items = await output.read()
        if not items:
            break
        for i in items:
            error = error or 'error' in i

            progress_id = i.get('id')
            if last_id:
                if progress_id == last_id:
                    sys.stdout.write('\x1b[2K\r')
                elif not progress_id or progress_id != last_id:
                    sys.stdout.write('\n')
            last_id = progress_id

            if progress_id:
                sys.stdout.write('{}: '.format(progress_id))
            sys.stdout.write(i.get('status') or i.get('error') or '')

            progress_bar = i.get('progress')
            if progress_bar:
                sys.stdout.write(' ' + progress_bar)

            if not progress_id:
                sys.stdout.write('\n')
            sys.stdout.flush()
    if last_id:
        sys.stdout.write('\n')
        sys.stdout.flush()
    return not error


async def pull(client, docker_image):
    from .client import APIError

    try:
        output = await client.pull(docker_image.name, stream=True, decode=True)
    except APIError as e:
        if e.response.status_code == 404:
            return False
        raise
    else:
        with output as reader:
            success = await _echo_download_progress(reader)
            return success


async def push(client, docker_image):
    output = await client.push(docker_image.name, stream=True, decode=True)
    with output as reader:
        success = await _echo_download_progress(reader)
        return success


async def build(client, images_map, image, *, loop):
    from .tasks import build as build_tasks

    result = await build_tasks(client, images_map, image, loop=loop)
    return result
