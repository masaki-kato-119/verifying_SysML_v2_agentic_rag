# RAG 精度計測レポート（HybridRAG / GraphRAG）

測定日: 2026-09-14
対象: `eval/qa_golden_set.json`（20問）
実行: `scripts/run_retrieval_eval.py`（無料）、`scripts/run_answer_eval.py`（実課金 $1.8885）

このレポートは、プロジェクトレビュー `PROJECT_REVIEW_2026-09-04.md` の課題 P2-H
「RAG 側の精度が未計測」に対する**初回の計測**である。それまで `eval/results/` には
`sysml_lint_*` しか無く、`retrieval_*` / `answer_*` は 0 件だった。

---

## 0. 先に読むこと — この数値の性質

**正解ラベルが疎である。** 1問あたり1〜2チャンクしか正解にしていないが、同じ論点を扱う
チャンクは他にもある。例えば qa-hybrid-01（Port Definition の定義）の正解は
`Port Definitions` の chunk 1146 だけだが、同じ節の 1147 も、`PortDefinition` の
説明である 842 も内容的には該当する。したがって **Recall / Precision / nDCG は実際の
有用性を過小評価する方向に出る**。数値をそのまま「この RAG の精度」として外部へ
提示しないこと。

正解データの由来と限界は `eval/README.md` の該当節、および
`qa_golden_set.json` の `review_note` を参照。

---

## 1. 検索精度（無料・LLM不使用）

### Hybrid 検索（10問）

| 指標 | k=3 | k=5 | k=10 |
|---|---:|---:|---:|
| Recall | 0.150 | 0.200 | 0.400 |
| Precision | 0.067 | 0.060 | 0.070 |
| nDCG | 0.089 | 0.112 | 0.197 |

MRR = **0.152**

ケース別:

| case | RR | Recall@5 |
|---|---:|---:|
| qa-hybrid-01 | 0.20 | 0.50 |
| qa-hybrid-02 | 0.14 | 0.00 |
| qa-hybrid-03 | 0.17 | 0.00 |
| qa-hybrid-04 | 0.07 | 0.00 |
| qa-hybrid-05 | 0.00 | 0.00 |
| qa-hybrid-06 | 0.33 | 1.00 |
| qa-paraphrase-01 | 0.00 | 0.00 |
| qa-paraphrase-02 | 0.50 | 0.50 |
| qa-attribution-01 | 0.07 | 0.00 |
| qa-attribution-02 | 0.04 | 0.00 |

### Graph 検索（7問）

- **経路探索 5/5 完全一致**、平均ノード重なり（Jaccard）1.000、relations も全件一致
- **近傍探索 2/2**、out/in とも precision = recall = 1.00

`answerable: false` の4問は検索評価の対象外（スキップ）。

---

## 2. 回答精度（実課金）

`scripts/run_backend_eval.py` と同じ経路（全MCPサーバー同時提示）で20問を実行。

| 指標 | 結果 |
|---|---|
| 不正引用（実在しない `chunk-N` の引用） | **0 / 20** |
| 棄却率（`answerable: false` を「検証不能」と答えられたか） | **4 / 4** |
| LLM-as-judge correctness | **4.20 / 5**（10問） |
| LLM-as-judge completeness | **3.70 / 5**（10問） |

トークン: 入力 601,775 / 出力 29,862（LLM呼び出し 64回）、実測コスト **$1.8885**。

judge 点が低かったケース:

| case | correctness | completeness |
|---|---:|---:|
| qa-attribution-01 | 2 | 2 |
| qa-hybrid-04 | 3 | 2 |
| qa-hybrid-03 | 4 | 3 |
| qa-hybrid-05 | 4 | 3 |
| qa-attribution-02 | 4 | 3 |

---

## 3. 読み取れること

**引用の健全性と棄却は強い。** 不正引用 0/20、棄却 4/4 は、このシステムが
「知らないことを知らないと言う」「出典を捏造しない」という、RAG で最も壊れやすい
部分を守れていることを示す。SysML チェッカー側で一貫して採ってきた
「偽陽性を出さない」という方針と同じ性質の強さである。

**検索の順位付けは弱い。** MRR 0.152 は、正解チャンクが上位に来ていないことを意味する。
ただし §0 の疎ラベル問題があるため、この数値は下限として読むべきである。実際
qa-hybrid-01 では、正解としていない 1147（同じ `Port Definitions` 節）が3位、
842（`PortDefinition` の説明）が9位に入っており、利用者から見れば有用な結果が
返っている。

**検索順位の弱さに対して回答品質は保たれている（correctness 4.20/5）。** 単発の
検索順位より、エージェントが複数ツールを反復して呼べることの方が効いている可能性が
高い。ただし本計測はその因果を確かめていないので、仮説にとどまる。

**completeness が correctness より低い（3.70 vs 4.20）。** 答えは正しいが情報が
足りない傾向。低スコアの qa-attribution-01（出典の明記を求める問い）と
qa-hybrid-04（コード例の提示を求める問い）は、いずれも「特定のものを出せ」という
問いであり、検索順位の弱さが直接効いていると考えられる。

---

## 4. 計測中に見つかった欠陥（修復済み）

**初回計測では Hybrid の全10ケースが Recall / MRR ともに 0.000 になった。**
検索が全滅したのではなく、`relevant_chunk_ids` が**古いチャンク分割時の値のまま**で
現在の `HybridRAG/data/sqlite.db`（2026-08-27構築）と一致しなくなっていた。

根拠:

- qa-hybrid-01 の正解とされていた chunk 1169 は `ConnectionUsage` / `HappensBefore` の
  記述で、Port とは無関係。1415 も `MergeAction` / `SendAction` の話だった。
- 一方そのとき実際に返っていたのは 1376（Ports Overview）、587（Ports Textual
  Notation）、1147・1146（Port Definitions）で、**検索側は正しく引けていた**。
- `id` 列との取り違えも否定した（`id=1169` → `chunk_index` 1168、`SuccessionAsUsage`）。
- ズレ幅は index とともに増大しており（−16 〜 −35）、定数オフセットではない。
  再チャンク化によるドリフトである。

`expected_answer` が引用している原文（2026-08-24 に人間検証済み）を `chunk_text` から
逆引きして10ケース全てを復元した。**検索結果は一切参照していない**ので、
「システムが返したものを正解にする」という循環は無い。元の ID 件数（1件/2件）も
維持している。

| case | 旧 | 新 | 逆引きの根拠 |
|---|---|---|---|
| qa-hybrid-01 | 1169, 1415 | 1146, 1377 | Port Definitions / Port（基底型） |
| qa-hybrid-02 | 1220, 1224 | 1194, 1198 | Action Definitions / Action Usages |
| qa-hybrid-03 | 1156, 1162 | 1140, 1135 | Part Definitions / Item Definitions |
| qa-hybrid-04 | 1179 | 1156 | `connection def C specializes ...` のコード例 |
| qa-hybrid-05 | 1239 | 1212 | `join j;` を含むコード例 |
| qa-hybrid-06 | 1032 | 1015 | SatisfyRequirementUsage の Description |
| qa-paraphrase-01 | 1169, 1415 | 1146, 1377 | hybrid-01 と同一と `expected_answer` が宣言 |
| qa-paraphrase-02 | 1156, 1162 | 1140, 1135 | hybrid-03 と同一と `expected_answer` が宣言 |
| qa-attribution-01 | 1224 | 1198 | Action Usages |
| qa-attribution-02 | 1328 | 1293 | Requirement Definitions |

**このドリフトは再インデックスのたびに再発する。** `chunk_index` は位置依存の
連番であり、golden set の照合キーとしては脆い。`section_title` + 本文ハッシュのような
安定キーへの変更を別途検討すること。

---

## 5. 併せて訂正した記述

`PROJECT_REVIEW_2026-09-04.md` の P2-H が
「`qa_golden_set.json` は自ら `"reviewed_by_domain_expert": false` と宣言」と書いていたが
**これは誤り**で、git の初回コミット（2026-08-27）から一貫して `true` であり、
2026-08-24 のレビュー記録も入っている。`eval/README.md` 側の古い記述を JSON の宣言と
取り違えたもので、README・レビュー文書の両方を 2026-09-14 に訂正した。

ただし「数値をそのまま精度として扱わない」という注意自体は残している。理由が
「未レビューだから」ではなく「**正解ラベルが疎で、かつ実出力を見ながら作られた
経緯があるから**」に変わっただけである。

---

## 6. 次に手を入れるなら

1. **正解ラベルの疎さを解消する。** 1問あたりの正解チャンクを、同じ論点を扱う
   チャンクまで広げる。これをやらない限り Recall / Precision は過小評価のままで、
   改善したかどうかの判定にも使いにくい。
2. **照合キーを `chunk_index` から安定キーへ。** §4 のドリフト再発を止める。
3. **completeness の底上げ。** 「特定のコード例を出せ」「出典を明記せよ」という
   問いが弱い。検索順位の改善（リランキング既定化など）が効くかを測る余地がある。
   `run_retrieval_eval.py --with-rerank` は無料で試せる。
