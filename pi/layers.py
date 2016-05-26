import hashlib
import binascii


class Layer:
    _hash = None

    def __init__(self, name, docker_image, *, parent=None):
        self.name = name
        self.docker_image = docker_image
        self.parent = parent

    def __hashable__(self):
        raise NotImplementedError

    def hash(self):
        if self._hash is None:
            h = hashlib.sha1()
            if self.parent is not None:
                h.update(self.parent.hash())
            for chunk in self.__hashable__():
                h.update(chunk)
            self._hash = h.digest()
        return self._hash

    def version(self):
        return binascii.hexlify(self.hash()).decode('ascii')[:12]


class DockerfileLayer(Layer):

    def __init__(self, name, docker_image, docker_file, *, parent=None):
        super().__init__(name, docker_image, parent=parent)
        self.file_name = docker_file

    def __hashable__(self):
        with open(self.file_name, 'rb') as f:
            return [f.read()]
