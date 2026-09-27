"""ULTRON Brain Agent — canonical production runtime.

Single active brain process. Visual state is published through the shared
ULTRON NATS event bus, while reasoning/execution remains in the core.

This revision adds a typed action lifecycle so EXECUTING represents real
action dispatch/completion rather than an instantaneous Popen call.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser
import re   
import difflib
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

import keyboard
from nats.aio.client import Client as NATS
from ollama import AsyncClient
import psutil

from visual_events import publish_visual_event

from memory_db import (
    init_memory_db,
    save_fact,
    get_all_facts,
    query_facts,
    log_chat,
    get_recent_chat_history,
)

# Optional extra dependencies for advanced tools
try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

NATS_URL = os.getenv(
    "NATS_URL",
    "nats://127.0.0.1:4222",
)

OLLAMA_HOST = os.getenv(
    "OLLAMA_HOST",
    "http://127.0.0.1:11434",
)

MODEL_NAME = os.getenv(
    "LLM_MODEL",
    "qwen2.5:7b",
)

# =========================================================
# ACTION EXECUTION LIFECYCLE
# =========================================================

EXECUTION_MIN_HOLD_SEC = float(
    os.getenv("ULTRON_EXECUTION_MIN_HOLD_SEC", "0.65")
)
EXECUTION_ACTION_ACK_SEC = float(
    os.getenv("ULTRON_EXECUTION_ACTION_ACK_SEC", "0.15")
)


@dataclass(slots=True)
class PendingAction:
    """A typed action with an explicit completion policy."""

    name: str
    execute: Callable[[], Any]
    completion: Literal["dispatch", "wait"] = "dispatch"


# --- ALL AGENTIC TOOLS DEFINITION ---
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_telemetry",
            "description": (
                "Get real-time CPU utilization %, RAM usage %, battery status,"
                " and storage details."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_facts",
            "description": "Searches stored personal user facts, preferences, favorite games/movies, and user identity stored in SQLite memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Keyword to search user memory (e.g., 'favorite game', 'browser', 'name')."
                    }
                },
                "required": ["search_term"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "Searches static project documentation, local text files, and system manuals ingested in ChromaDB. DO NOT use this for personal user facts or preferences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query for static project documents."
                    }
                },
                "required": ["query"]
            }
        }
    },


{
        "type": "function",
        "function": {
            "name": "run_python_script",
            "description": (
                "Execute a local Python (.py) file in the system or project"
                " workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "script_path": {
                        "type": "string",
                        "description": (
                            "The relative or absolute file path to the Python"
                            " script in snake_case (e.g., 'voice_listener.py' or 'gesture.py')."
                        ),
                    },
                    "args": {
                        "type": "string",
                        "description": (
                            "Optional command line arguments to pass to the"
                            " script."
                        ),
                    },
                },
                "required": ["script_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_media",
            "description": (
                "Control system audio playback (mute, play/pause, volume up,"
                " volume down)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "volume_up",
                            "volume_down",
                            "mute",
                            "play_pause",
                        ],
                    }
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": (
                "Open local Windows applications, system settings, or local"
                " folders (e.g., calculator, vscode, task manager, settings,"
                " downloads, ultron folder)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": (
                            "Target application, folder, or system utility."
                        ),
                    }
                },
                "required": ["app_name"],
            },
        },
    },
   {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Opens a specific website or performs a web search. Supports opening multiple tabs if explicitly requested.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "The URL, domain, or common site name (e.g., youtube, netflix, google)."
                    },
                    "count": {
                        "type": "integer",
                        "description": "The number of times/tabs to open the website (e.g., 2, 3, 5, 10). Defaults to 1 unless specified by user."
                    }
                },
                "required": ["target"]
            }
        }
    },
    # --- NEW EXTENDED TOOLS ---
    {
        "type": "function",
        "function": {
            "name": "activate_protocol",
            "description": (
                "Trigger automated system environment presets like dev_mode,"
                " media_mode, or stealth_mode."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "protocol": {
                        "type": "string",
                        "enum": ["dev_mode", "stealth_mode", "gaming_mode"],
                        "description": "The system macro state to load.",
                    }
                },
                "required": ["protocol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_process",
            "description": (
                "Forcefully terminate a running system task or non-responsive"
                " process."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "process_name": {
                        "type": "string",
                        "description": (
                            "Name of executable or application to kill (e.g.,"
                            " chrome, discord, notepad)."
                        ),
                    }
                },
                "required": ["process_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_clipboard",
            "description": (
                "Read current clipboard text or write new text/code directly"
                " into the system clipboard."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write"],
                        "description": (
                            "Read from clipboard or write text to clipboard."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Text to write if action is 'write'.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_power_control",
            "description": (
                "Lock workstation, sleep system, or initiate reboot/shutdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["lock", "sleep", "restart", "shutdown"],
                        "description": "Power state action.",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "organize_folder",
            "description": (
                "Clean and structure messy folders by categorizing files by"
                " extension."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_folder": {
                        "type": "string",
                        "description": (
                            "Folder alias like 'downloads', 'desktop', or full"
                            " path."
                        ),
                    }
                },
                "required": ["target_folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "live_web_search",
            "description": (
                "Fetch real-time information, news, or live data from the web."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search prompt query.",
                    }
                },
                "required": ["query"],
            },
        },
    },
]

# System & Folder Mappings
APP_MAP = {
    "calculator": "calc",
    "calc": "calc",
    "notepad": "notepad",
    "task manager": "taskmgr",
    "taskmgr": "taskmgr",
    "cmd": "start cmd",
    "terminal": "start wt",
    "powershell": "start powershell",
    "explorer": "explorer",
    "file explorer": "explorer",
    "downloads": "explorer shell:Downloads",
    "documents": "explorer shell:Personal",
    "ultron core": r"explorer C:\Users\Krish\Ultron-core",
    "ultron folder": r"explorer C:\Users\Krish\Ultron-core",
    "ultron": r"explorer C:\Users\Krish\Ultron-core",
    "settings": "start ms-settings:",
    "bluetooth": "start ms-settings:bluetooth",
    "wifi": "start ms-settings:network-wifi",
    "display": "start ms-settings:display",
    "sound": "start ms-settings:sound",
    "vscode": "code",
    "code": "code",
    "chrome": "start chrome",
    "edge": "start msedge",
    "spotify": "start spotify",
    "discord": "start discord",
}

SITE_MAP = {
    "netflix": "https://www.netflix.com",
    "hotstar": "https://www.hotstar.com",
    "disney hotstar": "https://www.hotstar.com",
    "google docs": "https://docs.google.com",
    "docs": "https://docs.google.com",
    "google drive": "https://drive.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://www.github.com",
    "google": "https://www.google.com",
    "reddit": "https://www.reddit.com",
    "chatgpt": "https://chat.openai.com",
}

def resolve_script_filename(requested_name: str, base_dir: str = ".") -> str | None:
    """
    Resolves spoken/transcribed file names (e.g. 'audio lesson.py' or 'voice listener')
    to actual existing .py files in your project directory.
    """
    clean_req = requested_name.strip().lower()
    if not clean_req.endswith(".py"):
        clean_req += ".py"

    # Get all .py files in project directory
    try:
        existing_files = [f for f in os.listdir(base_dir) if f.endswith(".py")]
    except Exception:
        return None

    # 1. Direct exact match
    if clean_req in existing_files:
        return clean_req

    # 2. Convert spaces and hyphens to underscores (snake_case)
    snake_case = clean_req.replace(" ", "_").replace("-", "_")
    if snake_case in existing_files:
        return snake_case

    # 3. Strip non-alphanumeric characters for clean comparison
    def simplify(name: str) -> str:
        return "".join(c for c in name.replace(".py", "").lower() if c.isalnum())

    req_simple = simplify(clean_req)
    for f in existing_files:
        if simplify(f) == req_simple:
            return f

    # 4. Fuzzy match fallback for STT mishearings ("audio lesson" -> "audio_listen.py")
    matches = difflib.get_close_matches(snake_case, existing_files, n=1, cutoff=0.4)
    if matches:
        return matches[0]

    return None


class UltronBrain:
    """Core ULTRON reasoning/orchestration engine."""

    def __init__(self, nc: NATS):
        self.nc = nc
        self.client = AsyncClient(
            host=OLLAMA_HOST,
        )
        self.task_lock = asyncio.Lock()
        self.current_task_id: str | None = None
        self.refresh_system_prompt()

    async def _publish_visual(
        self,
        mode: str,
        *,
        task_id: str | None = None,
    ) -> None:
        """Publish visual state without allowing the visual bus to break the brain."""
        try:
            await publish_visual_event(
                self.nc,
                mode,  # type: ignore[arg-type]
                source="brain_agent",
                task_id=task_id or self.current_task_id,
            )
        except Exception as exc:
            print(f"[VISUAL EVENT WARNING]: Failed to publish {mode.upper()} state: {exc}")

    def refresh_system_prompt(self):
        facts = get_all_facts()
        facts_summary = ""
        if facts:
            facts_list = "\n".join([f"- {f['key']}: {f['value']}" for f in facts])
            facts_summary = f"\n\nSTORED USER FACTS & PREFERENCES:\n{facts_list}"

        self.system_prompt = (
            f"""You are Ultron, an advanced AI assistant. Keep all spoken responses concise and direct.{facts_summary}

CRITICAL RULES:
1. MEMORY STORAGE: If the user states a fact, preference, or detail about themselves (e.g., favorite game, name, movie list), you MUST execute `remember_fact`.
2. MEMORY RECALL: For personal user facts/preferences, look at STORED USER FACTS above or execute `recall_facts`. Do NOT use `query_knowledge_base` for personal user facts.
3. ZERO HALLUCINATION: If a tool or memory search returns no matching information, explicitly state that you do not have that stored in memory. NEVER make up or guess user preferences, games, or movies."""
        )

        self.history = [{"role": "system", "content": self.system_prompt}]

    async def _run_pending_actions(
        self,
        actions: list[PendingAction],
        task_id: str,
    ) -> tuple[bool, str | None]:
        """Run staged actions with an explicit execution lifecycle.

        EXECUTING begins before the first action starts and remains active
        until every staged action has been dispatched/verified according to
        its completion policy. A minimum visual hold makes very fast GUI
        actions perceptible without pretending the system is still executing
        after the action lifecycle has actually completed.
        """

        if not actions:
            return True, None

        execution_started = asyncio.get_running_loop().time()
        await self._publish_visual("executing", task_id=task_id)

        for action in actions:
            try:
                print(
                    f"[ACTION START] [task={task_id}] "
                    f"{action.name}"
                )

                result = await asyncio.to_thread(action.execute)

                if action.completion == "wait" and isinstance(result, subprocess.Popen):
                    return_code = await asyncio.to_thread(result.wait)
                    if return_code != 0:
                        raise RuntimeError(
                            f"Action '{action.name}' exited with code {return_code}."
                        )
                elif isinstance(result, subprocess.Popen):
                    await asyncio.sleep(EXECUTION_ACTION_ACK_SEC)
                    if result.poll() not in (None, 0):
                        raise RuntimeError(
                            f"Action '{action.name}' exited with code {result.returncode}."
                        )

                print(
                    f"[ACTION COMPLETE] [task={task_id}] "
                    f"{action.name}"
                )

            except Exception as exc:
                print(
                    f"[ACTION FAILED] [task={task_id}] "
                    f"{action.name}: {exc}"
                )
                await self._publish_visual("alert", task_id=task_id)
                return False, str(exc)

        elapsed = asyncio.get_running_loop().time() - execution_started
        remaining = EXECUTION_MIN_HOLD_SEC - elapsed

        if remaining > 0:
            await asyncio.sleep(remaining)

        return True, None

    async def process_intent(
        self,
        prompt: str,
        task_id: str,
    ) -> tuple[str, list]:
        self.current_task_id = task_id
        await self._publish_visual("thinking", task_id=task_id)
        self.history.append({"role": "user", "content": prompt})
        # Increased num_predict from 45 to 150 so token generation isn't cut off when returning multiple tools
        fast_options = {"num_predict": 150, "temperature": 0.2}

        try:
            response = await self.client.chat(
                model=MODEL_NAME,
                messages=self.history,
                tools=TOOLS,
                options=fast_options,
            )
        except Exception as e:
            print(f"[BRAIN ERROR]: LLM inference failed: {e}")
            await self._publish_visual("alert", task_id=task_id)
            return "An anomaly occurred within my core processing.", []

        # Safely extract message content/tool calls regardless of dict or object structure
        if hasattr(response, "message"):
            msg_obj = response.message
            message = {
                "role": getattr(msg_obj, "role", "assistant"),
                "content": getattr(msg_obj, "content", "") or "",
                "tool_calls": getattr(msg_obj, "tool_calls", []) or [],
            }
        else:
            message = response.get("message", {})

        content_text = message.get("content", "") or ""
        tool_calls = list(message.get("tool_calls", []) or [])

        # FALLBACK: Catch raw <tool_call> tags in Qwen's text output and convert to tool calls
        if "<tool_call>" in content_text:
            matches = re.findall(
                r"<tool_call>\s*(.*?)\s*</tool_call>", content_text, re.DOTALL
            )
            for m in matches:
                try:
                    parsed = json.loads(m.strip())
                    tool_calls.append(
                        {
                            "function": {
                                "name": parsed.get("name"),
                                "arguments": parsed.get("arguments", {}),
                            }
                        }
                    )
                except Exception as e:
                    print(f"[TOOL PARSE ERROR]: {e}")

            # Strip raw XML tags out so they don't get printed to the user
            content_text = re.sub(
                r"<tool_call>.*?</tool_call>", "", content_text, flags=re.DOTALL
            ).strip()
            message["content"] = content_text

        pending_actions: list[PendingAction] = []

        if tool_calls:
            self.history.append(message)
            for tool in tool_calls:
                # Handle both dict and object structures safely
                if isinstance(tool, dict):
                    func_name = tool.get("function", {}).get("name")
                    args = tool.get("function", {}).get("arguments", {})
                else:
                    func_name = getattr(getattr(tool, "function", None), "name", None)
                    args = getattr(getattr(tool, "function", None), "arguments", {})

                # Safe argument parsing if returned as stringified JSON
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                print(f"[BRAIN EXECUTING TOOL]: {func_name}({args})")

                # --- HANDLER BRANCHES FOR ALL TOOLS ---
                if func_name == "get_system_telemetry":
                    cpu = psutil.cpu_percent(interval=0.1)
                    ram = psutil.virtual_memory().percent
                    battery = psutil.sensors_battery()
                    bat_str = f"{battery.percent}%" if battery else "AC Power"
                    res = (
                        f"System Metrics: CPU at {cpu}%, RAM at {ram}%, Power Source:"
                        f" {bat_str}."
                    )
                
                elif func_name == "run_python_script":
                    raw_path = str(args.get("script_path", "")).strip()
                    extra_args = str(args.get("args", "")).strip()
# Resolve spoken or misheard filenames (e.g., 'voice listener' or 'audio lesson') to actual files on disk
                    actual_file = resolve_script_filename(raw_path)
                    if actual_file and os.path.exists(actual_file):
                        cmd = f"py .\\{actual_file} {extra_args}".strip()
                        pending_actions.append(
                            PendingAction(
                                name=f"run_python_script:{actual_file}",
                                execute=lambda c=cmd: subprocess.Popen(c, shell=True),
                                completion="wait",
                            )
                        )
                        res = f"Executing script '{actual_file}'."
                    else:
                        res = f"Script '{raw_path}' could not be resolved to any file in project directory."
                elif func_name == "control_media":
                    action = args.get("action")
                    key_map = {
                        "volume_up": "volume up",
                        "volume_down": "volume down",
                        "mute": "volume mute",
                        "play_pause": "play/pause media",
                    }
                    target_key = key_map.get(action)
                    if target_key:
                        pending_actions.append(
                            PendingAction(
                                name=f"control_media:{action}",
                                execute=lambda k=target_key: keyboard.send(k),
                            )
                        )
                        res = f"Media action '{action}' staged."
                    else:
                        res = f"Unknown action '{action}'."

                elif func_name == "open_application":
                    app_name = str(args.get("app_name", "")).lower().strip()
                    command = APP_MAP.get(app_name, app_name)
                    pending_actions.append(
                        PendingAction(
                            name=f"open_application:{app_name}",
                            execute=lambda cmd=command: subprocess.Popen(cmd, shell=True),
                        )
                    )
                    res = f"Application '{app_name}' staged for launch."

                elif func_name == "open_website":
                    target = str(args.get("target", "")).lower().strip()
                    
                    # Parse count integer safely (defaulting to 1, capped at 15 to prevent accidental system freezes)
                    try:
                        count = int(args.get("count", 1))
                        count = max(1, min(count, 15))
                    except (ValueError, TypeError):
                        count = 1

                    if target in SITE_MAP:
                        url = SITE_MAP[target]
                    elif target.startswith(("http://", "https://")):
                        url = target
                    elif "." in target and " " not in target:
                        url = f"https://{target}"
                    else:
                        encoded_query = urllib.parse.quote(target)
                        url = f"https://www.google.com/search?q={encoded_query}"

                    # Queue the launcher action as many times as requested
                    for _ in range(count):
                        pending_actions.append(
                            PendingAction(
                                name=f"open_website:{url}",
                                execute=lambda u=url: subprocess.Popen(
                                    f"start {u}", shell=True
                                ),
                            )
                        )

                    res = f"Website destination '{url}' staged ({count} time(s))."
                    
                elif func_name == "activate_protocol":
                    protocol = args.get("protocol")
                    if protocol == "dev_mode":
                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:dev_mode:ide",
                                execute=lambda: subprocess.Popen("code", shell=True),
                            )
                        )
                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:dev_mode:terminal",
                                execute=lambda: subprocess.Popen("start wt", shell=True),
                            )
                        )
                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:dev_mode:github",
                                execute=lambda: webbrowser.open("https://github.com"),
                            )
                        )
                        res = "Dev protocol initiated. IDE, terminal, and repository staged."
                    elif protocol == "stealth_mode":
                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:stealth_mode:mute",
                                execute=lambda: keyboard.send("volume mute"),
                            )
                        )
                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:stealth_mode:chrome",
                                execute=lambda: subprocess.Popen(
                                    "taskkill /F /IM chrome.exe", shell=True
                                ),
                            )
                        )
                        res = "Stealth protocol active. Audio muted and browser instances terminated."
                    else:
                        res = f"Protocol '{protocol}' acknowledged."

                elif func_name == "terminate_process":
                    proc = (
                        str(args.get("process_name", ""))
                        .lower()
                        .replace(".exe", "")
                        .strip()
                    )
                    cmd = f"taskkill /F /IM {proc}.exe"
                    pending_actions.append(
                        PendingAction(
                            name=f"terminate_process:{proc}",
                            execute=lambda c=cmd: subprocess.Popen(c, shell=True),
                        )
                    )
                    res = (
                        f"Termination signal dispatched for process '{proc}'."
                    )

                elif func_name == "manage_clipboard":
                    if pyperclip is None:
                        res = "Clipboard module unavailable. Install using 'pip install pyperclip'."
                    else:
                        action = args.get("action")
                        if action == "read":
                            clip_text = pyperclip.paste()
                            res = f"Clipboard contents captured: '{clip_text[:120]}...'"
                        elif action == "write":
                            pyperclip.copy(args.get("content", ""))
                            res = "New text successfully written to system clipboard."
                        else:
                            res = "Invalid clipboard action."

                elif func_name == "system_power_control":
                    cmd_type = args.get("command")
                    if cmd_type == "lock":
                        pending_actions.append(
                            PendingAction(
                                name="system_power_control:lock",
                                execute=lambda: subprocess.Popen(
                                    "rundll32.exe user32.dll,LockWorkStation",
                                    shell=True,
                                ),
                            )
                        )
                        res = "Workstation locked."
                    elif cmd_type == "sleep":
                        pending_actions.append(
                            PendingAction(
                                name="system_power_control:sleep",
                                execute=lambda: subprocess.Popen(
                                    "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
                                    shell=True,
                                ),
                            )
                        )
                        res = "System entering sleep mode."
                    else:
                        res = f"Power action '{cmd_type}' staged."

                elif func_name == "organize_folder":

                    def sanitize():
                        target_dir = os.path.expanduser("~/Downloads")
                        categories = {
                            "Images": [".png", ".jpg", ".jpeg", ".svg"],
                            "Documents": [".pdf", ".docx", ".txt", ".csv"],
                            "Software": [".exe", ".msi"],
                        }
                        for file in os.listdir(target_dir):
                            ext = os.path.splitext(file)[1].lower()
                            for cat, exts in categories.items():
                                if ext in exts:
                                    cat_folder = os.path.join(target_dir, cat)
                                    os.makedirs(cat_folder, exist_ok=True)
                                    try:
                                        shutil.move(
                                            os.path.join(target_dir, file),
                                            os.path.join(cat_folder, file),
                                        )
                                    except Exception:
                                        pass

                    pending_actions.append(
                        PendingAction(
                            name="organize_folder:downloads",
                            execute=sanitize,
                            completion="wait",
                        )
                    )
                    res = "Downloads directory sanitization scheduled."

                elif func_name == "live_web_search":
                    if DDGS is None:
                        res = "Search module unavailable. Install using 'pip install duckduckgo_search'."
                    else:
                        query = str(args.get("query", ""))
                        try:
                            with DDGS() as ddgs:
                                search_results = [
                                    r["body"]
                                    for r in ddgs.text(query, max_results=2)
                                ]
                            res = f"Live Search Results: {' '.join(search_results)}"
                        except Exception as e:
                            res = f"Web search encountered an error: {e}"

                elif func_name == "query_knowledge_base":
                    query_text = str(args.get("query", ""))
                    try:
                        import chromadb
                        from ollama import Client as SyncOllamaClient

                        chroma_client = chromadb.PersistentClient(path="./chroma_db")
                        collection = chroma_client.get_or_create_collection(name="ultron_knowledge")
                        ollama_sync = SyncOllamaClient()

                        # Vectorize query
                        emb_res = ollama_sync.embed(model="nomic-embed-text", input=query_text)
                        query_emb = emb_res["embeddings"][0]

                        # Search vector DB
                        results = collection.query(query_embeddings=[query_emb], n_results=3)
                        matched_docs = results.get("documents", [[]])[0]

                        if matched_docs:
                            res = "Knowledge Base Content:\n" + "\n---\n".join(matched_docs)
                        else:
                            res = "No matching documents found in knowledge base."
                    except Exception as e:
                        res = f"Knowledge base search error: {e}"
                else:
                    res = "Tool unavailable."

                print(f"[TOOL RESULT]: {res}")
                self.history.append({"role": "tool", "content": res})

            # Return to reasoning state while synthesizing tool results.
            await self._publish_visual("thinking", task_id=task_id)

            # Pass 2: Fast synthesis after tool execution
            try:
                final_response = await self.client.chat(
                    model=MODEL_NAME,
                    messages=self.history,
                    options=fast_options,
                )
                final_text = final_response["message"]["content"]
            except Exception as e:
                print(f"[BRAIN ERROR]: Synthesis pass failed: {e}")
                await self._publish_visual("alert", task_id=task_id)
                final_text = "Action execution completed, but synthesis encountered an error."
        else:
            final_text = message.get("content", "Command acknowledged.")

        self.history.append({"role": "assistant", "content": final_text})
        if len(self.history) > 11:
            self.history = [self.history[0]] + self.history[-10:]

        return final_text, pending_actions


async def main():
    nc = NATS()

    try:
        await nc.connect(
            servers=[NATS_URL],
            name="ultron-brain",
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )
    except Exception as e:
        print(f"[NATS CONNECTION ERROR]: {e}")
        return

    try:
        init_memory_db()
    except Exception as e:
        print(f"[MEMORY DB ERROR]: {e}")
        await nc.drain()
        await nc.close()
        return

    brain = UltronBrain(nc)

    print(
        f"[ULTRON BRAIN]: Synchronized Professional Engine ({MODEL_NAME})."
    )

    async def intent_handler(msg):
        async with brain.task_lock:
            task_id = str(uuid.uuid4())

            try:
                data = json.loads(msg.data.decode())
                prompt = str(data.get("prompt", "")).strip()

                if not prompt:
                    return

                print(
                    f"\n[ULTRON INTENT RECEIVED] "
                    f"[task={task_id}]: '{prompt}'"
                )

                reply_text, pending_actions = await brain.process_intent(
                    prompt,
                    task_id,
                )

                print(
                    f"[ULTRON BRAIN RESPONSE] "
                    f"[task={task_id}]: '{reply_text}'"
                )

                # -------------------------------------------------
                # PHYSICAL ACTION EXECUTION
                # -------------------------------------------------
                action_ok, action_error = await brain._run_pending_actions(
                    pending_actions,
                    task_id,
                )

                if not action_ok:
                    reply_text = (
                        "I could not complete the requested action. "
                        "The execution layer reported an error."
                    )

                # -------------------------------------------------
                # SPEECH RESPONSE
                # -------------------------------------------------
                payload = json.dumps(
                    {
                        "text": reply_text,
                        "speech": reply_text,
                        "taskId": task_id,
                        "execution": {
                            "success": action_ok,
                            "error": action_error,
                        },
                    },
                    separators=(",", ":"),
                ).encode()

                await nc.publish(
                    "ultron.voice",
                    payload,
                )

                await nc.flush()

                # -------------------------------------------------
                # TASK COMPLETE
                # -------------------------------------------------
                await brain._publish_visual(
                    "idle" if action_ok else "alert",
                    task_id=task_id,
                )

            except Exception as e:

                print(
                    f"[INTENT HANDLING ERROR] "
                    f"[task={task_id}]: {e}"
                )

                await brain._publish_visual(
                    "alert",
                    task_id=task_id,
                )

                try:
                    error_payload = json.dumps(
                        {
                            "text": (
                                "An internal error occurred "
                                "while processing your request."
                            ),
                            "speech": (
                                "An internal error occurred "
                                "while processing your request."
                            ),
                            "taskId": task_id,
                        },
                        separators=(",", ":"),
                    ).encode()

                    await nc.publish(
                        "ultron.voice",
                        error_payload,
                    )

                    await nc.flush()

                except Exception as voice_error:

                    print(
                        f"[VOICE ERROR] "
                        f"[task={task_id}]: {voice_error}"
                    )

                # Give ALERT a short visual window before returning
                # to the neutral entity state.
                await asyncio.sleep(0.25)

                await brain._publish_visual(
                    "idle",
                    task_id=task_id,
                )

    await nc.subscribe(
        "ultron.intent",
        cb=intent_handler,
    )

    print(
        "[ULTRON BRAIN]: Intent bus online. "
        "Autonomous visual state synchronization active."
    )

    try:

        while True:
            await asyncio.sleep(3600)

    except asyncio.CancelledError:
        pass

    finally:

        print(
            "[ULTRON BRAIN]: "
            "Shutting down NATS connection gracefully..."
        )

        try:
            await nc.drain()
        except Exception:
            pass

        try:
            await nc.close()
        except Exception:
            pass


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\n[ULTRON] Brain agent offline."
        )
