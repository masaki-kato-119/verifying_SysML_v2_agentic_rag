"""SysML v2 パーサーのコーパス回帰テスト。

tests/fixtures/sysml_corpus/ 配下の .sysml ファイルを使い、パーサーの
現在の能力を固定する。

- working/    : 正しくパースでき、かつlintがクラッシュしない構文。退行したら失敗させる。
- known_broken/: 現在パースできない既知の欠陥（sysml_v2_checker_advanced/COVERAGE.md
                 参照）。フェーズ4（ANTLR4移植完了）時点では空になっているが、
                 今後新たに発見された未対応構文の最小再現ケースを追加する場所として
                 引き続き使う。「まだ壊れていること」を明示的に検証するため、直ると
                 このテストの方が失敗する形で「known_broken から working へ
                 移動すべき」ことを自動的に知らせる。
"""

from pathlib import Path

import pytest

from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "sysml_corpus"
WORKING_FILES = sorted((CORPUS_DIR / "working").glob("*.sysml"))
KNOWN_BROKEN_FILES = sorted((CORPUS_DIR / "known_broken").glob("*.sysml"))


@pytest.mark.parametrize("path", WORKING_FILES, ids=lambda p: p.stem)
def test_working_corpus_parses_successfully(path: Path):
    text = path.read_text(encoding="utf-8")
    ast = parse_sysml(text, strict=True)
    assert ast.get("type") != "error", (
        f"{path.name} は working/ に分類されているのにパースエラーになった: "
        f"{ast.get('message')}"
    )


@pytest.mark.parametrize("path", WORKING_FILES, ids=lambda p: p.stem)
def test_working_corpus_lint_does_not_crash(path: Path):
    """linter.py が working/ の全ケースを例外なく処理できることを確認する
    （無修正で使い回す契約の検証。具体的なissue内容までは問わない）。"""
    text = path.read_text(encoding="utf-8")
    ast = parse_sysml(text, strict=True)
    lint_sysml(ast)


@pytest.mark.parametrize("path", KNOWN_BROKEN_FILES, ids=lambda p: p.stem)
def test_known_broken_corpus_still_fails(path: Path):
    """まだ直っていないことを固定する（直ったら XPASS でこのテストが落ちる）。"""
    text = path.read_text(encoding="utf-8")
    ast = parse_sysml(text, strict=True)
    if ast.get("type") != "error":
        pytest.fail(
            f"{path.name} が想定外にパースできるようになった。"
            f"known_broken/ から working/ へ移動し、"
            f"sysml_v2_checker_advanced/COVERAGE.md を更新すること。"
        )
