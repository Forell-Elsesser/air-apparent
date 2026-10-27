"""Adapter error type, kept in its own module so pure helpers can raise it without importing the adapter."""


class AdapterError(RuntimeError):
    """A call failed, returned a non-zero API code, or violated its return contract."""
