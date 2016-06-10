from typing import Optional, Union, List, Any

from .utils import ImmutableDict


class Scalar:

    @classmethod
    def construct(cls, loader, node):
        return cls(loader.construct_scalar(node))


class Sequence:

    @classmethod
    def construct(cls, loader, node):
        return cls(loader.construct_sequence(node))


class Mapping:
    __params__ = ImmutableDict()

    @classmethod
    def construct(cls, loader, node):
        params = loader.construct_mapping(node)
        unknown = set(params).difference(cls.__params__)
        if unknown:
            raise TypeError('Unknown params {!r} for {!r}'.format(unknown, cls))
        clean_params = {cls.__params__[k]: v for k, v in params.items()}
        return cls(**clean_params)


class DockerImage(Scalar):
    __tag__ = '!DockerImage'

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return '<{}({.name!r})>'.format(self.__tag__, self)


class ProvisionType:

    def accept(self, visitor):
        raise NotImplementedError


class Dockerfile(ProvisionType, Scalar):
    __tag__ = '!Dockerfile'

    def __init__(self, file_name: Optional[str]):
        self.file_name = file_name or 'Dockerfile'

    def __repr__(self):
        return '<{}({.file_name!r})>'.format(self.__tag__, self)

    def accept(self, visitor):
        return visitor.visit_dockerfile(self)


class AnsibleTasks(ProvisionType, Sequence):
    __tag__ = '!AnsibleTasks'

    def __init__(self, tasks: list):
        self.tasks = tasks

    def __repr__(self):
        return '<{}([count={:d}])>'.format(self.__tag__, len(self.tasks))

    def accept(self, visitor):
        return visitor.visit_ansibletasks(self)


class Image(Mapping):
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


class Argument(ParameterType, Mapping):
    __tag__ = '!Argument'

    def accept(self, visitor):
        return visitor.visit_argument(self)


class Option(ParameterType, Mapping):
    __tag__ = '!Option'

    def accept(self, visitor):
        return visitor.visit_option(self)


class CommandType:

    def accept(self, visitor):
        raise NotImplementedError


class ShellCommand(CommandType, Mapping):
    __tag__ = '!ShellCommand'
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('image', 'image'),
        ('params', 'params'),
        ('shell', 'shell'),
        ('help', 'help'),
    ])

    def __init__(self, name: str, image: Union[DockerImage, str], shell: str,
                 params: Optional[List[ParameterType]]=None,
                 help: Optional[str]=None):
        self.name = name
        self.image = image
        self.params = params
        self.shell = shell
        self.help = help

    def accept(self, visitor):
        return visitor.visit_shellcommand(self)


class SubCommand(CommandType, Mapping):
    __tag__ = '!SubCommand'
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('image', 'image'),
        ('call', 'call'),
        ('help', 'help'),
    ])

    def __init__(self, name: str, image: Union[DockerImage, str],
                 call: Union[str, List[str]], help: Optional[str]=None):
        self.name = name
        self.image = image
        self.call = call
        self.help = help

    def accept(self, visitor):
        return visitor.visit_subcommand(self)
