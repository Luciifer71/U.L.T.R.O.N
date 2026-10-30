"""Dispatch a command without importing unrelated optional dependencies."""
import os
import runpy
import sys

COMMANDS = {'start': 'cli.start_ultron', 'verify': 'cli.verify_ultron', 'report': 'cli.collect_ultron_report', 'accept': 'cli.ultron_acceptance', 'diagnose': 'cli.ultron_diagnostics', 'speech': 'cli.speech_diagnostics', 'google': 'cli.google_connect', 'resources': 'cli.resource_cli', 'send': 'cli.send_intent', 'benchmark': 'cli.model_benchmark', 'brain_agent': 'agents.brain_agent', 'action_daemon': 'agents.action_daemon', 'voice_listener': 'agents.voice_listener'}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print("Usage: python run_ultron.py <command> [arguments]")
        print("Commands: " + ", ".join(COMMANDS))
        return 0
    command = sys.argv[1]
    if command not in COMMANDS:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 2
    if command in {"brain_agent", "action_daemon", "voice_listener"}:
        from ultron.paths import project_root
        os.chdir(project_root())
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    runpy.run_module("ultron." + COMMANDS[command], run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
