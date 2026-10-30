"""ULTRON computer-control capability layer.

The package exposes structured capabilities for applications, files,
processes and terminal execution.  It is intentionally independent from the
LLM so the Brain can request capabilities without constructing raw OS
commands itself.
"""

from .models import (
    ActionResult,
    AuditRecord,
    CapabilityError,
    CapabilityResult,
    PolicyDecision,
    PolicyDenied,
    ResolvedApplication,
)
from .capability_broker import CapabilityBroker
from .application_discovery import ApplicationDiscovery
from .execution import ExecutionEngine

__all__ = [
    "ActionResult",
    "ApplicationDiscovery",
    "AuditRecord",
    "CapabilityBroker",
    "CapabilityError",
    "CapabilityResult",
    "ExecutionEngine",
    "PolicyDecision",
    "PolicyDenied",
    "ResolvedApplication",
]
