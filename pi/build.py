import io
import re
import sys
import json
import tarfile
import logging
import subprocess
from asyncio import coroutine
from tempfile import NamedTemporaryFile

from ._res import LOCAL_PYTHON_BIN, LOCAL_PYTHON_LIB


log = logging.getLogger(__name__)

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


def _echo_build_progress(client, output):
    error = False
    latest_container = None
    try:
        for status in output:
            if 'stream' in status:
                sys.stdout.write(status['stream'])
                match = re.search(u'Running in ([0-9a-f]+)',
                                  status['stream'])
                if match:
                    latest_container = match.group(1)
            elif 'error' in status:
                error = True
                sys.stdout.write(status['error'])
        return not error
    except BaseException as original_exc:
        try:
            if latest_container is not None:
                sys.stdout.write('Stopping current container {}...'
                                 .format(latest_container))
                client.stop(latest_container, 5)
                client.remove_container(latest_container)
        except Exception:
            log.exception('Failed to delete current container')
        finally:
            raise original_exc


class Builder(object):

    def __init__(self, client, async_client, layer, *, loop):
        self.client = client
        self.async_client = async_client
        self.layer = layer
        self.loop = loop
        if layer.parent:
            from_ = layer.parent.docker_image()
        else:
            from_ = layer.image.from_
        self.from_ = from_

    def visit(self, obj):
        return obj.accept(self)

    @coroutine
    def visit_dockerfile(self, obj):
        image = self.layer.docker_image()

        with open(obj.file_name, 'rb') as f:
            docker_file = f.read()

        if self.from_ is not None:
            from_stmt = 'FROM {}'.format(self.from_.name).encode('ascii')
            docker_file = ANCESTOR_RE.sub(from_stmt, docker_file)

        output = yield from self.async_client.build(
            tag=image.name,
            fileobj=io.BytesIO(docker_file),
            rm=True,
            stream=True,
            decode=True,
        )
        result = yield from self.loop.run_in_executor(
            None,
            _echo_build_progress,
            self.client,
            output,
        )
        return result

    @coroutine
    def visit_ansibletasks(self, obj):
        from ._requires import yaml

        c = yield from self.async_client.create_container(
            self.from_.name,
            '/bin/sh',
            detach=True,
            tty=True,
        )

        c_id = c['Id']
        plays = [{'hosts': c_id, 'tasks': obj.tasks}]
        try:
            yield from self.async_client.start(c)
            yield from self.async_client.put_archive(c, '/', _pi_python_tar())
            with NamedTemporaryFile('w+', encoding='utf-8') as pb_file, \
                    NamedTemporaryFile('w+', encoding='ascii') as inv_file:
                pb_file.write(yaml.dump(plays))
                pb_file.flush()

                inv_file.write(ANSIBLE_INVENTORY.format(
                    host=c_id,
                    python_path=REMOTE_PYTHON_BIN,
                ))
                inv_file.flush()

                def call_ansible():
                    return subprocess.call(['ansible-playbook',
                                            '-i', inv_file.name,
                                            pb_file.name])
                exit_code = yield from self.loop.run_in_executor(None,
                                                                 call_ansible)
                if exit_code:
                    return False

                # cleanup
                rm_id = yield from self.async_client.exec_create(
                    c,
                    ['rm', '-rf', REMOTE_PYTHON_PREFIX],
                )
                yield from self.async_client.exec_start(rm_id)

                # commit
                yield from self.async_client.pause(c)
                yield from self.async_client.commit(
                    c,
                    self.layer.image.repository,
                    self.layer.version(),
                )
                yield from self.async_client.unpause(c)
                return True
        finally:
            yield from self.async_client.remove_container(c, v=True, force=True)
