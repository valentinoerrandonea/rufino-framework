from dataclasses import dataclass
from pathlib import Path
from typing import Any
from jinja2 import Environment, BaseLoader, StrictUndefined

from rufino.engine.process.helpers.frontmatter import (
    parse_frontmatter,
    FrontmatterError,
)


class TemplateError(Exception):
    """Raised when template parsing or rendering fails."""


@dataclass(frozen=True)
class QuestionTemplate:
    template_name: str
    required_context: tuple[str, ...]
    expected_answer: str
    body_template: str  # markdown after the frontmatter


_ENV = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=False)


def parse_template_file(path: Path) -> QuestionTemplate:
    text = path.read_text()
    try:
        fm, body = parse_frontmatter(text)
    except FrontmatterError as e:
        raise TemplateError(f"Template {path}: {e}") from e
    if not fm:
        raise TemplateError(f"Template {path} missing frontmatter")

    for required in ("template_name", "required_context", "expected_answer"):
        if required not in fm:
            raise TemplateError(f"Template {path} missing frontmatter field: {required}")

    return QuestionTemplate(
        template_name=fm["template_name"],
        required_context=tuple(fm["required_context"]),
        expected_answer=fm["expected_answer"],
        body_template=body,
    )


def render_question(template: QuestionTemplate, *, context: dict[str, Any]) -> str:
    missing = [c for c in template.required_context if c not in context]
    if missing:
        raise TemplateError(f"Missing required context: {missing}")
    tmpl = _ENV.from_string(template.body_template)
    return tmpl.render(**context)
