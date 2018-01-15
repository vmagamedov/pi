import pytest

from pi.types import Command, DockerImage, Service
from pi.resolve import ImagesCollector, Dep


def test_images_collect():
    i1 = DockerImage(name='d1')
    i2 = DockerImage(name='d2')
    i3 = DockerImage(name='d3')

    services_map = {
        'a': Service(name='a', image=i1, requires=[]),
        'b': Service(name='b', image=i2, requires=['a']),
    }

    cmd = Command(name='fuxin', image=i3, run='sh', requires=['b'])

    assert set(ImagesCollector.collect({}, services_map, cmd)) == {
        Dep(None, i1), Dep(None, i2), Dep(None, i3),
    }


def test_images_collect_ref_cycle():
    i1 = DockerImage(name='d1')
    i2 = DockerImage(name='d2')
    i3 = DockerImage(name='d3')
    i4 = DockerImage(name='d4')

    services_map = {
        'a': Service(name='a', image=i1, requires=['c']),
        'b': Service(name='b', image=i2, requires=['a']),
        'c': Service(name='c', image=i3, requires=['b']),
    }

    cmd = Command(name='planner', image=i4, run='sh', requires=['c'])

    with pytest.raises(TypeError) as err:
        ImagesCollector.collect({}, services_map, cmd)
    err.match('Service "c" has circular reference')
