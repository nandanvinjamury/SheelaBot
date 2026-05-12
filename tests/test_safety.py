from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sheela.tools.safety import SafetyChecker, matches_glob

TZ = "America/New_York"


def _today() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")


# --- matches_glob ------------------------------------------------------


def test_glob_single_star_does_not_cross_separator():
    assert matches_glob("01 Daily/2026-05-12.md", "01 Daily/*.md")
    assert not matches_glob("01 Daily/sub/x.md", "01 Daily/*.md")


def test_glob_double_star_crosses_separators():
    assert matches_glob("06 Recipes/Dinner/x.md", "06 Recipes/**")
    assert matches_glob("06 Recipes/x.md", "06 Recipes/**")
    assert matches_glob(
        "09 Hobbies/Sport/Match log.md",
        "09 Hobbies/**/Match log.md",
    )
    assert matches_glob(
        "09 Hobbies/Match log.md", "09 Hobbies/**/Match log.md"
    )


def test_glob_escapes_special_chars():
    # Folder name contains spaces (no regex meaning) — still matches
    assert matches_glob("04 Money/Earnings.md", "04 Money/Earnings.md")


# --- SafetyChecker -----------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def checker(vault: Path) -> SafetyChecker:
    return SafetyChecker(vault_path=vault, tz=TZ)


def test_allows_inbox(checker: SafetyChecker):
    d = checker.check("Inbox.md")
    assert d.allowed
    assert "allowed" in d.reason.lower()


def test_allows_memory(checker: SafetyChecker):
    assert checker.check("Agent/MEMORY.md").allowed


def test_allows_recipes(checker: SafetyChecker):
    assert checker.check("06 Recipes/Dinner/Weeknight pasta.md").allowed
    assert checker.check("06 Recipes/Pantry.md").allowed


def test_allows_match_log(checker: SafetyChecker):
    assert checker.check("09 Hobbies/Sport/Match log.md").allowed


def test_confirms_people_notes(checker: SafetyChecker):
    d = checker.check("03 People/Family/Parent.md")
    assert not d.allowed
    assert d.needs_confirmation
    assert "confirmation" in d.reason


def test_confirms_persona_config(checker: SafetyChecker):
    d = checker.check("Agent/PERSONA.md")
    assert not d.allowed
    assert d.needs_confirmation


def test_confirmed_bypass_for_confirm_list(checker: SafetyChecker):
    assert checker.check(
        "03 People/Family/Parent.md", confirmed=True
    ).allowed


def test_confirmed_bypass_does_not_apply_to_deny(checker: SafetyChecker):
    d = checker.check(".git/config", confirmed=True)
    assert not d.allowed
    assert "off-limits" in d.reason


def test_path_traversal_blocked(checker: SafetyChecker):
    d = checker.check("../escape.md")
    assert not d.allowed
    assert "escape" in d.reason.lower()


def test_daily_today_append_allowed(checker: SafetyChecker):
    today_path = f"01 Daily/{_today()}.md"
    d = checker.check(today_path, operation="append")
    assert d.allowed


def test_daily_today_overwrite_denied(checker: SafetyChecker):
    today_path = f"01 Daily/{_today()}.md"
    d = checker.check(today_path, operation="overwrite")
    assert not d.allowed
    assert "append-only" in d.reason


def test_daily_other_day_denied(checker: SafetyChecker):
    d = checker.check("01 Daily/2020-01-01.md", operation="append")
    assert not d.allowed
    assert "today" in d.reason.lower()


def test_daily_denial_not_overridable_by_confirmed(checker: SafetyChecker):
    # Hard restriction — confirmed=True does NOT lift the today-only / append-only rules
    d = checker.check("01 Daily/2020-01-01.md", operation="append", confirmed=True)
    assert not d.allowed


def test_uncategorized_path_requires_confirmation(checker: SafetyChecker):
    d = checker.check("Career/Day job/randomly_invented.md")
    assert not d.allowed
    assert d.needs_confirmation
    # And confirmed=True allows it through
    assert checker.check(
        "Career/Day job/randomly_invented.md", confirmed=True
    ).allowed


def test_channel_allowlist_supplements_global(vault: Path):
    class FakeRouter:
        def get_writable_paths(self, channel):
            if channel == "#side-project":
                return ["08 Career/Side project/**"]
            return []

    c = SafetyChecker(
        vault_path=vault,
        tz=TZ,
        channel_router=FakeRouter(),  # type: ignore[arg-type]
    )
    # Not allowed globally; allowed for #side-project
    assert not c.check("08 Career/Side project/Kanban.md").allowed
    assert c.check(
        "08 Career/Side project/Kanban.md", channel="#side-project"
    ).allowed
