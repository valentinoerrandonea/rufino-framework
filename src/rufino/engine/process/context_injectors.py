import re
from dataclasses import dataclass, field
from typing import Protocol


class QueryLayer(Protocol):
    def run(self, query_string: str) -> list[str]: ...


@dataclass
class StubQueryLayer:
    canned_results: dict[str, list[str]] = field(default_factory=dict)

    def run(self, query_string: str) -> list[str]:
        return self.canned_results.get(query_string, [])


_VAR_RE = re.compile(r"<(\w+)>")


def apply_context_injectors(
    *,
    injectors: list[dict],
    variables: dict[str, str],
    query: QueryLayer,
) -> dict[str, str]:
    """Render each injector's query with `variables`, run via Query layer, collect results.

    If a variable in the query is missing from `variables`, the injector returns a
    placeholder string instead of failing — this lets the LLM proceed with partial context.
    """
    context: dict[str, str] = {}
    for inj in injectors:
        name = inj["name"]
        template = inj["query"]
        missing = [m.group(1) for m in _VAR_RE.finditer(template) if m.group(1) not in variables]
        if missing:
            context[name] = "(unable to resolve query — missing variables)"
            continue
        rendered = _VAR_RE.sub(lambda m: variables[m.group(1)], template)
        results = query.run(rendered)
        context[name] = "\n".join(f"- {r}" for r in results) if results else "(no results)"
    return context
