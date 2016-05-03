import codecs
import os.path

import yaml


def read_config():
    config = {}
    if os.path.exists('pi.yaml'):
        with codecs.open('pi.yaml', encoding='utf-8') as f:
            config = yaml.load(f.read()) or {}
    return config
