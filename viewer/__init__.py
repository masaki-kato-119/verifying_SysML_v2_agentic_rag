"""SysML v2 Viewer。

sysml_v2_checker_advancedのSemantic Model（parse_sysml_with_semantic_model()/
build_semantic_model()）を入力に、構造図を描画するためのGraph IR / View IR /
SVGレンダラー / バックエンドAPI / フロントエンドを提供する。
SysMLv2_Viewer_実装仕様書.md参照。

sysml_v2_checker_advancedパッケージには依存を追加するが、逆方向の依存は無い
（Parser/Semantic Model側はViewerの存在を一切知らない）。
"""
