from .ui.main import build_cli


def main():
    cli = build_cli()
    cli()


if __name__ == '__main__':
    main()
