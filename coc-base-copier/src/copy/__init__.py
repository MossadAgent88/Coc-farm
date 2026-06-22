"""CoC base-copier: detector + canonical layout schema.

This package builds a canonical :class:`~src.copy.schema.Layout` from a single
screenshot of a Clash of Clans village. It is the *copy* half of the
base-copier; the *paste* half is a separate, future module that consumes the
JSON described in ``docs/layout-schema.md``.

Import as ``src.copy`` (not ``copy``) so it never shadows the stdlib module.
"""

from src.copy.schema import (
    SCHEMA_VERSION,
    Layout,
    LayoutObject,
    WallChain,
    GridInfo,
    SourceInfo,
)

__all__ = [
    "SCHEMA_VERSION",
    "Layout",
    "LayoutObject",
    "WallChain",
    "GridInfo",
    "SourceInfo",
]
