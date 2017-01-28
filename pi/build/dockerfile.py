import io
import re
import sys
import logging


log = logging.getLogger(__name__)

ANCESTOR_RE = re.compile(b'^FROM[ ]+\{\{ancestor\}\}',
                         flags=re.MULTILINE)


async def _echo_build_progress(client, output):
    error = False
    latest_container = None
    try:
        while True:
            items = await output.read()
            if not items:
                break

            for i in items:
                if 'stream' in i:
                    sys.stdout.write(i['stream'])
                    match = re.search(u'Running in ([0-9a-f]+)',
                                      i['stream'])
                    if match:
                        latest_container = match.group(1)
                elif 'error' in i:
                    error = True
                    sys.stdout.write(i['error'])
        return not error
    except BaseException as original_exc:
        try:
            if latest_container is not None:
                sys.stdout.write('Stopping current container {}...'
                                 .format(latest_container))
                await client.stop(latest_container, 5)
                await client.remove_container(latest_container)
        except Exception:
            log.exception('Failed to delete current container')
        finally:
            raise original_exc


async def build(client, layer, dockerfile):
    image = layer.docker_image()
    if layer.parent:
        from_ = layer.parent.docker_image()
    else:
        from_ = layer.image.from_

    with open(dockerfile.file_name, 'rb') as f:
        docker_file = f.read()

    if from_ is not None:
        from_stmt = 'FROM {}'.format(from_.name).encode('ascii')
        docker_file = ANCESTOR_RE.sub(from_stmt, docker_file)

    with (await client.build(
            tag=image.name,
            fileobj=io.BytesIO(docker_file),
            rm=True,
            stream=True,
            decode=True,
    )) as output:
        result = await _echo_build_progress(client, output)
    return result
