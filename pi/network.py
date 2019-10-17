from .http import HTTPError


async def ensure_network(docker, name):
    try:
        await docker.create_network(data={
            'Name': name,
            'Driver': 'bridge',
            'CheckDuplicate': True,
        })
    except HTTPError as err:
        if err.reason == 'Conflict':
            return
        raise
