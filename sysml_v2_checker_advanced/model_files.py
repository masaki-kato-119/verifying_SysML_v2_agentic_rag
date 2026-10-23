"""複数ファイルのモデル: 一緒に検証するほかの .sysml を集めて AST にする。

参照実装（sysml-mcp-server の validate_sysml）と同じ決まりにする。

- file_path だけ: 同じフォルダの .sysml（サブフォルダは含めない）を一緒に読む。
- directory: フォルダの中（サブフォルダも含む）の .sysml をすべて一緒に読む。"" なら読まない。
- 構文エラーのファイルは、エラー回復で読めた部分を使う（参照実装も回復で読めた部分の要素をほかのファイルに
  見せる。2026-10-22）。回復した木も作れなければ読まない。回復の仕方は参照実装（Xtext）と ANTLR で違うので、
  どの要素が残るかは一致しない（ANTLR の方が多く残しやすい）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from .antlr_transformer import parse_sysml_with_semantic_model_recovering


@dataclass
class OtherFiles:
    asts: List[dict] = field(default_factory=list)
    loaded: List[str] = field(default_factory=list)  # 一緒に読んだファイル
    partial: List[str] = field(default_factory=list)  # 構文エラーがあり、回復で読めた部分だけ使ったファイル
    unparsable: List[str] = field(default_factory=list)  # 回復しても読めなかったファイル


def model_files(file_path: Optional[str] = None, directory: Optional[str] = None) -> List[Path]:
    """一緒に検証するファイル（file_path 自身は除く）。"""
    if directory == "":
        return []
    target = Path(file_path).resolve() if file_path else None
    if directory is not None:
        files = sorted(Path(directory).rglob("*.sysml"))
    elif target is not None:
        files = sorted(target.parent.glob("*.sysml"))
    else:
        return []
    return [f for f in files if f.resolve() != target]


def load_other_files(paths: Iterable[Path], base: Optional[Path] = None) -> OtherFiles:
    out = OtherFiles()
    for path in paths:
        label = str(path.relative_to(base)) if base is not None and path.is_relative_to(base) else str(path)
        try:
            ast, errors = parse_other_file(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            ast, errors = None, []
        if ast is None:
            out.unparsable.append(label)
            continue
        out.asts.append(ast)
        out.loaded.append(label)
        if errors:
            out.partial.append(label)
    return out


def parse_other_file(text: str) -> Tuple[Optional[dict], List[str]]:
    """一緒に読むファイルの (AST, 構文エラー)。構文エラーがあれば、AST は回復で読めた部分（読めなければ None）。"""
    ast, _model, errors = parse_sysml_with_semantic_model_recovering(text)
    if not isinstance(ast, dict) or ast.get("type") == "error":
        return None, errors
    return ast, errors


def declared_names(asts: Iterable[dict]) -> Set[str]:
    """AST の中で宣言されたすべての名前（平らな名前表のルールが、ほかのファイルの型を知るため）。"""
    names: Set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("name"), str):
                names.add(node["name"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for ast in asts:
        walk(ast)
    return names
