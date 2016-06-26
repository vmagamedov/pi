import io
import re

from .utils import cached_property
from .types import DockerImage


ANCESTOR_RE = re.compile(b'^FROM[ ]+\{\{ancestor\}\}',
                         flags=re.MULTILINE)


class Context:

    def __init__(self, layers):
        self.layers = {l.name: l for l in layers}

    @cached_property
    def client(self):
        from .client import get_client

        return get_client()

    def require_image(self, image):
        if not isinstance(image, DockerImage):
            layer = self.layers[image]
            image = layer.docker_image()
        # check and autoload image
        return image

    def layers_path(self, name):
        path = []
        parent = self.layers[name]
        while parent is not None:
            path.append(parent)
            parent = path[-1].parent
        return tuple(reversed(path))

    def image_exists(self, image):
        from .client import APIError

        try:
            self.client.inspect_image(image.name)
        except APIError as e:
            if e.response.status_code == 404:
                return False
            raise
        else:
            return True

    def image_pull(self, image, printer):
        from .client import APIError

        try:
            output = self.client.pull(image.name, stream=True)
        except APIError as e:
            if e.response.status_code == 404:
                return False
            raise
        else:
            # NOTE: `printer` is also responsible in detecting errors
            return printer(output)

    def image_push(self, image, printer):
        output = self.client.push(image.name, stream=True)
        # NOTE: `printer` is also responsible in detecting errors
        return printer(output)

    def image_build_dockerfile(self, image, file_name, printer):
        with open(file_name, 'rb') as f:
            output = self.client.build(tag=image.name, fileobj=f,
                                       rm=True, stream=True)
            return printer(self.client, output)

    def image_build_dockerfile_from(self, image, file_name, from_, printer):
        with open(file_name, 'rb') as f:
            docker_file = f.read()

        from_stmt = 'FROM {}'.format(from_.name).encode('ascii')
        docker_file = ANCESTOR_RE.sub(from_stmt, docker_file)

        output = self.client.build(tag=image.name,
                                   fileobj=io.BytesIO(docker_file),
                                   rm=True, stream=True)
        return printer(self.client, output)
