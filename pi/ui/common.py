from .._requires import click


class ExtGroup(click.Group):

    def __init__(self, *args, ext_help=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ext_help = ext_help

    def parse_args(self, ctx, args):
        if not args:
            click.echo(ctx.get_help(), color=ctx.color)
            ctx.exit()
        return super().parse_args(ctx, args)

    def format_help_text(self, ctx, formatter):
        super().format_help_text(ctx, formatter)
        if self.ext_help is not None:
            self.ext_help(ctx, formatter)


class ProxyCommand(click.Command):

    def parse_args(self, ctx, args):
        ctx.args = args

    def invoke(self, ctx):
        if self.callback is not None:
            ctx.invoke(self.callback, args=ctx.args)
