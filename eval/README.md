# 精度評価パイプライン

`eval/backend_selection_queries.json`（既存、バックエンド選択率のみを測定）とは別に、
検索精度・回答精度・引用整合性・棄却率を測定するための golden set と評価スクリプト一式。

## ファイル構成

- `qa_golden_set.json` — Hybrid/Graph RAG用の正解ラベル付きQ&Aセット（20問）。
- `sysml_lint_golden_set.json` — SysML v2 Checker（linter）用の正解ラベル付きスニペット（53件、2026-08-20にb5_golden_set_expansionで19件から拡充、d7_documentation_stmt_optional_nameでさらに更新）。
- `results/` — 評価実行結果のJSON（`retrieval_<timestamp>.json` / `answer_<timestamp>.json` / `sysml_lint_<timestamp>.json` / `conformance_<timestamp>.json`）。
- `../scripts/run_retrieval_eval.py` — 検索精度評価（無料、APIコストなし）。
- `../scripts/run_answer_eval.py` — 回答精度評価（実APIコスト、予算上限つき）。
- `../scripts/run_sysml_lint_eval.py` — SysML linter診断精度評価（無料、LLM不使用）。
- `../scripts/run_conformance_eval.py` — 公式SysML v2 Pilot Implementationの標準ライブラリとの
  静的コンフォーマンス評価（無料、LLM不使用。別途cloneが必要）。

## `qa_golden_set.json` について（要レビュー）

**`"reviewed_by_domain_expert": false` — ドメインレビュー未実施。** `relevant_chunk_ids` /
`expected_graph_path` / `expected_answer` は、実際に索引済みの
`SysML_Language_Specification_v2.pdf`（HybridRAG: `HybridRAG/data/sqlite.db`、
GraphRAG: `GraphRAG/data/graphs/SysML_Language_Specification_v2.pkl`）に対して
`vector_search`/`hybrid_search`/`find_path` の実出力を人手で確認しながら下書きしたもので、
SysML v2仕様に関するドメイン知識のあるレビューを経ていない。回帰判定の正解として
そのまま信頼する前に確認すること。

グラフ系ケース（`qa-graph-*`）は特に注意が必要。GraphRAGの抽出グラフは102ノードと
小規模で、一部の `is-a` 関係が意味的に粗い（例: `port` が `constraint` や `case` の
直下に `is-a` で繋がっている）。`expected_graph_path`/`expected_neighbors` は
「SysML的に正しい階層」ではなく「現在のグラフが実際に返す経路・近傍」を写し取った
ものであり、グラフ抽出の品質そのものを評価するものではない（それは別課題）。

`relevant_chunk_ids` は `hybrid_search` が返す `chunk_id`
（例: `<絶対パス>::chunk-1769`）の末尾の整数（`chunk_index`）のみを記録している。
絶対パスは索引時の一時アップロード先に依存し環境非依存ではないため、比較は
末尾の数値（または `metadata.chunk_index`）で行う。

## `run_retrieval_eval.py`（無料）

```bash
python scripts/run_retrieval_eval.py
python scripts/run_retrieval_eval.py --only qa-hybrid-01,qa-graph-01
python scripts/run_retrieval_eval.py --with-rerank              # Cross-Encoderリランキングを有効化(無料)
python scripts/run_retrieval_eval.py --with-query-expansion     # LLMクエリ拡張を有効化(実APIコストあり)
```

`--with-rerank`/`--with-query-expansion`はHybrid検索ケースのみに影響する
（2026-08-24に追加。`a3_hybrid_retrieval_tuning`の検証用）。**検証結果:
rerankを全ケース一律で有効化するとRecall@5が0.750→0.450に悪化する**
（使用しているCross-Encoderが英語単言語モデルで、日本語クエリには
不向きなため）。個別ケース(`qa-hybrid-05`)では有効だが、既定を変えると
全体で悪化するため、既定は無効のままにしている。クエリ拡張は無害だが
決定的な改善にはならない。

LLMを呼ばず、`HybridRAG/rag/search.py` の `RAGSearcher.search_hybrid` と
`GraphRAG/graphrag/query_engine.py` の `GraphQueryEngine` を直接（インプロセスで）
呼び出す。**MCPサーバー（`HybridRAG/mcp_server.py`）をサブプロセスとして起動しない**
——起動時に `preload_reranker()` が無条件に走り、Cross-Encoderモデルの
HuggingFaceからの取得で数十秒〜のネットワーク依存の遅延が発生するため、
「無料・即実行可」という目的に反すると判断した。呼び出しているのはMCPツールが
薄くラップしている実体そのものであり、検索ロジックは同一。

指標計算は既存の `HybridRAG/rag/eval.py`（Recall@k/Precision@k/nDCG@k/MRR、
`tests/test_hybrid_rag_eval.py` でテスト済み）と、今回追加した
`GraphRAG/graphrag/eval.py`（経路の完全一致・ノード重なり・近傍のPrecision/Recall、
`tests/test_graphrag_eval.py` でテスト済み）を使う。

結果は `eval/results/retrieval_<timestamp>.json` に保存される。

## `run_answer_eval.py`（実APIコスト・予算上限あり）

```bash
python scripts/run_answer_eval.py --dry-run                          # コスト見積もりのみ
python scripts/run_answer_eval.py --only qa-hybrid-01 --yes --budget-usd 1
python scripts/run_answer_eval.py --yes --budget-usd 5               # 全件実行
```

`openai_call_mcp.resolve_with_history`（本番と同じ経路、全MCPサーバー同時提示）で
各ケースを実行し、次を測定する。

- **引用整合性**（追加コストなし）: 回答文中の `chunk-\d+` 引用を、実際にそのターンの
  ツール出力に含まれていたIDと照合する。存在しないIDへの引用は「捏造引用」として
  最重要度で報告する。
- **正確性・完全性**（LLM-as-judge、追加コスト発生）: `expected_answer` を持つケースで、
  安価なモデル（デフォルト `gpt-5.6-luna`）に1-5点で採点させる。判定理由も保存する。
- **棄却率**: `answerable: false` のケースで、`openai.md` が要求する
  「検証不能」「根拠不在」のいずれかの宣言が回答に含まれるかを確認する。
  含まれない場合は「誤った断定回答」として最優先で報告する（最も危険な失敗モード）。
- **再現性**（`--repeat N`）: 同一ケースをN回実行し、判定のばらつきを見る。

`--dry-run` は `openai_call_mcp` を import しない（= `OPENAI_API_KEY` 不要）。
概算コストとケース一覧だけを表示する。

`--yes` での実行時は、事前に概算コスト（ラフな平均トークン数ベース、実測ではない）が
`--budget-usd`（デフォルト $5）を超えないか確認したうえで開始し、実行中も
実際のトークン使用量から実測コストを積算する。上限を超えた時点で残りのケースを
打ち切り、それまでの結果を保存する。

結果は `eval/results/answer_<timestamp>.json` に保存される。

**既知の制約（2026-08-11に判明、キーワードを拡充して緩和済み）:** 棄却率の判定は
`openai.md` が要求する「検証不能」「根拠不在」に加え、実行で観測された同義表現
（「確認できません」「検出されませんでした」「見当たりません」等、
`scripts/run_answer_eval.py` の `REQUIRED_REFUSAL_MARKERS` 参照）も受理するよう
拡充した。当初は厳密一致のみで `qa-negative-03`（モデルは「該当条文は検出
されませんでした」と正しく棄却していた）を `refusal_ok: false` と誤検出して
いたが、拡充後は正しく `true` になることを確認済み（再実行結果:
`eval/results/answer_20260811T124551Z.json`）。ただし依然としてキーワード
ベースのヒューリスティックであり万能ではない。`refusal_ok: false` のケースは
`final_text` を目視確認することを推奨する。

## 既存の `backend_selection_queries.json` との関係

`eval/backend_selection_queries.json`（12件）は「どのMCPサーバーを呼ぶべきか」という
ルーティング正解のみを持ち、`scripts/run_backend_eval.py` で使う。
`qa_golden_set.json` はそれとは独立したファイルで、検索結果・回答内容・引用の
正しさまで踏み込んで評価する。トピックが重なるケースがあっても、正解の粒度が
異なるため統合していない。

## `run_sysml_lint_eval.py`（無料、LLM不使用）

```bash
python scripts/run_sysml_lint_eval.py              # golden setのみ
python scripts/run_sysml_lint_eval.py --corpus      # 実コーパス41ファイルも走査
```

`sysml_v2_checker_advanced.parser.parse_sysml`/`lint_sysml` を直接呼び出すだけの
決定的な評価で、LLM呼び出しは一切ないためAPIコストは発生しない。

- `clean` ケース: 誤検出（false positive）が無いか——診断0件を期待する。
- `broken` ケース: 見逃し（false negative）が無いか——特定の診断が出ることを期待する。
- `known_bug` ケース: 調査で見つかったが未修正の既知バグの現在の挙動を記録するだけで、
  pass/fail集計には含めない。挙動が記録時と変わったら警告を出す。

2026-08-11の初回実行で、標準ライブラリ修飾名（`ScalarValues::Real`等）の誤検出と、
`state X;`（state_usage）がシンボルテーブルに未登録で有効な遷移でも「存在しない」と
誤検出するバグを発見・修正済み。`allocate`文のfrom/toエンド解決が
正しく宣言されたpart instanceでも誤検出するバグ（`sysml-known-bug-01`）は、2026-08-20に
シンボルテーブルを型解決専用（`self.symbols`）と要素参照専用（`self.element_refs`）に
分離する設計変更で根治した。golden setの当該ケースは `sysml-clean-10` として再分類済み。

**2026-08-20のgolden set拡充（b5_golden_set_expansion）**: item/interface/allocation/
calculation/constraint の各def・usage、circular inheritance、multiplicity範囲、
expose、dependency、binding connector、succession、Nary Connector、state
entry/do/exit action、case/analysis/verification/use_case/view/viewpoint/
rendering/metadata/assert_constraint_usageの各usage等を追加し19件→51件に拡充した。
拡充作業の過程で、`requirement`/`analysis_case`/`verification_case`/`use_case`の
「高度ルールチェック」4関数（`_check_requirement_advanced_rules`等、下位ヘルパー
計12個を含む）が`lint()`のパイプラインから一切呼び出されておらず完全に到達不能で
あることを新たに発見した（`sysml-known-bug-02`として記録）。

**2026-08-20の`b7_orphaned_advanced_rules_rewire`で修正済み。** `self.analysis_cases`
等の未初期化によるクラッシュリスクの解消、`_check_requirement_structure`の
`reqBody`キー不一致の修正（実在する`documentation`子ノードベースの検証に
書き換え）、`caseBody`等の存在しないキーを読んでいた3関数のno-op化、
`lint()`内の欠番だった第9・第12パスとしての再配線、という4段階で対応した。
golden setの`sysml-known-bug-02`は`sysml-broken-25`へ、doc無しrequirementで
新たに推奨警告が出るようになった`sysml-clean-09`は`sysml-broken-24`へ、
それぞれ更新済み（51件のまま、clean 26・broken 25）。

**2026-08-20の`d7_documentation_stmt_optional_name`で更新**: `documentationStmt`の
`simpleName`（identification）を任意化し、`_check_documentation_stmt`のidentification
必須チェックを撤廃。`requirementBodyElement`専用だった`docMember`規則は廃止し
`documentationStmt`へ統一した（公式SysML v2標準ライブラリ58ファイル全件を
止めていた「名前無しdoc」構文エラーの根治が目的）。requirement内のdocが
常にidentification必須エラーを出していた
既知の制約（`sysml-broken-22`）は解消し`sysml-clean-28`へ、名前無しトップレベルdoc
の`sysml-clean-29`・空bodyの`sysml-broken-26`を新設（53件、clean 28・broken 25）。

結果は `eval/results/sysml_lint_<timestamp>.json` に保存される。
