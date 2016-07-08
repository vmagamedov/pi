import io
import re
import subprocess
from tempfile import NamedTemporaryFile

from ._res import PYTHON_LOCAL_PATH

from .utils import cached_property
from .types import DockerImage


ANCESTOR_RE = re.compile(b'^FROM[ ]+\{\{ancestor\}\}',
                         flags=re.MULTILINE)

ANSIBLE_INVENTORY = (
    '{host} ansible_connection=docker '
    'ansible_user=root '
    'ansible_python_interpreter={python_path}'
)

PYTHON_REMOTE_PATH = '/pi-python'


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

    def image_build_dockerfile(self, image, file_name, from_, printer):
        with open(file_name, 'rb') as f:
            docker_file = f.read()

        if from_ is not None:
            from_stmt = 'FROM {}'.format(from_.name).encode('ascii')
            docker_file = ANCESTOR_RE.sub(from_stmt, docker_file)

        output = self.client.build(tag=image.name,
                                   fileobj=io.BytesIO(docker_file),
                                   rm=True, stream=True)
        return printer(self.client, output)

    def image_build_ansibletasks(self, repository, version, tasks, from_):
        from ._requires import yaml

        c = self.client.create_container(from_.name, '/bin/sh',
                                         detach=True, tty=True,
                                         volumes=[PYTHON_REMOTE_PATH])

        c_id = c['Id']
        plays = [{'hosts': c_id, 'tasks': tasks}]
        try:
            self.client.start(c, binds={
                PYTHON_LOCAL_PATH: {'bind': PYTHON_REMOTE_PATH, 'mode': 'ro'}
            })
            with NamedTemporaryFile('w+', encoding='utf-8') as pb_file, \
                    NamedTemporaryFile('w+', encoding='ascii') as inv_file:
                pb_file.write(yaml.dump(plays))
                pb_file.flush()

                inv_file.write(ANSIBLE_INVENTORY.format(
                    host=c_id,
                    python_path='{}/python'.format(PYTHON_REMOTE_PATH),
                ))
                inv_file.flush()

                exit_code = subprocess.call(['ansible-playbook',
                                             '-i', inv_file.name,
                                             pb_file.name])
                if exit_code:
                    return False

                self.client.commit(c, repository, version)
                return True
        finally:
            self.client.remove_container(c, v=True, force=True)
