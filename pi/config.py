import codecs
import os.path

from operator import itemgetter
from collections import OrderedDict


from ._requires import yaml
from ._requires.yaml import SafeLoader
from ._requires.yaml.nodes import ScalarNode, SequenceNode, MappingNode
from ._requires.yaml.resolver import BaseResolver

from . import types


class Unknown:

    def __init__(self, loader, suffix, node):
        self.tag = suffix
        if isinstance(node, ScalarNode):
            obj = loader.construct_scalar(node)
        elif isinstance(node, SequenceNode):
            obj = loader.construct_sequence(node, True)
        elif isinstance(node, MappingNode):
            obj = loader.construct_mapping(node, True)
        else:
            raise TypeError(repr(node))
        self.obj = obj

    def __repr__(self):
        return '!{}({!r})'.format(self.tag, self.obj)


class Loader(SafeLoader):

    def construct_mapping(self, node, deep=False):
        items = list(super().construct_mapping(node, deep=deep).items())
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
Loader.add_multi_constructor('!', Unknown)

Loader.register(types.Meta)
Loader.register(types.Image)
Loader.register(types.DockerImage)
Loader.register(types.Argument)
Loader.register(types.Option)
Loader.register(types.Command)
Loader.register(types.Service)
Loader.register(types.LocalPath)
Loader.register(types.NamedVolume)
Loader.register(types.Expose)
Loader.register(types.Download)
Loader.register(types.File)
Loader.register(types.Bundle)
Loader.register_enum(types.Mode)


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml.load(f.read(), Loader) or {}
    return config
