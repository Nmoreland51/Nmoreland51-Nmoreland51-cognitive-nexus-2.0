"""Providers package for Cognitive Nexus.

Abstracts local and external model providers, inference backends, and service status.
"""

from .local import LocalModelProvider

__all__ = ["LocalModelProvider"]
