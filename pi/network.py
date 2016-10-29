from .client import APIError


def ensure_network(client, name):
    try:
        client.create_network(name, driver='bridge', check_duplicate=True)
    except APIError as e:
        err = e.response.json()
        msg = 'network with name {} already exists'.format(name)
        if 'message' in err and err['message'] == msg:
            return
        raise