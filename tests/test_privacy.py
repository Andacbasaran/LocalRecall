"""Gizlilik filtresi birim testleri."""

from localrecall.capture.privacy import PrivacyFilter
from localrecall.capture.window_info import ActiveWindowInfo
from localrecall.config import DEFAULT_BLOCKED_PROCESSES, DEFAULT_BLOCKED_TITLE_KEYWORDS


def test_privacy_filter_blocks_password_managers_and_incognito():
    pf = PrivacyFilter(DEFAULT_BLOCKED_PROCESSES, DEFAULT_BLOCKED_TITLE_KEYWORDS)

    skip, reason = pf.should_skip(ActiveWindowInfo("Bitwarden.exe", "Bitwarden"))
    assert skip is True
    assert "bitwarden.exe" in reason

    skip, reason = pf.should_skip(ActiveWindowInfo("chrome.exe", "Yeni Sekme - Gizli - Google Chrome"))
    assert skip is True
    assert "gizli" in reason

    skip, reason = pf.should_skip(ActiveWindowInfo("msedge.exe", "Banka - InPrivate - Microsoft Edge"))
    assert skip is True
    assert "inprivate" in reason

    skip, reason = pf.should_skip(ActiveWindowInfo("Code.exe", "main.py - LocalRecall"))
    assert skip is False
    assert reason == ""
