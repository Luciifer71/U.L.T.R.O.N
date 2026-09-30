from __future__ import annotations

from ultron_control.application_discovery import ApplicationDiscovery
from ultron_control.policy import CapabilityPolicy, PolicyConfig


def test_normalization() -> None:
    assert ApplicationDiscovery.normalize_name("Microsoft Edge.exe") == "microsoft edge"
    assert ApplicationDiscovery.normalize_name("  file-explorer ") == "file explorer"


def test_policy_defaults() -> None:
    policy = CapabilityPolicy(PolicyConfig())
    assert policy.decide("filesystem.list").allowed
    assert policy.decide("filesystem.delete", destructive=True).requires_confirmation
    assert policy.decide("process.terminate", destructive=True).requires_confirmation
    assert policy.decide("terminal.execute").requires_confirmation


if __name__ == "__main__":
    test_normalization()
    test_policy_defaults()
    print("ULTRON control-plane unit checks passed.")
