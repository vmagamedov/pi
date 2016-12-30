import io
import tarfile
import subprocess

from asyncio import coroutine
from tempfile import NamedTemporaryFile

from .._res import LOCAL_PYTHON_BIN, LOCAL_PYTHON_LIB

from .._requires import yaml


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


@coroutine
def build(client, layer, ansible_tasks, *, loop):
    if layer.parent:
        from_ = layer.parent.docker_image()
    else:
        from_ = layer.image.from_

    c = yield from client.create_container(
        from_.name,
        '/bin/sh',
        detach=True,
        tty=True,
    )

    c_id = c['Id']
    plays = [{'hosts': c_id, 'tasks': ansible_tasks.tasks}]
    try:
        yield from client.start(c)
        yield from client.put_archive(c, '/', _pi_python_tar())
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

            exit_code = yield from loop.run_in_executor(None, call_ansible)
            if exit_code:
                return False

            # cleanup
            rm_id = yield from client.exec_create(
                c,
                ['rm', '-rf', REMOTE_PYTHON_PREFIX],
            )
            yield from client.exec_start(rm_id)

            # commit
            yield from client.pause(c)
            yield from client.commit(
                c,
                layer.image.repository,
                layer.version(),
            )
            yield from client.unpause(c)
            return True
    finally:
        yield from client.remove_container(c, v=True, force=True)
