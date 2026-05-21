"""Tests for the soffice-availability helper used by `process-batch --multimodal`."""
from unittest.mock import patch

import pytest

from rufino.runtime.prereq_checker import check_soffice_available


def test_check_soffice_returns_true_when_present():
    with patch("shutil.which", return_value="/opt/homebrew/bin/soffice"):
        available, msg = check_soffice_available()
    assert available is True
    assert "soffice" in msg.lower()


def test_check_soffice_returns_false_when_absent():
    with patch("shutil.which", return_value=None):
        available, msg = check_soffice_available()
    assert available is False
    msg_low = msg.lower()
    assert "libreoffice" in msg_low or "brew install" in msg_low


def test_check_soffice_message_is_actionable_when_missing():
    """The message must include the install command so the user can copy-paste."""
    with patch("shutil.which", return_value=None):
        _, msg = check_soffice_available()
    assert "brew install" in msg
