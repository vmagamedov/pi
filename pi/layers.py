import hashlib
import binascii
import collections


Image = collections.namedtuple('Image', 'name')


class Layer:
    _hash = None

    def __init__(self, name, repo, *, parent=None):
        self.name = name
        self._repo = repo
        self._parent = parent

    def __hashable__(self):
        raise NotImplementedError

    def hash(self):
        if self._hash is None:
            h = hashlib.sha1()
            if self._parent is not None:
                h.update(self._parent.hash())
            for chunk in self.__hashable__():
                h.update(chunk)
            self._hash = h.digest()
        return self._hash

    def version(self):
        return binascii.hexlify(self.hash()).decode('ascii')[:12]

    def image(self):
        return Image('{}:{}'.format(self._repo, self.version()))


class DockerfileLayer(Layer):

    def __init__(self, name, repo, docker_file, *, parent=None):
        super().__init__(name, repo, parent=parent)
        self.file_name = docker_file

    def __hashable__(self):
        with open(self.file_name, 'rb') as f:
            return [f.read()]
