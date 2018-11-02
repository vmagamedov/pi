Command-line tool for managing containerized environments. Helps you build nice
and unique CLI for your project, manage containers, images and services.

Licensed under **BSD-3-Clause** license. See LICENSE.txt

**Project CLI** means that you can create nested structure of commands, which
will use containers (Docker) to run and services (e.g. PostgreSQL) to perform
some complex tasks.

**Managing images** means that you can define hierarchical images structure
and Pi will build them on demand, for example when you call a command, which
require some images to run, which are not built yet. You don't have to assign
versions (tags) for these images yourself, Pi will use hashing algorithm to
automatically create them.

**Managing services** means that you can specify, that some services should be
started before running a command. Or you can manually start and stop services.

Installation
~~~~~~~~~~~~

Pi requires Python 3.5 or higher. You can install Pi directly into your
system packages, it has zero dependencies, so it can be uninstalled without
leaving any traces in your system:

.. code-block:: shell

    $ pip3 install pi-env

Example
~~~~~~~

Example ``pi.yaml`` file:

.. code-block:: yaml

    - !Meta
      namespace: foo
      description: |
        Project command-line interface

    - !Service
      name: pg
      network-name: postgres
      image: !DockerImage postgres:10-alpine

    - !Image
      name: test
      from: !DockerImage python:3.6-alpine
      repository: localhost/foo/test
      tasks:
      - run: pip3 install --no-deps --no-cache-dir -r {{reqs}}
        reqs: !File requirements.txt

    - !Command
      name: test
      image: test
      requires: [pg]
      description: Run py.test
      params:
      - !Argument {name: tests, default: ''}
      run: py.test {{tests}}

If you call ``pi test``, Pi will build ``test`` image if needed and will make
sure that ``pg`` service is running, which is required to run tests.

This ``pg`` service will be available for the tests at ``postgres:5432``
address. Both command ``pi test`` and ``pg`` service will be running inside
containers, which will be in the same unique network, automatically created for
specified ``foo`` namespace.

Here is how your project will be looking in the shell:

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
      test  Run py.test

You can see list of all defined images:

.. code-block:: shell

    $ pi image -l
      Image name    Docker image                     Size        Versions
    --------------  -------------------------------  --------  ----------
    ✔ test          localhost/foo/test:4efe5a0454a9  88.58 MB           1

You also can see status of all defined services:

.. code-block:: shell

    $ pi service -s
    Service name    Status    Docker image
    --------------  --------  ------------------
    pg              running   postgres:10-alpine

And of cause you can run your commands:

.. code-block:: shell

    $ pi test
    ...............................
    31 passed in 0.35 seconds

Contributing
~~~~~~~~~~~~

Run ``python -m pi test`` and ``python -m pi lint`` in order to test and lint
your changes before submitting your pull requests.
