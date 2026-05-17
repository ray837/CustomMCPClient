""" ╔══════════════════════════════════════════════════════════════════╗ ║          Ultra-Advanced MCP Client  —  Claude-Code Style         ║ ╠══════════════════════════════════════════════════════════════════╣ ║  MCP Primitives                                                  ║ ║    ● Tools        agentic loop · parallel execution · registry   ║ ║    ● Resources    list · read · templates · live subscribe       ║ ║    ● Prompts      list · expand args · inject into conversation  ║ ║    ● Elicitation  server-driven structured user-input            ║ ║    ● Sampling     server-initiated LLM completions               ║ ║    ● Logging      rich server log display                        ║ ║    ● Progress     live progress from server notifications        ║ ║    ● Roots        expose local filesystem paths to servers       ║ ╠══════════════════════════════════════════════════════════════════╣ ║  Slash Commands                                                   ║ ║    /help  /tools  /resources  /read <uri>  /prompts              ║ ║    /prompt <name> [key=val]  /servers  /history  /clear          ║ ║    /roots  /roots add <path>  /stream  /export                   ║ ╚══════════════════════════════════════════════════════════════════╝ """

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import textwrap
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
# Notification types for real-time server push display
try:
    from mcp.types import LoggingMessageNotification, ProgressNotification
    HAS_NOTIFICATION_TYPES = True
except ImportError:
    HAS_NOTIFICATION_TYPES = False
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ── Optional MCP type imports (version-safe) ─────────────────────────────────
try:
    from mcp.types import CreateMessageResult, TextContent
    HAS_SAMPLING = True
except ImportError:
    HAS_SAMPLING = False

try:
    from mcp.types import ElicitResult
    HAS_ELICITATION = True
except ImportError:
    HAS_ELICITATION = False

load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# RICH CONSOLE  &  THEME
# ══════════════════════════════════════════════════════════════════════════════

THEME = Theme({
    "info":      "bold cyan",
    "success":   "bold green",
    "warn":      "bold yellow",
    "error":     "bold red",
    "tool":      "bold magenta",
    "resource":  "bold blue",
    "prompt_h":  "bold cyan",
    "server":    "bold white",
    "dim":       "dim white",
    "user_c":    "bold green",
    "asst":      "bold cyan",
    "cmd":       "bold yellow",
    "elicit":    "bold bright_cyan",
    "sample":    "bold bright_magenta",
    "log_dbg":   "dim",
    "log_info":  "cyan",
    "log_warn":  "yellow",
    "log_err":   "red",
})
console = Console(theme=THEME, highlight=False)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
MODEL_NAME      = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")
MAX_TOKENS      = int(os.getenv("MAX_TOKENS", "4096"))
MAX_TOOL_ROUNDS    = int(os.getenv("MAX_TOOL_ROUNDS", "10"))
MAX_HISTORY_TURNS  = int(os.getenv("MAX_HISTORY_TURNS", "10"))
MAX_TOOL_RESULT_CH = int(os.getenv("MAX_TOOL_RESULT_CHARS", "2000"))
MAX_DESC_CHARS     = int(os.getenv("MAX_DESC_CHARS", "120"))
SSL_VERIFY         = os.getenv("SSL_VERIFY", "true").lower() != "false"
CONFIRM_TOOLS      = os.getenv("CONFIRM_TOOLS", "sensitive")   # always | sensitive | never
TOOL_TIMEOUT       = int(os.getenv("TOOL_TIMEOUT", "30"))       # seconds per tool call
AUTO_LOAD_HISTORY  = os.getenv("AUTO_LOAD_HISTORY", "true").lower() == "true"
HISTORY_FILE       = Path(os.getenv("HISTORY_FILE",
                         str(Path.home() / ".mcp_client" / "history.json")))
SENSITIVE_PATTERNS = [p.strip().lower() for p in os.getenv(
    "SENSITIVE_PATTERNS",
    "disburse,foreclose,delete,remove,drop,grant_waiver,process_payment,"
    "process_foreclosure,mark_loan,reset,wipe,purge,close_loan"
).split(",") if p.strip()]
SYSTEM_PROMPT   = os.getenv("SYSTEM_PROMPT", (
    "You are a highly capable AI assistant with access to tools, resources, and "
    "prompt templates from connected MCP servers. Think step by step. "
    "Use tools whenever they would help the user. Be concise but thorough."
))

log = logging.getLogger("mcp-adv")
logging.basicConfig(level=logging.WARNING)

# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ServerInfo:
    name:               str
    path:               str
    session:            Any                    # ClientSession
    tools:              list = field(default_factory=list)
    resources:          list = field(default_factory=list)
    resource_templates: list = field(default_factory=list)
    prompts:            list = field(default_factory=list)
    log_buffer:         list = field(default_factory=list)


@dataclass
class Turn:
    role:         str
    content:      str
    ts:           datetime      = field(default_factory=datetime.now)
    tool_calls:   list          = field(default_factory=list)
    tool_call_id: str | None    = None   # set for role='tool' turns


# ══════════════════════════════════════════════════════════════════════════════
# MCP CALLBACK HANDLERS  (Sampling · Elicitation · Logging · Progress)
# ══════════════════════════════════════════════════════════════════════════════

class MCPCallbacks:
    """ Implements the client-side half of MCP's server-to-client protocols.  Sampling   — server asks client to run an LLM completion Elicitation— server asks client to collect structured input from user Logging    — server sends log messages to client Progress   — server reports incremental progress """

    def __init__(self, get_openai, server_name: str):
        self._get_openai = get_openai
        self.server_name = server_name

    # ── Sampling ─────────────────────────────────────────────────────────────
    async def handle_sampling(self, ctx, request) -> Any:
        """ Server → Client: 'please run this LLM prompt for me'. We fulfil it using our configured endpoint (Groq / any OpenAI-compat). """
        console.print(f" [sample]⚡ Sampling request from '{self.server_name}'...[/sample]")
        try:
            params = getattr(request, "params", request)
            sys_p  = getattr(params, "systemPrompt", None)
            msgs   = getattr(params, "messages", [])
            max_t  = min(getattr(params, "maxTokens", 1024), MAX_TOKENS)

            oai_msgs: list[dict] = []
            if sys_p:
                oai_msgs.append({"role": "system", "content": sys_p})
            for m in msgs:
                role    = getattr(m, "role", "user")
                content = getattr(m, "content", m)
                text    = getattr(content, "text", str(content))
                oai_msgs.append({"role": role, "content": text})

            resp = await self._get_openai().chat.completions.create(
                model=MODEL_NAME, max_tokens=max_t, messages=oai_msgs,
            )
            text = resp.choices[0].message.content or ""
            console.print(f"[dim]  ↳ Sampling done — {len(text)} chars[/dim]")

            if HAS_SAMPLING:
                return CreateMessageResult(
                    role="assistant",
                    content=TextContent(type="text", text=text),
                    model=MODEL_NAME,
                    stopReason="end_turn",
                )
            return {"role": "assistant", "content": {"type": "text", "text": text}}

        except Exception as exc:
            log.error("Sampling error: %s", exc)
            raise

    # ── Elicitation ───────────────────────────────────────────────────────────
    async def handle_elicitation(self, ctx, request) -> Any:
        """ Server → Client: 'please collect structured input from the user'. Renders a mini-form in the terminal; returns the filled data. """
        console.print()
        console.print(Panel(
            "[bold]An MCP server needs structured input from you.[/bold]",
            title=f"[elicit]⚡ Elicitation  —  {self.server_name}[/elicit]",
            border_style="bright_cyan",
        ))
        try:
            params     = getattr(request, "params", request)
            message    = getattr(params, "message", "Please provide the requested information:")
            schema     = getattr(params, "requestedSchema", {})
            schema_d   = schema if isinstance(schema, dict) else {}
            properties = schema_d.get("properties", {})
            required   = schema_d.get("required", [])

            console.print(f"[elicit]{message}[/elicit] ")
            collected: dict[str, Any] = {}

            for fname, fdef in properties.items():
                ftype = fdef.get("type", "string")
                desc  = fdef.get("description", fname)
                req   = fname in required
                label = f"[bold]{fname}[/bold][dim]({'required' if req else 'optional'})[/dim]: {desc}"
                console.print(f"  {label}")

                try:
                    if ftype == "boolean":
                        collected[fname] = Confirm.ask(f"  → {fname}")
                    elif ftype in ("integer", "number"):
                        raw = Prompt.ask(f"  → {fname}")
                        collected[fname] = (int if ftype == "integer" else float)(raw)
                    else:
                        val = Prompt.ask(f"  → {fname}", default="")
                        if val or req:
                            collected[fname] = val
                except (ValueError, TypeError):
                    collected[fname] = Prompt.ask(f"  → {fname} (raw)")

            console.print(f"\n[success]✓ Input collected ({len(collected)} fields)[/success] ")

            if HAS_ELICITATION:
                return ElicitResult(action="accept", content=collected)
            return {"action": "accept", "content": collected}

        except (KeyboardInterrupt, EOFError):
            console.print(" [warn]Elicitation cancelled by user[/warn]")
            if HAS_ELICITATION:
                return ElicitResult(action="cancel")
            return {"action": "cancel"}

    # ── Logging ───────────────────────────────────────────────────────────────
    def handle_log(self, params) -> None:
        level = getattr(params, "level", "info").lower()
        data  = getattr(params, "data", "")
        logger= getattr(params, "logger", "")
        style_map = {
            "debug":     "log_dbg",
            "info":      "log_info",
            "notice":    "log_info",
            "warning":   "log_warn",
            "error":     "log_err",
            "critical":  "log_err",
            "alert":     "log_err",
            "emergency": "log_err",
        }
        s = style_map.get(level, "log_info")
        tag = f"[{s}][{self.server_name}:{level.upper()}][/{s}]"
        logger_tag = f" [dim]{logger}[/dim]" if logger else ""
        console.print(f"{tag}{logger_tag} {data}")

    # ── Progress ──────────────────────────────────────────────────────────────
    def handle_progress(self, params) -> None:
        token    = getattr(params, "progressToken", "?")
        progress = getattr(params, "progress", 0)
        total    = getattr(params, "total", None)
        if total and total > 0:
            pct  = int((progress / total) * 100)
            done = pct // 5
            bar  = "█" * done + "░" * (20 - done)
            console.print(f"[dim]  [{bar}] {pct}%  (token:{token})[/dim]")
        else:
            console.print(f"[dim]  ↳ progress {progress}  (token:{token})[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
# MCP → OPENAI SCHEMA CONVERSION
# ══════════════════════════════════════════════════════════════════════════════

def _slim_schema(schema: dict) -> dict:
    """Strip verbose param descriptions to save tokens."""
    if not isinstance(schema, dict):
        return schema
    slim = {}
    for k, v in schema.items():
        if k in ("$schema", "additionalProperties", "examples", "default"):
            continue
        if k == "properties" and isinstance(v, dict):
            slim["properties"] = {
                pname: {
                    pk: (pv[:80] if isinstance(pv, str) and pk == "description" else pv)
                    for pk, pv in pdef.items()
                    if pk in ("type", "description", "enum", "minimum", "maximum")
                }
                for pname, pdef in v.items()
            }
        else:
            slim[k] = v
    return slim


def mcp_tool_to_openai(tool) -> dict:
    schema = tool.inputSchema or {"type": "object", "properties": {}}
    # First line of description only, capped — saves ~60% of schema tokens
    desc = (tool.description or "").split(" ")[0][:MAX_DESC_CHARS]
    return {
        "type": "function",
        "function": {
            "name":        tool.name,
            "description": desc,
            "parameters":  _slim_schema(schema),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CLIENT
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# REAL-TIME NOTIFICATION SESSION
# ══════════════════════════════════════════════════════════════════════════════

# ── Shared notification renderer (used by both callback and session override) ──

NOTIF_ICONS  = {"debug": "·", "info": "ℹ", "notice": "●",
                "warning": "⚠", "error": "✗", "critical": "✗✗"}
NOTIF_STYLES = {"debug": "dim", "info": "cyan", "notice": "blue",
                "warning": "yellow", "error": "red", "critical": "bold red"}


def _render_log(srv_name: str, level: str, data: str, logger: str = "") -> None:
    """ Write a server log line immediately to stdout (no Rich buffering). Called only once per notification via logging_callback. """
    import sys
    level  = (level or "info").lower()
    icon   = NOTIF_ICONS.get(level, "·")
    # Guard: logger may arrive as Python None, not missing
    src    = f"[{logger}] " if logger and logger not in ("None", "none") else ""
    sys.stdout.write("  " + icon + " [" + srv_name + "] " + src + data + "\n")
    sys.stdout.flush()


def _render_progress(progress: int, total: int | None) -> None:
    if total and total > 0:
        pct  = int((progress / total) * 100)
        done = pct // 5
        bar  = "█" * done + "░" * (20 - done)
        import sys
        sys.stdout.write(f"  [{bar}] {pct:3d}%  {progress}/{total}\n")
        sys.stdout.flush()


class NotifyingClientSession(ClientSession):
    """ Subclass of ClientSession that shows server notifications in real-time.  Three-layer interception strategy (most → least reliable): 1. logging_callback  — official SDK param, catches ctx.info/warning/error 2. _received_notification override — catches progress + other notifications 3. post-init monkey-patch — belt-and-suspenders fallback """

    def __init__(self, *args, srv_console: Console, srv_name: str = "server", **kwargs):
        self._srv_name    = srv_name
        self._srv_console = srv_console

        # ── Layer 1: inject logging_callback into SDK-supported param ─────────
        # The MCP SDK calls this for every notifications/message the server sends.
        def _log_cb(params):
            level  = str(getattr(params, "level", "info"))
            data   = str(getattr(params, "data", ""))
            logger = str(getattr(params, "logger", ""))
            _render_log(srv_name, level, data, logger)

        # Accept sync or async callback (SDK version varies)
        async def _async_log_cb(params):
            _log_cb(params)

        kwargs.setdefault("logging_callback", _async_log_cb)
        super().__init__(*args, **kwargs)

    # ── Layer 2: _received_notification — progress ONLY (logs go via callback) ──
    async def _received_notification(self, notification) -> None:
        """ Handles progress bars and resource-change notices. Log messages are intentionally SKIPPED here — logging_callback already handles them. Handling both causes triple-printing. """
        await super()._received_notification(notification)
        try:
            actual = getattr(notification, "root", notification)
            ntype  = type(actual).__name__

            # ⚠ Do NOT handle LoggingMessage here — logging_callback owns it
            if "LoggingMessage" in ntype:
                return

            if "Progress" in ntype:
                params   = actual.params
                progress = getattr(params, "progress", 0)
                total    = getattr(params, "total", None)
                _render_progress(progress, total)

            elif "ResourceUpdated" in ntype:
                uri = getattr(getattr(actual, "params", None), "uri", "?")
                import sys
                sys.stdout.write("  Resource updated: " + str(uri) + "\n")
                sys.stdout.flush()

        except Exception:
            pass

class AdvancedMCPClient:
    """ Ultra-advanced MCP client supporting all eight MCP primitives, multi-server connections, a full agentic tool loop, and a rich slash-command REPL — modelled after Claude Code. """

    def __init__(self):
        self.exit_stack   = AsyncExitStack()
        self._servers:    dict[str, ServerInfo] = {}
        self._tool_map:   dict[str, ServerInfo] = {}   # tool_name → server
        self._oai_tools:  list[dict]            = []   # merged openai schemas
        self._history:    list[Turn]            = []   # conversation turns
        self._roots:      list[str]             = []   # filesystem roots
        self._streaming       = False
        self._openai: AsyncOpenAI | None = None
        self._model: str                 = MODEL_NAME
        self._confirm_mode: str          = CONFIRM_TOOLS
        self._tool_timeout: int          = TOOL_TIMEOUT
        self._cancelled: bool            = False   # set True by Ctrl+C mid-tool

    # ── OpenAI client ─────────────────────────────────────────────────────────
    def _get_openai(self) -> AsyncOpenAI:
        if self._openai is None:
            kwargs: dict = dict(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
            if not SSL_VERIFY:
                kwargs["http_client"] = httpx.AsyncClient(verify=False)
            self._openai = AsyncOpenAI(**kwargs)
        return self._openai

    # ── Rate-limit aware LLM call ─────────────────────────────────────────────
    async def _llm_call(self, **kwargs) -> Any:
        """ Wraps chat.completions.create with 429 handling: - Extracts wait time from Groq error message - Auto-retries TPM (per-minute) limit after short wait - For TPD (daily limit): shows model-switch instructions and raises """
        import re as _re, openai as _oai
        for attempt in range(3):
            try:
                return await self._get_openai().chat.completions.create(**kwargs)
            except _oai.RateLimitError as exc:
                err_msg  = str(exc)
                m        = _re.search(r"try again in ([0-9hms. ]+)", err_msg)
                wait_str = m.group(1).strip() if m else "a while"
                secs     = 0
                for num, unit in _re.findall(r"([0-9.]+)([hms])", wait_str):
                    secs += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
                is_daily = "per day" in err_msg or "TPD" in err_msg
                kind     = "TPD — daily quota" if is_daily else "TPM — per-minute"
                console.print(f"[warn]  ⚠  Rate limit ({kind})  |  wait: {wait_str}[/warn]")
                if is_daily:
                    console.print("[warn]Daily token limit exhausted.[/warn] ")
                    console.print("  [cmd]/model mixtral-8x7b-32768[/cmd]    — own 100k TPD")
                    console.print("  [cmd]/model llama-3.1-8b-instant[/cmd]  — own 500k TPD")
                    console.print("  [cmd]/model gemma2-9b-it[/cmd]           — own 100k TPD")
                    console.print(f"  Or wait {wait_str} for reset.")
                    raise
                if attempt < 2 and secs < 120:
                    console.print(f"[dim]  Retrying in {int(secs)+1}s (attempt {attempt+1}/2)...[/dim]")
                    await asyncio.sleep(secs + 1)
                else:
                    raise
            except Exception as exc:
                if hasattr(exc, "status_code") and getattr(exc, "status_code", 0) == 413:
                    console.print("[error]Request too large — lower MAX_TOKENS or MAX_HISTORY_TURNS in .env[/error]")
                raise
        raise RuntimeError("Max LLM retries exceeded")


    # ── Server connection ─────────────────────────────────────────────────────
    async def connect_server(self, script_path: str) -> None:
        is_http = script_path.startswith(("http://", "https://"))

        if is_http:
            url  = script_path
            name = url.rstrip("/").split("/")[-1] or url.split("/")[2]
        else:
            path = Path(script_path).resolve()
            name = path.stem

        callbacks = MCPCallbacks(self._get_openai, name)
        session_kwargs: dict = {}
        if HAS_SAMPLING:
            session_kwargs["sampling_callback"] = callbacks.handle_sampling
        if HAS_ELICITATION:
            session_kwargs["elicitation_callback"] = callbacks.handle_elicitation

        if is_http:
            # ── HTTP / SSE transport (remote MCP servers) ─────────────────────
            try:
                from mcp.client.streamable_http import streamablehttp_client
                transport = await self.exit_stack.enter_async_context(
                    streamablehttp_client(url)
                )
                stdio, write = transport[0], transport[1]
            except ImportError:
                try:
                    from mcp.client.sse import sse_client
                    transport = await self.exit_stack.enter_async_context(
                        sse_client(url)
                    )
                    stdio, write = transport
                except ImportError:
                    raise RuntimeError(
                        "HTTP MCP transport not available. "
                        "Install: pip install mcp[http]   or   pip install mcp>=1.5"
                    )
        else:
            # ── stdio transport (local server scripts) ────────────────────────
            if path.suffix == ".py":
                params = StdioServerParameters(
                    command="uv",
                    args=["--directory", str(path.parent), "run", path.name],
                )
            elif path.suffix == ".js":
                params = StdioServerParameters(command="node", args=[str(path)])
            else:
                raise ValueError(f"Unsupported server type: {path.suffix}  (.py or .js only)")
            transport = await self.exit_stack.enter_async_context(stdio_client(params))
            stdio, write = transport

        session: ClientSession = await self.exit_stack.enter_async_context(
            NotifyingClientSession(
                stdio, write,
                srv_console=console,   # Rich console for real-time output
                srv_name=name,
                **session_kwargs,
            )
        )
        await session.initialize()

        # Tell the server to send ALL log levels (debug+) to this client.
        # Without this call the server silently drops notifications/message.
        try:
            await session.set_logging_level("debug")
        except Exception:
            pass   # older servers may not support this — ok to ignore

        info = ServerInfo(name=name, path=str(path), session=session)
        self._servers[name] = info

        # ── Discover all primitives ───────────────────────────────────────────

        # Tools
        try:
            resp = await session.list_tools()
            info.tools = resp.tools
            for tool in resp.tools:
                self._tool_map[tool.name] = info
                self._oai_tools.append(mcp_tool_to_openai(tool))
        except Exception as e:
            log.warning("[%s] tools unavailable: %s", name, e)

        # Resources
        try:
            resp = await session.list_resources()
            info.resources = resp.resources
        except Exception as e:
            log.debug("[%s] resources unavailable: %s", name, e)

        # Resource templates
        try:
            resp = await session.list_resource_templates()
            info.resource_templates = resp.resourceTemplates
        except Exception as e:
            log.debug("[%s] resource templates unavailable: %s", name, e)

        # Prompts
        try:
            resp = await session.list_prompts()
            info.prompts = resp.prompts
        except Exception as e:
            log.debug("[%s] prompts unavailable: %s", name, e)

        # Register notification handlers
        self._register_notifications(session, callbacks)

        self._print_server_banner(info)

    async def connect_servers(self, paths: list[str]) -> None:
        """Connect to all servers concurrently."""
        await asyncio.gather(*[self.connect_server(p) for p in paths])
        log.info("All servers connected. Tools: %s", list(self._tool_map.keys()))

    def _register_notifications(self, session: ClientSession, cb: MCPCallbacks) -> None:
        """Wire up server-push notifications (logging, progress, resource changes)."""
        try:
            @session.set_logging_handler
            async def on_log(params):
                cb.handle_log(params)
        except Exception:
            pass
        try:
            @session.set_progress_handler
            async def on_progress(params):
                cb.handle_progress(params)
        except Exception:
            pass

    def _print_server_banner(self, info: ServerInfo) -> None:
        lines = []
        if info.tools:
            lines.append(f"  [tool]Tools[/tool]      {', '.join(t.name for t in info.tools)}")
        if info.resources:
            lines.append(f"  [resource]Resources[/resource]  {len(info.resources)} available")
        if info.resource_templates:
            lines.append(f"  [resource]Templates[/resource]  {len(info.resource_templates)} available")
        if info.prompts:
            lines.append(f"  [prompt_h]Prompts[/prompt_h]    {', '.join(p.name for p in info.prompts)}")
        body = " ".join(lines) if lines else "  [dim](no primitives discovered)[/dim]"
        console.print(Panel(body, title=f"[server]⚡ {info.name}[/server]", border_style="white"))

    # ── Resource helpers ──────────────────────────────────────────────────────

    async def list_all_resources(self) -> list[tuple[str, Any]]:
        out = []
        for srv in self._servers.values():
            for r in srv.resources:
                out.append((srv.name, r))
        return out

    async def read_resource(self, uri: str) -> str:
        """Read a resource by URI — tries all servers until one succeeds."""
        for srv in self._servers.values():
            try:
                result = await srv.session.read_resource(uri)
                parts = []
                for c in result.contents:
                    if hasattr(c, "text"):
                        parts.append(c.text)
                    elif hasattr(c, "blob"):
                        parts.append(f"[binary blob {len(c.blob)} bytes]")
                return " ".join(parts)
            except Exception:
                continue
        raise ValueError(f"No server could read resource: {uri}")

    async def subscribe_resource(self, uri: str) -> None:
        for srv in self._servers.values():
            try:
                await srv.session.subscribe_resource(uri)
                console.print(f"[success]✓ Subscribed to {uri}[/success]")
                return
            except Exception:
                continue
        console.print(f"[warn]No server supports subscription for {uri}[/warn]")

    # ── Prompt helpers ────────────────────────────────────────────────────────

    async def list_all_prompts(self) -> list[tuple[str, Any]]:
        out = []
        for srv in self._servers.values():
            for p in srv.prompts:
                out.append((srv.name, p))
        return out

    async def get_prompt(self, name: str, arguments: dict | None = None) -> str:
        """Expand a prompt template and return its text."""
        for srv in self._servers.values():
            for p in srv.prompts:
                if p.name == name:
                    result = await srv.session.get_prompt(name, arguments or {})
                    parts = []
                    for msg in result.messages:
                        content = msg.content
                        text = getattr(content, "text", str(content))
                        parts.append(f"[{msg.role}]: {text}")
                    return "\n ".join(parts)
        raise ValueError(f"Prompt '{name}' not found in any connected server")

    # ── Roots ─────────────────────────────────────────────────────────────────

    def add_root(self, path: str) -> None:
        resolved = str(Path(path).resolve())
        if resolved not in self._roots:
            self._roots.append(resolved)
            console.print(f"[success]✓ Root added: {resolved}[/success]")
            # Notify all servers
            for srv in self._servers.values():
                try:
                    asyncio.create_task(
                        srv.session.send_roots_list_changed()
                    )
                except Exception:
                    pass
        else:
            console.print(f"[warn]Root already registered: {resolved}[/warn]")

    # ── Messages helper ───────────────────────────────────────────────────────

    def _build_messages(self) -> list[dict]:
        """ Convert Turn history → OpenAI message dicts. Sliding window of MAX_HISTORY_TURNS keeps token count bounded. Tool-call pairs are kept together to avoid broken message chains. """
        msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        history = self._history
        if len(history) > MAX_HISTORY_TURNS:
            history = history[-MAX_HISTORY_TURNS:]
            # Skip orphaned tool results at the start of the window
            while history and history[0].role == "tool":
                history = history[1:]
        for t in history:
            if t.role == "tool":
                # Tool result — tool_call_id MUST be a top-level field
                msgs.append({
                    "role":         "tool",
                    "tool_call_id": t.tool_call_id or "",
                    "content":      t.content,
                })
            elif t.role == "assistant" and t.tool_calls:
                # Assistant message that requested tool calls — include serialised tool_calls
                msgs.append({
                    "role":       "assistant",
                    "content":    t.content or None,
                    "tool_calls": [tc.model_dump() for tc in t.tool_calls],
                })
            else:
                msgs.append({"role": t.role, "content": t.content})
        return msgs

    # ── Tool execution ────────────────────────────────────────────────────────

    def _is_sensitive(self, name: str) -> bool:
        """True if the tool name matches any sensitive pattern."""
        nl = name.lower()
        return any(p in nl for p in SENSITIVE_PATTERNS)

    async def _exec_tool(self, name: str, args: dict) -> str:
        """Execute a tool with confirmation gate, timeout, and cancellation support."""

        # ── Confirmation gate ─────────────────────────────────────────────────
        needs_confirm = (
            self._confirm_mode == "always"
            or (self._confirm_mode == "sensitive" and self._is_sensitive(name))
        )
        if needs_confirm:
            args_preview = json.dumps(args, indent=2, ensure_ascii=False)
            console.print(Panel(
                f"[bold]{name}[/bold] [dim]{args_preview}[/dim]",
                title="[warn]⚡ Tool execution — confirm required[/warn]",
                border_style="yellow",
            ))
            try:
                ans = console.input("[warn]  Run this tool? [[bold]y[/bold]/N]: [/warn]").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans not in ("y", "yes"):
                console.print("[dim]  ↳ Skipped by user.[/dim]")
                return f"SKIPPED: User declined to run '{name}'."

        # ── Execute with timeout + cancellation ───────────────────────────────
        srv = self._tool_map.get(name)
        if not srv:
            return f"ERROR: unknown tool '{name}'"
        try:
            self._cancelled = False
            result = await asyncio.wait_for(
                srv.session.call_tool(name, args),
                timeout=self._tool_timeout,
            )
            parts = []
            for c in result.content:
                if hasattr(c, "text"):
                    parts.append(c.text)
                elif hasattr(c, "data"):
                    parts.append("[image data]")
                else:
                    parts.append(json.dumps(c, default=str))
            raw = " ".join(parts) or "(empty)"
            if len(raw) > MAX_TOOL_RESULT_CH:
                raw = (raw[:MAX_TOOL_RESULT_CH]
                       + f" …[truncated {len(raw)} chars total]")
            return raw
        except asyncio.TimeoutError:
            console.print(f"[error]  ⏱ Tool '{name}' timed out after {self._tool_timeout}s[/error]")
            return f"TIMEOUT: '{name}' exceeded {self._tool_timeout}s. Use /timeout to adjust."
        except asyncio.CancelledError:
            return f"CANCELLED: '{name}' was cancelled by user."
        except Exception as exc:
            return f"ERROR calling {name}: {exc}"

    # ── Agentic query loop ────────────────────────────────────────────────────

    async def process_query(self, user_input: str) -> str:
        """ Full agentic loop: 1. Append user message 2. Call LLM 3. Execute any tool_calls in parallel 4. Append results, repeat until finish_reason == 'stop' """
        self._history.append(Turn(role="user", content=user_input))

        tool_kwargs: dict = {}
        if self._oai_tools:
            tool_kwargs["tools"]       = self._oai_tools
            tool_kwargs["tool_choice"] = "auto"

        final_text = ""
        rounds = 0

        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            console.print(f"[dim]  [LLM call #{rounds}][/dim]", end="")

            response = await self._llm_call(
                model=self._model,
                max_tokens=MAX_TOKENS,
                messages=self._build_messages(),
                **tool_kwargs,
            )
            console.print()

            choice = response.choices[0]
            msg    = choice.message
            finish = choice.finish_reason

            # Append assistant turn
            self._history.append(Turn(
                role="assistant",
                content=msg.content or "",
                tool_calls=msg.tool_calls or [],
            ))

            if finish == "stop" or not msg.tool_calls:
                final_text = msg.content or ""
                break

            # Execute all tool calls in parallel
            tc_list = msg.tool_calls
            console.print(f"[tool]⚙ Calling {len(tc_list)} tool(s)...[/tool]")

            results = await asyncio.gather(*[
                self._exec_tool(
                    tc.function.name,
                    json.loads(tc.function.arguments or "{}"),
                )
                for tc in tc_list
            ])

            for tc, result in zip(tc_list, results):
                short = result[:120].replace(" ", " ")
                console.print(
                    f"  [tool]●[/tool] [bold]{tc.function.name}[/bold] → [dim]{short}…[/dim]"
                )
                self._history.append(Turn(
                    role="tool",
                    content=result,        # plain text — not wrapped in JSON
                    tool_call_id=tc.id,   # top-level field, used in _build_messages
                ))

        else:
            console.print(f"[warn]⚠ MAX_TOOL_ROUNDS ({MAX_TOOL_ROUNDS}) reached[/warn]")

        return final_text

    # ── Streaming query ───────────────────────────────────────────────────────

    async def stream_query(self, user_input: str) -> str:
        """Streaming variant — tokens printed as they arrive."""
        self._history.append(Turn(role="user", content=user_input))

        tool_kwargs: dict = {}
        if self._oai_tools:
            tool_kwargs["tools"]       = self._oai_tools
            tool_kwargs["tool_choice"] = "auto"

        console.print("[asst]Assistant:[/asst] ", end="")
        collected   = ""
        finish_reason = "stop"

        raw = await self._llm_call(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=self._build_messages(),
            stream=True,
            **tool_kwargs,
        )
        async for chunk in raw:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason
            if delta and delta.content:
                console.print(delta.content, end="")
                collected += delta.content

        console.print()

        if finish_reason == "tool_calls":
            # Hand off to full agentic loop for tool execution
            self._history.pop()
            return await self.process_query(user_input)

        self._history.append(Turn(role="assistant", content=collected))
        return collected

    # ══════════════════════════════════════════════════════════════════════════
    # SLASH COMMAND HANDLERS
    # ══════════════════════════════════════════════════════════════════════════

    def _cmd_help(self) -> None:
        table = Table(box=box.ROUNDED, show_header=False, border_style="dim")
        table.add_column("cmd",  style="cmd",  no_wrap=True)
        table.add_column("desc", style="white")
        rows = [
            ("/help",               "Show this help"),
            ("/tools",              "List all tools from all servers"),
            ("/resources",          "List all resources"),
            ("/read <uri>",         "Read and display a resource"),
            ("/subscribe <uri>",    "Subscribe to resource change notifications"),
            ("/prompts",            "List all prompt templates"),
            ("/prompt <name> [k=v]","Expand a prompt and inject into conversation"),
            ("/servers",            "Show server connection status"),
            ("/history",            "Print conversation history"),
            ("/clear",              "Reset conversation history"),
            ("/roots",              "List filesystem roots"),
            ("/roots add <path>",   "Add a filesystem root"),
            ("/stream",             "Toggle streaming on/off"), ("/confirm [mode]",      "Tool confirmation: always | sensitive | never"),
            ("/timeout [secs]",      "Set per-tool timeout in seconds"),
            ("/model <name>",        "Switch LLM model without restart"),
            ("/quota",               "Rate limit info and model quota tips"),
            ("/save",                "Save conversation to disk"),
            ("/load",                "Reload last saved conversation"),
            ("/sessions",            "Show saved session info"),
            ("/ping [server]",       "Check server reachability"),
            ("/export",             "Export conversation to JSON"),
            ("quit / exit",         "Close the client"),
        ]
        for r in rows:
            table.add_row(*r)
        console.print(Panel(table, title="[server]Commands[/server]", border_style="dim"))

    def _cmd_tools(self) -> None:
        table = Table(title="Available Tools", box=box.ROUNDED, border_style="magenta")
        table.add_column("Server",      style="server",  no_wrap=True)
        table.add_column("Tool",        style="tool",    no_wrap=True)
        table.add_column("Description", style="white")
        for srv in self._servers.values():
            for t in srv.tools:
                desc = (t.description or "")[:70]
                table.add_row(srv.name, t.name, desc)
        if not any(srv.tools for srv in self._servers.values()):
            table.add_row("—", "—", "No tools registered")
        console.print(table)

    async def _cmd_resources(self) -> None:
        table = Table(title="Available Resources", box=box.ROUNDED, border_style="blue")
        table.add_column("Server",   style="server",   no_wrap=True)
        table.add_column("Name",     style="resource", no_wrap=True)
        table.add_column("URI",      style="dim")
        table.add_column("MIMEType", style="dim")
        has_any = False
        for srv in self._servers.values():
            for r in srv.resources:
                table.add_row(
                    srv.name,
                    getattr(r, "name", ""),
                    getattr(r, "uri", ""),
                    getattr(r, "mimeType", "") or "",
                )
                has_any = True
            for rt in srv.resource_templates:
                table.add_row(
                    srv.name,
                    f"[dim]template:[/dim] {getattr(rt, 'name', '')}",
                    getattr(rt, "uriTemplate", ""),
                    getattr(rt, "mimeType", "") or "",
                )
                has_any = True
        if not has_any:
            table.add_row("—", "—", "No resources available", "")
        console.print(table)

    async def _cmd_read(self, uri: str) -> None:
        if not uri:
            console.print("[warn]Usage: /read <uri>[/warn]")
            return
        console.print(f"[dim]Reading {uri}...[/dim]")
        try:
            content = await self.read_resource(uri)
            mime = uri.rsplit(".", 1)[-1].lower() if "." in uri else "text"
            lang_map = {
                "py": "python", "js": "javascript", "ts": "typescript",
                "json": "json", "yaml": "yaml", "yml": "yaml",
                "md": "markdown", "html": "html", "css": "css",
                "sh": "bash", "sql": "sql", "toml": "toml",
            }
            lang = lang_map.get(mime, "text")
            syntax = Syntax(content, lang, theme="monokai", line_numbers=True, word_wrap=True)
            console.print(Panel(syntax, title=f"[resource]{uri}[/resource]", border_style="blue"))
        except Exception as exc:
            console.print(f"[error]Failed to read resource: {exc}[/error]")

    async def _cmd_prompts(self) -> None:
        table = Table(title="Prompt Templates", box=box.ROUNDED, border_style="cyan")
        table.add_column("Server",      style="server",   no_wrap=True)
        table.add_column("Name",        style="prompt_h", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Arguments",   style="dim")
        has_any = False
        for srv in self._servers.values():
            for p in srv.prompts:
                args = ", ".join(
                    f"{a.name}{'*' if getattr(a,'required',False) else ''}"
                    for a in (getattr(p, "arguments", None) or [])
                )
                table.add_row(
                    srv.name,
                    p.name,
                    (getattr(p, "description", "") or "")[:60],
                    args,
                )
                has_any = True
        if not has_any:
            table.add_row("—", "—", "No prompts available", "")
        console.print(table)

    async def _cmd_prompt(self, raw_args: str) -> None:
        """ /prompt <name> [key=value ...] Expands the template and injects it as the next user message. """
        parts = raw_args.strip().split()
        if not parts:
            console.print("[warn]Usage: /prompt <name> [key=value ...][/warn]")
            return
        name = parts[0]
        args: dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                k, _, v = part.partition("=")
                args[k] = v
        try:
            expanded = await self.get_prompt(name, args)
            console.print(Panel(
                expanded,
                title=f"[prompt_h]Prompt: {name}[/prompt_h]",
                border_style="cyan",
            ))
            inject = Confirm.ask("Inject this prompt into the conversation?", default=True)
            if inject:
                self._history.append(Turn(role="user", content=expanded))
                console.print("[success]✓ Prompt injected into conversation[/success]")
        except Exception as exc:
            console.print(f"[error]{exc}[/error]")

    def _cmd_servers(self) -> None:
        table = Table(title="Connected Servers", box=box.ROUNDED, border_style="white")
        table.add_column("Server",    style="server")
        table.add_column("Path",      style="dim")
        table.add_column("Tools",     justify="right", style="tool")
        table.add_column("Resources", justify="right", style="resource")
        table.add_column("Prompts",   justify="right", style="prompt_h")
        for srv in self._servers.values():
            table.add_row(
                srv.name,
                srv.path,
                str(len(srv.tools)),
                str(len(srv.resources) + len(srv.resource_templates)),
                str(len(srv.prompts)),
            )
        if not self._servers:
            table.add_row("—", "—", "—", "—", "—")
        console.print(table)

    def _cmd_history(self) -> None:
        if not self._history:
            console.print("[dim]No history yet.[/dim]")
            return
        for i, turn in enumerate(self._history):
            ts = turn.ts.strftime("%H:%M:%S")
            if turn.role == "user":
                console.print(Panel(
                    turn.content, title=f"[user_c]You[/user_c]  [dim]{ts}[/dim]",
                    border_style="green",
                ))
            elif turn.role == "assistant":
                console.print(Panel(
                    Markdown(turn.content) if turn.content else "[dim](tool call only)[/dim]",
                    title=f"[asst]Assistant[/asst]  [dim]{ts}[/dim]",
                    border_style="cyan",
                ))

    def _cmd_roots(self, arg: str = "") -> None:
        if arg.startswith("add "):
            self.add_root(arg[4:].strip())
        else:
            if not self._roots:
                console.print("[dim]No roots configured. Use /roots add <path>[/dim]")
            else:
                for r in self._roots:
                    console.print(f"  [resource]•[/resource] {r}")

    def _cmd_export(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"conversation_{ts}.json"
        data = [
            {"role": t.role, "content": t.content, "ts": t.ts.isoformat()}
            for t in self._history
        ]
        Path(fname).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        console.print(f"[success]✓ Exported {len(data)} turns → {fname}[/success]")

    # ══════════════════════════════════════════════════════════════════════════
    # MAIN REPL
    # ══════════════════════════════════════════════════════════════════════════

    # ── Conversation persistence ─────────────────────────────────────────────
    def _save_history(self) -> None:
        """Persist conversation history to disk."""
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "model":   self._model,
                "saved":   _now(),
                "turns":   [
                    {"role": t.role, "content": t.content,
                     "ts": t.ts.isoformat(),
                     "tool_call_id": t.tool_call_id}
                    for t in self._history
                ],
            }
            HISTORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            console.print(f"[dim]  History saved → {HISTORY_FILE} ({len(self._history)} turns)[/dim]")
        except Exception as exc:
            console.print(f"[warn]  Could not save history: {exc}[/warn]")

    def _load_history(self) -> bool:
        """Load persisted conversation history from disk. Returns True if loaded."""
        try:
            if not HISTORY_FILE.exists():
                return False
            data = json.loads(HISTORY_FILE.read_text())
            turns = data.get("turns", [])
            if not turns:
                return False
            self._history = [
                Turn(
                    role=t["role"],
                    content=t["content"],
                    ts=datetime.fromisoformat(t.get("ts", _now())),
                    tool_call_id=t.get("tool_call_id"),
                )
                for t in turns
            ]
            saved_model = data.get("model", "")
            console.print(
                f"[success]✓ Loaded {len(self._history)} turns from previous session[/success] "
                f"[dim]({data.get('saved','?')} | model: {saved_model})[/dim]"
            )
            return True
        except Exception as exc:
            console.print(f"[warn]  Could not load history: {exc}[/warn]")
            return False

    async def chat_loop(self) -> None:
        # Auto-load history
        if AUTO_LOAD_HISTORY:
            self._load_history()

        mode = "[success]STREAM[/success]" if self._streaming else "[info]STANDARD[/info]"
        confirm_badge = {"always": "[error]CONFIRM:ALL[/error]",
                         "sensitive": "[warn]CONFIRM:SENSITIVE[/warn]",
                         "never": "[dim]CONFIRM:OFF[/dim]"}[self._confirm_mode]
        console.print()
        console.print(Rule(
            f"[server]MCP Client[/server]  "
            f"[bold]{self._model}[/bold]  "
            f"{mode}  {confirm_badge}  "
            f"[dim]timeout:{self._tool_timeout}s[/dim]"
        ))
        servers_line = "  ".join(
            f"[server]{n}[/server]([tool]{len(s.tools)}T[/tool]/"
            f"[resource]{len(s.resources)}R[/resource]/"
            f"[prompt_h]{len(s.prompts)}P[/prompt_h])"
            for n, s in self._servers.items()
        )
        if servers_line:
            console.print(f"[dim]Servers: {servers_line}[/dim]")
        console.print(f"[dim]Type [bold]/help[/bold]  ·  Ctrl+C to cancel tool  ·  [bold]quit[/bold] to exit[/dim] ")

        while True:
            try:
                raw = console.input("[user_c]You:[/user_c] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print(" [dim]Bye.[/dim]")
                break

            if not raw:
                continue

            # ── Exit ─────────────────────────────────────────────────────────
            if raw.lower() in ("quit", "exit", "q"):
                console.print("[dim]Closing...[/dim]")
                break

            # ── Slash commands ────────────────────────────────────────────────
            if raw.startswith("/"):
                cmd, _, rest = raw[1:].partition(" ")
                cmd = cmd.lower()
                try:
                    if cmd == "help":
                        self._cmd_help()
                    elif cmd == "tools":
                        self._cmd_tools()
                    elif cmd == "resources":
                        await self._cmd_resources()
                    elif cmd == "read":
                        await self._cmd_read(rest.strip())
                    elif cmd == "subscribe":
                        await self.subscribe_resource(rest.strip())
                    elif cmd == "prompts":
                        await self._cmd_prompts()
                    elif cmd == "prompt":
                        await self._cmd_prompt(rest)
                    elif cmd == "servers":
                        self._cmd_servers()
                    elif cmd == "history":
                        self._cmd_history()
                    elif cmd == "clear":
                        self._history.clear()
                        console.print("[success]✓ History cleared[/success]")
                    elif cmd == "roots":
                        self._cmd_roots(rest.strip())
                    elif cmd == "model":
                        if not rest.strip():
                            console.print(
                                f"Current model: [bold]{self._model}[/bold] "
                                "Available Groq models (each has its own TPD quota): "
                                "  [cmd]llama-3.3-70b-versatile[/cmd]       ← best quality "
                                "  [cmd]mixtral-8x7b-32768[/cmd]             ← fast, 32k context "
                                "  [cmd]llama-3.1-8b-instant[/cmd]           ← fastest, low token cost "
                                "  [cmd]gemma2-9b-it[/cmd]                   ← lightweight "
                                "  [cmd]llama3-groq-70b-8192-tool-use-preview[/cmd]  ← tool-tuned  "
                                "Usage: [cmd]/model mixtral-8x7b-32768[/cmd]"
                            )
                        else:
                            self._model = rest.strip()
                            # Reset client so new model takes effect immediately
                            if self._openai:
                                await self._openai.close()
                                self._openai = None
                            console.print(f"[success]✓ Model switched to: {self._model}[/success]")
                            console.print("[dim]  Client reset — next call uses the new model.[/dim]")
                    elif cmd == "quota":
                        console.print(
                            f"Model      : [bold]{self._model}[/bold] "
                            f"Base URL   : [dim]{OPENAI_BASE_URL}[/dim]  "
                            "[bold]Groq Free Tier Limits:[/bold]"
                            "  TPM (tokens/min) : 12,000  ← hit during heavy tool use "
                            "  TPD (tokens/day) : 100,000 ← hit after sustained testing  "
                            "[bold]When you hit TPD:[/bold]"
                            "  Each model has its OWN daily quota. Switch to a fresh one: "
                            "  [cmd]/model mixtral-8x7b-32768[/cmd]   → separate 100k TPD "
                            "  [cmd]/model llama-3.1-8b-instant[/cmd] → separate 500k TPD  "
                            "[bold]Permanent fix:[/bold] Upgrade to Groq Dev Tier at console.groq.com/billing"
                        )
                    elif cmd == "confirm":
                        modes = ("always", "sensitive", "never")
                        if rest.strip().lower() in modes:
                            self._confirm_mode = rest.strip().lower()
                            console.print(f"[success]✓ Confirmation mode: {self._confirm_mode}[/success]")
                        else:
                            console.print(f"Current: [bold]{self._confirm_mode}[/bold]")
                            console.print("  [cmd]/confirm always[/cmd]     confirm every tool call")
                            console.print("  [cmd]/confirm sensitive[/cmd]  confirm destructive tools only (default)")
                            console.print("  [cmd]/confirm never[/cmd]      auto-execute all tools (use with care)")
                    elif cmd == "timeout":
                        if rest.strip().isdigit():
                            self._tool_timeout = int(rest.strip())
                            console.print(f"[success]✓ Tool timeout: {self._tool_timeout}s[/success]")
                        else:
                            console.print(f"Current timeout: [bold]{self._tool_timeout}s[/bold]  Usage: /timeout 60")
                    elif cmd == "save":
                        self._save_history()
                    elif cmd == "load":
                        self._load_history()
                    elif cmd == "sessions":
                        f = HISTORY_FILE
                        if f.exists():
                            import json as _j
                            d = _j.loads(f.read_text())
                            console.print(
                                f"[bold]Saved session[/bold]  {f} "
                                f"  Turns : {len(d.get('turns', []))} "
                                f"  Model : {d.get('model','?')} "
                                f"  Saved : {d.get('saved','?')} "
                                "Use [cmd]/load[/cmd] to restore."
                            )
                        else:
                            console.print(f"[dim]No saved session found at {HISTORY_FILE}[/dim]")
                    elif cmd == "ping":
                        target = rest.strip() or None
                        for sname, srv in self._servers.items():
                            if target and sname != target:
                                continue
                            try:
                                await asyncio.wait_for(srv.session.list_tools(), timeout=3)
                                console.print(f"[success]● {sname}[/success] — reachable")
                            except Exception as e:
                                console.print(f"[error]✗ {sname}[/error] — {e}")
                    elif cmd == "stream":
                        self._streaming = not self._streaming
                        state = "[success]ON[/success]" if self._streaming else "[warn]OFF[/warn]"
                        console.print(f"Streaming: {state}")
                    elif cmd == "export":
                        self._cmd_export()
                    else:
                        console.print(f"[warn]Unknown command: /{cmd}  (try /help)[/warn]")
                except Exception as exc:
                    console.print(f"[error]Command error: {exc}[/error]")
                continue

            # ── LLM query — with Ctrl+C cancel support ────────────────────────
            query_task = None
            try:
                fn = self.stream_query if self._streaming else self.process_query
                query_task = asyncio.ensure_future(fn(raw))
                answer = await query_task
                if answer and not self._streaming:
                    console.print(Panel(
                        Markdown(answer),
                        title="[asst]Assistant[/asst]",
                        border_style="cyan",
                    ))
                # Auto-save after every turn
                self._save_history()
            except KeyboardInterrupt:
                if query_task:
                    query_task.cancel()
                self._cancelled = True
                console.print(" [warn]  ⚡ Cancelled — current tool/LLM call aborted[/warn]")
                # Remove the incomplete user turn from history
                if self._history and self._history[-1].role == "user":
                    self._history.pop()
            except Exception as exc:
                console.print(f"[error]Error: {exc}[/error]")
                log.error("Query error", exc_info=True)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    async def cleanup(self) -> None:
        await self.exit_stack.aclose()
        if self._openai:
            await self._openai.close()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

def _print_usage() -> None:
    console.print(Panel(
        textwrap.dedent("""\ [bold]Usage:[/bold] python mcp_client_advanced.py <server.py> [server2.py ...] [--stream]  [bold]Env / .env:[/bold] OPENAI_BASE_URL   your endpoint  (default: Groq) OPENAI_API_KEY    API key  [required] MODEL_NAME        model name MAX_TOKENS        max tokens per call  (default 4096) MAX_TOOL_ROUNDS   agentic loop cap     (default 10) SSL_VERIFY        false to skip TLS    (default true) SYSTEM_PROMPT     override system prompt """),
        title="[server]Advanced MCP Client[/server]",
        border_style="dim",
    ))


async def main() -> None:
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        _print_usage()
        sys.exit(0 if args else 1)

    streaming    = "--stream" in args
    server_paths = [a for a in args if not a.startswith("--")]

    if not OPENAI_API_KEY:
        console.print("[error]OPENAI_API_KEY is not set. Add it to your .env file.[/error]")
        sys.exit(1)

    client = AdvancedMCPClient()
    client._streaming = streaming
    try:
        await client.connect_servers(server_paths)
        await client.chat_loop()
    except Exception as exc:
        console.print(f"[error]Fatal: {exc}[/error]")
        log.error("Fatal error", exc_info=True)
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
