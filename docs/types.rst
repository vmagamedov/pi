Types
~~~~~

Pi uses YAML_ format and it's tagged values feature to assemble types defined
here into complex structure, which will describe your project's CLI and
environment.

``pi.yaml`` - is a list of these top-level types: :py:class:`Meta`,
:py:class:`Service`, :py:class:`Image` and :py:class:`Command`. Their order is
not significant.

.. py:class:: Meta

    Project-specific settings

    .. code-block:: yaml

        - !Meta:
          namespace: example
          description: |
            This is an example project

    :param namespace: Name, used to namespace such things like network, to make
        them unique and isolated for every project
    :param description: Description for a project, which will be seen when users
        will run ``pi --help`` command

.. py:class:: DockerImage

    Reference to a name of the Docker image

    Takes single argument - image name. Image name should include repository
    name and tag:

    .. code-block:: yaml

        !DockerImage "python:3.6-alpine"

.. py:class:: Image

    Defines how to build and distribute an image

    .. code-block:: yaml

        - !Image
          name: env
          repository: my.registry/project/name
          from: base
          description: "Project environment"
          tasks:
          - run: cp {{config}} /etc
            config: !File "config.py"

    :param name: short name of the image, used to reference it within this
        config/project
    :param repository: full name of the image. This name is used to distribute
        image using registries
    :param from: base image, to build this one from. It is a name of the other
        image defined in this config, or a regular external Docker image
    :param description: description of this image
    :param tasks: list of tasks, used to build this image

    Each task represents a shell command to run. This command can be a simple
    string:

    .. code-block:: yaml

        tasks:
        - run: mkdir /etc/app

    Or a template with parameters. Jinja2 is used as a template language:

    .. code-block:: yaml

        tasks:
        - run: pip install {{packages|join(" ")}}
          packages:
          - flask
          - sqlalchemy

    You can also use some special handy directives:

    .. code-block:: yaml

        tasks:
        - run: sh -c {{install_sh}}
          install_sh: !Download "https://some.host/install.sh"

    Pi will download this file for you and it will be available inside
    container during build process. All you need it to describe what you want
    to do with already downloaded file. So you don't have to install curl with
    ca-certificates into container and remove it in the end.

.. py:class:: Download

    Directive to transfer downloaded on the host machine file into container

    Takes single argument - url:

    .. code-block:: yaml

        tasks:
        - run: sh -c {{install_sh}}
          install_sh: !Download "https://some.host/install.sh"

.. py:class:: File

    Directive to transfer file from the host machine into container

    Takes single argument - local file path:

    .. code-block:: yaml

        tasks:
        - run: cp {{config}} /etc/config.yaml
          config: !File "config.yaml"

.. py:class:: Bundle

    Directive to transfer directory from the host machine into container

    Takes single argument - local directory path:

    .. code-block:: yaml

        tasks:
        - run: cd {{src}} && python setup.py install
          src: !Bundle "src"

.. py:class:: Service

    Defines a service

    .. code-block:: yaml

        - !Service
          name: pg
          network-name: postgres
          image: !DockerImage postgres:10-alpine

    :param name: name of this service
    :param image: image, used to run this service
    :param volumes: list of volumes to mount, defined using
        :py:class:`LocalPath` or :py:class:`NamedVolume` types
    :param ports: list of exposed ports, defined using :py:class:`Expose` type
    :param environ: map of environment variables
    :param requires: list of service names; Pi will ensure that these services
        are running before starting this service
    :param exec: service's entry point
    :param args: args passed to the service's entry point
    :param network-name: host name of the container, by default ``network-name``
        will be equal to the ``name`` of the service
    :param description: description, used to help users when they run
        ``pi service --help`` command, which will list all defined services and
        their descriptions

.. py:class:: Command

    Defines a command with parameters, to run inside configured container
    and environment

    .. code-block:: yaml

        - !Command
          name: test
          image: test
          requires: [pg]
          description: Run py.test
          params:
          - !Argument {name: tests, default: ''}
          run: py.test {{tests}}

    :param name: name of this command
    :param image: image, used to run this command
    :param run: command to run inside container
    :param params: list of command-line arguments of type :py:class:`Argument`
        and options of type :py:class:`Option`
    :param volumes: list of volumes to mount, defined using
        :py:class:`LocalPath` or :py:class:`NamedVolume` types
    :param ports: list of exposed ports, defined using :py:class:`Expose` type
    :param environ: map of environment variables
    :param requires: list of service names; Pi will ensure that these services
        are running
    :param network-name: make this container available to the other containers
        in current namespace under specified host name
    :param description: description, used to help users, when they run
        ``pi [command] --help`` command

.. py:class:: Argument

    Defines command's argument

    :param name: argument's name
    :param type: argument's type - ``str`` (default), ``int`` or ``bool``
    :param default: argument's default value

.. py:class:: Option

    Defines command's option

    :param name: option's name
    :param type: option's type - ``str`` (default), ``int`` or ``bool``
    :param default: option's default value

.. py:class:: LocalPath

    Specifies file or directory from the local file system to mount

    .. code-block:: yaml

        volumes:
        - !LocalPath {from: "config.yaml", to: "/etc/config.yaml"}

    :param from: Local path
    :param to: Path inside container
    :param mode: :py:class:`RO` (default) or :py:class:`RW`

.. py:class:: NamedVolume

    Specifies existing named volume to mount

    .. code-block:: yaml

        ...
        volumes:
        - !NamedVolume {name: db, to: "/var/db/data", mode: !RW }

    :param name: Volume's name
    :param to: Path inside container
    :param mode: :py:class:`RO` (default) or :py:class:`RW`

.. py:class:: RO

    Defines read-only mode

.. py:class:: RW

    Defines read/write mode

.. py:class:: Expose

    Defines port mapping to expose

    .. code-block:: yaml

        ...
        ports:
        - !Expose {port: 5000, as: 5000, addr: 0.0.0.0}

    :param port: port inside container
    :param as: port outside container
    :param addr: network interface for binding, ``127.0.0.1`` by default
    :param proto: protocol, ``tcp`` by default

.. _YAML: http://yaml.org/spec/
