"""Serialization Utilities"""
import pickle

from typing import Any


class SerializationError(Exception):
    """Base Serialization Exception"""

    pass


class Serializer:
    """Serialization class based on Parsl's Serializer"""

    @staticmethod
    def serialize(obj: Any) -> str:
        """Serialize object to str string"""
        if isinstance(obj, bytes):
            identifier = '01\n'
            obj = obj.hex()
        elif isinstance(obj, str):
            identifier = '02\n'
        else:
            identifier = '03\n'
            obj = pickle.dumps(obj).hex()

        assert isinstance(obj, str)

        return identifier + obj

    @staticmethod
    def deserialize(string: str) -> Any:
        """Deserialize string"""
        if not isinstance(string, str):
            raise ValueError(
                'deserialize only accepts str arguments, '
                'not {}'.format(type(string))
            )
        try:
            identifier, string = string.split('\n', 1)
        except ValueError:
            raise SerializationError(
                'String does not have required '
                'identifier for deserialization'
            )
        if identifier == '01':
            return bytes.fromhex(string)
        elif identifier == '02':
            return string
        elif identifier == '03':
            return pickle.loads(bytes.fromhex(string))
        else:
            raise SerializationError(
                'Unknown identifier {} for '
                'deserialization'.format(identifier)
            )