from enum import Enum
from typing import Optional, Union, Any, Sequence, Mapping
from dataclasses import dataclass, field, MISSING
from collections import OrderedDict

from .utils import ImmutableDict, cached_property


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

        required = {
            rename_from.get(f.name, f.name)
            for f in cls.__dataclass_fields__.values()
            if f.default is MISSING and f.default_factory is MISSING
        }
        optional = {
            rename_from.get(f.name, f.name)
            for f in cls.__dataclass_fields__.values()
            if f.default is not MISSING or f.default_factory is not MISSING
        }

        missing = set(required).difference(params)
        if missing:
            raise TypeError('Missing params {!r} for {!r}'.format(missing, cls))

        clean_params = {cls.__rename_to__.get(k, k): v
                        for k, v in params.items()
                        if k in required or k in optional}

        return cls(**clean_params)


@dataclass(frozen=True)
class Meta(MappingConstruct):
    __tag__ = '!Meta'

    namespace: Optional[str] = None
    description: Optional[str] = None

    def accept(self, visitor):
        return visitor.visit_meta(self)


@dataclass(frozen=True)
class DockerImage(ScalarConstruct):
    __tag__ = '!DockerImage'

    name: str

    def accept(self, visitor):
        return visitor.visit_dockerimage(self)

    @classmethod
    def from_image(cls, image, version):
        return cls('{}:{}'.format(image.repository, version))


@dataclass(frozen=True)
class Task:
    run: str
    where: Mapping[str, Any]

    def accept(self, visitor):
        return visitor.visit_task(self)

    @classmethod
    def from_config(cls, d):
        run = d['run']
        where = OrderedDict((k, v) for k, v in d.items()
                            if k != 'run')
        return cls(run, where)


@dataclass(frozen=True)
class Image(MappingConstruct):
    __tag__ = '!Image'
    __rename_to__ = ImmutableDict([
        ('from', 'from_'),
        ('tasks', '_tasks'),
    ])

    name: str
    repository: str
    from_: Optional[Union[str, DockerImage]] = None
    _tasks: Sequence[Any] = field(default=(), hash=False)
    description: Optional[str] = None

    def accept(self, visitor):
        return visitor.visit_image(self)

    @cached_property
    def tasks(self) -> Sequence[Task]:
        return tuple(Task.from_config(d) for d in self._tasks)


class Mode(EnumConstruct, Enum):
    RO = '!RO'
    RW = '!RW'

    def accept(self, visitor):
        return getattr(visitor, 'visit_{}'.format(self.name))(self)


class VolumeType:

    def accept(self, visitor):
        raise NotImplementedError


@dataclass(frozen=True)
class LocalPath(VolumeType, MappingConstruct):
    __tag__ = '!LocalPath'
    __rename_to__ = ImmutableDict([
        ('from', 'from_'),
    ])

    from_: str
    to: str
    mode: Mode = Mode.RO

    def accept(self, visitor):
        return visitor.visit_localpath(self)


@dataclass(frozen=True)
class NamedVolume(VolumeType, MappingConstruct):
    __tag__ = '!NamedVolume'

    name: str
    to: str
    mode: Mode = Mode.RO

    def accept(self, visitor):
        return visitor.visit_namedvolume(self)


@dataclass(frozen=True)
class Expose(MappingConstruct):
    __tag__ = '!Expose'
    __rename_to__ = ImmutableDict([
        ('as', 'as_'),
    ])

    port: int
    as_: int
    addr: str = '127.0.0.1'
    proto: str = 'tcp'  # TODO: replace with enum

    def accept(self, visitor):
        return visitor.visit_expose(self)


@dataclass(frozen=True)
class Service(MappingConstruct):
    __tag__ = '!Service'
    __rename_to__ = ImmutableDict([
        ('network-name', 'network_name'),
    ])

    name: str
    image: Union[str, DockerImage]
    exec: Optional[Union[str, Sequence[str]]] = None
    args: Optional[Union[str, Sequence[str]]] = None
    volumes: Optional[Sequence[VolumeType]] = None
    ports: Optional[Sequence[Expose]] = None
    environ: Optional[Mapping[str, str]] = None
    requires: Optional[Sequence[str]] = None
    network_name: Optional[str] = None
    description: Optional[str] = None

    def accept(self, visitor):
        return visitor.visit_service(self)


@dataclass(frozen=True)
class ParameterType:
    name: str
    type: Optional[str] = None
    default: Any = None

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


@dataclass(frozen=True)
class Command(MappingConstruct):
    __tag__ = '!Command'
    __rename_to__ = ImmutableDict([
        ('network-name', 'network_name'),
    ])

    name: str
    image: Union[str, DockerImage]
    run: Union[str, Sequence[str]]
    params: Optional[Sequence[ParameterType]] = None
    volumes: Optional[Sequence[VolumeType]] = None
    ports: Optional[Sequence[Expose]] = None
    environ: Optional[Mapping[str, str]] = None
    requires: Optional[Sequence[str]] = None
    network_name: Optional[str] = None
    description: Optional[str] = None

    def accept(self, visitor):
        return visitor.visit_command(self)


class ActionType:

    def accept(self, visitor):
        raise NotImplementedError


@dataclass(frozen=True)
class Download(ActionType, ScalarConstruct):
    __tag__ = '!Download'

    url: str

    def accept(self, visitor):
        return visitor.visit_download(self)


@dataclass(frozen=True)
class File(ActionType, ScalarConstruct):
    __tag__ = '!File'

    path: str

    def accept(self, visitor):
        return visitor.visit_file(self)


@dataclass(frozen=True)
class Bundle(ActionType, ScalarConstruct):
    __tag__ = '!Bundle'

    path: str

    def accept(self, visitor):
        return visitor.visit_bundle(self)
