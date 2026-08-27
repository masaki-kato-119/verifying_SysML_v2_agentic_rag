"""検索経路の「高コストな操作の回数」を固定する性能回帰テスト。

実測レイテンシではなく呼び出し回数を検証する。壁時計時間は実行環境で揺れるため
CI で不安定になるが、「候補 1 件ごとに API を呼ぶ」「毎回モデルをロードする」
といった性能劣化は回数で決定的に検出できる。

背景: 蓄積された実測データでは use_graph=1 かつ use_rerank=1 の構成が
平均 51 秒・最大 127 秒かかっていた。原因特定には至っていないが、
この種の退行を今後は検出できるようにする。
"""

import rag.search as search_mod
import rag.search_diversity as search_diversity_mod
from rag.search import HybridSearchResult, Reranker, _apply_mmr, get_global_reranker


def _result(chunk_id: str, text: str, score: float) -> HybridSearchResult:
    return HybridSearchResult(
        chunk_id=chunk_id,
        text=text,
        metadata={},
        score_hybrid=score,
    )


class _FakeCrossEncoder:
    """predict の呼び出し回数と 1 回あたりのペア数を記録するスタブ。"""

    def __init__(self):
        self.call_count = 0
        self.batch_sizes = []

    def predict(self, pairs):
        self.call_count += 1
        self.batch_sizes.append(len(pairs))
        # 入力順に降順スコアを返す（並べ替えの検証用）
        return [float(len(pairs) - i) for i in range(len(pairs))]


def test_rerank_scores_all_candidates_in_a_single_batch():
    """リランクは候補数によらず predict を 1 回だけ呼ぶ（バッチ処理）。

    1 候補ずつ predict を呼ぶ実装に退行すると、候補数に比例して
    モデル推論のオーバーヘッドが増える。
    """
    reranker = Reranker.__new__(Reranker)  # __init__ はモデルをロードするため回避
    fake = _FakeCrossEncoder()
    reranker.model = fake

    candidates = [_result(f"c{i}", f"text {i}", score=1.0) for i in range(40)]
    out = reranker.rerank(query="q", candidates=candidates, top_k=10)

    assert fake.call_count == 1, "predict は 1 回のバッチ呼び出しであるべき"
    assert fake.batch_sizes == [40], "全候補が 1 バッチで渡されるべき"
    assert len(out) == 10
    assert out[0].score_rerank >= out[-1].score_rerank


def test_rerank_empty_candidates_does_not_invoke_model():
    """候補が空ならモデルを呼ばない。"""
    reranker = Reranker.__new__(Reranker)
    fake = _FakeCrossEncoder()
    reranker.model = fake

    assert reranker.rerank(query="q", candidates=[], top_k=5) == []
    assert fake.call_count == 0


def test_global_reranker_is_loaded_only_once(monkeypatch):
    """get_global_reranker はプロセス内で 1 度しかモデルを生成しない。

    検索のたびに CrossEncoder をロードする実装に戻ると、1 回あたり
    数十秒のロード時間が加算される。
    """
    monkeypatch.setattr(search_mod, "_GLOBAL_RERANKER", None)
    instantiations = []

    class _StubReranker:
        def __init__(self):
            instantiations.append(1)

    monkeypatch.setattr(search_mod, "Reranker", _StubReranker)

    first = get_global_reranker()
    second = get_global_reranker()

    assert first is second
    assert len(instantiations) == 1


def test_mmr_embeds_candidates_in_one_batch_request(monkeypatch):
    """MMR は候補の埋め込みをバッチ API で 1 回にまとめる。

    候補ごとに embed_text を呼ぶ実装（実測で候補 40 件 = 41 往復、
    MMR だけで 10.5 秒 = 検索全体の 93%）への退行を検出する。
    """
    single_calls = []
    batch_calls = []

    def fake_embed(text: str):
        single_calls.append(text)
        return [float(len(text) % 7), float(len(text) % 5), 1.0]

    def fake_embed_batch(texts):
        texts = list(texts)
        batch_calls.append(len(texts))
        return [[float(len(t) % 7), float(len(t) % 5), 1.0] for t in texts]

    monkeypatch.setattr(search_diversity_mod, "embed_text", fake_embed)
    monkeypatch.setattr(search_diversity_mod, "embed_texts", fake_embed_batch)

    results = [_result(f"c{i}", f"text-{'x' * i}", score=1.0 - i * 0.01) for i in range(40)]
    out = _apply_mmr(results, query="query", lambda_param=0.5, top_k=10)

    assert batch_calls == [40], f"候補は 1 バッチで取得すべきだが {batch_calls}"
    assert single_calls == ["query"], (
        f"個別の embed_text はクエリの 1 回だけのはずが {len(single_calls)} 回"
    )
    assert len(out) == 10


def test_mmr_falls_back_to_individual_embeddings_on_batch_failure(monkeypatch):
    """バッチが失敗したら 1 件ずつに切り替え、個別の失敗は 0 ベクトル扱いにする。"""
    single_calls = []

    def flaky_embed(text: str):
        single_calls.append(text)
        if text == "text-xx":
            raise RuntimeError("this one is broken")
        return [float(len(text) % 7), float(len(text) % 5), 1.0]

    def failing_batch(texts):
        raise RuntimeError("batch endpoint unavailable")

    monkeypatch.setattr(search_diversity_mod, "embed_text", flaky_embed)
    monkeypatch.setattr(search_diversity_mod, "embed_texts", failing_batch)

    results = [_result(f"c{i}", f"text-{'x' * i}", score=1.0 - i * 0.01) for i in range(5)]
    out = _apply_mmr(results, query="query", lambda_param=0.5, top_k=3)

    # クエリ 1 回 + 候補 5 件（1 件は失敗するが処理は継続する）
    assert len(single_calls) == 6
    assert len(out) == 3


def test_mmr_falls_back_without_extra_embedding_calls(monkeypatch):
    """クエリの埋め込みに失敗したら、候補の埋め込みは行わずに打ち切る。"""
    calls = []

    def failing_embed(text: str):
        calls.append(text)
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(search_diversity_mod, "embed_text", failing_embed)

    results = [_result(f"c{i}", f"text {i}", score=1.0) for i in range(20)]
    out = _apply_mmr(results, query="query", lambda_param=0.5, top_k=5)

    assert len(calls) == 1, "クエリ埋め込みの失敗後に候補を埋め込むべきではない"
    assert len(out) == 5
