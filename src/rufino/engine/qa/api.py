import uuid
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.qa.template import parse_template_file, render_question
from rufino.engine.qa.store import QuestionStore
from rufino.engine.qa.callback_registry import CallbackRegistry, PendingCallback


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

        Returns the question slug.
        """
        template_path = self.templates_dir / f"{template_name.replace('_', '-')}.md"
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
        return self._store.get_answer(slug)
