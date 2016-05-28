import hashlib
import binascii
import collections


Image = collections.namedtuple('Image', 'name')


class Layer:
    _hash = None

    def __init__(self, name, repository, *, parent=None):
        self.name = name
        self._repository = repository
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
        return Image('{}:{}'.format(self._repository, self.version()))


class DockerfileLayer(Layer):

    def __init__(self, name, repository, file_name, *, parent=None):
        super().__init__(name, repository, parent=parent)
        self.file_name = file_name

    def __hashable__(self):
        with open(self.file_name, 'rb') as f:
            return [f.read()]


class AnsibleTasksLayer(Layer):

    def __init__(self, name, repository, ansible_tasks, *, parent=None):
        super().__init__(name, repository, parent=parent)
        self.ansible_tasks = ansible_tasks

    def __hashable__(self):
        return [repr(self.ansible_tasks).encode('utf-8')]
