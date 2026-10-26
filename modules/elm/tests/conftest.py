"""Make the shared ELM fixtures (``world``, frozen clock) visible to
every test module in this package without per-file boilerplate."""
from .support import _frozen_clock, world  # noqa: F401
