"""Serialization Unit Tests"""
import numpy as np

from pytest import raises

from proxystore.backend import serialize, deserialize
from proxystore.backend.serialization import SerializationError


def test_serialization() -> None:
    """Test serialization"""
    x = b'test string'
    b = serialize(x)
    assert deserialize(b) == x

    x = 'test string'
    b = serialize(x)
    assert deserialize(b) == x

    x = np.array([1, 2, 3])
    b = serialize(x)
    assert np.array_equal(deserialize(b), x)

    with raises(ValueError):
        # deserialize raises ValueError on non-string inputs
        deserialize(b'xxx')

    with raises(SerializationError):
        # No identifier
        deserialize('xxx')

    with raises(SerializationError):
        # Fake identifer 'xxx'
        deserialize('xxx\nxxx')