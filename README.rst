**Pi** is a command-line tool for managing development environments.
It is configurable with ``pi.yaml`` file, which is like ``Makefile`` on
steroids - with nice commands UI, containerized environments and services,
which are required in order to run your commands.

:Status: *under active development*

Features
~~~~~~~~

Define development environments using hierarchy of images, which then will
be used to run your commands and services.

Build images using ``Dockerfile`` or `Ansible` tasks, or just use lots of
existing `Docker` images.

Design a good-looking, human-oriented, self documented command-line UI,
with ability to group commands into groups (sub-commands), and to define
arguments and options for them. You can always type
``pi [command] --help`` to find command you need and read how to use it.
