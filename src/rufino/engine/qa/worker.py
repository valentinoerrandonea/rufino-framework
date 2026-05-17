import logging
from pathlib import Path
from typing import Callable

from rufino.engine.process.helpers.frontmatter import FrontmatterError
from rufino.engine.qa.store import QuestionStore, QuestionStoreError
from rufino.engine.qa.callback_registry import CallbackRegistry


_log = logging.getLogger(__name__)


def poll_and_dispatch(
    *,
    vault_root: Path,
    state_dir: Path,
    handler: Callable,
) -> int:
    """For every question with answer present, invoke handler() and mark answered.

    Crash semantics:
    - If `get_answer` raises (malformed YAML, bareword answer, traversal),
      that single file is skipped with a warning. Other questions still run.
    - If `handler` raises, the callback stays in the registry and the
      question file stays in `questions/` so the next poll can retry.

    Returns the number of callbacks dispatched successfully.
    """
    store = QuestionStore(vault_root / "questions")
    registry = CallbackRegistry(state_dir / "callbacks.json")
    dispatched = 0

    questions_dir = vault_root / "questions"
    if not questions_dir.exists():
        return 0

    for p in questions_dir.glob("*.md"):
        if not p.is_file():
            continue
        slug = p.stem

        try:
            answer = store.get_answer(slug)
        except (QuestionStoreError, FrontmatterError) as e:
            _log.warning("skipping %s: %s", slug, e)
            continue

        if answer is None:
            continue

        cb = registry.get(slug)
        if cb is None:
            _log.warning(
                "answered question %s has no registered callback; skipping", slug
            )
            continue

        try:
            handler(
                adapter_name=cb.adapter_name,
                adapter_state=cb.adapter_state,
                answer=answer,
            )
        except Exception:
            _log.exception("handler failed for slug=%s; leaving for retry", slug)
            continue

        # Mark answered BEFORE deleting the callback. If we crash between the
        # two steps the worst case is a duplicate dispatch on retry, which is
        # recoverable. The opposite order silently drops the user's answer.
        store.mark_answered(slug)
        registry.delete(slug)
        dispatched += 1

    return dispatched
