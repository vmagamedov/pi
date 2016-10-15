import io
import re
import tarfile
import subprocess
from tempfile import NamedTemporaryFile

from ._res import LOCAL_PYTHON_BIN, LOCAL_PYTHON_LIB

from .client import echo_build_progress


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


class Builder(object):

    def __init__(self, client, layer):
        self.client = client
        self.layer = layer
        if layer.parent:
            from_ = layer.parent.docker_image()
        else:
            from_ = layer.image.from_
        self.from_ = from_

    def visit(self, obj):
        return obj.accept(self)

    def visit_dockerfile(self, obj):
        image = self.layer.docker_image()

        with open(obj.file_name, 'rb') as f:
            docker_file = f.read()

        if self.from_ is not None:
            from_stmt = 'FROM {}'.format(self.from_.name).encode('ascii')
            docker_file = ANCESTOR_RE.sub(from_stmt, docker_file)

        output = self.client.build(tag=image.name,
                                   fileobj=io.BytesIO(docker_file),
                                   rm=True, stream=True)
        return echo_build_progress(self.client, output)

    def visit_ansibletasks(self, obj):
        from ._requires import yaml

        c = self.client.create_container(self.from_.name, '/bin/sh',
                                         detach=True, tty=True)

        c_id = c['Id']
        plays = [{'hosts': c_id, 'tasks': obj.tasks}]
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
                self.client.commit(c, self.layer.image.repository,
                                   self.layer.version())
                self.client.unpause(c)
                return True
        finally:
            self.client.remove_container(c, v=True, force=True)
