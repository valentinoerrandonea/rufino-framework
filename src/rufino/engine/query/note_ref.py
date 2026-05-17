from dataclasses import dataclass


@dataclass(frozen=True)
class NoteRef:
    relative_path: str
    score: float = 1.0
