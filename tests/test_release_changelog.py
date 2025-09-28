from scripts.release import build_changelog


def test_build_changelog_no_tag():
    text = build_changelog("")
    assert "# Changelog" in text
    assert "Initial release" in text


