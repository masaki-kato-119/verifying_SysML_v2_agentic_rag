"""scripts/sysml_to_svg.py の新規ユニットテスト（SysMLv2_Viewer_実装仕様書.md 5.4章）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sysml_to_svg import sysml_text_to_svg  # noqa: E402


def test_valid_text_produces_svg():
    svg = sysml_text_to_svg("package P { part def A; }")
    assert svg.startswith("<svg")
    assert 'data-element-id="$root::A"' in svg


def test_parse_error_raises_value_error():
    with pytest.raises(ValueError, match="パースエラー"):
        sysml_text_to_svg("this is not valid sysml {{{")
