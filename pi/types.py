from enum import Enum

from ._requires.typing import Optional, Union, Any, Sequence

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
    __params__ = ImmutableDict()

    @classmethod
    def construct(cls, loader, node):
        params = loader.construct_mapping(node, deep=True)
        unknown = set(params).difference(cls.__params__)
        if unknown:
            raise TypeError('Unknown params {!r} for {!r}'.format(unknown, cls))
        clean_params = {cls.__params__[k]: v for k, v in params.items()}
        return cls(**clean_params)


class Meta(MappingConstruct):
    __tag__ = '!Meta'
    __params__ = ImmutableDict([
        ('description', 'description'),
    ])

    def __init__(self, description: Optional[str]=None):
        self.description = description


class DockerImage(ScalarConstruct):
    __tag__ = '!DockerImage'

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return '<{}({.name!r})>'.format(self.__tag__, self)


class ProvisionType:

    def accept(self, visitor):
        raise NotImplementedError


class Dockerfile(ProvisionType, ScalarConstruct):
    __tag__ = '!Dockerfile'

    def __init__(self, file_name: Optional[str]):
        self.file_name = file_name or 'Dockerfile'

    def __repr__(self):
        return '<{}({.file_name!r})>'.format(self.__tag__, self)

    def accept(self, visitor):
        return visitor.visit_dockerfile(self)


class AnsibleTasks(ProvisionType, SequenceConstruct):
    __tag__ = '!AnsibleTasks'

    def __init__(self, tasks: list):
        self.tasks = tasks

    def __repr__(self):
        return '<{}([count={:d}])>'.format(self.__tag__, len(self.tasks))

    def accept(self, visitor):
        return visitor.visit_ansibletasks(self)


class Image(MappingConstruct):
    __tag__ = '!Image'
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('repository', 'repository'),
        ('provision-with', 'provision_with'),
        ('from', 'from_'),
    ])

    def __init__(self, name: str, repository: str,
                 provision_with: ProvisionType,
                 from_: Optional[Union[DockerImage, str]]=None):
        self.name = name
        self.repository = repository
        self.provision_with = provision_with
        self.from_ = from_

    def __repr__(self):
        return (
            '<{0.__tag__}(name={0.name!r} repository={0.repository!r} '
            'provision-with={0.provision_with!r} from={0.from_!r})>'
            .format(self)
        )


class VolumeType:

    def accept(self, visitor):
        raise NotImplementedError


class Mode(EnumConstruct, Enum):
    RO = '!RO'
    RW = '!RW'

    def accept(self, visitor):
        return getattr(visitor, 'visit_{}'.format(self.name))(self)


class LocalPath(VolumeType, MappingConstruct):
    __tag__ = '!LocalPath'
    __params__ = ImmutableDict([
        ('from', 'from_'),
        ('to', 'to'),
        ('mode', 'mode'),
    ])

    def __init__(self, from_: str, to: str, mode: Mode=Mode.RO):
        self.from_ = from_
        self.to = to
        self.mode = mode

    def accept(self, visitor):
        return visitor.visit_localpath(self)


class NamedVolume(VolumeType, MappingConstruct):
    __tag__ = '!NamedVolume'
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('to', 'to'),
        ('mode', 'mode'),
    ])

    def __init__(self, name: str, to: str, mode: Mode=Mode.RO):
        self.name = name
        self.to = to
        self.mode = mode

    def accept(self, visitor):
        return visitor.visit_namedvolume(self)


class Expose(MappingConstruct):
    __tag__ = '!Expose'
    __params__ = ImmutableDict([
        ('port', 'port'),
        ('as', 'as_'),
        ('addr', 'addr'),
        ('proto', 'proto'),
    ])

    def __init__(self, port: int, as_: int, addr: str='127.0.0.1',
                 proto: str='tcp'):
        self.port = port
        self.as_ = as_
        self.addr = addr
        self.proto = proto


class ParameterType:
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('type', 'type'),
        ('default', 'default'),
    ])

    def __init__(self, name: str, type: Optional[str]=None,
                 default: Optional[Any]=None):
        self.name = name
        self.type = type
        self.default = default

    def __repr__(self):
        return (
            '<{0.__tag__}(name={0.name!r} type={0.type!r} '
            'default={0.default!r})>'
            .format(self)
        )

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


class ShellCommand(CommandType, MappingConstruct):
    __tag__ = '!ShellCommand'
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('image', 'image'),
        ('params', 'params'),
        ('shell', 'shell'),
        ('volumes', 'volumes'),
        ('ports', 'ports'),
        ('raw-input', 'raw_input'),
        ('description', 'description'),
    ])

    def __init__(self, name: str, image: Union[DockerImage, str], shell: str,
                 params: Optional[Sequence[ParameterType]]=None,
                 volumes: Optional[Sequence[VolumeType]]=None,
                 ports: Optional[Sequence[Expose]]=None,
                 raw_input: Optional[bool]=False,
                 description: Optional[str]=None):
        self.name = name
        self.image = image
        self.params = params
        self.shell = shell
        self.volumes = volumes or []
        self.ports = ports or []
        self.raw_input = raw_input
        self.description = description

    def accept(self, visitor):
        return visitor.visit_shellcommand(self)


class SubCommand(CommandType, MappingConstruct):
    __tag__ = '!SubCommand'
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('image', 'image'),
        ('call', 'call'),
        ('volumes', 'volumes'),
        ('ports', 'ports'),
        ('raw-input', 'raw_input'),
        ('description', 'description'),
    ])

    def __init__(self, name: str, image: Union[DockerImage, str],
                 call: Union[str, Sequence[str]],
                 volumes: Optional[Sequence[VolumeType]]=None,
                 ports: Optional[Sequence[Expose]]=None,
                 raw_input: Optional[bool]=False,
                 description: Optional[str]=None):
        self.name = name
        self.image = image
        self.call = call
        self.volumes = volumes or []
        self.ports = ports or []
        self.raw_input = raw_input
        self.description = description

    def accept(self, visitor):
        return visitor.visit_subcommand(self)
