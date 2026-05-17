import uuid
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.qa.template import parse_template_file, render_question
from rufino.engine.qa.store import QuestionStore
from rufino.engine.qa.callback_registry import CallbackRegistry, PendingCallback


class QALoopError(Exception):
    """Raised on unsafe template_name, missing template, or contract violations."""


@dataclass
class QALoopAPI:
    vault_root: Path
    templates_dir: Path
    state_dir: Path

    def __post_init__(self) -> None:
        self._store = QuestionStore(self.vault_root / "questions")
        self._registry = CallbackRegistry(self.state_dir / "callbacks.json")

    def ask_user(
        self,
        *,
        template_name: str,
        context: dict,
        adapter_name: str,
        adapter_state: dict,
    ) -> str:
        """Render a question to the vault and register a pending callback.

        Returns the question slug. The same slug is later resolved by
        `get_answer` even after the file is moved to `questions/answered/`.
        """
        template_path = self._resolve_template_path(template_name)
        if not template_path.exists():
            raise QALoopError(f"template not found: {template_name!r}")
        template = parse_template_file(template_path)

        body = render_question(template, context=context)
        slug = f"{template.template_name}-{uuid.uuid4().hex[:8]}"
        self._store.write_question(
            slug=slug,
            template_name=template.template_name,
            body=body,
        )
        self._registry.register(PendingCallback(
            question_slug=slug,
            adapter_name=adapter_name,
            adapter_state=adapter_state,
        ))
        return slug

    def get_answer(self, slug: str) -> str | None:
        """Return the user's answer, or None if still pending.

        Reads from `questions/<slug>.md` first; falls back to
        `questions/answered/<slug>.md` after the worker has moved the file.
        Raises `QuestionStoreError` if the file contains a malformed answer
        (e.g. unquoted YAML bareword that parsed as bool / int / date).
        """
        return self._store.get_answer(slug)

    def _resolve_template_path(self, template_name: str) -> Path:
        candidate = (
            self.templates_dir / f"{template_name.replace('_', '-')}.md"
        ).resolve()
        root = self.templates_dir.resolve()
        # Reject escape AND reject subdirectory components (template_name
        # must map to a flat filename directly under templates_dir).
        if candidate.parent != root:
            raise QALoopError(
                f"template_name must be flat (no path components or traversal): "
                f"{template_name!r}"
            )
        return candidate
