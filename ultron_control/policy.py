"""Capability policy for the ULTRON control plane.

The LLM may request capabilities, but policy decides whether a capability is
allowed to execute.  This prevents the model itself from being the authority
that decides which operations are safe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .models import PolicyDecision


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """Runtime policy switches."""

    mode: str = os.getenv("ULTRON_CONTROL_POLICY", "interactive")
    allow_system_changes: bool = os.getenv(
        "ULTRON_ALLOW_SYSTEM_CHANGES", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    allow_process_termination: bool = os.getenv(
        "ULTRON_ALLOW_PROCESS_TERMINATION", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    allow_file_deletion: bool = os.getenv(
        "ULTRON_ALLOW_FILE_DELETION", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    allow_arbitrary_terminal: bool = os.getenv(
        "ULTRON_ALLOW_ARBITRARY_TERMINAL", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}


class CapabilityPolicy:
    """Central policy engine.

    Read-only capabilities are allowed by default.  Destructive or system-wide
    actions are approval-gated unless explicitly enabled through configuration.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def decide(self, capability: str, *, destructive: bool = False, system_change: bool = False) -> PolicyDecision:
        if system_change and not self.config.allow_system_changes:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=True,
                reason="System-changing operation requires explicit approval or policy configuration.",
            )

        if destructive and capability == "process.terminate" and not self.config.allow_process_termination:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=True,
                reason="Process termination is approval-gated by default.",
            )

        if destructive and capability == "filesystem.delete" and not self.config.allow_file_deletion:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=True,
                reason="File deletion is approval-gated by default.",
            )

        if capability == "terminal.execute" and not self.config.allow_arbitrary_terminal:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=True,
                reason="Arbitrary terminal execution requires explicit approval or a future trusted-command policy.",
            )

        return PolicyDecision(allowed=True)
