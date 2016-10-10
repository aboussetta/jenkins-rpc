import click
import pickle


@click.group()
def cli():
    pass


@cli.command()
@click.option('--cache-file', default='test-cache')
@click.option('--query')
def query(cache_file, query):
    with open(cache_file, 'rb') as f:
        key, criteria = query.split('=')
        buildobjs = pickle.load(f)
        for build in buildobjs:
            item = build.getattr(key)
            if criteria in item:
                print(build)


cli()
