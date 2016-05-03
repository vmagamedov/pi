from .ui import ui
from .config import read_config
from .commands import create_commands


if __name__ == '__main__':
    config = read_config()
    for c in create_commands(config):
        ui.add_command(c)
    ui()
