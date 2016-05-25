import codecs
import os.path

import yaml.loader


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml.load(f.read(), yaml.loader.BaseLoader) or {}
    return config
