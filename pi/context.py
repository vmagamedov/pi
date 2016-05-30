from .utils import cached_property
from .layers import Image


class Context:

    def __init__(self, layers):
        self.layers = {l.name: l for l in layers}

    @cached_property
    def client(self):
        from .client import get_client

        return get_client()

    def require_image(self, image):
        if not isinstance(image, Image):
            layer = self.layers[image]
            image = layer.image()
        # check and autoload image
        return image

    def layers_path(self, name):
        path = []
        parent = self.layers[name]
        while parent is not None:
            path.append(parent)
            parent = path[-1].parent
        return tuple(reversed(path))

    def layer_exists(self, image):
        from .client import APIError

        try:
            self.client.inspect_image(image.name)
        except APIError as e:
            if e.response.status_code == 404:
                return False
            raise
        else:
            return True

    def maybe_pull(self, image, printer):
        from .client import APIError

        try:
            output = self.client.pull(image.name, stream=True)
        except APIError as e:
            if e.response.status_code == 404:
                return False
            raise
        else:
            printer(output)
            return True

    def image_build_dockerfile(self, image, file_name, printer):
        with open(file_name, 'rb') as f:
            output = self.client.build(tag=image.name, fileobj=f,
                                       rm=True, stream=True)
            printer(self.client, output)
