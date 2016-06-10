from typing import Optional, Union

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
    pass


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
            '<!Image(name={0.name!r} repository={0.repository!r} '
            'provision-with={0.provision_with!r} from={0.from_!r})>'
            .format(self)
        )
