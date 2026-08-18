"""Contract tests for the native Google Docs inline comment workflow."""

from pathlib import Path


SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "google-docs-inline-comments"
    / "SKILL.md"
)


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_inline_comment_skill_is_discoverable() -> None:
    text = _skill_text()
    assert text.startswith("---\nname: google-docs-inline-comments\n")
    assert "description:" in text.split("---", 2)[1]


def test_inline_comment_skill_keeps_native_anchor_safeguards() -> None:
    text = _skill_text()
    assert "drive_comment_add` creates a file level comment" in text
    assert "browser:control-in-app-browser" in text
    assert "Prefer connected Chrome" in text
    assert "explicitly approves" in text
    assert "existing comment IDs" in text
    assert "visible confirmation from Docs" in text
    assert "to start\n   with `kix.`" in text
    assert "Do not retry submission" in text
