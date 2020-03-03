from setuptools import setup, find_packages

setup(
    name='pi-env',
    version='0.1.2rc4',
    description='Command-line interface for your projects',
    author='Vladimir Magamedov',
    author_email='vladimir@magamedov.com',
    url='https://github.com/vmagamedov/pi',
    packages=find_packages(),
    include_package_data=True,
    license='BSD-3-Clause',
    python_requires='>=3.7',
    install_requires=[],
    entry_points={
        'console_scripts': ['pi=pi.__main__:main'],
    }
)
