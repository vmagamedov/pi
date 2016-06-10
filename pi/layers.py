import hashlib
import binascii

from .types import DockerImage


class _HashableChunks:

    def visit(self, obj):
        return obj.accept(self)

    def visit_dockerfile(self, obj):
        with open(obj.file_name, 'rb') as f:
            yield f.read()

    def visit_ansibletasks(self, obj):
        yield repr(obj.tasks).encode('utf-8')


class Layer:
    _hash = None

    def __init__(self, image, *, parent=None):
        self._image = image
        self.parent = parent

    @property
    def name(self):
        return self._image.name

    def hash(self):
        if self._hash is None:
            h = hashlib.sha1()
            if self.parent is not None:
                h.update(self.parent.hash())
            chunks = _HashableChunks().visit(self._image.provision_with)
            for chunk in chunks:
                h.update(chunk)
            self._hash = h.digest()
        return self._hash

    def version(self):
        return binascii.hexlify(self.hash()).decode('ascii')[:12]

    def docker_image(self):
        return DockerImage('{}:{}'.format(self._image.repository,
                                          self.version()))
