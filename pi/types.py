"""
    Configuration
    ~~~~~~~~~~~~~

    `Pi` uses tagged values feature of the YAML_ format, which are mapped
    directly into internal types of `Pi`. This kind of DSL is used to
    describe project environment in a most simple way.

    .. _YAML: http://yaml.org/spec/
"""
from enum import Enum
from typing import Optional, Union, Any, Sequence, Mapping  # noqa
from collections import OrderedDict

from ._requires import attr

from .utils import ImmutableDict


class EnumConstruct:

    @classmethod
    def construct(cls, loader, node):
        assert not loader.construct_scalar(node),\
            '{}: No arguments expected'.format(cls.__name__)
        return cls(node.tag)


class ScalarConstruct:

    @classmethod
    def construct(cls, loader, node):
        return cls(loader.construct_scalar(node))


class SequenceConstruct:

    @classmethod
    def construct(cls, loader, node):
        return cls(loader.construct_sequence(node, deep=True))


class MappingConstruct:
    __rename_to__ = ImmutableDict()

    @classmethod
    def construct(cls, loader, node):
        rename_from = {v: k for k, v in cls.__rename_to__.items()}

        params = loader.construct_mapping(node, deep=True)

        required = {rename_from.get(a.name, a.name)
                    for a in cls.__attrs_attrs__
                    if a.default is attr.NOTHING}

        optional = {rename_from.get(a.name, a.name)
                    for a in cls.__attrs_attrs__
                    if a.default is not attr.NOTHING}

        missing = set(required).difference(params)
        if missing:
            raise TypeError('Missing params {!r} for {!r}'.format(missing, cls))

        clean_params = {cls.__rename_to__.get(k, k): v
                        for k, v in params.items()
                        if k in required or k in optional}

        return cls(**clean_params)


@attr.s
class Meta(MappingConstruct):
    """``!Meta`` -- Project-specific settings

    :param str namespace: used to namespace entities to avoid names collision
        in different projects on the same host
    :param str description: description of the project, showed in the "help" of
        the project's CLI
    """
    __tag__ = '!Meta'

    namespace = attr.ib(default=None)  # type: Optional[str]
    description = attr.ib(default=None)  # type: Optional[str]

    def accept(self, visitor):
        return visitor.visit_meta(self)


@attr.s
class DockerImage(ScalarConstruct):
    __tag__ = '!DockerImage'

    name = attr.ib()

    def accept(self, visitor):
        return visitor.visit_dockerimage(self)

    @classmethod
    def from_image(cls, image, version):
        return cls('{}:{}'.format(image.repository, version))


@attr.s
class Task:
    run = attr.ib()
    where = attr.ib(default=attr.Factory(dict))

    def accept(self, visitor):
        return visitor.visit_task(self)

    @classmethod
    def from_config(cls, d):
        run = d['run']
        where = OrderedDict((k, v) for k, v in d.items()
                            if k != 'run')
        return cls(run, where)


def _convert_tasks(tasks):
    return [Task.from_config(d) for d in tasks]


@attr.s
class Image(MappingConstruct):
    __tag__ = '!Image'
    __rename_to__ = ImmutableDict([
        ('from', 'from_'),
    ])

    name = attr.ib()  # type: str
    repository = attr.ib()  # type: str
    from_ = attr.ib(default=None)  # type: Optional[Union[str, DockerImage]]
    # type: Sequence[Task]
    tasks = attr.ib(default=tuple(), hash=False, convert=_convert_tasks)
    description = attr.ib(default=None)  # type: Optional[str]

    def accept(self, visitor):
        return visitor.visit_image(self)


class VolumeType:

    def accept(self, visitor):
        raise NotImplementedError


class Mode(EnumConstruct, Enum):
    RO = '!RO'
    RW = '!RW'

    def accept(self, visitor):
        return getattr(visitor, 'visit_{}'.format(self.name))(self)


@attr.s
class LocalPath(VolumeType, MappingConstruct):
    __tag__ = '!LocalPath'
    __rename_to__ = ImmutableDict([
        ('from', 'from_'),
    ])

    from_ = attr.ib()  # type: str
    to = attr.ib()  # type: str
    mode = attr.ib(default=Mode.RO)  # type: Mode

    def accept(self, visitor):
        return visitor.visit_localpath(self)


@attr.s
class NamedVolume(VolumeType, MappingConstruct):
    __tag__ = '!NamedVolume'

    name = attr.ib()  # type: str
    to = attr.ib()  # type: str
    mode = attr.ib(default=Mode.RO)  # type: Mode

    def accept(self, visitor):
        return visitor.visit_namedvolume(self)


@attr.s
class Expose(MappingConstruct):
    __tag__ = '!Expose'
    __rename_to__ = ImmutableDict([
        ('as', 'as_'),
    ])

    port = attr.ib()  # type: int
    as_ = attr.ib()  # type: int
    addr = attr.ib(default='127.0.0.1')  # type: str
    proto = attr.ib(default='tcp')  # type: str

    def accept(self, visitor):
        return visitor.visit_expose(self)


@attr.s
class Service(MappingConstruct):
    __tag__ = '!Service'
    __rename_to__ = ImmutableDict([
        ('network-name', 'network_name'),
    ])

    name = attr.ib()  # type: str
    image = attr.ib()  # type: Union[str, DockerImage]
    volumes = attr.ib(default=None)  # type: Optional[Sequence[VolumeType]]
    ports = attr.ib(default=None)  # type: Optional[Sequence[Expose]]
    environ = attr.ib(default=None)  # type: Optional[Mapping[str: str]]
    requires = attr.ib(default=None)  # type: Optional[Sequence[str]]
    exec = attr.ib(default=None)  # type: Union[str, Sequence[str]]
    args = attr.ib(default=None)  # type: Union[str, Sequence[str]]
    network_name = attr.ib(default=None)  # type: Optional[str]
    description = attr.ib(default=None)  # type: Optional[str]

    def accept(self, visitor):
        return visitor.visit_service(self)


@attr.s
class ParameterType:
    name = attr.ib()  # type: str
    type = attr.ib(default=None)  # type: Optional[str]
    default = attr.ib(default=None)  # type: Any

    def accept(self, visitor):
        raise NotImplementedError


class Argument(ParameterType, MappingConstruct):
    __tag__ = '!Argument'

    def accept(self, visitor):
        return visitor.visit_argument(self)


class Option(ParameterType, MappingConstruct):
    __tag__ = '!Option'

    def accept(self, visitor):
        return visitor.visit_option(self)


class CommandType:

    def accept(self, visitor):
        raise NotImplementedError


@attr.s
class Command(CommandType, MappingConstruct):
    __tag__ = '!Command'
    __rename_to__ = ImmutableDict([
        ('network-name', 'network_name'),
    ])

    name = attr.ib()  # type: str
    image = attr.ib()  # type: Union[str, DockerImage]
    run = attr.ib()  # type: Union[str, Sequence[str]]
    params = attr.ib(default=None)  # type: Optional[Sequence[ParameterType]]
    volumes = attr.ib(default=None)  # type: Optional[Sequence[VolumeType]]
    ports = attr.ib(default=None)  # type: Optional[Sequence[Expose]]
    environ = attr.ib(default=None)  # type: Optional[Mapping[str: str]]
    requires = attr.ib(default=None)  # type: Optional[Sequence[str]]
    network_name = attr.ib(default=None)  # type: Optional[str]
    description = attr.ib(default=None)  # type: Optional[str]

    def accept(self, visitor):
        return visitor.visit_command(self)


class ActionType:

    def accept(self, visitor):
        raise NotImplementedError


@attr.s
class Download(ActionType, ScalarConstruct):
    __tag__ = '!Download'

    url = attr.ib()

    def accept(self, visitor):
        return visitor.visit_download(self)


@attr.s
class File(ActionType, ScalarConstruct):
    __tag__ = '!File'

    path = attr.ib()

    def accept(self, visitor):
        return visitor.visit_file(self)


@attr.s
class Bundle(ActionType, ScalarConstruct):
    __tag__ = '!Bundle'

    path = attr.ib()

    def accept(self, visitor):
        return visitor.visit_bundle(self)
