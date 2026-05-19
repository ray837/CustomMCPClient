"""
mcp_skills.py — Skills subsystem for AdvancedMCPClient
═══════════════════════════════════════════════════════════════════════════════
Adds a Claude-Code-style Skills system:

  • Skills are Markdown files (SKILL.md or <name>.md) stored under a
    configurable directory (~/.mcp_client/skills/ by default).
  • Each file may start with a YAML frontmatter block (--- … ---) that
    declares:  name, description, triggers (list of keywords), priority.
  • When the user sends a query, SkillsManager scores every loaded skill
    against the query text; high-scoring skills are auto-injected as a
    plan preamble into the system prompt for that single LLM turn.
  • Skills can also be pinned (always on), manually activated, or
    explicitly disabled per session.

Slash commands added to the REPL:
  /skills               — list all loaded skills + status
  /skill <name>         — show full skill content
  /skill use <name>     — manually activate a skill for the next turn
  /skill pin <name>     — always-on for this session
  /skill off <name>     — disable a skill for this session
  /skill reload         — rescan skills directory
  /plan                 — show which skills will fire on the next query
  /skilldir [path]      — show or change the skills directory
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import os
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── YAML frontmatter parser (no PyYAML dependency) ───────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Splits optional YAML frontmatter (--- … ---) from the rest of the doc.
    Returns (meta_dict, body_text).  Uses only stdlib — no PyYAML needed.
    """
    meta: dict = {}
    if not text.startswith("---"):
        return meta, text

    end = text.find("\n---", 3)
    if end == -1:
        return meta, text

    fm_block = text[3:end].strip()
    body     = text[end + 4:].lstrip("\n")

    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()

        # Handle YAML list shorthand:  triggers: [a, b, c]  or  - item
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",")]
        elif val == "":
            # Might be a multi-line list — collect following "- item" lines
            # (we'll pick them up on the next pass; leave empty for now)
            meta[key] = []
        else:
            # Try int / float coercion, else keep as string
            try:
                meta[key] = int(val)
            except ValueError:
                try:
                    meta[key] = float(val)
                except ValueError:
                    meta[key] = val.strip("'\"")

    # Second pass: collect YAML block-list items (- value)
    _collecting: str | None = None
    for line in fm_block.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("-"):
            _collecting = stripped[:-1].strip()
            if _collecting not in meta:
                meta[_collecting] = []
        elif stripped.startswith("- ") and _collecting:
            val_item = stripped[2:].strip().strip("'\"")
            if isinstance(meta.get(_collecting), list):
                meta[_collecting].append(val_item)

    return meta, body


# ══════════════════════════════════════════════════════════════════════════════
# DATA MODEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SkillDef:
    """One loaded skill."""
    name:        str                    # unique identifier (stem of filename)
    path:        Path                   # source file
    description: str        = ""        # short description shown in /skills table
    triggers:    list[str]  = field(default_factory=list)   # keyword triggers
    priority:    int        = 5         # 1-10; higher fires first / wins conflicts
    body:        str        = ""        # full instruction text (injected into prompt)

    # Session-level state (not persisted)
    pinned:      bool       = False     # always-on this session
    disabled:    bool       = False     # suppressed this session
    activated:   bool       = False     # manually activated for ONE turn

    # ── Scoring ──────────────────────────────────────────────────────────────

    def score(self, query: str) -> float:
        """
        Return a relevance score ∈ [0, 1] for this skill against a query.
        Combines:
          • Trigger keyword hits (weighted by priority)
          • Description word overlap
          • Exact name match
        """
        if self.disabled:
            return 0.0
        if self.pinned or self.activated:
            return 1.0          # always fires

        q = query.lower()
        words = set(re.findall(r"\w+", q))
        score = 0.0

        # Trigger keyword match
        for trigger in self.triggers:
            t = trigger.lower().strip()
            if not t:
                continue
            if t in q:
                score += 0.35
            elif any(w.startswith(t[:4]) for w in words if len(t) >= 4):
                score += 0.15   # prefix / fuzzy match

        # Description overlap
        desc_words = set(re.findall(r"\w+", self.description.lower()))
        overlap = words & desc_words - STOP_WORDS
        if desc_words:
            score += 0.30 * (len(overlap) / max(len(desc_words), 1))

        # Name match
        if self.name.lower() in q:
            score += 0.40

        # Normalise by priority (higher priority skills get a small boost)
        score *= 0.9 + (self.priority / 100)

        return min(score, 1.0)

    def format_header(self) -> str:
        """One-line summary for /skills table."""
        status = (
            "📌 pinned"   if self.pinned   else
            "🟢 active"   if self.activated else
            "🔴 disabled" if self.disabled  else
            "⚪ auto"
        )
        trig = ", ".join(self.triggers[:5]) or "—"
        return f"{status}  |  triggers: {trig}"


# ── English stop-words (excluded from description overlap scoring) ────────────
STOP_WORDS = {
    "a","an","the","and","or","of","to","in","for","on","at","by","with",
    "is","it","be","as","do","if","up","we","he","she","they","this","that",
    "use","when","how","what","can","will","from","into","about","also",
    "which","you","your","my","i","me","we","our","was","are","were","been",
    "has","have","had","not","but","so","all","any","its",
}


# ══════════════════════════════════════════════════════════════════════════════
# SKILLS MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class SkillsManager:
    """
    Loads, indexes, scores, and injects Skills into the MCP client's agentic loop.

    Integration points (call these from AdvancedMCPClient):
      • __init__  — pass skills_dir; call load()
      • load()    — (re)scans directory and populates self.skills
      • select(query)     → list[SkillDef]   — skills to fire
      • build_plan(query) → str              — formatted plan text to inject
      • activate(name)    — manually activate for next turn
      • pin(name)         — always-on this session
      • disable(name)     — suppress this session
      • clear_activated() — call after each LLM turn to reset one-shot flags
    """

    AUTO_THRESHOLD = float(os.getenv("SKILL_AUTO_THRESHOLD", "0.30"))
    MAX_SKILLS_PER_TURN = int(os.getenv("MAX_SKILLS_PER_TURN", "3"))

    def __init__(self, skills_dir: Path | str | None = None):
        default =  ".mcp_client" / "skills"
        print(default)
        self.skills_dir: Path = Path(skills_dir) if skills_dir else default
        self.skills: dict[str, SkillDef] = {}   # name → SkillDef
        self._last_fired: list[str] = []

    # ── I/O ──────────────────────────────────────────────────────────────────

    def load(self) -> int:
        """
        Scan skills_dir for *.md files and load each as a SkillDef.
        Files may use YAML frontmatter; if absent, name = stem,
        description = first non-blank line, triggers inferred from name words.
        Returns number of skills loaded.
        """
        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            _write_example_skills(self.skills_dir)

        loaded = 0
        for md_file in sorted(self.skills_dir.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(text)

                name = str(meta.get("name", md_file.stem)).lower().replace(" ", "_")
                desc = str(meta.get("description", ""))
                if not desc:
                    # Fall back to first non-blank line of body
                    for ln in body.splitlines():
                        ln = ln.strip().lstrip("#").strip()
                        if ln:
                            desc = ln[:120]
                            break

                raw_triggers = meta.get("triggers", [])
                if isinstance(raw_triggers, str):
                    raw_triggers = [t.strip() for t in raw_triggers.split(",")]
                triggers = [str(t) for t in raw_triggers if t]
                if not triggers:
                    # Infer triggers from the skill name parts
                    triggers = [p for p in re.split(r"[_\-\s]+", name) if len(p) > 2]

                skill = SkillDef(
                    name        = name,
                    path        = md_file,
                    description = desc,
                    triggers    = triggers,
                    priority    = int(meta.get("priority", 5)),
                    body        = body.strip(),
                )
                # Preserve session flags on reload
                if name in self.skills:
                    skill.pinned   = self.skills[name].pinned
                    skill.disabled = self.skills[name].disabled

                self.skills[name] = skill
                loaded += 1
            except Exception as exc:
                import logging
                logging.getLogger("mcp-skills").warning("Failed to load %s: %s", md_file, exc)

        return loaded

    def reload(self) -> int:
        """Re-scan skills directory without resetting session flags."""
        return self.load()

    # ── Selection ─────────────────────────────────────────────────────────────

    def select(self, query: str) -> list[SkillDef]:
        """
        Return skills that should fire for this query, sorted by score descending.
        Respects MAX_SKILLS_PER_TURN unless skills are pinned.
        """
        scored = [
            (skill.score(query), skill)
            for skill in self.skills.values()
            if not skill.disabled
        ]
        scored.sort(key=lambda x: (-x[0], -x[1].priority))

        pinned  = [s for sc, s in scored if s.pinned]
        auto    = [s for sc, s in scored if not s.pinned and sc >= self.AUTO_THRESHOLD]
        manual  = [s for sc, s in scored if s.activated and not s.pinned]

        # Deduplicate; pinned always included, then manual, then auto (capped)
        seen: set[str] = set()
        result: list[SkillDef] = []
        for s in (pinned + manual + auto):
            if s.name not in seen:
                seen.add(s.name)
                result.append(s)
            if len(result) >= self.MAX_SKILLS_PER_TURN + len(pinned):
                break

        self._last_fired = [s.name for s in result]
        return result

    def build_plan(self, query: str) -> str:
        """
        Build the plan/preamble text to prepend to the system prompt.
        Returns empty string if no skills fire.
        """
        skills = self.select(query)
        if not skills:
            return ""

        parts = [
            "═══════════════════════════════════════════════",
            "  SKILL PLAN  —  follow these instructions",
            "═══════════════════════════════════════════════",
        ]
        for i, skill in enumerate(skills, 1):
            parts.append(f"\n── Skill {i}: {skill.name.upper()} ──")
            parts.append(skill.body)

        parts.append("\n═══════════════════════════════════════════════")
        parts.append("  End of skill plan. Now handle the user request.")
        parts.append("═══════════════════════════════════════════════\n")
        return "\n".join(parts)

    # ── Session control ───────────────────────────────────────────────────────

    def _get(self, name: str) -> SkillDef | None:
        name = name.lower().strip()
        return self.skills.get(name)

    def activate(self, name: str) -> bool:
        """Activate a skill for the NEXT turn only."""
        s = self._get(name)
        if s:
            s.activated = True
            return True
        return False

    def pin(self, name: str) -> bool:
        """Pin a skill as always-on for this session."""
        s = self._get(name)
        if s:
            s.pinned   = True
            s.disabled = False
            return True
        return False

    def disable(self, name: str) -> bool:
        """Suppress auto-activation of a skill for this session."""
        s = self._get(name)
        if s:
            s.disabled  = True
            s.pinned    = False
            s.activated = False
            return True
        return False

    def unpin(self, name: str) -> bool:
        s = self._get(name)
        if s:
            s.pinned = False
            return True
        return False

    def clear_activated(self) -> None:
        """Reset one-shot activations after each LLM turn."""
        for s in self.skills.values():
            s.activated = False

    @property
    def last_fired(self) -> list[str]:
        return list(self._last_fired)


# ══════════════════════════════════════════════════════════════════════════════
# EXAMPLE SKILLS  (written on first run if directory is empty)
# ══════════════════════════════════════════════════════════════════════════════

def _write_example_skills(skills_dir: Path) -> None:
    """Write starter example skills so the directory is not empty."""

    examples = {
        "code_review.md": textwrap.dedent("""\
            ---
            name: code_review
            description: Structured code review with security, performance, and style analysis
            triggers: [review, audit, check code, inspect, code quality, refactor]
            priority: 7
            ---

            ## Code Review Plan

            Follow this structured plan when asked to review code:

            1. **Read the full code** before commenting on anything.
            2. **Security** — check for injection risks, hardcoded secrets, unsafe deserialization, missing auth.
            3. **Performance** — flag N+1 queries, unnecessary allocations, blocking async calls.
            4. **Error handling** — every exception path must be intentional; no bare `except`.
            5. **Readability** — naming, single-responsibility, comment quality.
            6. **Tests** — identify untested paths; suggest specific test cases.
            7. Produce a prioritised findings table: CRITICAL / MAJOR / MINOR / NIT.
            8. End with a one-paragraph summary and a concrete next step.
            """),

        "api_design.md": textwrap.dedent("""\
            ---
            name: api_design
            description: REST/JSON API design with consistent patterns, versioning, and error contracts
            triggers: [api, endpoint, REST, route, schema, openapi, swagger, fastapi]
            priority: 6
            ---

            ## API Design Plan

            When designing or reviewing an API:

            1. **Resource naming** — plural nouns, no verbs (`/loans`, not `/getLoan`).
            2. **HTTP semantics** — GET read-only, POST create, PUT replace, PATCH partial, DELETE.
            3. **Versioning** — prefix routes with `/v1/`; never break existing clients.
            4. **Error contract** — always return `{"error": {"code": "...", "message": "...", "details": {...}}}`.
            5. **Pagination** — cursor-based for large sets; include `next_cursor` and `total`.
            6. **Auth** — document which endpoints require JWT / API key; show header examples.
            7. **OpenAPI** — provide a YAML schema block for every new endpoint.
            8. **Rate limits** — note headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`.
            """),

        "test_automation.md": textwrap.dedent("""\
            ---
            name: test_automation
            description: Playwright/Pytest test automation plan for banking and fintech flows
            triggers: [test, playwright, pytest, automation, POM, fixture, e2e, maker checker, challan, CBDT, GST, ICEGATE]
            priority: 8
            ---

            ## Test Automation Plan

            When writing or reviewing automated tests:

            1. **Page Object Model** — one class per page; locators as properties; actions as methods.
            2. **Fixtures** — use `conftest.py`; `scope="session"` for browser, `scope="function"` for page.
            3. **Assertions** — use `expect()` for Playwright; never `time.sleep()`; use `wait_for_selector`.
            4. **Test data** — parametrize with `@pytest.mark.parametrize`; never hardcode in test body.
            5. **Maker / Checker** — separate test functions for maker submission and checker approval; assert intermediate states.
            6. **GOCD** — ensure test run command matches the pipeline's `go.cd` task block.
            7. **Allure tags** — annotate with `@allure.feature`, `@allure.story`, `@allure.severity`.
            8. **Error output** — on failure, capture screenshot and attach to Allure report.
            """),

        "debug_plan.md": textwrap.dedent("""\
            ---
            name: debug_plan
            description: Systematic debugging plan for errors, exceptions, and unexpected behaviour
            triggers: [debug, error, exception, traceback, bug, fix, not working, fails, crash, issue]
            priority: 6
            ---

            ## Debugging Plan

            Follow this plan systematically — do not guess:

            1. **Reproduce** — identify the minimal input that triggers the problem.
            2. **Read the traceback** — start from the BOTTOM (the actual error line), work upward.
            3. **Isolate** — binary-search the call stack; add strategic `print` / `logging.debug`.
            4. **Hypothesise** — write down 2-3 candidate root causes before touching code.
            5. **Verify** — test each hypothesis with the smallest possible change.
            6. **Fix** — make the fix; explain WHY it works, not just what changed.
            7. **Regression test** — add a test that would have caught this bug.
            8. **Document** — add an inline comment if the fix is non-obvious.
            """),

        "mcp_server.md": textwrap.dedent("""\
            ---
            name: mcp_server
            description: Build or extend MCP servers using FastMCP with tools, resources, and prompts
            triggers: [mcp, fastmcp, server, tool, resource, prompt template, mcp server, model context protocol]
            priority: 7
            ---

            ## MCP Server Build Plan

            When building or extending an MCP server:

            1. **FastMCP** — use `from fastmcp import FastMCP; mcp = FastMCP("name")`.
            2. **Tools** — decorate with `@mcp.tool()`; type-annotate all params; return plain string or dict.
            3. **Resources** — decorate with `@mcp.resource("scheme://path")`; return text or blob.
            4. **Prompts** — decorate with `@mcp.prompt()`; accept `str` args, return `str`.
            5. **Error handling** — raise `ValueError` for user errors; `RuntimeError` for server errors.
            6. **Logging** — use `ctx.info()`, `ctx.warning()`, `ctx.error()` inside tool functions (not `print`).
            7. **Progress** — call `await ctx.report_progress(current, total)` for long operations.
            8. **Transport** — stdio for local; SSE/HTTP for remote; document the run command in README.
            """),
    }

    for fname, content in examples.items():
        target = skills_dir / fname
        if not target.exists():
            target.write_text(content, encoding="utf-8")
