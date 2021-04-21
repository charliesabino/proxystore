"""Utility Functions for Proxies"""
from __future__ import annotations

from typing import Any, Optional

import proxystore as ps


def get_key(proxy: ps.proxy.Proxy) -> Optional[str]:
    """Returns key associated object wrapped by proxy

    Args:
        proxy (Proxy)

    Returns:
        key (str) if it exists otherwise `None`
    """
    if hasattr(proxy.__factory__, 'key'):
        return proxy.__factory__.key
    return None


def extract(proxy: ps.proxy.Proxy) -> Any:
    """Returns object wrapped by proxy"""
    return proxy.__wrapped__


def is_resolved(proxy: ps.proxy.Proxy) -> bool:
    """Check if a proxy is resolved"""
    return proxy.__resolved__


def resolve_async(proxy: ps.proxy.Proxy) -> None:
    """Begin resolving proxy asynchronously"""
    if not is_resolved(proxy):
        proxy.__factory__.resolve_async()