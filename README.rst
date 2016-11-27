`Pi` -- command-line tool for managing development environments.
It is configurable using DSL with YAML_ syntax, which is
like `Makefile` on steroids -- with nice command-line UI and containerized
environments.

:Build with: Dockerfile_ | Ansible_
:Run with: `Docker`_
:Works on: `Linux` | `macOS` | `Windows`

Example
~~~~~~~

Configuration to build this documentation, `pi.yaml`:

.. code-block:: yaml

    - !Meta
      description: |
        Project command-line interface

    - !Image
      name: docs
      from: !DockerImage python:3.5.2-alpine
      repository: reg.local/pi/docs
      provision-with: !AnsibleTasks
        - pip: name={{item}} executable=pip3 extra_args='--no-cache-dir'
          with_items:
            - sphinx==1.4.8
            - sphinx_rtd_theme==0.1.10a0

    - !ShellCommand
      name: build docs
      image: docs
      eval: sphinx-build -b html docs build

Inspect projects without leaving your shell:

.. code-block:: shell

    $ pi
    Usage: pi [OPTIONS] COMMAND [ARGS]...

      Project command-line interface

    Options:
      --help  Show this message and exit.

    Core commands:
      + image
      + service

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

`Pi` requires `Python` 3.4 or higher. To build images with `Ansible`_,
you will obviously need to install `Ansible`_ too (but this is optional
feature).

You can install `Pi` directly into your system packages, it has zero
dependencies, so it can be uninstalled without leaving any traces in your
system:

.. code-block:: shell

    $ pip3 install {COMING SOON}

.. _YAML: http://yaml.org/spec/
.. _Docker: https://github.com/docker/docker
.. _Dockerfile: https://docs.docker.com/engine/reference/builder/
.. _Ansible: https://github.com/ansible/ansible
