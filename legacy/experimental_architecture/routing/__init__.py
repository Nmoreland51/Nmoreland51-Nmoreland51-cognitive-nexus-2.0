"""Routing package for Cognitive Nexus.

Provides abstractions for intent routing, prompt transformation, and
reasoning flow selection.
"""

from .router import RouteDecision, Router

__all__ = ["RouteDecision", "Router"]
