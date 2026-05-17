"""Stub fetcher that returns a list of (filename, content) pairs."""

CANNED = [
    ("clase4-svm.md", "Apunte crudo de SVM."),
    ("clase5-trees.md", "Apunte crudo de decision trees."),
]


def fetch(since: str | None) -> list[dict]:
    return [{"filename": fn, "content": c} for fn, c in CANNED]
