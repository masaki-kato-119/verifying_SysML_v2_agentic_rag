"""複数ファイルのモデル: 一緒に検証するほかの .sysml を集めて AST にする。

参照実装（sysml-mcp-server の validate_sysml）と同じ決まりにする。

- file_path だけ: 同じフォルダの .sysml（サブフォルダは含めない）を一緒に読む。
- directory: フォルダの中（サブフォルダも含む）の .sysml をすべて一緒に読む。"" なら読まない。
- 構文エラーのファイルは読まない（参照実装もそのファイルの要素をほかのファイルから見せない）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set

from .parser import parse_sysml


@dataclass
class OtherFiles:
    asts: List[dict] = field(default_factory=list)
    loaded: List[str] = field(default_factory=list)  # 一緒に読んだファイル
    unparsable: List[str] = field(default_factory=list)  # 構文エラーで読めなかったファイル


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
            ast = parse_sysml(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            out.unparsable.append(label)
            continue
        if not isinstance(ast, dict) or ast.get("type") == "error":
            out.unparsable.append(label)
            continue
        out.asts.append(ast)
        out.loaded.append(label)
    return out


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
