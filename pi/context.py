from .utils import cached_property


class DockerMixin:

    @cached_property
    def client(self):
        from .client import get_client

        return get_client()


class ImagesMixin:

    def require_image(self, image):
        return 'ubuntu:trusty'
