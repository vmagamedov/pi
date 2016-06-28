import codecs
import os.path
from operator import itemgetter
from collections import OrderedDict

from ._requires.yaml import load as yaml_load
from ._requires.yaml import loader as yaml_loader
from ._requires.yaml.resolver import BaseResolver

from . import types


class Loader(yaml_loader.SafeLoader):

    def construct_mapping(self, node, deep=False):
        items = list(super().construct_mapping(node, deep=False).items())
        items.sort(key=itemgetter(0))
        return OrderedDict(items)

    def construct_yaml_map(self, node):
        data = OrderedDict()
        yield data
        value = self.construct_mapping(node)
        data.update(value)

    @classmethod
    def register(cls, type_):
        cls.add_constructor(type_.__tag__, type_.construct)

    @classmethod
    def register_enum(cls, enum):
        for enum_value in enum:
            cls.add_constructor(enum_value.value, enum.construct)


Loader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG,
                       Loader.construct_yaml_map)

Loader.register(types.Meta)
Loader.register(types.Image)
Loader.register(types.Dockerfile)
Loader.register(types.DockerImage)
Loader.register(types.AnsibleTasks)
Loader.register(types.Argument)
Loader.register(types.Option)
Loader.register(types.ShellCommand)
Loader.register(types.SubCommand)
Loader.register(types.LocalPath)
Loader.register(types.NamedVolume)
Loader.register(types.Expose)
Loader.register_enum(types.Mode)


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml_load(f.read(), Loader) or {}
    return config
