import sys
import os.path

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
extensions = ['sphinx.ext.autodoc']

source_suffix = '.rst'
master_doc = 'index'

project = 'Pi'
copyright = '2018, Vladimir Magamedov'
author = 'Vladimir Magamedov'

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_theme_options = {'display_version': False}


def setup(app):
    app.add_stylesheet('style.css')
