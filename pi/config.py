import codecs
import os.path

import yaml.loader

from .layers import Image


class Loader(yaml.loader.SafeLoader):

    def construct_docker(self, node):
        name = self.construct_scalar(node)
        return Image(name)


Loader.add_constructor('!docker', Loader.construct_docker)


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml.load(f.read(), Loader) or {}
    return config
