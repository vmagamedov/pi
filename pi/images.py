import click


@click.group()
def image():
    pass


@image.command('pull')
def image_pull():
    pass


@image.command('push')
def image_push():
    pass


def build_images_cli(config):
    cli = click.Group()
    cli.add_command(image)
    return cli
