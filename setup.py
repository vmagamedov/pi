from setuptools import setup, find_packages

setup(
    name='Pi',
    version='0.1.dev0',
    description='Command-line interface for your projects',
    author='Vladimir Magamedov',
    author_email='vladimir@magamedov.com',
    url='https://github.com/vmagamedov/pi',
    packages=find_packages(),
    license='BSD',
    install_requires=[],
    entry_points={
        'console_scripts': ['pi=pi.__main__:main'],
    }
)
