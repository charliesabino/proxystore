"""Utilities for client interactions with endpoints."""
from __future__ import annotations

import uuid

import requests
from requests.exceptions import RequestException  # noqa: F401

from proxystore.endpoint.constants import MAX_CHUNK_LENGTH
from proxystore.utils import chunk_bytes


def evict(
    address: str,
    key: str,
    endpoint: uuid.UUID | str | None = None,
) -> None:
    """Evict the object associated with the key.

    Args:
        address: Address of endpoint.
        key: Key associated with object to evict.
        endpoint: Optional UUID of remote endpoint to forward operation to.

    Raises:
        RequestException: If the endpoint request results in an unexpected
            error code.
    """
    endpoint_str = (
        str(endpoint) if isinstance(endpoint, uuid.UUID) else endpoint
    )
    response = requests.post(
        f'{address}/evict',
        params={'key': key, 'endpoint': endpoint_str},
    )
    response.raise_for_status()


def exists(
    address: str,
    key: str,
    endpoint: uuid.UUID | str | None = None,
) -> bool:
    """Check if an object associated with the key exists.

    Args:
        address: Address of endpoint.
        key: Key potentially associated with stored object.
        endpoint: Optional UUID of remote endpoint to forward operation to.

    Returns:
        If an object associated with the key exists.

    Raises:
        RequestException: If the endpoint request results in an unexpected
            error code.
    """
    endpoint_str = (
        str(endpoint) if isinstance(endpoint, uuid.UUID) else endpoint
    )
    response = requests.get(
        f'{address}/exists',
        params={'key': key, 'endpoint': endpoint_str},
    )
    response.raise_for_status()
    return response.json()['exists']


def get(
    address: str,
    key: str,
    endpoint: uuid.UUID | str | None = None,
) -> bytes | None:
    """Get the serialized object associated with the key.

    Args:
        address: Address of endpoint.
        key: Key associated with object to retrieve.
        endpoint: Optional UUID of remote endpoint to forward operation to.

    Returns:
        Serialized object or `None` if the object does not exist.

    Raises:
        RequestException: If the endpoint request results in an unexpected
            error code.
    """
    endpoint_str = (
        str(endpoint) if isinstance(endpoint, uuid.UUID) else endpoint
    )
    response = requests.get(
        f'{address}/get',
        params={'key': key, 'endpoint': endpoint_str},
        stream=True,
    )

    if response.status_code == 400:
        return None

    response.raise_for_status()

    data = bytearray()
    for chunk in response.iter_content(chunk_size=None):
        data += chunk
    return bytes(data)


def put(
    address: str,
    key: str,
    data: bytes,
    endpoint: uuid.UUID | str | None = None,
) -> None:
    """Put a serialized object in the store.

    Args:
        address: Address of endpoint.
        key: Key associated with object to retrieve.
        data: Serialized data to put in the store.
        endpoint: Optional UUID of remote endpoint to forward operation to.

    Raises:
        RequestException: If the endpoint request results in an unexpected
            error code.
    """
    endpoint_str = (
        str(endpoint) if isinstance(endpoint, uuid.UUID) else endpoint
    )
    response = requests.post(
        f'{address}/set',
        headers={'Content-Type': 'application/octet-stream'},
        params={'key': key, 'endpoint': endpoint_str},
        data=chunk_bytes(data, MAX_CHUNK_LENGTH),
        stream=True,
    )
    response.raise_for_status()
