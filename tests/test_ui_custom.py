from unittest.mock import Mock

import pytest

from pi.types import Service
from pi.utils import SequenceMap
from pi.ui.custom import _required_services


def mk_service(name, requires):
    return Service(name=name, image=None, requires=requires)


def test_required_services():
    env = Mock(services=SequenceMap([
        mk_service('a', None),
        mk_service('b', ['a']),
        mk_service('c', ['b']),
    ], lambda i: i.name))
    cmd = Mock(requires=['c'])
    assert [s.name for s in _required_services(env, cmd)] == ['a', 'b', 'c']


def test_required_services_duplicates():
    env = Mock(services=SequenceMap([
        mk_service('a', None),
        mk_service('b', ['a']),
        mk_service('c', ['a']),
    ], lambda i: i.name))
    cmd = Mock(requires=['c', 'b'])
    assert [s.name for s in _required_services(env, cmd)] == ['a', 'c', 'b']


def test_required_services_undefined():
    env = Mock(services=SequenceMap([], lambda i: i.name))
    cmd = Mock(requires=['a'])
    with pytest.raises(TypeError) as err:
        list(_required_services(env, cmd))
    err.match('Service "a" is not defined')


def test_required_services_ref_cycle():
    env = Mock(services=SequenceMap([
        mk_service('a', ['c']),
        mk_service('b', ['a']),
        mk_service('c', ['a']),
    ], lambda i: i.name))
    cmd = Mock(requires=['c'])
    with pytest.raises(TypeError) as err:
        list(_required_services(env, cmd))
    err.match('Service "c" has circular reference')
