from typing import Optional

from .utils import ImmutableDict


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


class Scalar:

    @classmethod
    def construct(cls, loader, node):
        return cls(loader.construct_scalar(node))


class ProvisionType:
    pass


class Dockerfile(ProvisionType, Scalar):
    __tag__ = '!Dockerfile'

    def __init__(self, file_name: Optional[str]):
        self.file_name = file_name or 'Dockerfile'

    def __repr__(self):
        return '<!Dockerfile({.file_name!r})>'.format(self)


class Image(Mapping):
    __tag__ = '!Image'
    __params__ = ImmutableDict([
        ('name', 'name'),
        ('repository', 'repository'),
        ('from', 'from_'),
        ('provision-with', 'provision_with'),
    ])

    def __init__(self, name: str, repository: str, from_: str,
                 provision_with: ProvisionType):
        self.name = name
        self.repository = repository
        self.from_ = from_
        self.provision_with = provision_with

    def __repr__(self):
        return (
            '<!Image(name={0.name!r} repository={0.repository!r} '
            'from={0.from_!r} provision-with={0.provision_with!r})>'
            .format(self)
        )


class DockerImage(Scalar):
    __tag__ = '!DockerImage'

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return '<!DockerImage({.name!r})>'.format(self)
