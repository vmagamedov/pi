import codecs
import os.path

from ._requires.yaml import load as yaml_load
from ._requires.yaml import loader as yaml_loader

from . import types


class Loader(yaml_loader.SafeLoader):

    @classmethod
    def register(cls, type_):
        cls.add_constructor(type_.__tag__, type_.construct)


Loader.register(types.Image)
Loader.register(types.Dockerfile)
Loader.register(types.DockerImage)
Loader.register(types.AnsibleTasks)
Loader.register(types.Argument)
Loader.register(types.Option)
Loader.register(types.ShellCommand)
Loader.register(types.SubCommand)
Loader.register(types.RO)
Loader.register(types.RW)
Loader.register(types.LocalPath)
Loader.register(types.NamedVolume)


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml_load(f.read(), Loader) or {}
    return config
