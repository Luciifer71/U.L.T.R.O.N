"""Shared data models for ULTRON's control plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class CapabilityError(RuntimeError):
    """Base error for capability-layer failures."""


class PolicyDenied(CapabilityError):
    """Raised when an operation requires approval or is blocked."""

    def __init__(self, message: str, *, capability: str, reason: str) -> None:
        super().__init__(message)
        self.capability = capability
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Decision returned by the policy layer."""

    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedApplication:
    """A validated application launch target."""

    requested_name: str
    display_name: str
    command: tuple[str, ...]
    source: str
    executable: str | None = None
    app_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Normalized result from a physical action."""

    success: bool
    operation: str
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at_ms: int | None = None
    completed_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    """Result returned by a broker capability."""

    success: bool
    capability: str
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    requires_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Structured audit event emitted by the control plane."""

    task_id: str
    capability: str
    operation: str
    target: str | None
    success: bool
    timestamp_ms: int
    duration_ms: int | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
