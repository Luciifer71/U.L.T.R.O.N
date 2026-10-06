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
import inspect

import uuid

from dataclasses import dataclass

from typing import Any, Callable, Literal



import keyboard

from nats.aio.client import Client as NATS

from ollama_runtime import OllamaRuntime, OllamaRuntimeConfig

import psutil



from visual_events import publish_visual_event

from ultron_control.capability_broker import CapabilityBroker
from ultron_control.request_planning import explicit_launch_plan, PlanClarification, validate_application_targets
from ultron_control.intent_guard import (
    build_replay_plan,
    contains_physical_action_request,
    extract_replay_plan,
    is_conversational_only,
    is_replay_request,
    is_task_status_request,
    looks_incomplete_request,
    normalize_tool_calls,
    contains_execution_claim,
)



from memory_db import (

    init_memory_db,

    save_fact,

    get_all_facts,

    query_facts,

    log_chat,

    get_recent_chat_history,

    create_task,

    update_task,

    get_latest_task,

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

    os.getenv("ULTRON_EXECUTION_MIN_HOLD_SEC", "1.20")

)



EXECUTION_ACTION_ACK_SEC = float(

    os.getenv("ULTRON_EXECUTION_ACTION_ACK_SEC", "0.20")

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

            "description": "Searches static project documentation and local manuals ingested in ChromaDB. Never use this for internet/web searches or for searching inside a website.",

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

                "Open installed Windows applications, system utilities, or local"

                " folders. Use this for browser applications such as Chrome, Edge,"

                " Opera, Firefox, and Brave."

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

            "description": (

                "Navigate to a web destination. For a site-specific search, provide"

                " BOTH target and query in the SAME call whenever supported."

                " Use this for websites, not installed browser applications."

            ),

            "parameters": {

                "type": "object",

                "properties": {

                    "target": {

                        "type": "string",

                        "description": "The URL, domain, or common site name (e.g., youtube, netflix, google)."

                    },

                    "query": {

                        "type": "string",

                        "description": "Optional search query to execute on the target website."

                    },

                    "count": {

                        "type": "integer",

                        "description": "Number of tabs/navigation requests. Defaults to 1; maximum 15."

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

                "Fetch real-time information, news, or live data from the internet."

                " Do not use this for searching inside a named website when"

                " open_website target+query expresses the request."

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



    # 4. Controlled fuzzy fallback for STT mishearings.
    #
    # A low fuzzy threshold can turn a missing executable request into an
    # unrelated Python file (for example, "launch_game.py" previously
    # resolving to "ollama_runtime.py"). Keep fuzzy matching only when the
    # match is strong and clearly better than the runner-up.
    matches = difflib.get_close_matches(
        snake_case,
        existing_files,
        n=2,
        cutoff=0.72,
    )

    if matches:
        best_ratio = difflib.SequenceMatcher(
            None,
            snake_case,
            matches[0],
        ).ratio()

        if len(matches) == 1:
            return matches[0]

        second_ratio = difflib.SequenceMatcher(
            None,
            snake_case,
            matches[1],
        ).ratio()

        if best_ratio - second_ratio >= 0.10:
            return matches[0]

    return None





class UltronBrain:

    """Core ULTRON reasoning/orchestration engine."""



    def __init__(self, nc: NATS):

        self.nc = nc

        self.ollama = OllamaRuntime(

            OllamaRuntimeConfig(

                host=OLLAMA_HOST,

                model=MODEL_NAME,

            )

        )

        self.task_lock = asyncio.Lock()

        # Centralized Windows capability control plane.
        # Physical system actions should flow through the broker rather than
        # directly through shell commands wherever a broker capability exists.
        self.capabilities = CapabilityBroker()

        self.current_task_id: str | None = None

        # Bounded, explicit replay state. Only replay-safe operations are stored.
        self.last_replay_plan: list[dict[str, Any]] | None = None
        self.execution_ledger: dict[str, list[dict[str, Any]]] = {}

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

3. ZERO HALLUCINATION: If a tool or memory search returns no matching information, explicitly state that you do not have that stored in memory. NEVER make up or guess user preferences, games, or movies.

4. APPLICATIONS VS WEBSITES: `open_application` is for installed Windows applications such as Chrome, Edge, VS Code, Notion, Steam, File Explorer, and Task Manager. Do NOT treat a browser application name as a website.

5. WEBSITE SEARCH: To search inside a website, use ONE `open_website` call with both `target` and `query` whenever supported. Example: target=`youtube`, query=`quantum computers`. Do NOT use `query_knowledge_base` or `live_web_search` for an on-site search requested by the user.

6. INCOMPLETE REQUESTS: Never invent missing targets, application names, search destinations, or arguments. Ask the user for the missing information.

7. EXECUTION TRUTH: Tool calls are only a plan. Never claim a physical action happened merely because a tool call was produced. The execution layer is authoritative.

8. REPEAT REQUESTS: When the user asks to repeat or redo a previous task, use the stored replay plan supplied by the execution system. Never invent a previous task from conversational wording alone."""
        )

        recent_history = get_recent_chat_history(limit=10)
        self.history = [
            {"role": "system", "content": self.system_prompt},
            *recent_history,
        ]



    def _compose_latest_task_status(self) -> str:
        """Return status from durable task memory, never from model inference."""
        task = get_latest_task()

        if not task:
            return "I do not have a previous task recorded yet."

        status = str(task.get("status") or "unknown").replace("_", " ").lower()
        prompt = str(task.get("prompt") or "").strip()
        result = str(task.get("result_text") or "").strip()
        error = str(task.get("error_text") or "").strip()

        response = f"Task status: {status}. Last task: {prompt}"
        if result:
            response += f" Result: {result}"
        if error and error not in result:
            response += f" Error: {error}"

        return response



    async def _run_pending_actions(
        self,
        actions: list[PendingAction],
        task_id: str,
    ) -> tuple[bool, str | None]:
        """Execute staged actions and persist authoritative execution evidence."""

        if not actions:
            self.execution_ledger[task_id] = []
            return True, None

        execution_started = asyncio.get_running_loop().time()
        update_task(
            task_id,
            "executing",
            event_message="Physical action execution started.",
        )
        await self._publish_visual("executing", task_id=task_id)

        errors: list[str] = []
        outcomes: list[dict[str, Any]] = []

        for action in actions:
            outcome: dict[str, Any] = {
                "name": action.name,
                "success": False,
                "message": "",
                "error": None,
                "state": None,
                "verification": None,
                "verificationReason": None,
            }

            try:
                print(
                    f"[ACTION START] [task={task_id}] "
                    f"{action.name}"
                )

                if inspect.iscoroutinefunction(action.execute):
                    result = await action.execute()
                else:
                    result = await asyncio.to_thread(action.execute)

                if hasattr(result, "success"):
                    result_data = getattr(result, "data", None)
                    capability_failed = getattr(result, "success") is False

                    if (
                        not capability_failed
                        and isinstance(result_data, dict)
                        and result_data.get("success") is False
                    ):
                        capability_failed = True

                    outcome["success"] = not capability_failed
                    outcome["message"] = str(
                        getattr(result, "message", "") or ""
                    )
                    outcome["error"] = (
                        getattr(result, "error", None)
                        or (
                            result_data.get("error")
                            if isinstance(result_data, dict)
                            else None
                        )
                    )

                    if isinstance(result_data, dict):
                        for key in (
                            "state",
                            "verification",
                            "verificationReason",
                            "pid",
                            "target",
                            "resolved",
                            "launchMethod",
                            "source",
                        ):
                            if key in result_data:
                                outcome[key] = result_data[key]

                    if capability_failed:
                        raise RuntimeError(
                            str(
                                outcome["error"]
                                or outcome["message"]
                                or "Capability execution failed."
                            )
                        )

                elif isinstance(result, subprocess.Popen):
                    if action.completion == "wait":
                        return_code = await asyncio.to_thread(result.wait)
                        if return_code != 0:
                            raise RuntimeError(
                                f"Action '{action.name}' exited with code {return_code}."
                            )
                    else:
                        await asyncio.sleep(EXECUTION_ACTION_ACK_SEC)
                        if result.poll() not in (None, 0):
                            raise RuntimeError(
                                f"Action '{action.name}' exited with code {result.returncode}."
                            )

                    outcome["success"] = True
                    outcome["message"] = "Process action completed."

                else:
                    outcome["success"] = True
                    outcome["message"] = "Action completed."

                print(
                    f"[ACTION COMPLETE] [task={task_id}] "
                    f"{action.name}"
                )

            except Exception as exc:
                outcome["success"] = False
                outcome["error"] = str(exc)
                outcome["message"] = (
                    outcome["message"]
                    or "Action execution failed."
                )

                error_text = f"{action.name}: {exc}"
                errors.append(error_text)

                print(
                    f"[ACTION FAILED] [task={task_id}] "
                    f"{error_text}"
                )

            outcomes.append(outcome)

        self.execution_ledger[task_id] = outcomes

        while len(self.execution_ledger) > 100:
            oldest_task = next(iter(self.execution_ledger))
            self.execution_ledger.pop(oldest_task, None)

        elapsed = (
            asyncio.get_running_loop().time()
            - execution_started
        )
        remaining = EXECUTION_MIN_HOLD_SEC - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

        if errors:
            return False, " | ".join(errors)

        return True, None

    def _compose_execution_response(self, task_id: str) -> str:
        """Create a truthful action response from the execution ledger only."""

        outcomes = self.execution_ledger.get(task_id, [])
        if not outcomes:
            return "No physical actions were executed."

        verified: list[str] = []
        dispatched: list[str] = []
        failed: list[str] = []

        for outcome in outcomes:
            name = str(outcome.get("name") or "action")
            verification = outcome.get("verification")
            state = outcome.get("state")
            error = str(outcome.get("error") or "").strip()

            if not outcome.get("success"):
                label = self._friendly_action_name(name)
                failed.append(f"{label} ({error})" if error else label)
                continue

            if (
                state == "dispatched"
                or verification == "not_observable"
            ):
                dispatched.append(
                    self._friendly_action_name(name)
                )
            elif (
                state == "verified"
                or (
                    isinstance(verification, dict)
                    and verification.get("running") is True
                )
            ):
                verified.append(
                    self._friendly_action_name(name)
                )
            else:
                dispatched.append(
                    self._friendly_action_name(name)
                )

        parts: list[str] = []

        if verified:
            parts.append(
                "Opened and verified: "
                + ", ".join(verified)
                + "."
            )

        if dispatched:
            parts.append(
                "Dispatched: "
                + ", ".join(dispatched)
                + "."
            )

        if failed:
            parts.append(
                "Could not complete: "
                + ", ".join(failed)
                + "."
            )

        return " ".join(parts)

    @staticmethod
    def _friendly_action_name(action_name: str) -> str:
        if action_name.startswith("open_application:"):
            return action_name.split(":", 1)[1]

        if action_name.startswith("open_website:"):
            target = action_name.split(":", 1)[1]
            try:
                parsed = urllib.parse.urlparse(target)
                host = (
                    parsed.netloc
                    or ""
                ).lower().removeprefix("www.")

                if host == "youtube.com":
                    if "search_query" in urllib.parse.parse_qs(
                        parsed.query
                    ):
                        return "YouTube search"
                    return "YouTube navigation"

                if host:
                    return f"web navigation to {host}"

            except Exception:
                pass

            return "website navigation"

        if action_name.startswith("control_media:"):
            return (
                action_name
                .split(":", 1)[1]
                .replace("_", " ")
            )

        if action_name.startswith("run_python_script:"):
            return action_name.split(":", 1)[1]

        return action_name



    async def process_intent(
        self,
        prompt: str,
        task_id: str,
    ) -> tuple[str, list]:
        self.current_task_id = task_id
        self.last_plan_error = None
        await self._publish_visual("thinking", task_id=task_id)

        self.history.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        if looks_incomplete_request(prompt):
            return (
                "I need one more detail before I execute that. "
                "Which app, file, folder, or target did you mean?",
                [],
            )

        try:
            explicit_calls = explicit_launch_plan(prompt)
        except PlanClarification as exc:
            self.last_plan_error = str(exc)
            return str(exc), []

        replay_request = is_replay_request(prompt)
        replay_calls = extract_replay_plan(
            prompt,
            self.last_replay_plan,
        )

        if replay_request and not replay_calls:
            return (
                "I do not have a safe previous task to repeat yet. "
                "Please give me the task again once.",
                [],
            )

        # A validated executable request becomes a durable task here.
        # Incomplete, status, acknowledgement, and invalid replay requests
        # never reach this point.
        create_task(task_id, prompt, status="thinking")

        selected_calls = replay_calls or explicit_calls
        if selected_calls:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": selected_calls,
            }
            tool_calls = list(selected_calls)
            content_text = ""
        else:
            fast_options = {
                "num_predict": 256,
                "temperature": 0.2,
            }
            try:
                response = await self.ollama.chat(
                    model=MODEL_NAME,
                    messages=self.history,
                    tools=TOOLS,
                    options=fast_options,
                )
            except Exception as e:
                print(
                    "[BRAIN ERROR]: LLM inference failed: "
                    f"{type(e).__name__}: {e!r}"
                )
                await self._publish_visual(
                    "alert",
                    task_id=task_id,
                )
                return (
                    "An anomaly occurred within my core processing.",
                    [],
                )

            if hasattr(response, "message"):
                msg_obj = response.message
                message = {
                    "role": getattr(
                        msg_obj,
                        "role",
                        "assistant",
                    ),
                    "content": getattr(
                        msg_obj,
                        "content",
                        "",
                    )
                    or "",
                    "tool_calls": getattr(
                        msg_obj,
                        "tool_calls",
                        [],
                    )
                    or [],
                }
            else:
                message = response.get(
                    "message",
                    {},
                )

            content_text = message.get(
                "content",
                "",
            ) or ""

            tool_calls = list(
                message.get(
                    "tool_calls",
                    [],
                )
                or []
            )

        # A prose answer cannot execute a physical request. Retry planning once,
        # retaining context and the same validation/execution path.
        if (
            not tool_calls
            and "<tool_call>" not in content_text
            and contains_physical_action_request(prompt)
        ):
            print(f"[PLAN RETRY] [task={task_id}]: model returned no tool calls.")
            retry_messages = [
                *self.history,
                {
                    "role": "user",
                    "content": (
                        "For my latest request, return the necessary tool calls "
                        "using the provided tools. Nothing has executed yet. "
                        "Do not claim success or invent missing targets. If the "
                        "request is ambiguous or unsupported, ask for clarification."
                    ),
                },
            ]
            try:
                retry = await self.ollama.chat(
                    model=MODEL_NAME, messages=retry_messages, tools=TOOLS,
                    options={"num_predict": 256, "temperature": 0},
                )
                retry_msg = getattr(retry, "message", None)
                if retry_msg is None:
                    retry_msg = retry.get("message", {})
                if isinstance(retry_msg, dict):
                    message = dict(retry_msg)
                else:
                    message = {
                        "role": getattr(retry_msg, "role", "assistant"),
                        "content": getattr(retry_msg, "content", "") or "",
                        "tool_calls": getattr(retry_msg, "tool_calls", []) or [],
                    }
                content_text = message.get("content", "") or ""
                tool_calls = list(message.get("tool_calls", []) or [])
            except Exception as exc:
                print(f"[PLAN RETRY ERROR]: {type(exc).__name__}: {exc!r}")

        if "<tool_call>" in content_text:
            matches = re.findall(
                r"<tool_call>\s*(.*?)\s*</tool_call>",
                content_text,
                re.DOTALL,
            )

            for match in matches:
                try:
                    parsed = json.loads(
                        match.strip()
                    )
                    tool_calls.append(
                        {
                            "function": {
                                "name": parsed.get("name"),
                                "arguments": parsed.get(
                                    "arguments",
                                    {},
                                ),
                            }
                        }
                    )
                except Exception as exc:
                    print(
                        f"[TOOL PARSE ERROR]: "
                        f"{type(exc).__name__}: {exc!r}"
                    )

            content_text = re.sub(
                r"<tool_call>.*?</tool_call>",
                "",
                content_text,
                flags=re.DOTALL,
            ).strip()

            message["content"] = content_text

        if tool_calls:
            normalized_calls, clarification = normalize_tool_calls(
                prompt,
                tool_calls,
            )

            if clarification:
                self.last_plan_error = clarification
                return clarification, []

            tool_calls = normalized_calls
            if not replay_calls:
                grounding_error = validate_application_targets(prompt, tool_calls)
                if grounding_error:
                    self.last_plan_error = grounding_error
                    print(f"[PLAN REJECTED] [task={task_id}]: {grounding_error}")
                    return grounding_error, []
            message["tool_calls"] = tool_calls

            replay_plan = build_replay_plan(tool_calls)
            if replay_plan:
                self.last_replay_plan = replay_plan

        if not tool_calls and contains_physical_action_request(prompt):
            self.last_plan_error = "No validated execution plan was produced."
            # Do not ask a tools-disabled synthesis pass to invent an outcome.
            reply = (
                content_text if content_text and not contains_execution_claim(content_text)
                else "I could not produce a validated execution plan. Please restate the action and its target."
            )
            self.history.append({"role": "assistant", "content": reply})
            if len(self.history) > 11:
                self.history = [self.history[0], *self.history[-10:]]
            return reply, []

        pending_actions: list[PendingAction] = []

        if tool_calls:
            self.history.append(message)

            for tool in tool_calls:
                if isinstance(tool, dict):
                    function = tool.get(
                        "function",
                        {},
                    ) or {}
                    func_name = function.get("name")
                    args = function.get(
                        "arguments",
                        {},
                    )
                else:
                    function = getattr(
                        tool,
                        "function",
                        None,
                    )
                    func_name = getattr(
                        function,
                        "name",
                        None,
                    )
                    args = getattr(
                        function,
                        "arguments",
                        {},
                    )

                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                args = dict(args or {})

                print(
                    f"[BRAIN EXECUTING TOOL]: "
                    f"{func_name}({args})"
                )

                if func_name == "get_system_telemetry":
                    cpu = psutil.cpu_percent(interval=0.1)
                    ram = psutil.virtual_memory().percent
                    battery = psutil.sensors_battery()
                    bat_str = (
                        f"{battery.percent}%"
                        if battery
                        else "AC Power"
                    )
                    res = (
                        f"System Metrics: CPU at {cpu}%, "
                        f"RAM at {ram}%, Power Source: {bat_str}."
                    )

                elif func_name == "run_python_script":
                    raw_path = str(
                        args.get(
                            "script_path",
                            "",
                        )
                    ).strip()
                    extra_args = str(
                        args.get(
                            "args",
                            "",
                        )
                    ).strip()

                    actual_file = resolve_script_filename(
                        raw_path
                    )

                    if actual_file and os.path.exists(
                        actual_file
                    ):
                        cmd = (
                            f"py .\\\\{actual_file} "
                            f"{extra_args}"
                        ).strip()

                        pending_actions.append(
                            PendingAction(
                                name=(
                                    "run_python_script:"
                                    f"{actual_file}"
                                ),
                                execute=lambda c=cmd: subprocess.Popen(
                                    c,
                                    shell=True,
                                ),
                                completion="wait",
                            )
                        )

                        res = (
                            f"Executing script '{actual_file}'."
                        )

                    else:
                        res = (
                            f"Script '{raw_path}' could not be resolved "
                            "to any file in project directory."
                        )

                elif func_name == "control_media":
                    action = args.get("action")

                    key_map = {
                        "volume_up": "volume up",
                        "volume_down": "volume down",
                        "mute": "volume mute",
                        "play_pause": "play/pause media",
                    }

                    target_key = key_map.get(
                        action
                    )

                    if target_key:
                        pending_actions.append(
                            PendingAction(
                                name=(
                                    "control_media:"
                                    f"{action}"
                                ),
                                execute=lambda k=target_key: keyboard.send(k),
                            )
                        )
                        res = (
                            f"Media action '{action}' staged."
                        )
                    else:
                        res = (
                            f"Unknown action '{action}'."
                        )

                elif func_name == "open_application":
                    app_name = str(
                        args.get(
                            "app_name",
                            "",
                        )
                    ).strip()

                    if not app_name:
                        res = "No application name was provided."
                    else:
                        async def open_app(
                            target_app: str = app_name,
                        ) -> Any:
                            return await self.capabilities.open_resource(
                                target_app,
                                task_id=task_id,
                                verify=True,
                            )

                        pending_actions.append(
                            PendingAction(
                                name=(
                                    "open_application:"
                                    f"{app_name}"
                                ),
                                execute=open_app,
                                completion="dispatch",
                            )
                        )

                        res = (
                            f"Application '{app_name}' "
                            "staged through the capability broker."
                        )

                elif func_name == "open_website":
                    raw_target = str(
                        args.get(
                            "target",
                            "",
                        )
                    ).strip()
                    target = raw_target.lower()
                    search_query = str(
                        args.get(
                            "query",
                            "",
                        )
                    ).strip()

                    try:
                        count = int(
                            args.get(
                                "count",
                                1,
                            )
                        )
                        count = max(
                            1,
                            min(count, 15),
                        )
                    except (
                        ValueError,
                        TypeError,
                    ):
                        count = 1

                    if not raw_target:
                        res = (
                            "No website target was provided."
                        )
                    else:
                        site_search_templates = {
                            "youtube": (
                                "https://www.youtube.com/"
                                "results?search_query={}"
                            ),
                            "google": (
                                "https://www.google.com/"
                                "search?q={}"
                            ),
                            "github": (
                                "https://github.com/"
                                "search?q={}"
                            ),
                            "reddit": (
                                "https://www.reddit.com/"
                                "search/?q={}"
                            ),
                            "bing": (
                                "https://www.bing.com/"
                                "search?q={}"
                            ),
                            "duckduckgo": (
                                "https://duckduckgo.com/"
                                "?q={}"
                            ),
                        }

                        normalized_domain = (
                            target
                            .replace(
                                "https://",
                                "",
                            )
                            .replace(
                                "http://",
                                "",
                            )
                            .removeprefix(
                                "www."
                            )
                            .rstrip("/")
                        )

                        site_key = (
                            normalized_domain
                            if normalized_domain
                            in site_search_templates
                            else target
                        )

                        template = site_search_templates.get(
                            site_key
                        )

                        if search_query and template:
                            url = template.format(
                                urllib.parse.quote_plus(
                                    search_query
                                )
                            )
                        elif (
                            search_query
                            and "."
                            in raw_target
                            and " "
                            not in raw_target
                        ):
                            url = (
                                "https://www.google.com/"
                                "search?q="
                                + urllib.parse.quote_plus(
                                    f"site:{normalized_domain} "
                                    f"{search_query}"
                                )
                            )
                        elif target in SITE_MAP:
                            url = SITE_MAP[target]
                        elif target.startswith(
                            (
                                "http://",
                                "https://",
                            )
                        ):
                            url = raw_target
                        elif (
                            "."
                            in raw_target
                            and " "
                            not in raw_target
                        ):
                            url = (
                                f"https://{raw_target}"
                            )
                        else:
                            encoded_query = urllib.parse.quote(
                                raw_target,
                                safe="",
                            )
                            url = (
                                "https://www.google.com/"
                                "search?q="
                                f"{encoded_query}"
                            )

                        for _ in range(count):
                            async def open_web(
                                target_url: str = url,
                            ) -> Any:
                                return await self.capabilities.open_resource(
                                    target_url,
                                    task_id=task_id,
                                    verify=False,
                                )

                            pending_actions.append(
                                PendingAction(
                                    name=(
                                        "open_website:"
                                        f"{url}"
                                    ),
                                    execute=open_web,
                                    completion="dispatch",
                                )
                            )

                        if search_query:
                            res = (
                                f"Website search navigation to "
                                f"'{url}' staged ({count} time(s))."
                            )
                        else:
                            res = (
                                f"Website destination '{url}' staged "
                                f"({count} time(s))."
                            )

                elif func_name == "activate_protocol":
                    protocol = args.get("protocol")

                    if protocol == "dev_mode":
                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:dev_mode:ide",
                                execute=lambda: subprocess.Popen(
                                    "code",
                                    shell=True,
                                ),
                            )
                        )

                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:dev_mode:terminal",
                                execute=lambda: subprocess.Popen(
                                    "start wt",
                                    shell=True,
                                ),
                            )
                        )

                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:dev_mode:github",
                                execute=lambda: webbrowser.open(
                                    "https://github.com"
                                ),
                            )
                        )

                        res = (
                            "Dev protocol initiated. IDE, terminal, "
                            "and repository staged."
                        )

                    elif protocol == "stealth_mode":
                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:stealth_mode:mute",
                                execute=lambda: keyboard.send(
                                    "volume mute"
                                ),
                            )
                        )

                        pending_actions.append(
                            PendingAction(
                                name="activate_protocol:stealth_mode:chrome",
                                execute=lambda: subprocess.Popen(
                                    "taskkill /F /IM chrome.exe",
                                    shell=True,
                                ),
                            )
                        )

                        res = (
                            "Stealth protocol active. Audio muted and "
                            "browser instances terminated."
                        )

                    else:
                        res = (
                            f"Protocol '{protocol}' acknowledged."
                        )

                elif func_name == "terminate_process":
                    proc = (
                        str(
                            args.get(
                                "process_name",
                                "",
                            )
                        )
                        .lower()
                        .replace(
                            ".exe",
                            "",
                        )
                        .strip()
                    )

                    cmd = (
                        f"taskkill /F /IM {proc}.exe"
                    )

                    pending_actions.append(
                        PendingAction(
                            name=(
                                "terminate_process:"
                                f"{proc}"
                            ),
                            execute=lambda c=cmd: subprocess.Popen(
                                c,
                                shell=True,
                            ),
                        )
                    )

                    res = (
                        f"Termination signal dispatched for "
                        f"process '{proc}'."
                    )

                elif func_name == "manage_clipboard":
                    if pyperclip is None:
                        res = (
                            "Clipboard module unavailable. Install using "
                            "'pip install pyperclip'."
                        )
                    else:
                        action = args.get("action")

                        if action == "read":
                            clip_text = pyperclip.paste()
                            res = (
                                "Clipboard contents captured: "
                                f"'{clip_text[:120]}...'"
                            )

                        elif action == "write":
                            pyperclip.copy(
                                args.get(
                                    "content",
                                    "",
                                )
                            )
                            res = (
                                "New text successfully written to "
                                "system clipboard."
                            )

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
                        res = "Workstation lock staged."

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
                        res = "System sleep staged."

                    else:
                        res = (
                            f"Power action '{cmd_type}' "
                            "is not implemented."
                        )

                elif func_name == "organize_folder":
                    target_dir = str(
                        args.get(
                            "target_folder",
                            "",
                        )
                    ).strip()

                    if target_dir:
                        resolved_dir = os.path.expanduser(
                            target_dir
                        )
                    else:
                        resolved_dir = os.path.expanduser(
                            "~/Downloads"
                        )

                    def sanitize(
                        folder: str = resolved_dir,
                    ) -> Any:
                        categories = {
                            "Images": [
                                ".png",
                                ".jpg",
                                ".jpeg",
                                ".svg",
                            ],
                            "Documents": [
                                ".pdf",
                                ".docx",
                                ".txt",
                                ".csv",
                            ],
                            "Software": [
                                ".exe",
                                ".msi",
                            ],
                        }

                        for file in os.listdir(folder):
                            ext = os.path.splitext(
                                file
                            )[1].lower()

                            for cat, exts in categories.items():
                                if ext in exts:
                                    cat_folder = os.path.join(
                                        folder,
                                        cat,
                                    )

                                    os.makedirs(
                                        cat_folder,
                                        exist_ok=True,
                                    )

                                    try:
                                        shutil.move(
                                            os.path.join(
                                                folder,
                                                file,
                                            ),
                                            os.path.join(
                                                cat_folder,
                                                file,
                                            ),
                                        )
                                    except Exception:
                                        pass

                    pending_actions.append(
                        PendingAction(
                            name=(
                                "organize_folder:"
                                f"{resolved_dir}"
                            ),
                            execute=sanitize,
                            completion="wait",
                        )
                    )

                    res = (
                        f"Folder organization for "
                        f"'{resolved_dir}' staged."
                    )

                elif func_name == "live_web_search":
                    if DDGS is None:
                        res = (
                            "Search module unavailable. Install using "
                            "'pip install duckduckgo_search'."
                        )
                    else:
                        query = str(
                            args.get(
                                "query",
                                "",
                            )
                        ).strip()

                        try:
                            with DDGS() as ddgs:
                                search_results = [
                                    r["body"]
                                    for r in ddgs.text(
                                        query,
                                        max_results=2,
                                    )
                                ]

                            res = (
                                "Live Search Results: "
                                + " ".join(
                                    search_results
                                )
                            )
                        except Exception as e:
                            res = (
                                f"Web search encountered an error: "
                                f"{e}"
                            )

                elif func_name == "query_knowledge_base":
                    query_text = str(
                        args.get(
                            "query",
                            "",
                        )
                    ).strip()

                    try:
                        import chromadb
                        from ollama import Client as SyncOllamaClient

                        chroma_client = (
                            chromadb.PersistentClient(
                                path="./chroma_db"
                            )
                        )

                        collection = (
                            chroma_client.get_or_create_collection(
                                name="ultron_knowledge"
                            )
                        )

                        ollama_sync = SyncOllamaClient()

                        emb_res = ollama_sync.embed(
                            model="nomic-embed-text",
                            input=query_text,
                        )

                        query_emb = emb_res[
                            "embeddings"
                        ][0]

                        results = collection.query(
                            query_embeddings=[
                                query_emb
                            ],
                            n_results=3,
                        )

                        matched_docs = results.get(
                            "documents",
                            [[]],
                        )[0]

                        if matched_docs:
                            res = (
                                "Knowledge Base Content:\n"
                                + "\n---\n".join(
                                    matched_docs
                                )
                            )
                        else:
                            res = (
                                "No matching documents found "
                                "in knowledge base."
                            )

                    except Exception as e:
                        res = (
                            f"Knowledge base search error: "
                            f"{e}"
                        )

                else:
                    res = "Tool unavailable."

                print(
                    f"[TOOL RESULT]: {res}"
                )

                self.history.append(
                    {
                        "role": "tool",
                        "content": res,
                    }
                )

        # For physical actions the final response is deliberately deferred
        # to the authoritative execution ledger in main().
        if not pending_actions:
            try:
                final_response = await self.ollama.chat(
                    model=MODEL_NAME,
                    messages=self.history,
                    options={
                        "num_predict": 160,
                        "temperature": 0.2,
                    },
                )

                if hasattr(
                    final_response,
                    "message",
                ):
                    final_text = (
                        getattr(
                            final_response.message,
                            "content",
                            "",
                        )
                        or ""
                    )
                else:
                    final_text = (
                        final_response.get(
                            "message",
                            {},
                        ).get(
                            "content",
                            "",
                        )
                    )

            except Exception as e:
                print(
                    "[BRAIN ERROR]: Synthesis pass failed: "
                    f"{type(e).__name__}: {e!r}"
                )

                final_text = (
                    content_text
                    or "The requested information was processed."
                )
        else:
            final_text = (
                content_text
                or "The requested actions have been staged for execution."
            )

        self.history.append(
            {
                "role": "assistant",
                "content": final_text,
            }
        )

        if len(self.history) > 11:
            self.history = (
                [self.history[0]]
                + self.history[-10:]
            )

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



    # Ollama is a required dependency for intent processing.

    # Do not accept intents until the endpoint and configured model are healthy.

    await brain.ollama.wait_until_ready()



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

                log_chat("user", prompt)

                # Status and courtesy messages must never be handed to the LLM
                # as fresh physical-action decisions. These are deterministic
                # conversational paths.
                if is_task_status_request(prompt):
                    await brain._publish_visual("thinking", task_id=task_id)
                    reply_text = brain._compose_latest_task_status()
                    pending_actions = []
                    action_ok = True
                    action_error = None

                elif is_conversational_only(prompt):
                    await brain._publish_visual("thinking", task_id=task_id)
                    conversational_text = re.sub(r"[^a-z0-9']+", " ", prompt.lower()).strip()
                    if conversational_text in {"do you hear me", "can you hear me", "are you listening"}:
                        reply_text = "Yes, I received your message. I'm listening."
                    elif conversational_text in {"yes", "yes please", "yeah", "yep", "sure"}:
                        reply_text = "Understood. Please state the action you want me to perform."
                    else:
                        reply_text = "Understood. I'm ready for your next command."
                    pending_actions = []
                    action_ok = True
                    action_error = None

                else:
                    reply_text, pending_actions = await brain.process_intent(
                        prompt,
                        task_id,
                    )

                    # -------------------------------------------------
                    # PHYSICAL ACTION EXECUTION
                    # -------------------------------------------------

                    action_ok, action_error = await brain._run_pending_actions(
                        pending_actions,
                        task_id,
                    )
                    if brain.last_plan_error:
                        action_ok = False
                        action_error = brain.last_plan_error

                if pending_actions:
                    # The execution ledger, not the model's planning text, is
                    # authoritative for physical action claims.
                    reply_text = brain._compose_execution_response(
                        task_id
                    )

                    if not action_ok and action_error:
                        print(
                            f"[EXECUTION SUMMARY ERROR] "
                            f"[task={task_id}]: {action_error}"
                        )

                                # Never allow an LLM-generated response to claim physical
                # execution when the execution layer has no evidence.
                execution_evidence = brain.execution_ledger.get(task_id) or []

                if (
                    not execution_evidence
                    and contains_physical_action_request(prompt)
                    and contains_execution_claim(reply_text)
                    and not is_task_status_request(prompt)
                ):
                    print(
                        f"[EXECUTION TRUTH GUARD] "
                        f"[task={task_id}]: blocked unsupported execution claim."
                    )
                    reply_text = (
                        "I did not execute that action because no validated "
                        "execution plan was produced."
                    )
                    action_ok = False
                    action_error = "No validated execution evidence."

                print(
                    f"[ULTRON BRAIN RESPONSE] "
                    f"[task={task_id}]: '{reply_text}'"
                )

                log_chat("assistant", reply_text)

                if not is_task_status_request(prompt) and not is_conversational_only(prompt):
                    final_status = "completed" if action_ok else "failed"
                    update_task(
                        task_id,
                        final_status,
                        result_text=reply_text,
                        error_text=action_error,
                        execution=brain.execution_ledger.get(task_id),
                        event_message=(
                            "Task completed successfully."
                            if action_ok
                            else "Task completed with execution failures."
                        ),
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
                # TASK COMPLETE / TERMINAL VISUAL STATE
                # -------------------------------------------------

                if action_ok:
                    await brain._publish_visual(
                        "idle",
                        task_id=task_id,
                    )
                else:
                    await brain._publish_visual(
                        "alert",
                        task_id=task_id,
                    )

                    # Keep ALERT visibly present before returning
                    # to the neutral idle state.
                    await asyncio.sleep(0.75)

                    await brain._publish_visual(
                        "idle",
                        task_id=task_id,
                    )

            except Exception as e:
                print(
                    f"[INTENT HANDLING ERROR] "
                    f"[task={task_id}]: {e}"
                )

                try:
                    update_task(
                        task_id,
                        "failed",
                        error_text=str(e),
                        event_message="Task handling raised an unexpected error.",
                    )
                except Exception as memory_error:
                    print(
                        f"[TASK MEMORY ERROR] [task={task_id}]: {memory_error}"
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
