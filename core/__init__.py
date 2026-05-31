"""Core compatibility exports for Cognitive Nexus.

The active reasoning stack lives in ``core.reasoning`` and
``core.reality_grounding``.  The top-level modules exported here are lightweight
compatibility layers retained for older imports and packaged builds.
"""

from .observation import Observation, ObservationLog
from .model import BeliefSystem, InternalModel
from .cognition import CognitionEngine, Hypothesis
from .grounding import GroundingAgent, FactCheck
from .compression import TheoryCompressor, ExtractedPattern

__all__ = [
    "Observation",
    "ObservationLog",
    "BeliefSystem",
    "InternalModel",
    "CognitionEngine",
    "Hypothesis",
    "GroundingAgent",
    "FactCheck",
    "TheoryCompressor",
    "ExtractedPattern",
]
