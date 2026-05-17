from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
from jinja2 import Environment, BaseLoader, StrictUndefined


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
    if not text.startswith("---\n"):
        raise TemplateError(f"Template {path} missing frontmatter")
    try:
        _, fm_block, body = text.split("---\n", 2)
    except ValueError:
        raise TemplateError(f"Template {path} unterminated frontmatter")

    fm = yaml.safe_load(fm_block) or {}
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
