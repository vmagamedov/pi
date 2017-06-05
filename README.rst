`Pi` -- command-line tool for managing development environments.
It is configurable using DSL with YAML_ syntax, which is
like `Makefile` on steroids -- nice command-line UI and containerized
environments.

Example
~~~~~~~

Configuration to build documentation, `pi.yaml`:

.. code-block:: yaml

    - !Meta
      description: |
        Project command-line interface

    - !Image
      name: docs
      from: !DockerImage python:3.5-alpine
      repository: reg.local/pi/docs
      tasks:
      - run: pip3 install {{packages|join(" ")}}
        packages:
        - sphinx
        - sphinx_rtd_theme

    - !Command
      name: build docs
      image: docs
      run: sphinx-build -b html docs build

Inspect projects without leaving your shell:

.. code-block:: shell

    $ pi
    Usage: pi [OPTIONS] COMMAND [ARGS]...

      Project command-line interface

    Options:
      --debug  Run in debug mode
      --help   Show this message and exit.

    Core commands:
      + image    Images creation and delivery
      + service  Services status and management

    Custom commands:
      + build

Command in action:

.. code-block:: shell

    $ pi build docs
    Running Sphinx v1.4.8
    ... snip ...
    build succeeded.

Installation
~~~~~~~~~~~~

`Pi` requires `Python` 3.5 or higher. You can install `Pi` directly into your
system packages, it has zero dependencies, so it can be uninstalled without
leaving any traces in your system:

.. code-block:: shell

    $ pip3 install pi-env

.. _YAML: http://yaml.org/spec/
