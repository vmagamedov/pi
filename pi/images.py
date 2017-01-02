import sys
import hashlib
import binascii

from asyncio import coroutine

from .types import DockerImage, Image


class _HashableChunks:

    def visit(self, obj):
        return obj.accept(self)

    def visit_dockerfile(self, obj):
        with open(obj.file_name, 'rb') as f:
            yield f.read()

    def visit_ansibletasks(self, obj):
        yield repr(obj.tasks).encode('utf-8')

    def visit_tasks(self, obj):
        # FIXME: implement proper hashing
        yield repr(obj).encode('utf-8')


class Layer:
    _hash = None

    def __init__(self, image, *, parent=None):
        self.image = image
        self.parent = parent

    @property
    def name(self):
        return self.image.name

    def hash(self):
        if self._hash is None:
            h = hashlib.sha1()
            if self.parent is not None:
                h.update(self.parent.hash())
            chunks = _HashableChunks().visit(self.image.provision_with)
            for chunk in chunks:
                h.update(chunk)
            self._hash = h.digest()
        return self._hash

    def version(self):
        return binascii.hexlify(self.hash()).decode('ascii')[:12]

    def docker_image(self):
        return DockerImage('{}:{}'.format(self.image.repository,
                                          self.version()))


def get_docker_image(layers, image):
    if isinstance(image, str):
        layer = layers.get(image)
        return layer.docker_image()
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


def construct_layers(config):
    deps = {}
    layers = {}
    image_by_name = {}

    images = [i for i in config if isinstance(i, Image)]
    for image in images:
        if image.from_ is not None:
            if not isinstance(image.from_, DockerImage):
                deps[image.name] = image.from_
                image_by_name[image.name] = image
                continue
        layers[image.name] = Layer(image, parent=None)

    # check missing parents
    missing = {name for name, parent_name in deps.items()
               if parent_name not in deps and parent_name not in layers}
    if missing:
        raise TypeError('These images has missing parent images: {}'
                        .format(', '.join(sorted(missing))))

    for name, parent_name in resolve_deps(deps):
        image = image_by_name[name]
        parent = layers[parent_name]
        layers[name] = Layer(image, parent=parent)

    return list(layers.values())


@coroutine
def _echo_download_progress(output):
    error = False
    last_id = None
    while True:
        items = yield from output.read()
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


class Puller:

    def __init__(self, client, *, loop):
        self.client = client
        self.loop = loop

    def visit(self, obj):
        return obj.accept(self)

    @coroutine
    def visit_dockerimage(self, obj):
        from .client import APIError

        try:
            output = yield from self.client.pull(obj.name, stream=True,
                                                 decode=True)
        except APIError as e:
            if e.response.status_code == 404:
                return False
            raise
        else:
            with output as reader:
                success = yield from _echo_download_progress(reader)
                return success


class Pusher:

    def __init__(self, client, *, loop):
        self.client = client
        self.loop = loop

    def visit(self, obj):
        return obj.accept(self)

    @coroutine
    def visit_dockerimage(self, obj):
        output = yield from self.client.push(obj.name, stream=True,
                                             decode=True)
        with output as reader:
            success = yield from _echo_download_progress(reader)
            return success


class Builder(object):

    def __init__(self, client, layer, *, loop):
        self.client = client
        self.layer = layer
        self.loop = loop

    def visit(self, obj):
        return obj.accept(self)

    @coroutine
    def visit_dockerfile(self, obj):
        from .build.dockerfile import build

        result = yield from build(self.client, self.layer, obj)
        return result

    @coroutine
    def visit_ansibletasks(self, obj):
        from .build.ansible import build

        result = yield from build(self.client, self.layer, obj, loop=self.loop)
        return result

    @coroutine
    def visit_tasks(self, obj):
        from .build.tasks import build

        result = yield from build(self.client, self.layer, obj, loop=self.loop)
        return result
