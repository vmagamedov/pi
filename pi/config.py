import codecs
import os.path

import yaml.loader

from . import types


class Loader(yaml.loader.SafeLoader):

    @classmethod
    def register(cls, type_):
        cls.add_constructor(type_.__tag__, type_.construct)


Loader.register(types.Image)
Loader.register(types.Dockerfile)
Loader.register(types.DockerImage)
Loader.register(types.AnsibleTasks)


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml.load(f.read(), Loader) or {}
    return config
