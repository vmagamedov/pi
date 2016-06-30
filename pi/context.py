import io
import re
import subprocess
from tempfile import NamedTemporaryFile

from ._requires import click

from .utils import cached_property
from .types import DockerImage


ANCESTOR_RE = re.compile(b'^FROM[ ]+\{\{ancestor\}\}',
                         flags=re.MULTILINE)

ANSIBLE_INVENTORY = (
    '{host} ansible_connection=docker '
    'ansible_user=root '
    'ansible_python_interpreter={python_path}'
)


def _get_python_path(client, image):
    c = client.create_container(image, 'which python2')
    client.start(c)
    client.wait(c, 3)
    bin_output = client.logs(c)
    try:
        output = bin_output.decode('utf-8')
    except UnicodeDecodeError:
        return
    if not output.startswith('/'):
        return
    path, = output.splitlines()
    return path


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

        python_path = _get_python_path(self.client, from_.name)
        if python_path is None:
            click.echo('Can\'t find location of the Python executable '
                       'in the base image. Make sure that Python 2.x is '
                       'installed there.')
            click.echo('For example you can check this by calling '
                       '`which python2` inside the container, '
                       'launched using image "{}"'.format(from_.name))
            return False

        c = self.client.create_container(from_.name, '/bin/sh',
                                         detach=True, tty=True)

        c_id = c['Id']
        plays = [{'hosts': c_id, 'tasks': tasks}]
        try:
            self.client.start(c)
            with NamedTemporaryFile('w+', encoding='utf-8') as pb_file, \
                    NamedTemporaryFile('w+', encoding='ascii') as inv_file:
                pb_file.write(yaml.dump(plays))
                pb_file.flush()

                inv_file.write(ANSIBLE_INVENTORY.format(
                    host=c_id,
                    python_path=python_path,
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
