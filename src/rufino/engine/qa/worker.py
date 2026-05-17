import logging
from pathlib import Path
from typing import Callable

from rufino.engine.qa.store import QuestionStore
from rufino.engine.qa.callback_registry import CallbackRegistry


_log = logging.getLogger(__name__)


def poll_and_dispatch(
    *,
    vault_root: Path,
    state_dir: Path,
    handler: Callable,
) -> int:
    """For every question with answer present, invoke handler() and mark answered.

    The handler is invoked BEFORE the callback is consumed from the registry
    so that a handler crash leaves the question + callback intact for retry.

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
        answer = store.get_answer(slug)
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

        # Handler succeeded — only now consume the callback and archive the file.
        registry.consume(slug)
        store.mark_answered(slug)
        dispatched += 1

    return dispatched
