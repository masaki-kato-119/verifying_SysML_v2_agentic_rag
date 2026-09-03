"""SysML v2 Viewer バックエンド（SysMLv2_Viewer_実装仕様書.md 7章）。

FastAPIによるローカルWebサーバー。viewer/graph_ir.py・view_ir.py・
svg_renderer.pyと、既存のsysml_v2_checker_advanced.semantic_modelを
呼ぶだけの薄い層に保つ（7.2節：ロジックはコアライブラリ側に置き、
ここでは重複させない）。
"""
