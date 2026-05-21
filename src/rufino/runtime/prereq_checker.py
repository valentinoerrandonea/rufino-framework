"""Prereq checker: report whether system tools and Python version are present.

Used by the wizard to decide which features can be offered to the user
(e.g. embeddings need Ollama, WhatsApp ingest needs Node).
"""
import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PrereqCheck:
    name: str
    kind: str          # "command" | "python_min_version"
    target: str        # command name or version string
    for_feature: str   # human-readable label for messages


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str


def check_prereq(check: PrereqCheck) -> CheckResult:
    if check.kind == "command":
        path = shutil.which(check.target)
        if path:
            return CheckResult(ok=True, message=f"{check.target} found at {path}")
        return CheckResult(
            ok=False,
            message=f"{check.target!r} not installed — required for {check.for_feature}",
        )

    if check.kind == "python_min_version":
        major, minor = (int(x) for x in check.target.split("."))
        if sys.version_info >= (major, minor):
            return CheckResult(
                ok=True,
                message=f"python {sys.version_info[0]}.{sys.version_info[1]}",
            )
        return CheckResult(
            ok=False,
            message=f"python {check.target}+ required for {check.for_feature}",
        )

    raise ValueError(f"Unknown check kind: {check.kind!r}")


BUILT_IN_CHECKS: tuple[PrereqCheck, ...] = (
    PrereqCheck(name="ollama", kind="command", target="ollama",
                for_feature="embeddings"),
    PrereqCheck(name="security_cli", kind="command", target="security",
                for_feature="Keychain secrets (macOS)"),
    PrereqCheck(name="node", kind="command", target="node",
                for_feature="WhatsApp ingestor"),
    PrereqCheck(name="python311", kind="python_min_version", target="3.11",
                for_feature="transform hooks"),
    PrereqCheck(name="gh_cli", kind="command", target="gh",
                for_feature="GitHub ingestor"),
    PrereqCheck(name="ripgrep", kind="command", target="rg",
                for_feature="lexical search performance"),
    PrereqCheck(name="soffice", kind="command", target="soffice",
                for_feature="multimodal DOCX/PPTX processing"),
)


def check_soffice_available() -> tuple[bool, str]:
    """Convenience wrapper used by ``process-batch --multimodal`` to fail fast
    when LibreOffice is not installed.

    Returns ``(available, human_message)``. The message is actionable when
    missing — it includes the macOS install command so users can copy-paste.
    """
    path = shutil.which("soffice")
    if path:
        return True, f"soffice found at {path}"
    return False, (
        "soffice not found in PATH — multimodal mode requires LibreOffice. "
        "Install on macOS with: brew install --cask libreoffice"
    )
