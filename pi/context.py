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
