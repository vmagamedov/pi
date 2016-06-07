from typing import Optional


class Mapping:

    @classmethod
    def construct(cls, loader, node):
        return cls(**loader.construct_mapping(node))


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


class Image(Mapping):
    __tag__ = '!Image'

    def __init__(self, name: str, repository: str, from_: str,
                 provision_with: ProvisionType):
        self.name = name
        self.repository = repository
        self.from_ = from_
        self.provision_with = provision_with


class DockerImage(Scalar):
    __tag__ = '!DockerImage'

    def __init__(self, name: str):
        self.name = name
