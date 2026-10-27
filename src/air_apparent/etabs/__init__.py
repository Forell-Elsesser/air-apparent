"""ETABS adapters: a narrow protocol, an in-memory fake, and an optional live COM adapter."""

from .adapter import AdapterError, EtabsAdapter, connect_live, list_instances
from .fake_adapter import FakeAdapter

__all__ = ["AdapterError", "EtabsAdapter", "FakeAdapter", "connect_live", "list_instances"]
