from enum import Enum

from ._requires import attr
from ._requires.typing import Optional, Union, Any, Sequence, Mapping

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
    __tag__ = '!Meta'

    namespace = attr.ib(default=None)  # type: Optional[str]
    description = attr.ib(default=None)  # type: Optional[str]

    def accept(self, visitor):
        return visitor.visit_meta(self)


@attr.s
class DockerImage(ScalarConstruct):
    __tag__ = '!DockerImage'
    name = attr.ib()


class ProvisionType:

    def accept(self, visitor):
        raise NotImplementedError


@attr.s
class Dockerfile(ProvisionType, ScalarConstruct):
    __tag__ = '!Dockerfile'

    file_name = attr.ib(default='Dockerfile')  # type: str

    def accept(self, visitor):
        return visitor.visit_dockerfile(self)


@attr.s
class AnsibleTasks(ProvisionType, SequenceConstruct):
    __tag__ = '!AnsibleTasks'

    tasks = attr.ib(hash=False)  # type: list

    def accept(self, visitor):
        return visitor.visit_ansibletasks(self)


@attr.s
class Image(MappingConstruct):
    __tag__ = '!Image'
    __rename_to__ = ImmutableDict([
        ('provision-with', 'provision_with'),
        ('from', 'from_'),
    ])

    name = attr.ib()  # type: str
    repository = attr.ib()  # type: str
    provision_with = attr.ib()  # type: ProvisionType
    from_ = attr.ib(default=None)  # type: Optional[Union[str, Dockerfile]]

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

    name = attr.ib()  # type: str
    image = attr.ib()  # type: Union[str, DockerImage]
    volumes = attr.ib(default=None)  # type: Optional[Sequence[VolumeType]]
    ports = attr.ib(default=None)  # type: Optional[Sequence[Expose]]
    environ = attr.ib(default=None)  # type: Optional[Mapping[str: str]]
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
class ShellCommand(CommandType, MappingConstruct):
    __tag__ = '!ShellCommand'
    __rename_to__ = ImmutableDict([
        ('raw-input', 'raw_input'),
    ])

    name = attr.ib()  # type: str
    image = attr.ib()  # type: Union[str, DockerImage]
    shell = attr.ib()  # type: str
    params = attr.ib(default=None)  # type: Optional[Sequence[ParameterType]]
    volumes = attr.ib(default=None)  # type: Optional[Sequence[VolumeType]]
    ports = attr.ib(default=None)  # type: Optional[Sequence[Expose]]
    environ = attr.ib(default=None)  # type: Optional[Mapping[str: str]]
    raw_input = attr.ib(default=None)  # type: Optional[bool]
    requires = attr.ib(default=None)  # type: Optional[Sequence[str]]
    description = attr.ib(default=None)  # type: Optional[str]

    def accept(self, visitor):
        return visitor.visit_shellcommand(self)


@attr.s
class SubCommand(CommandType, MappingConstruct):
    __tag__ = '!SubCommand'
    __rename_to__ = ImmutableDict([
        ('raw-input', 'raw_input'),
    ])

    name = attr.ib()  # type: str
    image = attr.ib()  # type: Union[str, DockerImage]
    call = attr.ib()  # type: Union[str, Sequence[str]]
    volumes = attr.ib(default=None)  # type: Optional[Sequence[VolumeType]]
    ports = attr.ib(default=None)  # type: Optional[Sequence[Expose]]
    environ = attr.ib(default=None)  # type: Optional[Mapping[str: str]]
    raw_input = attr.ib(default=None)  # type: Optional[bool]
    requires = attr.ib(default=None)  # type: Optional[Sequence[str]]
    description = attr.ib(default=None)  # type: Optional[str]

    def accept(self, visitor):
        return visitor.visit_subcommand(self)
