"""
Demo MCP server — exercises all primitives so you can test the advanced client.

Primitives exposed:
  Tools      → add, get_weather, read_file_summary, search_web_mock
  Resources  → file://docs/readme, db://schema/users
  Prompts    → code_review, bug_report, explain_error
  Logging    → emits server-side log messages
  Elicitation→ triggered by the collect_user_info tool
  Sampling   → triggered by the ai_summarize tool
"""

from mcp.server.fastmcp import FastMCP
import logging

mcp = FastMCP("demo-server")
log = logging.getLogger("demo-server")


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    mcp.get_context().info(f"add({a}, {b})")
    return a + b


@mcp.tool()
def get_weather(city: str, units: str = "metric") -> dict:
    """
    Get current weather for a city.

    Args:
        city:  City name (e.g. Hyderabad, Bengaluru)
        units: 'metric' (°C) or 'imperial' (°F)
    """
    mock_data = {
        "hyderabad":  {"temp": 34, "desc": "Partly cloudy", "humidity": 55},
        "bengaluru":  {"temp": 26, "desc": "Overcast",      "humidity": 72},
        "mumbai":     {"temp": 30, "desc": "Humid",         "humidity": 85},
        "delhi":      {"temp": 38, "desc": "Hot & sunny",   "humidity": 30},
    }
    data = mock_data.get(city.lower(), {"temp": 28, "desc": "Sunny", "humidity": 60})
    unit_sym = "°C" if units == "metric" else "°F"
    temp = data["temp"] if units == "metric" else int(data["temp"] * 9 / 5 + 32)
    return {
        "city":        city,
        "temperature": f"{temp}{unit_sym}",
        "description": data["desc"],
        "humidity":    f"{data['humidity']}%",
    }


@mcp.tool()
def search_docs(query: str, limit: int = 3) -> list[dict]:
    """
    Search internal documentation.

    Args:
        query: Search query string
        limit: Max results (1-10)
    """
    mock_results = [
        {"title": "MCP Protocol Overview",   "url": "docs://mcp/overview",   "snippet": "MCP is a protocol for connecting AI models to tools..."},
        {"title": "Tool Schema Reference",   "url": "docs://mcp/tools",      "snippet": "Tools are defined with JSON Schema input validation..."},
        {"title": "Resource Management",     "url": "docs://mcp/resources",  "snippet": "Resources expose data that models can read..."},
        {"title": "Prompt Templates Guide",  "url": "docs://mcp/prompts",    "snippet": "Prompts are reusable message templates with arguments..."},
        {"title": "Elicitation Deep-Dive",   "url": "docs://mcp/elicitation","snippet": "Elicitation allows servers to collect structured input..."},
    ]
    hits = [r for r in mock_results if query.lower() in r["title"].lower()
            or query.lower() in r["snippet"].lower()]
    return hits[:limit] or mock_results[:limit]


@mcp.tool()
async def collect_user_info(purpose: str) -> dict:
    """
    Collect structured information from the user via elicitation.

    Args:
        purpose: Why the info is needed (shown to user)
    """
    ctx = mcp.get_context()
    ctx.info(f"Requesting elicitation for: {purpose}")

    # This triggers the client's elicitation handler
    result = await ctx.elicit(
        message=f"Please provide your details ({purpose})",
        schema={
            "type": "object",
            "properties": {
                "name":    {"type": "string",  "description": "Your full name"},
                "email":   {"type": "string",  "description": "Email address"},
                "confirm": {"type": "boolean", "description": "Confirm submission"},
            },
            "required": ["name"],
        },
    )
    return {"status": result.action, "data": getattr(result, "content", {})}


# ══════════════════════════════════════════════════════════════════════════════
# RESOURCES
# ══════════════════════════════════════════════════════════════════════════════

@mcp.resource("docs://readme")
def get_readme() -> str:
    """Project README"""
    return """\
# Advanced MCP Demo

This server demonstrates all MCP primitives:

## Tools
- `add` — arithmetic
- `get_weather` — mock weather
- `search_docs` — documentation search
- `collect_user_info` — elicitation demo

## Resources
- `docs://readme` — this document
- `db://schema/users` — DB schema

## Prompts
- `code_review` — structured code review
- `bug_report`  — bug report template
- `explain_error` — error explanation
"""


@mcp.resource("db://schema/users")
def get_users_schema() -> str:
    """Database schema for the users table"""
    return """\
CREATE TABLE users (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(255) UNIQUE NOT NULL,
    role        VARCHAR(50)  NOT NULL DEFAULT 'viewer',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_users_email  ON users(email);
CREATE INDEX idx_users_role   ON users(role);
"""


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.prompt()
def code_review(language: str, code: str) -> str:
    """
    Structured code review prompt.

    Args:
        language: Programming language (python, js, etc.)
        code:     Code snippet to review
    """
    return f"""\
Please perform a thorough code review for the following {language} code.

**Code:**
```{language}
{code}
```

Review checklist:
1. **Correctness** — Does it do what it's supposed to?
2. **Edge cases** — What inputs could break it?
3. **Performance** — Any obvious bottlenecks?
4. **Security** — Any injection risks or exposed secrets?
5. **Style** — Does it follow {language} conventions?
6. **Suggestions** — Provide a refactored snippet if improvements are significant.
"""


@mcp.prompt()
def bug_report(title: str, steps: str, expected: str, actual: str) -> str:
    """
    Structured bug report template.

    Args:
        title:    Short description of the bug
        steps:    Steps to reproduce
        expected: Expected behaviour
        actual:   Actual behaviour
    """
    return f"""\
## Bug Report: {title}

**Steps to Reproduce:**
{steps}

**Expected Behaviour:**
{expected}

**Actual Behaviour:**
{actual}

Please analyse this bug report and:
1. Identify the likely root cause
2. Suggest a fix with code example
3. List any related edge cases to check
"""


@mcp.prompt()
def explain_error(error: str, context: str = "") -> str:
    """
    Explain an error message in plain English.

    Args:
        error:   The error message or traceback
        context: Optional surrounding code or context
    """
    ctx_block = f"\n**Context:**\n```\n{context}\n```" if context else ""
    return f"""\
Please explain the following error in plain English for a developer:

```
{error}
```
{ctx_block}

In your explanation:
1. What does this error mean?
2. What is the most common cause?
3. How do I fix it?
4. How do I prevent it in future?
"""


if __name__ == "__main__":
    mcp.run()
