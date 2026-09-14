"""Findingの影響範囲（構想書§14「対象・根拠・影響範囲・修正候補を同一画面で」）。

2026-09-14にフロントエンド（viewer/frontend/app.js）から移設した。移設の理由:

- 走査の意味論（エッジ種別ごとの伝播方向）はこのプロジェクトで最も回帰が
  分かりにくい部分なのに、フロント側では**自動テストが無く**、ブラウザのDOM
  確認でしか触れていなかった（描画は見えるが走査結果の正しさは見えない）。
- JS側にテスト基盤を入れるには1,198行のクラシックスクリプトにexport境界を
  切る必要があり、そのリファクタリング自体がリスク。Python側なら既存のpytestが
  そのまま使える。
- フロントでは同じ走査が2箇所（Finding一覧とSVGハイライト）から呼ばれていた。
  片方だけ移すと二重実装になるため、全ノード分をここで一度に計算して返す。
"""

from typing import Dict, List

# 影響が伝播する向きはエッジ種別ごとに違う。`semantic_model.py`の`_make_edge`は
# from=宣言している側・to=参照先 でエッジを作るので、種別によって辿る向きが変わる。
# 2026-09-07に参照実装の意味論と突き合わせて決めた（詳細は各コメント）。
IMPACT_DIRECTION = {
    # 宣言はその参照先に依存する。`x : T`のTが変われば x が影響を受けるので、
    # 影響はエッジを**逆に**辿る。
    "specialization": "reverse",
    "subsetting": "reverse",
    "redefinition": "reverse",
    "feature_typing": "reverse",
    # `satisfy R by X` / `verify R by X` の`by`側（=X）が変われば、その
    # 充足・検証の主張が影響を受ける。これも宣言→参照先なので逆向き。
    "satisfy": "reverse",
    "verify": "reverse",
    # 振る舞いの流れは from=source なので、エッジの向きがそのまま影響の向き。
    "transition": "forward",
    "succession": "forward",
    "flow": "forward",
    # コネクタはどちらが上流と言えない（`c connect a to b`のエッジは c→a と
    # c→b で、a と b の間に上下は無い）。無向のまま扱う。
    "connection": "both",
}

# 未知の種別（将来エッジ種別が増えたとき）は無向として扱う。取りこぼすより
# 広く見せる方が、影響範囲の用途では安全側。
IMPACT_DIRECTION_DEFAULT = "both"

# 何次先まで辿るか。
#
# `graph_ir.py`の`_VERIFICATION_VIEW_DEPTH`とは**意図的に別の定数**にしてある。
# 検証ビューの深さは「図にどれだけ文脈を描くか」、こちらは「変更が何を壊しうるか」
# の話で、揃える理由がない。以前は「同じ値」というコメントで結び付けていたが、
# 片方を動かすともう片方の絞り込みが黙って変わるため独立させた。
IMPACT_DEPTH = 2


def impact_origin_id(element_id: str) -> str:
    """Findingのelement_idを、影響範囲の起点になる要素idへ寄せる。

    Findingは要素そのものではなく**その中の参照**（無名ノード）に付くことがあり、
    その種のidはGraph IRに存在しない（`graph_ir.py`の`_is_graph_node_type`が
    式・参照等の構造補助ノードを描画対象から外している）。無名ノードのstable_idは
    `<所有者のid>/<型>#<連番>`という形（`antlr_transformer.py`）なので、最初の
    `/`より前を取れば所有者になる。
    """
    if not element_id:
        return ""
    separator = element_id.find("/")
    return element_id if separator == -1 else element_id[:separator]


def build_impact_adjacency(edges: List[Dict]) -> Dict[str, Dict[str, set]]:
    """`{from_id: {to_id: {kind, ...}}}` の隣接表を伝播方向に従って作る。"""
    adjacency: Dict[str, Dict[str, set]] = {}

    def link(source: str, target: str, kind: str) -> None:
        adjacency.setdefault(source, {}).setdefault(target, set()).add(kind)

    for edge in edges:
        kind = edge.get("kind")
        direction = IMPACT_DIRECTION.get(kind, IMPACT_DIRECTION_DEFAULT)
        source, target = edge.get("from"), edge.get("to")
        if source is None or target is None:
            continue
        if direction in ("forward", "both"):
            link(source, target, kind)
        if direction in ("reverse", "both"):
            link(target, source, kind)
    return adjacency


def find_impacted_elements(
    adjacency: Dict[str, Dict[str, set]], origin_id: str, depth: int = IMPACT_DEPTH
) -> List[Dict]:
    """`origin_id`から`depth`次までの影響先を近い順に返す。

    各要素は`{"id", "distance", "kinds"}`。距離と経路の種別を持たせているのは、
    Inspectorが「何次で、何を通じて影響するのか」まで見せられるようにするため
    （ハイライトだけでは読めない）。
    """
    if not origin_id:
        return []
    impacted: List[Dict] = []
    visited = {origin_id}
    frontier = [origin_id]
    for distance in range(1, depth + 1):
        if not frontier:
            break
        next_frontier = []
        for node_id in frontier:
            for neighbor, kinds in sorted((adjacency.get(node_id) or {}).items()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_frontier.append(neighbor)
                impacted.append(
                    {"id": neighbor, "distance": distance, "kinds": sorted(kinds)}
                )
        frontier = next_frontier
    return impacted


def build_impact_map(graph_ir: Dict, depth: int = IMPACT_DEPTH) -> Dict[str, List[Dict]]:
    """Graph IRの全ノードについて影響範囲を求める。

    Findingごとに計算せず全ノード分を一度に返すのは、フロント側で
    「Finding一覧」と「選択要素のハイライト」の2箇所が同じ走査を必要とし、
    片方だけ移すと二重実装に戻るため。パース+lintが支配的なコスト
    （1万要素で約10秒）なので、深さ2のBFSを全ノードに回す分は誤差。
    """
    adjacency = build_impact_adjacency(graph_ir.get("edges") or [])
    return {
        node["id"]: find_impacted_elements(adjacency, node["id"], depth)
        for node in graph_ir.get("nodes") or []
    }
