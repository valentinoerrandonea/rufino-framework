from typing import Any
import yaml


class FrontmatterError(Exception):
    """Raised when frontmatter parsing or validation fails."""


def parse_frontmatter(note_text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body). Empty dict if no frontmatter present."""
    if not note_text.startswith("---\n"):
        return {}, note_text

    try:
        _, fm_block, body = note_text.split("---\n", 2)
    except ValueError:
        raise FrontmatterError("Frontmatter delimiter unterminated")

    try:
        fm = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError as e:
        raise FrontmatterError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(fm, dict):
        raise FrontmatterError("Frontmatter must be a mapping")

    return fm, body


def render_frontmatter(fm: dict[str, Any], body: str) -> str:
    """Render frontmatter + body to a markdown note string."""
    fm_yaml = yaml.safe_dump(fm, default_flow_style=False, sort_keys=True)
    return f"---\n{fm_yaml}---\n{body}"


def validate_against_schema(fm: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate frontmatter against output_schema declared in adapter manifest.

    Required fields must be present. Optional fields are not checked for presence.
    Type-level validation (date, list[str], etc.) is best-effort in v1.
    """
    required = schema.get("required", {})
    for field_name in required:
        if field_name not in fm:
            raise FrontmatterError(f"Required field missing: {field_name}")
