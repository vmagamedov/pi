import io
import re
import tarfile
import subprocess
from tempfile import NamedTemporaryFile

from ._res import LOCAL_PYTHON_BIN, LOCAL_PYTHON_LIB

from .utils import cached_property, search_container
from .types import DockerImage


ANCESTOR_RE = re.compile(b'^FROM[ ]+\{\{ancestor\}\}',
                         flags=re.MULTILINE)

ANSIBLE_INVENTORY = (
    '{host} ansible_connection=docker '
    'ansible_user=root '
    'ansible_python_interpreter={python_path}'
)

REMOTE_PYTHON_PREFIX = '/.pi-python'
REMOTE_PYTHON_BIN = '{}/bin/python2.7'.format(REMOTE_PYTHON_PREFIX)
REMOTE_PYTHON_LIB = '{}/lib/python27.zip'.format(REMOTE_PYTHON_PREFIX)


def _pi_python_tar():
    f = io.BytesIO()
    t = tarfile.open(mode='w', fileobj=f)

    py_bin_info = tarfile.TarInfo(REMOTE_PYTHON_BIN.lstrip('/'))
    py_bin_info.mode = 0o755
    with open(LOCAL_PYTHON_BIN, 'rb') as py_bin_file:
        py_bin_file.seek(0, 2)
        py_bin_info.size = py_bin_file.tell()
        py_bin_file.seek(0)
        t.addfile(py_bin_info, py_bin_file)

    py_lib_info = tarfile.TarInfo(REMOTE_PYTHON_LIB.lstrip('/'))
    with open(LOCAL_PYTHON_LIB, 'rb') as py_lib_file:
        py_lib_file.seek(0, 2)
        py_lib_info.size = py_lib_file.tell()
        py_lib_file.seek(0)
        t.addfile(py_lib_info, py_lib_file)

    t.close()
    f.seek(0)
    return f


class Context:

    def __init__(self, layers, services):
        self.layers = {l.name: l for l in layers}
        self.services = {s.name: s for s in services}

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

    def ensure_running(self, service_names):
        services = [self.services[name] for name in service_names]
        containers = self.client.containers(all=True)
        hosts = {}
        for service in services:
            label = 'pi-{}'.format(service.name)
            container = next(search_container(label, containers), None)
            if container is None:
                raise RuntimeError('Service {} is not running'
                                   .format(service.name))
            if container['State'] != 'running':
                assert False, 'TODO: auto-start'
            ip = container['NetworkSettings']['Networks']['bridge']['IPAddress']
            hosts[service.name] = ip
        return hosts

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
                                         detach=True, tty=True)

        c_id = c['Id']
        plays = [{'hosts': c_id, 'tasks': tasks}]
        try:
            self.client.start(c)
            self.client.put_archive(c, '/', _pi_python_tar())
            with NamedTemporaryFile('w+', encoding='utf-8') as pb_file, \
                    NamedTemporaryFile('w+', encoding='ascii') as inv_file:
                pb_file.write(yaml.dump(plays))
                pb_file.flush()

                inv_file.write(ANSIBLE_INVENTORY.format(
                    host=c_id,
                    python_path=REMOTE_PYTHON_BIN,
                ))
                inv_file.flush()

                exit_code = subprocess.call(['ansible-playbook',
                                             '-i', inv_file.name,
                                             pb_file.name])
                if exit_code:
                    return False

                # cleanup
                rm_id = self.client.exec_create(c, ['rm', '-rf',
                                                    REMOTE_PYTHON_PREFIX])
                self.client.exec_start(rm_id)

                # commit
                self.client.pause(c)
                self.client.commit(c, repository, version)
                self.client.unpause(c)
                return True
        finally:
            self.client.remove_container(c, v=True, force=True)
