import pytest
from pathlib import Path
from rufino.runtime.sandbox import (
    run_transform_hook,
    SandboxResult,
    SandboxTimeout,
    SandboxHookFailed,
)


FIXTURES = Path(__file__).parent / "fixtures" / "hooks"


def test_echo_hook_roundtrip():
    result = run_transform_hook(
        hook_path=FIXTURES / "echo_transform.py",
        input_data={"hello": "world"},
        timeout_seconds=10,
        allow_network=False,
    )
    assert isinstance(result, SandboxResult)
    assert result.output == {"hello": "world", "echoed": True}
    assert result.error is None


def test_timeout_enforced():
    with pytest.raises(SandboxTimeout):
        run_transform_hook(
            hook_path=FIXTURES / "slow_transform.py",
            input_data={},
            timeout_seconds=1,
            allow_network=False,
        )


def test_network_hook_runs_without_raising():
    """The sandbox's network restriction is best-effort (PATH-stripped subprocess),
    not a hard firewall. This test only asserts the hook executes cleanly and
    returns a well-formed JSON payload, NOT that network was actually blocked.
    Real network isolation would require a network namespace (Linux) or a
    pf-rule (macOS), neither portable here.
    """
    result = run_transform_hook(
        hook_path=FIXTURES / "network_transform.py",
        input_data={},
        timeout_seconds=5,
        allow_network=False,
    )
    assert isinstance(result.output, dict)
    assert "network_ok" in result.output or "network_error" in result.output


def test_missing_hook_raises_clear_error(tmp_path: Path):
    with pytest.raises(SandboxHookFailed, match="not found"):
        run_transform_hook(
            hook_path=tmp_path / "nonexistent.py",
            input_data={},
            timeout_seconds=5,
            allow_network=False,
        )


def test_timeout_value_out_of_range_raises():
    with pytest.raises(ValueError):
        run_transform_hook(
            hook_path=FIXTURES / "echo_transform.py",
            input_data={},
            timeout_seconds=0,
            allow_network=False,
        )
    with pytest.raises(ValueError):
        run_transform_hook(
            hook_path=FIXTURES / "echo_transform.py",
            input_data={},
            timeout_seconds=301,
            allow_network=False,
        )
