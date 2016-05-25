import codecs
import os.path
import collections

import yaml.loader


docker = collections.namedtuple('docker', 'image')


class Loader(yaml.loader.SafeLoader):

    def construct_docker(self, node):
        value = self.construct_scalar(node)
        return docker(value)


Loader.add_constructor('!docker', Loader.construct_docker)


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml.load(f.read(), Loader) or {}
    return config
