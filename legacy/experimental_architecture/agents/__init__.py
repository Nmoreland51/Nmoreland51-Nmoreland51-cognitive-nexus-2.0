"""Cognitive Nexus agents package.

This package contains the core agent abstractions and routing helpers
for the emergent reasoning engine.
"""

from .base import Agent, AgentResult
from .nexus import NexusAgent, RoutingIntent

__all__ = ["Agent", "AgentResult", "NexusAgent", "RoutingIntent"]
