"""Code cross-check: source-scanning for OCR verification."""

from __future__ import annotations

from vi3ion.code_verify import build_index, find_code_matches


def _make_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.tsx").write_text(
        'export const COPY = { hero: "TOOLS OTHER PEOPLE WISH EXISTED." };\n'
        'const TAGS = ["学習", "三角"];\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "# Demo project\nThis line mentions positionsates.\n",
        encoding="utf-8",
    )
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "junk.js").write_text('const x = "hidden";\n', encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text('const x = "dependency";\n', encoding="utf-8")
    return tmp_path


def test_index_finds_literal_in_source(tmp_path):
    repo = _make_repo(tmp_path)
    index = build_index([repo])
    matches = find_code_matches("TOOLS OTHER PEOPLE WISH EXISTED.", index)
    assert matches
    assert matches[0].file == "app.tsx"
    assert matches[0].score == 1.0


def test_index_matches_kanji_literal(tmp_path):
    repo = _make_repo(tmp_path)
    index = build_index([repo])
    matches = find_code_matches("学習", index)
    assert any(m.snippet == "学習" for m in matches)


def test_skip_dirs_excluded(tmp_path):
    repo = _make_repo(tmp_path)
    index = build_index([repo])
    snippets = [m.snippet for m in find_code_matches("hidden", index)] + \
        [m.snippet for m in find_code_matches("dependency", index)]
    assert "hidden" not in snippets
    assert "dependency" not in snippets


def test_no_match_returns_empty(tmp_path):
    repo = _make_repo(tmp_path)
    index = build_index([repo])
    assert find_code_matches("zzz nothing like this", index) == []
