# SysML v2 独自チェッカー vs OMG公式Pilot Implementation 比較評価レポート

対象: `sysml_v2_checker_advanced/`（ANTLR4ベース、`sysml_v2_checker_advanced/antlr/SysMLMin.g4`という「最小」文法）
比較対象: OMG公式 SysML v2 Pilot Implementation（`sysml-v2-pilot-implementation` 由来の
Jupyter kernel jar **0.62.0** 経由。2026-09-24に 0.61.0 から更新。§v4 参照）

このファイルは4つの測定を並記している。**新しい順**。

- **v4（2026-09-24）** — 下記「v4」節。参照実装を 0.62.0 へ更新し、730件を取り直した。
  **参照実装の出力は730件すべてで 0.61.0 と同一**だったため、v3までの数値はそのまま有効。
- **v3（2026-09-07）** — 下記「v3」節。ルール別の一致率を初めて実測し、それを根拠に
  confidence が低い4ルールの偽陽性を潰した後の再測定。
- **v2（2026-09-04）** — 「v2」節。8/28のレポートで挙げた問題を修正した後の再測定。
  v3から見ると途中のスナップショットだが、当時の判断根拠として残してある。
- **v1（2026-08-28）** — 「v1」以降の節（旧レポート本文をそのまま残してある）。修正前の
  ベースライン。v2の差分表はこれを基準に取っている。

---

# v4（2026-09-24）: 参照実装を 0.62.0 へ更新（出力に変化なし）

測定日: 2026-09-24
参照実装: `jupyter-sysml-kernel-0.62.0`（conda-forge、2026-09-11公開）。従来は 0.61.0（2026-08-21公開）。
実行: `scripts/run_reference_comparison_eval.py --force`（batchモード、730件・約19分）

## v4-0. なぜ上げたか

参照実装が1バージョン進んでいた。こちらの精度の主張はすべて参照実装を基準に
測っているので、基準が動いたなら測り直さないと「古いオラクルに対する一致率」を
現在の数値として提示することになる。

## v4-1. 結論: **参照実装の出力は730件すべてで同一だった**

0.61.0 と 0.62.0 の `reference` 出力（crashed と、診断の (severity, line, message)
多重集合）をファイル単位で突き合わせた結果:

| | 件数 |
|---|---:|
| 完全一致 | **730 / 730** |
| 差異あり | **0** |

したがって **v3までに出した数値はすべてそのまま有効**であり、更新による再解釈は要らない。
agreement の集計もフル実行で v3以降の値を再現した:

| agreement | 件数 | 割合 |
|---|---:|---:|
| both_clean | 484 | 66.3% |
| both_error | 194 | 26.6% |
| reference_only_error | 51 | 7.0% |
| local_only_error | **1** | 0.1% |

**副産物の確認**: これは 9/07〜9/14 に `recheck_local_only.py`（保存済みの参照結果を
固定基準にしてローカル側だけ流し直す方式）で導いていた値と完全に一致する。
省力化のための方式が、フル実行と同じ答えを返すことが裏取りできた。

## v4-2. 標準ライブラリは更新不要だった（実測）

当初は「jarと`sysml.library`はlockstepで動かす必要がある」と見積もっていたが、
実測の結果**この更新に限っては不要**だった。

- `.conda` パッケージは対応する `sysml.library` を同梱している
  （`share/jupyter/kernels/sysml/sysml.library/`、95ファイル）。
- **0.61.0 同梱版と 0.62.0 同梱版は1バイトも違わない。** 標準ライブラリはこの2版間で
  変わっていない。
- ディスク上の `sysml.library`（GitHubからのsparse checkout、117ファイル）も、
  改行コードを正規化すれば同梱版と差分0。余分な23ファイルはEclipseのプロジェクト
  メタデータで、カーネルは読まない。

**次に上げるときは同梱版を正とすること。** GitHubのタグから別途取ってくると版の
対応付けを推測する余地が生まれるが、`.conda` の中身なら対応は自明である。

## v4-3. 手順と、その過程で直した2つの欠陥

1. `.conda` を取得（124,003,090バイト）し fat jar を展開。
2. `reference_driver.py` の `REFERENCE_VERSION` を `0.62.0` へ。パスに版を直書きして
   存在しなければ落ちるようにしてある（globで拾うと、古いjarが残っているときに
   黙ってそちらを使う）。
3. `RefDriver.class` を新しいjarのクラスパスで再コンパイル。
4. canary（`package P { part def }` を必ず拒否すること）を確認。
5. **バッチモードが逐次モードと一致することを測り直し**（100件、100/100一致）。
6. 730件フル実行。

**欠陥(a): `compare_reference_runs_batch_vs_serial.py` が自分の指示を実行できなかった。**
docstringは「jarが変わったら再検証せよ」と書いているのに、実装は保存済みの逐次結果
（＝古いjarで取ったもの）とバッチを比べる作りだった。これでは「バッチと逐次の差」と
「バージョンの差」が混ざる。`--fresh-serial` を追加し、逐次をその場で走らせて比べられる
ようにした。上記5はこのモードでの結果。

**欠陥(b): 長時間ジョブが最初の進捗行で即死していた。** 進捗表示に含まれる em dash が
Windowsのcp932でエンコードできず、出力をパイプ/リダイレクトすると `UnicodeEncodeError`
で落ちる。しかも**パイプ経由だと終了コードが後段コマンドのものになり、成功と区別が
付かない**。実際に1回目の実行は「終了コード0」を返しながら書き込み0件で死んでいた
（結果ファイル数を数えていなければ、そのまま「実行済み」として先へ進んでいた）。
eval スクリプト3本で stdout/stderr を UTF-8 に固定した。3本目 `run_answer_eval.py` は
実課金の評価で、途中で落ちると金銭的損失が出るため併せて直してある。

---

# v3（2026-09-07）: ルール別一致率の実測と、それに基づく偽陽性の解消

測定日: 2026-09-07
ローカル側の再実行: `scripts/recheck_local_only.py --rule-stats eval/rule_agreement.json`
参照実装の判定: v2のフル実行時のものを固定基準として再利用（jarとサンプルが固定なら
参照実装の判定は決定的なので、ローカル側の変更に対する再測定では動かす必要がない）。

## v3-0. この測定で何が新しいか

v1・v2は agreement をファイル単位でしか見ていなかった。v3では初めて
**ルール別の一致率**を出した。あるルールだけが error を出したファイルに絞れば、
そのファイルの agreement はそのルールの判定そのものになる。これで
「どのルールが偽陽性を出しているのか」が関数名の単位で分かる。

この数値には明示すべき限界がある。`both_error` は「参照実装もそのファイルを不正と
見た」までしか言っておらず、**同じ箇所を同じ理由で指摘したことは保証しない**。
したがって一致率は**上限**であって真の精度ではない。実際、後述のとおり
「一致」していた3ファイルはいずれも別の理由で不正だっただけだった。

算出方法は `scripts/recheck_local_only.py` の `build_rule_agreement`、
同梱テーブルの生成は `scripts/build_rule_confidence_table.py` を参照。
テーブルは `sysml_v2_checker_advanced/rule_confidence.json` として配布され、
`LintIssue.to_dict()` の `confidence` フィールドから読める。

## v3-1. agreement の変化（730件）

| agreement | v1 (8/28) | v2 (9/04) | **v3 (9/07)** | v2→v3 |
|---|---:|---:|---:|---:|
| both_clean | 253 (34.7%) | 433 (59.3%) | **458 (62.7%)** | +25 |
| both_error | 215 (29.5%) | 186 (25.5%) | 196 (26.8%) | +10 |
| local_only_error（偽陽性疑い） | 231 (31.6%) | 52 (7.1%) | **27 (3.7%)** | **−25** |
| reference_only_error（偽陰性疑い） | 26 (3.6%) | 59 (8.1%) | 49 (6.7%) | −10 |
| reference_crash（無関係） | 5 (0.7%) | 0 | 0 | — |

`local_only_error` は v1比で **231 → 27（−88%）**。

カテゴリ別（v3）:

| category | n | both_clean | both_error | local_only | reference_only |
|---|---:|---:|---:|---:|---:|
| official_examples | 322 | 247 (76.7%) | 57 (17.7%) | 16 (5.0%) | 2 (0.6%) |
| tooling_fixtures | 192 | 116 (60.4%) | 47 (24.5%) | 7 (3.6%) | 22 (11.5%) |
| xpect_test_cases | 126 | 80 (63.5%) | 25 (19.8%) | 3 (2.4%) | 18 (14.3%) |
| curated_models | 36 | 7 (19.4%) | 24 (66.7%) | 1 (2.8%) | 4 (11.1%) |
| industry | 28 | 3 (10.7%) | 25 (89.3%) | 0 | 0 |
| educational | 25 | 5 (20.0%) | 17 (68.0%) | 0 | 3 (12.0%) |
| textbook | 1 | 0 | 1 (100%) | 0 | 0 |

パース成功率（同じ730件）: **707/730 = 96.8%**。
**official_examples は 322/322 = 100%**、industry も 28/28 = 100%。
失敗23件の内訳はv2-4の分類（意図的な不正フィクスチャ・KerML固有構文・
非標準サンプル）から変わっていない。

## v3-2. ルール別一致率（初回測定と、修正後）

初回測定（2026-09-07、修正前）で confidence が算出できたのは発火30ルール中9ルール。
そのうち **0.25以下が4ルール**あり、これが `local_only_error` の主因だった。

| ルール | 修正前 conf | 単独発火(一致/不一致) | 発火 | 修正後 |
|---|---:|---:|---:|---|
| `_check_interface_usage` | **0.200** | 2/8 | 31 | 発火0（コーパス内で1件も出なくなった） |
| `_check_individual_definition` | **0.143** | 1/6 | 12 | **ルール削除** |
| `_check_allocation_usage` | **0.143** | 1/6 | 12 | 発火1（別の欠陥。v3-4） |
| `_check_transition` | **0.250** | 1/3 | 4 | 発火1（一致） |
| `_check_part_instance` | 0.667 | 8/4 | 12 | 0.667（未着手） |
| `_check_import` | 0.879 | 102/14 | 146 | 0.886（他ルールが黙り分母が増加） |
| `_check_accessible_feature_paths` | 1.000 | 3/0 | 5 | 1.000 |
| `_check_requirement_subject` | 1.000 | 6/0 | 10 | 1.000 |
| `__parse_error__`（擬似） | 1.000 | 23/0 | 23 | 1.000 |

修正後に算出可能なルールは **9 → 4**（擬似ルールを除く）に減った。
**これは精度が下がったのではなく、4ルールが発火しなくなって単独発火が閾値
（3件）を下回ったため**である。同梱テーブルからも該当エントリが消えている。

## v3-3. 4ルールの根本原因（3つは同じ根だった）

`_check_interface_usage` / `_check_allocation_usage` / `_check_transition` は、
症状も実装箇所も別だが**同一の構造的原因**を持っていた。

**シンボル表が入れ子を保持していない。** 参照は package 直下に平坦登録される
（`Interface Example::fuelTankPort` は `Interface Example::tankAssy` の隣）。
一方これらのルールは `sym_name.endswith(f"::{name}")` という末尾一致で引く。
したがって **多セグメントの参照は原理的に一致しない**:

- `tankAssy.fuelTankPort`（interface の connect エンド）
- `l.component` / `p.assembly.element`（allocate のエンド）
- `S2.S3`（transition の source/target）

なお当初「ドット区切りだから `::` 前提の照合に合わない」と考えたが**これは誤り**で、
パーサーは `.` を `::` へ正規化している。合わないのは区切り文字ではなく入れ子構造で、
`fuelTankPort` を持つのは `tankAssy` 自身ではなくその型 `FuelTankAssembly` である。
解決には型解決が必要になる。

参照実装への問い合わせで、いずれも**解決できる多セグメント参照はクリーン、
解決できないものはエラー**（`Couldn't resolve reference to Feature 'X'.`）と確定した
（canaryを前後に挟んで実施）。制約自体は実在し、単純名の判定は正しい。そこで
**多セグメントの形だけを判定対象外**にした（検出漏れは許容、偽陽性は出さない。
他の意味ルールと同じ方針）。

`_check_transition` にはもう1つ別の原因があった。`then done;` の `done` は
標準ライブラリ側の**暗黙の状態**で、ローカル宣言が無いためどの登録にも現れない。
参照実装は `done` と `start` を宣言なしで受理する（実測）。実測できたこの2つだけを
暗黙名として登録した。

`_check_individual_definition` だけは別種で、**制約そのものが存在しなかった**。
「individual definition は空の多重度を持つ必要がある」として多重度が**無いとき**に
発火していたが、参照実装は `individual def X[];` `individual def X[1];` を
いずれも `no viable alternative at input '['` で拒否する。**定義に多重度を書くこと
自体が文法上できない**ので、多重度が無いのが唯一の合法な状態だった。緩和ではなく
ルールごと削除した。

決め手はいずれも Pilot Implementation 自身の**valid**フィクスチャである。
`validation/valid/InterfaceUsage.sysml` と `validation/valid/IndividualUsage.sysml` は
`// XPECT noErrors` を宣言しており、`simpletests/AllocationTest.sysml` と
`simpletests/StateTest.sysml` も同様に無エラーが期待値である。

## v3-4. 「一致」も偽物だった（confidence の限界の実例）

修正の結果、3ファイルが `both_error → reference_only_error` へ移った。
`recheck_local_only.py` は `both_error` を「一致」に数えるため、これを
**「悪化」と報告し exit 1 を返す**。しかし参照実装が何を指摘していたかを
確かめると、いずれも**別の理由で不正なファイルに、こちらの偽陽性がたまたま
重なっていただけ**だった。

| ファイル | 参照実装が実際に出しているエラー | こちらの指摘と同じか |
|---|---|---|
| `validation/invalid/InterfaceUsage_Invalid.sysml` | `An interface definition end must be a port.` ×2、`An interface must be typed by interface definitions.` ×2 | 違う（エンドの存在を問うものは1件も無い） |
| `validation/invalid/IndividualUsage_Invalid.sysml` | `At most one individual definition is allowed.`、`An individual must be typed by one individual definition.` | 違う（多重度と無関係） |
| `sysml-v2-lsp/examples/bike.sysml` | L248 `Couldn't resolve reference to Feature 'WeightRequirement'.`（`verify WeightRequirement;`） | 違う（interfaceと無関係） |

**この3ルールの実質 confidence は 0.200 や 0.143 ですらなく 0 だった可能性が高い。**
`both_error` を一致に数える限りこの取り違えは起きるので、**このプランの回帰判定では
`local_only_error` の減少幅を主指標にすること**。

同じ検証の副産物として、`_check_allocation_usage` の type_name 側に別の欠陥を
見つけた。`connection def BC1` を型に指定した allocation を「存在しない
アロケーション 'BC1' を参照しています」と報告するが、`BC1` は**実在する**。
問題は不存在ではなく**種別の不一致**で、参照実装は
`An allocation must be typed by allocation definitions.` を3箇所（`:P` `:p` `:BC1`）に
出すのに対し、こちらは `:BC1` の1件だけを、しかも誤った理由で報告している。
blackboard プラン `sysml_checker_false_positives` の `fix_allocation_type_kind_check`
として起票済み。interface 側にも同形の枝があるので同じ問題を抱えている可能性が高い。

## v3-5. 残った `local_only_error` 27件の性質

**27件すべてパースに成功している**（パースエラー0件）。v2時点では52件中1件が
パースエラーだったので、残る偽陽性疑いは完全に意味検証側の話になった。

症状（正規化後、延べ）:

| 症状 | 件数 | 該当ルール（confidence） |
|---|---:|---|
| `Import <X> が存在しないパッケージ <X> を参照` | 12 | `_check_import`（0.886） |
| `Part instance <X> が存在しない型 <X> を参照` | 4 | `_check_part_instance`（0.667） |
| 循環継承（`A -> A` / `A -> C` / `C -> A`） | 6 | `_check_inheritance_consistency` ほか |
| 互換性のない型カテゴリの特殊化（`connection` → `part`） | 4 | 型システム側 |
| 多重度の範囲が不正 | 1 | — |

次の的は `_check_part_instance`（0.667、単独発火12件中4件が不一致）である。
`_check_import` は 0.886 と高いが発火146ファイルと最多なので、残り12件の
偽陽性を潰す価値はある。循環継承の6件は同じ内容が「型システム」プレフィックス付きと
無しで**二重報告**されているように見えるので、まずそこを確認するとよい。

### 【2026-09-07 追記・訂正】`_check_part_instance` の不一致は connection def の未登録では説明できなかった

上の「次の的」を書いた直後、`connection_def` が `_collect_symbols` のどの
シンボル表にも登録されていないことが判明した（`fix_allocation_type_kind_check`
で `connection def BC1` に種別エラーを出そうとして、その前の存在判定で
落ちることから発見）。`part x : CD;`（CDはconnection def）を参照実装は
クリーンと判定するのに対し、こちらは「存在しない型 'CD'」と報告していた。

**これが `_check_part_instance` の不一致4件の原因ではないかと考えたが、外れた。**
修正（`dfaaf00`）後の内訳は 8一致/4不一致 → **7一致/4不一致**（confidence
0.667 → 0.636）で、消えたのは**一致していた側**だった。該当は
`sysml-v2-lsp/examples/multiplicity.sysml` で、`connection def Axle` を
`part frontAxle : Axle[1]` として使っている。**不一致4件は1件も減っていない。**

したがって `_check_part_instance` の偽陽性の原因は依然として未特定である。
着手する際は、4件それぞれの型参照が何であるかを個別に確認すること。

なお同ファイルが `both_error → reference_only_error` へ移って「悪化」と
報告されたが、これも§v3-4と同じ偶然の一致だった。参照実装がこのファイルに
出す29件は全て `String`/`Real`/`Integer`/`Boolean` の解決失敗（v1 §4.3 に
記録済みの参照実装側の環境要因）と「attribute definition で型付けが必要」で、
`Axle` とは無関係である。**偶然の一致はこれで4例目**になった。

`connection_def` 登録の副産物として、`connection def CD2 :> CD;`（endを基底から
継承する形）を `_check_connection_structure_advanced` が「コネクターエンドが0個」
として落とすことも実測で確認した（参照実装はクリーン。`connection def CD;`
すなわちendが本当に0個の形は参照実装も
`Must have at least two related elements` を返すので、そちらの検出は正しい）。
継承したendを数えていないのが原因と見られるが、別原因なので別途対応する。

### 【2026-09-14 追記】`local_only_error` は 27 → 1 件になった

§v3-5 が挙げた次の的（import 系・型システム系）をすべて処理した結果、
`local_only_error` は **1件**、`both_clean` は **484件** になった。
8/28 のベースライン（231件）比で **−99.6%**。

処理した原因と対応コミット:

| 原因 | 件数 | commit |
|---|---:|---|
| `USCustomaryUnits` が標準ライブラリ一覧から漏れ | 7 | `440a750` |
| 入れ子 usage を辿る import | 6 | `1d3bccb` |
| import 経由で可視になった修飾参照（`P2a::A`） | 4 | `6951865` |
| 標準ライブラリ内 enum def への `::*` import | 4 | `d52c1f4` |
| 循環継承・型カテゴリ非互換（二重報告込み） | 4 | `68e07ef` |
| alias への import | 2 | `15c02b0` |
| 共役ポート `~P` の型解決 | 2 | （本コミット） |

**参照実装が受理するのにこちらが検出していたもの**は、いずれも参照実装で
境界を実測してから対処した。循環継承だけは error → warning への降格に留めて
いる（参照実装は受理するが、自己特殊化はモデリング上の誤りの可能性が高いため
位置情報付きの警告としては残す価値がある）。

### 残った1件: 参照実装が拒否しないが、こちらの指摘が妥当なサンプル

`eval/sysml_samples/raw/sysml2-cli/tests/fixtures/errors/e3007_inverted_bounds.sysml`

```
part def Vehicle {
    part wheels[5..2];  // Error: 5 > 2
}
```

こちらは `多重度の範囲が不正です: [5..2] (最小値が最大値を超えています)` を
報告するが、**参照実装(jar 0.61.0)はこれをクリーンと判定する**（2026-09-14、
canary を前後に挟んで実測。`[2..5]` も当然クリーン）。

**コードは修正しない。** このファイルは第三者ツール `sysml2-cli` の
「エラー検出テスト用フィクスチャ」で、ファイル名（`e3007_inverted_bounds`）も
コメント（`// Error: 5 > 2`）も意図的な不正であることを明示している。下限が
上限を超える多重度は論理的に空集合であり、指摘としては妥当。参照実装が
見ていないのは**あちらの検出漏れ**と解釈するのが自然で、こちらを合わせて
緩める理由がない。対になる `e3007_valid_multiplicity.sysml` は both_clean。

したがってこの1件は**恒久的に `local_only_error` として残る**。
`record_nonstandard_samples_in_report` と同じ扱いで、以後の計測で
「未処理の偽陽性」として再浮上させないためにここへ記録する。

## v3-6. 実装への反映

- `LintIssue.to_dict()` に `confidence` を追加した（`d82a14d`）。値だけでなく
  `basis`・`caveat`・単独発火の内訳を必ず一緒に返す。測っていないルールは `null` で、
  推定値では埋めない。
- 供給源は本レポートの実測のみ。GraphRAG側にも confidence があるが、
  `semantic_path_finder.py` の 0.9/0.6/0.3 のベタ書きなど**測定に基づかない手置きの
  定数**なので流用していない。
- ルール別集計を可能にするため `LintIssue.rule` の帰属も直した（`d82a14d`）。
  `_check_*` 内のローカル関数から作った指摘が `walk` になり、2ルールが同名に
  潰れていた。

---

# v2（2026-09-04）: 修正後の再測定

**注: v2の数値は2026-09-04時点のスナップショットである。現在値はv3節を見ること。**

測定日: 2026-09-04
ハーネス: `scripts/run_reference_comparison_eval.py --timeout 120 --workers 1 --canary-interval 25`
差分集計: `scripts/compare_reference_eval_runs.py --baseline eval/sysml_results_baseline_20260828`

## v2-0. この測定の信頼性について（先に読むこと）

v2の実行中に**ハーネス自体の重大な欠陥**を発見し、修正してから測り直している。

並列実行（`--workers 4`〜`6`）中は、参照実装が**明らかに不正な入力
`package P { part def }` に対してさえ診断0件を返す**ことがあった。負荷が無い状態で
同じ入力を単独実行すれば正しくエラー1件を返すので間欠障害であり、しかもこの失敗は
**「本当にクリーンなファイル」と区別が付かない**。放置すると `local_only_error` を
不当に増やし `both_error` を減らす形で集計を静かに壊す。原因は複数JVMが同一の
`sysml.library` ツリーを demand-load する際の失敗（EMFが
`FileNotFoundException: ...sysml.library\Kernel%20Libraries\...` を報告する。空白が
URIエンコードされた `%20` のまま解決されており、ライブラリ自身のディレクトリ名に
空白が含まれるため置き場所を変えても回避できない）。

対策として次を入れた（詳細は各ファイルのdocstring）。

1. **canary**: 実行前・25件ごと・実行後に既知の不正スニペットを参照実装へ流し、
   error診断が返ることを確認する。結果はcanaryが通るまでディスクへ書かず、
   落ちたら直前のcanary以降をまとめて破棄して中断する。
2. `reference_driver.py` が stderr のライブラリロード失敗マーカーを検出したら、
   診断が返っていても `crashed` として破棄する。8/28のベースライン730件に対して
   この判定で棄却されるものは0件（＝健全な実行を誤って落とさない）。
3. `--workers` の既定を6→1（逐次）へ変更。
4. **`--timeout` が無視されていたバグを修正**。`process_one` が受け取った値を
   `run_reference_check()` へ中継しておらず、何秒を指定してもドライバ側の既定30秒が
   使われていた。v1の `reference_crash` 5件も実際には30秒でのタイムアウトである。

**v2の実行ではcanaryを23回すべて通過し、1件も破棄していない。** したがって以下の数値は
「参照実装が終始検証を行っていたことが確認された状態」で得たものである。

## v2-1. agreement の変化（730件、確定値）

| agreement | v1 (8/28) | v2 (9/04) | 差分 |
|---|---:|---:|---:|
| both_clean | 253 (34.7%) | **433 (59.3%)** | +180 |
| both_error | 215 (29.5%) | 186 (25.5%) | −29 |
| local_only_error（偽陽性疑い） | 231 (31.6%) | **52 (7.1%)** | **−179** |
| reference_only_error（偽陰性疑い） | 26 (3.6%) | 59 (8.1%) | +33 |
| reference_crash（無関係） | 5 (0.7%) | **0** | −5 |

遷移の内訳:

| v1 → v2 | 件数 | 評価 |
|---|---:|---|
| local_only_error → both_clean | **180** | 改善 |
| both_error → reference_only_error | 40 | 要トリアージ（§v2-3） |
| reference_only_error → both_error | 7 | 改善 |
| reference_crash → both_error / local_only_error | 4 / 1 | 改善（タイムアウト解消） |
| （変化なし） | 498 | — |

カテゴリ別（v2）:

| category | n | both_clean | both_error | local_only | reference_only |
|---|---:|---:|---:|---:|---:|
| official_examples | 322 | 230 (71.4%) | 57 (17.7%) | 33 (10.2%) | 2 (0.6%) |
| tooling_fixtures | 192 | 115 (59.9%) | 43 (22.4%) | 8 (4.2%) | 26 (13.5%) |
| xpect_test_cases | 126 | 74 (58.7%) | 19 (15.1%) | 9 (7.1%) | 24 (19.0%) |
| curated_models | 36 | 6 (16.7%) | 24 (66.7%) | 2 (5.6%) | 4 (11.1%) |
| industry | 28 | 3 (10.7%) | 25 (89.3%) | 0 | 0 |
| educational | 25 | 5 (20.0%) | 17 (68.0%) | 0 | 3 (12.0%) |
| textbook | 1 | 0 | 1 (100%) | 0 | 0 |

v1が最重要問題として挙げた「official_examples の `local_only_error` 47.8%」は
**10.2% へ低下**した（154件 → 33件）。

参考: 同じ730件に対する**パース成功率は 702/730 = 96.2%**（official_examples は
319/322 = **99.1%**、industry は 28/28 = 100%）。

## v2-2. 残った `local_only_error` 52件の性質（重要）

**52件のうち、パースエラーは1件しかない。残り51件はパースに成功しており、
lintルールだけが誤検出している。**

つまり **v1の中心的な問題だった「文法カバレッジ不足」は実質的に解消した**。
残っているのは lint 側の問題である。

唯一のパースエラーは
`eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Vehicle Example/SysML v2 Spec Annex A SimpleVehicleModel.sysml:573`
の `exhibit state vehicleStates redefines vehicleStates;`（このファイルは参照実装が
**エラー0件**を返しているため、ローカルの真の文法ギャップと確定。§v2-4のE1）。

lintのみ51件の頻出ルール（ファイル数）:

| ファイル数 | ルール |
|---:|---|
| 10 | `Import 'X' が存在しないパッケージ 'Y' を参照しています` |
| 10 | `Interface usage 'X' の from エンドが存在しない要素を参照しています` |
| 10 | `Interface usage 'X' の to エンドが存在しない要素を参照しています` |
| 6 | `Individual definition 'X' は空の多重度を持つ必要があります` |
| 6 | `Allocation usage 'X' の to エンドが存在しない要素を参照しています` |
| 5 | `Allocation usage 'X' の from エンドが存在しない要素を参照しています` |
| 4 | `Part instance 'X' が存在しない型 'Y' を参照しています` |
| 4 | `Import 'X' が存在しない要素を参照しています` |
| 3 | `Transition のターゲットステート 'X' が存在しません` |

上位のほとんどが「**他ファイルや標準ライブラリにある要素を参照しており、単一ファイル
解析では解決できないものをエラーとして報告している**」ものである。これは v1 §4.2 が
`reference_only_error` 側の限界として説明した単一ファイル解析の制約の、鏡像にあたる。
`Individual definition` の多重度ルールだけは性質が異なり、独自ルールの妥当性そのものを
再検討すべき候補。

## v2-3. `both_error → reference_only_error` 40件のトリアージ（v1 P1-Dへの回答）

**問い**: 偽陽性を179件減らした代償として、「文法を緩めすぎて本来検出すべきものを
見逃すようになった」分が混ざっていないか。

**答え: 混ざっていない。** 40件の内訳は次の通りで、文法の過度な寛容化に由来するものは無い。

| 分類 | 件数 | 扱い |
|---|---:|---|
| 型解決カスケード（`Couldn't resolve` / `must be typed by`） | 21 | 設計上スコープ外（v1 §4.2）。偽陰性として数えない |
| **意味検証ルール未実装** | **14** | **真の偽陰性。ただし文法とは無関係** |
| 参照実装側の構文エラー（裸import artifact 等） | 5 | v1 §4.3。参照実装側の制約 |

40件はいずれも「**v1ではローカルがパースエラーを出していたため both_error に分類されて
いたファイル**」であり、文法を直してパースが通った結果、参照実装の**意味制約エラーだけが
残った**ものである。つまりルールは元から存在しておらず、パースエラーの陰に隠れていた。
**文法が緩くなったのではなく、隠れていた lint ルールの欠落が見えるようになった**と読むのが
正しい。

未実装の意味検証ルール14件の内訳（`semantic_rule` バケット）:

| 参照実装のメッセージ | 該当ファイル |
|---|---|
| `Subject must be first parameter.` | `16-concern-stakeholder.{input,expected}.sysml`, `26-subject-actor-stakeholder-trailing-comment.{input,expected}.sysml` |
| `Only one objective is allowed.` | `CaseSubjectObjective_Invalid.sysml` |
| `Must be model-level evaluable` | `MetadataUsage_Invalid.sysml` |
| `Must be owned by an occurrence definition or usage.` | `PortionUsage_Invalid.sysml` |
| `A package-level feature cannot be redefined` | `Redefinition_OwningType_Invalid.sysml` |
| `Must have at least two related elements` | `Relationship_invalid_relatedElement{0,1}.sysml` |
| `A parallel state cannot have successions or transitions.` | `TransitionUsage_invalid.sysml` |
| `An owned usage of a variation must be a variant.` | `Variability_invalid.sysml` |
| `A requirement verification must be in the objective of a verification case.` | `Verification_invalid.sysml` |
| `A view definition may have at most one view rendering.` | `ViewRendering_invalid.sysml` |

**`Subject must be first parameter.` は v1 §4.1 で未実装として挙げられ、
`sysml_linter_fixes` プランで実装済みとされたルールである。** 4ファイルで検出できて
いないため、実装の網羅漏れの疑いがある（最優先で確認すべき項目）。

それ以外の10件は、いずれも公式Pilot Implementation自身の
`xpect/tests/validation/invalid/*.sysml`（1ファイル1ルールの意図的invalidフィクスチャ）
由来であり、**既製の最小テストケースが揃っているため実装コストは低い**。

## v2-4. 文法ギャップの確定結果

730件のパース失敗28件を、最小再現の作成と参照実装の判定で分類した。参照実装の判定は
「当該ファイルが裸の `import` を含む場合は v1 §4.3 の artifact でファイル全体の解析に
失敗するため、その先の行の判定は使えない」ことを考慮し、必要なものは裸importを
`private import` へ書き換えたコピーで再確認している（canaryを前後に挟んで実施）。

> **【2026-09-04 追記・この節の重要な訂正】以下の「3種」は過小計上である。**
> 分類をファイルごとの**最初のANTLRエラーセグメントだけ**で行っていたため、
> 同一ファイル内の2番目以降のギャップを取りこぼしていた。`parse_sysml` の
> error dict は複数のエラーを `; ` 区切りで返す。E1 を修正した直後に、対象4ファイルが
> **別のより深い箇所で失敗し続ける**ことで判明した。
>
> 全セグメントを展開し直した結果、**OMG公式 Annex A 車両モデルだけで根本原因が
> さらに7種**見つかっている（§v2-6）。ギャップの棚卸しをするときは必ず全セグメントを
> 見ること（`scripts/run_conformance_eval.py` の `classify_parse_error` が意図的に
> 最初の1件だけを見るのは「変化の追跡」用途であり、棚卸しには使えない）。

### 修正すべきギャップ（最初のエラーで分類したときの3種）

| # | 構文 | 該当 | 参照実装の判定 | 状態 |
|---|---|---:|---|---|
| E1 | `exhibit state <名前> redefines <対象>;` | 4（うち公式2） | 4ファイルすべて**構文エラー0件＝受理** | ✅修正済み（commit 881ba05） |
| E2 | 括弧式の中のコメント `= ( /* c */ )` | 1（公式） | 構文エラー0件＝受理 | 未着手 |
| E4 | `entry state <名前>;`（state本体） | 1 | 構文エラー0件＝受理 | 未着手 |

E1 の修正で最小再現とAST反映は確認できたが、**対象4ファイルはまだパースできない**
（それぞれ §v2-6 のギャップを複数抱えている）。`pytest -q` 1,381件通過、
`scripts/recheck_local_only.py` で悪化0件。

- **E1**: `SysMLMin.g4:245-251`。第2代替（`exhibit ref` 形、247-250行）には継承節反復が
  あるのに第1代替（`exhibit state <名前>` 形、246行）には無い、という実装の非対称性。
  該当: 公式 `SysML v2 Spec Annex A SimpleVehicleModel.sysml:573`、同内容の
  `SimpleVehicleModel.sysml:573`、`Annex_A_VehicleViews.sysml:169`、
  `smart-home-complex2.sysml:676`。**246行への1節追加で4ファイルが通る見込み。**
- **E2**: `package P { attribute a : X[*] = ( /* c */ ); }` が
  `no viable alternative at input '(/* c */'` で失敗する。`= ( )`（空括弧）・`= ( b )`・
  `= ( b, c )` は通るので、**括弧の中にコメントが入ると壊れる**。エラーメッセージに
  コメント本文がそのまま現れるため、ブロックコメントが hidden チャネルへ送られていない
  疑いが強い。該当: 公式 `training/33. Analysis/Analysis Case Usage Example.sysml:11-12`。
- **E4**: `package P { state def S { entry state e; state x; } }` が
  `no viable alternative at input 'entrystate'` で失敗する。`entry; then x;` は通る。
  該当: `sysml-v2-lsp/examples/vehicle.sysml:75`。

### パースできないが修正対象ではないサンプル

**意図的な不正フィクスチャ（11件）** — 失敗が正しい挙動:
`missing_name` / `unclosed_brace` / `unterminated_string` / `bad_doc_syntax` /
`double_colon_typo` / `invalid_operator` / `syntax-error` / `missing_semicolon` /
`bad_multiplicity` / `unexpected_keyword` / `e3007_negative`。

**KerMLの構文（2件、SysML v2の範囲外）** — `datatype Real`:
`cross_file_a.sysml:4`、`datatype_basic.sysml:3`。

**参照実装も同じ行で拒否した＝ファイル側が非標準（10件）**:

| 構文 | 該当 | 参照実装の判定 |
|---|---|---|
| `alias <修飾名> as <名前>;` | `VehicleModel.sysml:201` | 201行で `mismatched input '::' expecting 'for'`（ローカルと同一のメッセージ）。SysML v2のalias記法は `alias <名前> for <修飾名>` |
| 制約式中の `&&` | `HVACSystemRequirements.sysml:51` | 51行で `no viable alternative at input '&'` |
| QPE（`value v: Integer[0..*] = .*/.*[Integer];`） | `QPE-Qualifier.sysml:6`, `QPE-Wildcard.sysml:8`, `QPE-Traversal.sysml:6` | 同じ行で `no viable alternative`。XPECTヘッダに `noErrors` と書かれているがjar 0.61.0経由では拒否される |
| `transition first then <対象>;`（source欠落）＋行コメント | `25-accept-transition-trailing-comment.{input,expected}.sysml:1` | 1行目で `no viable alternative at input 'transition'` |
| `final <名前>;` | `WebShopBehavior.sysml:26` | 26行で `no viable alternative at input 'final'` |
| `entry state <名前>;` | `sysml2-cli/tests/fixtures/vehicle.sysml:75,77` | 75行・77行で `no viable alternative at input 'entry'`。`private import` へ書き換えたコピーでも同じ（下記の注記参照） |
| `usecase`（1語） | `EIT_System_Use_Cases.sysml:10` | 参照実装はそれ以前の4行目 `actor EngineerTechnician;`（package直下のactor。ローカルは受理する）を拒否して解析を打ち切る。ファイル全体が非標準 |

いずれも `alias ... as ...` のように**ローカルと参照実装が同一の理由で拒否している**ため、
ローカル側を直す必要はない。以後の計測で「偽のギャップ」として再浮上させないための記録。

### 【2026-09-04 訂正】`entry state <名前>;` は当初「真のギャップ」と誤判定していた

`fix_entry_state_in_state_body`（E4）は「参照実装が構文エラー0件で受理する」という
根拠で起票したが、**その判定は誤りだった**。検証スクリプトが `vehicle.sysml` を
basename で探し、`sysml-v2-lsp/examples` というパスを優先指定していたが該当パスが
存在せず、フォールバックで**別の `vehicle.sysml`（59行・`entry` を一切含まない
`sysml-v2-lsp/test/fixtures/valid/`）**を検査していた。存在しない75行目について
「構文エラー0件」と読んでいたことになる。

改めて実ファイル（`sysml2-cli/tests/fixtures/vehicle.sysml`）と最小形の両方で
確認した結果、参照実装は `entry state e;` を**全形で拒否**する
（`do state e;`・`exit state e;`・本体付き・型節付き・state usage内も同様に拒否。
`entry action a;` は受理）。したがってこのファイルが非標準であり、ローカルの
修正は不要。

**教訓**: サンプルを basename で引くときは、パス指定が一致しなかった場合に
黙って別ファイルへフォールバックする実装にしないこと。行番号まで指定して
検証しているなら、対象ファイルの行数と実際の該当行の内容も一緒に出力して
突き合わせること。

## v2-6. Annex A 車両モデルの完全なギャップ一覧（2026-09-04追記）

`eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Vehicle Example/SysML v2 Spec Annex A SimpleVehicleModel.sysml`
は、**参照実装が診断0件を返す**（canary付きの健全実行で確認。agreement は `local_only_error`）。
つまりこのファイル内のすべての構文は正当なSysML v2であり、ローカルの失敗はすべて
真のギャップと断定できる。**確定的な適合目標として使える唯一のファイル**である。

E1 修正後もこのファイルは26エラーセグメントを出す。全セグメントを行番号でまとめると
根本原因は7種:

| # | 構文 | 発生行 | 箇所数 | 見立て |
|---|---|---|---:|---|
| G1 | `interface X : T connect [1] a.b to [1] c.d;`（interface usage の connect 節。多重度・端点の `::>`・ネストした interface を伴う） | 640, 642, 953, 968, 970, 999 | 6 | 最大。要設計 |
| G2 | `action X send Y via Z { ... }`（send アクションが本体を持つ） | 755, 765 | 2 | 中 |
| G3 | `@Rationale about <修飾名> { ... }`（metadata usage 短縮形に `about` 節） | 1121, 1128, 1134 | 3 | 中 |
| G4 | 先頭ドットの小数リテラル `= .6;` `= .98 [m];` | 1173, 1182, 1260, 1277, 1280, 1294 | 6 | **最も安価** |
| G5 | `action trigger accept X:T;` / `then action trigger accept X:T;` | 1390, 1416 | 2 | 中 |
| G6 | action 本体内の `item def X;` | 1412 | 1 | 小（登録漏れ） |
| G7 | `join <名前>;` / `fork <名前>;` / `then fork fork1;`（fork/join 制御ノード） | 1413, 1414, 1415, 1420, 1429, 1436 | 6 | 中 |

同内容の tooling_fixtures 側 `SimpleVehicleModel.sysml` と `Annex_A_VehicleViews.sysml`
も同じギャップを共有する。7種すべてを潰せば official_examples のパース成功率は
**319/322 → 322/322** になる見込み。blackboardプラン `sysml_linter_fixes_v2` の
`fix_annex_a_conformance_gaps`（P1）として起票済み。

**他のファイルにも同様の未列挙ギャップが残っている可能性がある。** 上表は Annex A に
限った棚卸しであり、`smart-home-complex2.sysml`（13セグメント）や
`VehicleModel.sysml`（60セグメント）などは未展開のまま。ただし後者2つは非標準構文を
含むファイルなので優先度は低い。

## v2-5. 次のアクション（blackboardプラン `sysml_linter_fixes_v2`）

| 優先 | 内容 |
|---|---|
| 済 | `fix_reference_harness_silent_failure`（§v2-0） |
| 高 | E1（`exhibit state ... redefines`）— 公式サンプル4件が1節追加で通る |
| 高 | `Subject must be first parameter.` の網羅漏れ確認（§v2-3） |
| 中 | E2・E4 の文法追加 |
| 中 | xpect invalid フィクスチャ由来の意味検証ルール10種（§v2-3。最小テストケースが既製） |
| 中 | `local_only_error` 51件の lint 偽陽性（§v2-2。単一ファイル解析の制約とどう折り合うかの設計判断を含む） |

---

# v1（2026-08-28）: 修正前のベースライン

作成日: 2026-08-28

**本レポートのスコープは「問題の洗い出し」までであり、修正の実装は別プランとする。**
次にこのプロジェクトへ入る人が本レポートだけを読んで各問題を再現・着手できることを目標に、
具体的なファイルパス・行番号・コード抜粋・診断メッセージを添えている。

> **v2からの注記**: 以下のv1本文に挙げられたP0-1〜P2-2の文法ギャップは、
> `sysml_linter_fixes` プラン（188タスク中186完了）で対応済みである。
> v1 §2.1 の数値は §v2-1 の "v1" 列に対応する。v1 §1.4-2 の
> 「参照実装はタイムアウトする」は、実際には `--timeout` が無視されていた
> ハーネスのバグ（§v2-0）が原因で、修正後は `reference_crash` 0件になった。

---

## 1. 評価方法の要約

### 1.1 参照実装の入手・実行方法

- 参照実装は OMG公式リポジトリ `Systems-Modeling/SysML-v2-Pilot-Implementation` 由来。実体は
  `eval/sysml_reference/vendor/_extracted/share/jupyter/kernels/sysml/jupyter-sysml-kernel-<版>-all.jar`
  （Jupyter用SysMLカーネルのfat jar）。**使用中の版は
  `eval/sysml_reference/reference_driver.py` の `REFERENCE_VERSION` が唯一の出どころ**で、
  現在は `0.62.0`（v1〜v3の測定時は `0.61.0`。両者の出力が730件すべてで同一であることは
  §v4-1 で確認済み）。版を上げるときの手順は同ファイルの `REFERENCE_VERSION` 上のコメントにある。
- 呼び出しは `eval/sysml_reference/vendor/RefDriver.java`（本評価用に用意した薄いラッパー）経由。
  内部で `org.omg.sysml.interactive.SysMLInteractive`（Jupyterカーネルが内部で使うのと同じAPI）の
  `si.loadLibrary(libraryDir)` → `si.process(text, false)` を呼び、`Issue`（Xtextの構文/意味診断）を
  JSONへシリアライズして標準出力に返す。
- Python側 `eval/sysml_reference/reference_driver.py` が `java -cp <classpath> RefDriver <libraryDir> <tmpfile>`
  をサブプロセスとして**サンプル1件ごとに新規JVMを起動**して呼び出す。

### 1.2 サンプル収集元

- `eval/sysml_samples/manifest.json` に730件をカタログ化（各: path, source_repo, category, sha256等）。
- カテゴリ: `official_examples`(322, 公式サンプル集), `tooling_fixtures`(192, サードパーティOSSツールのテストフィクスチャ),
  `xpect_test_cases`(126, 公式Pilot Implementation自身のXPECTテストから抽出。意図的なエラー例を含む),
  `curated_models`(36), `industry`(28), `educational`(25), `textbook`(1)。

### 1.3 比較ハーネスの仕組み

- `scripts/run_reference_comparison_eval.py` が各サンプルについて (a) ローカル
  `sysml_v2_checker_advanced.parser.parse_sysml`/`lint_sysml`、(b) 参照実装（上記RefDriver経由）を
  それぞれ実行し、診断を `{"severity", "line", "message"}` に正規化して
  `eval/sysml_results/<sha256[:16]>.json` へ保存する。
- 両実装の「error重大度の診断が1件でもあるか」を突き合わせ、`agreement` を
  `both_clean` / `both_error` / `local_only_error` / `reference_only_error` /
  `local_crash` / `reference_crash` / `both_crash` に分類する。
- `scripts/analyze_reference_comparison.py` で、`local_only_error`/`reference_only_error` バケットの
  メッセージを（引用符付き識別子・数値を `<X>`/`<N>` に正規化して）クラスタリングし、頻出パターンを抽出できる。

### 1.4 既知の制約（ハーネス自体の限界。診断結果を解釈する際に必ず考慮すること）

1. **単一ファイル解析が前提。** ローカルチェッカーもRefDriver呼び出しも1ファイル単位で完結しており、
   同一リポジトリ内の他ファイルへのimport解決は行わない（RefDriverは標準ライブラリ`libraryDir`のみロードする）。
   そのため、複数ファイルに分割されたモデル（例: `apollo-11-sysml-v2`）の一部だけを渡すと、
   参照実装側は「他ファイルの型/名前空間を解決できない」という大量のカスケードエラーを返す。
   これは両実装の設計上の限界であり、本レポートの多くの `reference_only_error` はこれが原因（§4.2参照）。
2. **参照実装はJVM起動オーバーヘッドが大きく、重いファイルでタイムアウトする。**
   `reference_crash` が5件（`official_examples`2件・`tooling_fixtures`2件・`industry`1件）発生しているが、
   いずれもJVMの起動/処理時間が確保したタイムアウトを超えたことによるもので、ファイル内容とは無関係。
   「両実装の相違」としてはカウントしていない。
3. **【本評価で新たに判明した重要な制約】参照実装（jar v0.61.0の`SysMLInteractive.process()`)は、
   ビジビリティ修飾子（`public`/`private`/`protected`）を伴わない裸の`import`文を、
   ファイル中のどの位置にあっても構文エラーとして拒否する。** 詳細と再現手順は §4.3 を参照。
   これは真の文法違反ではなく参照実装（もしくは評価に使っているJupyterカーネルAPIの使い方）側の
   アーティファクトである可能性が高く、`both_error`/`reference_only_error` の集計値を押し上げている。
4. `both_error`（両実装がエラーを検出）は「両実装が同じ問題を検出した」ことを意味しない。
   §5 のサンプリング調査の通り、実際にはほぼ全てのケースで両者は**別々の理由**でエラーを出している。

---

## 2. サンプルコーパスの統計

### 2.1 カテゴリ別件数と agreement 集計（730件全件、確定値）

| agreement | 件数 | 割合 |
|---|---:|---:|
| both_clean | 253 | 34.7% |
| local_only_error（ローカルのみエラー＝偽陽性の疑い） | 231 | 31.6% |
| both_error（両方エラー。ただし中身は別問題のことが多い） | 215 | 29.5% |
| reference_only_error（参照実装のみエラー＝偽陰性の疑い） | 26 | 3.6% |
| reference_crash（JVMタイムアウト。無関係として除外） | 5 | 0.7% |

### 2.2 カテゴリ別 agreement 内訳

| category | 総数 | both_clean | local_only_error | both_error | reference_only_error | reference_crash |
|---|---:|---:|---:|---:|---:|---:|
| official_examples | 322 | 108 (33.5%) | 154 (**47.8%**) | 55 (17.1%) | 3 (0.9%) | 2 |
| tooling_fixtures | 192 | 103 (53.6%) | 20 (10.4%) | 54 (28.1%) | 13 (6.8%) | 2 |
| xpect_test_cases | 126 | 36 (28.6%) | 47 (37.3%) | 36 (28.6%) | 7 (5.6%) | 0 |
| curated_models | 36 | 1 (2.8%) | 7 (19.4%) | 27 (75.0%) | 1 (2.8%) | 0 |
| industry | 28 | 1 (3.6%) | 2 (7.1%) | 24 (85.7%) | 0 | 1 |
| educational | 25 | 4 (16.0%) | 1 (4.0%) | 18 (72.0%) | 2 (8.0%) | 0 |
| textbook | 1 | 0 | 0 | 1 (100%) | 0 | 0 |

**official_examples（OMG公式サンプル集そのもの）の `local_only_error` 率が47.8%と突出して高い**。
つまりローカルの文法（`SysMLMin.g4`）は、OMG自身が公開している「正しいはずのSysML v2」の半数近くを
パースできていない。curated_models/industry/educational は `both_error` 率が非常に高いが、これは
§1.4-1の単一ファイル解析の限界（他ファイル依存の未解決参照カスケード）が主因であり、
文法カバレッジ不足とは別の問題として扱う（§5参照）。

---

## 3. 優先順位付けされた問題点一覧

優先度は「頻度（該当ファイル数）」と「影響度（構文の一大分類が丸ごと使えないか／個別ルールの欠落か／
単発の軽微な差か）」で判定している。件数は `eval/sysml_results/*.json` を機械的に集計した実測値。

### P0: 構文の一大分類が丸ごとパースできない（影響度・頻度ともに最大）

#### P0-1. `qualifiedName`（`.`区切りのみ）が式・alias対象・transition端点・代入対象などで
広範に使われており、`::`（パッケージ修飾参照）を受理できない

- **症状**: 式の中の列挙リテラル参照（`EnumType::literal`）、`alias`の対象、`transition`の
  `first`/`then`/`accept`対象、`succession`のconnector end、`assign`の代入先などで
  `::`を書くと `mismatched input '::' expecting {...}` / `no viable alternative at input '::'`。
- **頻度**: `local_only_error`中で**33ファイル・83件**（このバケット単独では最大規模の症状グループ）。
  実際には後述P0-4のtransition関連や、あらゆる式コンテキストに波及するため、実際の影響範囲はさらに広い。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1165-1167`
  ```
  qualifiedName
      : (ID | QUOTED_NAME) ('.' (ID | QUOTED_NAME))*
      ;
  ```
  一方、`::`と`.`の両方を受理する`namespacePath`（同ファイル1912-1914行）が別に存在するが、
  `inheritanceClause`の基底型やredefine対象など一部の場所でしか使われていない。
  式(`expression`の`nameRefExpr`, 1783行目付近)・`aliasStmt`(288-290行)・`transitionStmt`の
  `source`/`trigger`/`target`(1653-1659行)・`connectorEnd`(1150-1152行、`transitionStmt`や
  `successionStmt`が使う)・`assignmentStmt`の`target`(1314-1316行、`simpleName`のみでdot pathすら不可)
  は軒並み`qualifiedName`または`simpleName`を使っており、`::`を通せない。
- **再現例**:
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/org.omg.sysml.interactive/VehicleModel_2_Simplified.sysml:42`
    ```
    if ignitionCmd.ignitionOnOff==IgnitionOnOff::on
    ```
    → ローカル: `mismatched input '::' expecting {'[', 'bind'}` (line 42, column 75)
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/training/01. Packages/Documentation Example.sysml:13`
    ```
    alias Torque for ISQ::TorqueValue;
    ```
    → ローカル: `mismatched input '::' expecting {'{', ';'}` (line 13, column 21)
- **推定される修正方向（診断のみ、実装はスコープ外）**: `expression`の`nameRefExpr`・`aliasStmt`の
  `target`・`transitionStmt`の`source`/`trigger`/`target`・`connectorEnd`・`assignmentStmt`の`target`を
  `qualifiedName`から`namespacePath`（またはそれに準ずる`::`対応版）へ置き換える。広範囲に影響するため
  慎重な回帰テストが必要。

#### P0-2. Occurrence の portion usage（`snapshot`/`timeslice`）が極端に簡略化されすぎている

- **症状**: `snapshot`/`timeslice`usageの本体（`{ ... }`）・多重度・`ordered`修飾・`= value`値代入・
  `first`/`then`による連鎖宣言のいずれも受理できない。
- **頻度**: `local_only_error`中で**8ファイル・9件**が直接該当（ただし実際にはOccurrence章の構文全体が
  連鎖的に壊れるため、1ファイルあたりの実エラー数は非常に多い。例えば
  `Time Slice and Snapshot Example.sysml`は`local_only_error`パターン集計の最頻出クラスタ
  （`mismatched input ';' expecting {'[', 'bind'}`919件、`no viable alternative`491件等）の主要な発生源）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:158-162`
  ```
  portionUsageStmt
      : kind=('snapshot' | 'timeslice') simpleName ';'
      ;
  ```
  名前+`;`のみで、本体・多重度・値代入・`ordered`のいずれも無い。また`bareThenStmt`
  (1599-1601行、`'then' target=qualifiedName ';'`)は「既存要素への参照」のみを想定しており、
  `then timeslice ownership[0..*] ordered { ... }`のような「`then`に続けてportion usageを
  宣言と同時に連鎖させる」複合形には未対応。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/training/27. Occurrences/Time Slice and Snapshot Example.sysml:9-25`
  ```sysml
  part def Vehicle {
      timeslice assembly;
      first assembly then delivery;
      snapshot delivery {                       // ← 本体を持てない
          attribute deliveryDate : Date;
      }
      then timeslice ownership[0..*] ordered {  // ← then+多重度+ordered+本体、すべて未対応
          snapshot sale = start;                 // ← "= value" 未対応
          ref item owner : Person[1];
          timeslice driven[0..*] { ... }
      }
      snapshot junked = done;                    // ← "= value" 未対応
  }
  ```
  → ローカル: `missing '}' at 'snapshot'` (line 11), `mismatched input ';' expecting {'[', 'bind'}` (line 16, column 24) 等、多数のカスケードエラー。
- **他の該当例**: `.../examples/Simple Tests/OccurrenceTest.sysml:20`, `.../Individuals Examples/JohnIndividualExample.sysml:11`,
  `eval/sysml_samples/raw/sysml-v2-models/models/example_family/family.sysml:103`。
- **修正方向の当たり**: `portionUsageStmt`を他のusage系ルール（`itemUsage`等）と同型に拡張し、
  `multiplicitySpec?`・`'ordered'?`・`('=' value=expression)?`・`('{' partBodyElement* '}' | ';')`を追加する。
  加えて`bareThenStmt`/`bareFirstStmt`に「宣言を伴う連鎖」の代替を追加する必要がある。

#### P0-3. `individual` はプレフィックス修飾子であるべきなのに、独立した構文として実装されている

- **症状**: 公式コーパスでは`individual`は`occurrence def`/`item def`/`part def`/`action def`および
  それらのusageの**直前に付くプレフィックス修飾子**として使われる（例:
  `individual occurrence def IO2 { ... }`, `individual item ii : II1;`）。しかし現在の文法は
  `individual def X`（単独）と`individual NAME (: ID)?;`（単独usage）の2形しか受理しない。
- **頻度**: `local_only_error`中で**6ファイル・20件**（`IndividualTest.sysml`だけで6件の
  `extraneous input 'individual'`）。加えて`both_error`側でも`apollo-11-sysml-v2/Technical/SystemPackage.sysml`
  で同型のエラーが発生（該当箇所は他の理由でも同時にエラーになっているため`both_error`に分類されている）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:203-209`
  ```
  individualDef
      : isAbstract='abstract'? 'individual' 'def' simpleName inheritanceClause? '[' ']' ( '{' partBodyElement* '}' | ';' )
      ;
  individualUsage
      : isAbstract='abstract'? 'individual' simpleName ( ':' ID )? ';'
      ;
  ```
  `individual occurrence def`/`individual item def`/`individual part def`/`individual action def`や、
  `individual item ii : II1;`/`individual part p : IP1;`のような「`individual` + 他のキーワード」の
  組み合わせを受理する規則が存在しない。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/IndividualTest.sysml`
  ```sysml
  package IndividualTest {
      individual def IO1;                    // ← これは通る
      individual occurrence def IO2 {        // ← 通らない: line 3
          individual io : IO1;               // ← 通らない: line 4
      }
      individual item def II1 { ... }        // ← 通らない: line 7
      individual part def IP1 { ... }        // ← 通らない: line 18
      individual action def AP1 { ... }      // ← 通らない: line 29
  }
  ```
  → ローカル: `extraneous input 'individual' expecting {...}` (line 3/4/7/8/15/18/19/26/29...)
- **修正方向の当たり**: `occurrenceDef`/`itemDef`/`partDef`/`actionDef`（および対応する`*Usage`）の
  先頭に`isIndividual='individual'?`を追加する設計に変更するのが最も自然。現行の
  `individualDef`/`individualUsage`は「`individual`単体で他の型キーワードを伴わない」特殊ケース
  （`individual def IO1;`）用として残すか統合するかは要検討。

#### P0-4. メタデータのプレフィックス注釈`#Type`とショートハンド`@Type {...}`が未実装

- **症状**: `#Type`（要素宣言の前に置く「Prefix Metadata Annotation」）と、`@Type { ... }`/`@Type;`
  （`metadata`キーワードを省略した短縮usage形）のどちらも文法に存在しない。特に`@`はレキサーに
  トークンとして登録すらされておらず、`token recognition error at: '@'`という最も重症な形で失敗する。
- **頻度**: `local_only_error`中で `@` 絡み22ファイル・100件、`#` 絡み9ファイル・48件（重複ファイルを除くと
  実質25ファイル前後）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4`には`#`を使う規則が式の添字アクセス演算子
  `#(...)`（1675-1677行付近のコメント参照）としてしか存在せず、「宣言の前に置くprefix annotation」としての
  `#Type`は影も形もない。`@`はどの規則にもlexerトークンにも登場しない。`metadataUsage`(423-425行)は
  `'metadata' simpleName inheritanceClause? ...`のみで、`@`によるショートハンド形の代替を持たない。
- **再現例**: `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/src/org/omg/sysml/xpect/tests/simpletests/MetadataTest.sysml`
  ```sysml
  #Security enum def ClassificationLevel { ... }      // line 7: プレフィックス注釈
  ref y {
      @Classified { classificationLevel = ... }        // line 28: @ショートハンド usage
      @Security;                                        // line 31
  }
  private ref #Classified #Security z1;                 // line 34: 複数プレフィックス注釈
  abstract #Classified z2;                               // line 35
  ```
  → ローカル: line 28で `token recognition error at: '@'`（レキサーレベルの失敗）、
  line 7/34/35等で `extraneous input '#' expecting {...}`。
- **修正方向の当たり**: (a) レキサーに`@`トークンを追加する、(b) `metadataUsage`に
  `'@' typeRef=namespacePath ( '{' partBodyElement* '}' | ';' )`のようなショートハンド代替を追加する、
  (c) ほぼ全ての宣言規則（`topLevelElement`/`partBodyElement`が委譲する多数の規則）の先頭に
  `('#' namespacePath)*`のようなprefix annotationの反復を追加する、という3段階の対応が必要になる
  比較的大掛かりな拡張。影響ファイル数・影響範囲（宣言のほぼ全種類が対象になりうる）の両方から見て
  優先度は高いが、実装コストも大きい。

#### P0-5. State machine の `accept`/`do` トリガー・エフェクト節が狭すぎる、
`accept ... then X;`という「`first`省略の暗黙遷移」形が未対応

- **症状**:
  1. `transitionStmt`の`accept`節はトリガーを`qualifiedName`（単純参照）としてしか受理できず、
     `accept when EXPR`（式ガード付きトリガー）や`accept at EXPR`（クロックトリガー）を受理できない。
  2. `transitionStmt`の`do`節は`effect=qualifiedName`（既存アクションへの単純参照）としてしか受理できず、
     `do send new X() to Y`のようなインラインsendアクションを受理できない。
  3. `stateBodyElement`には`initialTransitionMember`(`'then' target=qualifiedName ';'`、1537-1539行)は
     あるが、「`accept`/`do`付きで、かつ`first`を省略した暗黙遷移」（`accept X do Y then Z;`のように
     enclosing stateを暗黙のsourceとする形）に対応する規則が無い。
  4. `assignmentStmt`の代入先`target`が`simpleName`のみで、`counter.count := ...`のようなドット区切り
     パスを受理できない。
- **頻度**: `local_only_error`中で send/accept/assign関連が**21ファイル・72件**。
- **根本原因/再現例**:
  - `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1653-1659`（`transitionStmt`）:
    ```
    transitionStmt
        : 'transition' simpleName? 'first' source=qualifiedName
          ( 'accept' trigger=qualifiedName (':' triggerType=namespacePath)? ('via' via=qualifiedName)? )?
          ( 'if' guard=expression )?
          ( 'do' ('action')? effect=qualifiedName )?
          'then' target=qualifiedName ';'
        ;
    ```
    `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/validation/05-State-based Behavior/5-State-based Behavior-1a.sysml:120`
    ```
    transition 'normal-degraded'
        first normal
        accept when 'sense temperature'.temp > vehicle1_c1.Tmax   // ← "when EXPR" 未対応
        do send new 'Over Temp'() to vehicle1_c1.vehicleController // ← インラインsend 未対応
        then degraded;
    ```
    → ローカル: `mismatched input 'accept' expecting 'then'` (line 120) （前の文がまだ閉じられていない扱いになりカスケード）
  - `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1486-1511`（`stateBodyElement`。
    `initialTransitionMember`(1537-1539行)はあるが accept/do付き版が無い）:
    `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/src/org/omg/sysml/xpect/tests/simpletests/StateTest.sysml:17-19,25`
    （XPECTコメントで `noErrors` と明記されている＝公式に正しい構文）
    ```sysml
    state S1;
        accept s : Sig
        do action D
        then S2;                 // "first"省略の暗黙遷移。stateBodyElementに対応する規則が無い
    ...
    accept Exit then done;       // 同上の最短形
    ```
  - `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1314-1316`（`assignmentStmt`）:
    ```
    assignmentStmt
        : isThen='then'? visibilityIndicator? ('action' actionName=simpleName?)? 'assign'? target=simpleName op=('=' | ':=') value=expression ';'
        ;
    ```
    `eval/sysml_samples/derived/.../simpletests/AssignmentTest.sysml:29`
    ```
    do assign counter.count := counter.count + 1;   // target が simpleName のみで dot path 不可
    ```
- **修正方向の当たり**: `transitionStmt`のtrigger節に`'when' guard=expression`・`'at' clock=expression`の
  代替を追加、effect節に`sendActionStmt`/`assignmentStmt`等の既存インラインアクション規則を埋め込む。
  `stateBodyElement`に「`('accept' ... )? ('if' ...)? ('do' ...)? 'then' target ';'`（`first`無し）」の
  代替を追加。`assignmentStmt`の`target`を`qualifiedName`（またはP0-1の対応後は`namespacePath`）に拡張。

---

### P1: 複数ファイルに影響する、個別の構文要素の欠落

#### P1-1. ShortName注釈 `<name>` が一部の `_def` 規則にしか実装されていない

- **症状**: `part <'1'> b: B;`のように、usage側の宣言名の前に短縮名`<...>`を書く形が
  `partUsage`等の**usage系規則には一つも実装されていない**（`packageDef`/`partDef`/`itemDef`/
  `viewDef`/`metadataDef`という一部の`_def`規則にのみ実装済み）。
- **頻度**: `local_only_error`中で**14ファイル・70件**。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:988-997`（`partUsage`。他の`*Usage`規則も同様）
  にはshortName節が無い。一方 `partDef`(707-709行)には`('<' shortName=(ID | QUOTED_NAME) '>')?`がある。
- **再現例**:
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/PartTest.sysml:6`
    ```
    part <'1'> b: B;
    ```
    → ローカル: `extraneous input '<' expecting {...}` (line 6, column 7) に続き
    `mismatched input '>' expecting {...}` (line 6, column 11)。
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/State Space Representation Examples/EVSample.sysml:231`
    ```
    requirement <C1> rangeRequirementSmall :> smallEVRequirement : RangeRequirement { ... }
    ```
- **修正方向の当たり**: `partUsage`/`itemUsage`/`requirementUsage`等のusage系規則にも
  `('<' shortName=(ID | QUOTED_NAME) '>')?`を（`simpleName`の直前あたりに）追加する。

#### P1-2. `exhibit state` usage が `partBodyElement` に登録されておらず、型節も無い

- **症状**: `exhibit state 'name': 'Type';`のように、`part def`本体内に書く`exhibit state`文が
  パースできない。
- **頻度**: 直接該当は2ファイルのみだが、`exhibit state`は状態表明の主要構文の一つ。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:154-156`
  ```
  exhibitStateUsageStmt
      : 'exhibit' 'state' simpleName ';'
      ;
  ```
  が(a) `packageBodyElement`/`topLevelElement`（109-111行付近）にしか登録されておらず
  `partBodyElement`（832-930行）には無い、(b) 型節（`: 'Type'`）を持たない。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/validation/05-State-based Behavior/5-State-based Behavior-1a.sysml:12,17`
  ```sysml
  part def VehicleA {
      perform action 'provide power': 'Provide Power';
      exhibit state 'vehicle states': 'Vehicle States';   // line 12: part def本体内、かつ型節あり
  }
  part def VehicleController {
      exhibit state 'controller states': 'Controller States';  // line 17
  }
  ```
  → ローカル: `extraneous input 'exhibit' expecting {...}` (line 17)（part def本体内では未登録のため）。
- **修正方向の当たり**: `exhibitStateUsageStmt`を`partBodyElement`にも追加し、
  `('exhibit' 'state' simpleName (':' namespacePath)? ';')`のように型節を付与する。

#### P1-3. `stateDef`（ネストした状態機械定義）が `partBodyElement` に登録されていない

- **症状**: `part def X { state def Y { ... } }`のように、part def本体内に`state def`（`state`ではなく
  `state def`、つまりネストした状態定義）を直接書く形がパースできない。`state`（defなし、usage形）は
  `partBodyElement`に登録済みだが`state def`は登録されていない。
- **頻度**: 1ファイル内で15箇所（`smart-home-complex.sysml`のような大規模実サンプルで、同一構造が
  繰り返し使われるため1ファイルへの影響が大きい）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1475-1477`
  ```
  stateDef
      : isAbstract='abstract'? 'state' 'def' simpleName inheritanceClause? ( '{' stateBodyElement* '}' | ';' )
      ;
  ```
  は`packageBodyElement`(54行目)と`stateBodyElement`(1490行目、state-in-state用)にしか登録されておらず、
  `partBodyElement`(832-930行)のリストには含まれていない（`stateUsage`は914行目で登録済み）。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-lsp/examples/smart-home-complex.sysml:175`
  ```sysml
  part def SomeDevice {
      ...
      state def DeviceLifecycle {     // line 175: part def本体内の state def
          doc /* ... */
          state provisioning;
          ...
      }
  }
  ```
  → ローカル: `extraneous input 'def' expecting {'{', ';', ':', ':>', ':>>', 'subsets', 'redefines', '[', 'type', ID, QUOTED_NAME}` (line 175, column 14)
  （`state`の直後は`stateUsage`としてしかマッチせず、`simpleName`ではない予約語`def`が来て失敗する）。
  同ファイル内に同型のエラーが10箇所（level 175, 307, 414, 456, 492, 705, 745, 818, 1023 他）繰り返される。
- **修正方向の当たり**: `partBodyElement`のリストに`stateDef`を追加する（1行追加で解決する見込みの
  高い、コストの低い修正）。

#### P1-4. `connectionEndMember` の型節が conjugation `~` に非対応（`portUsage` とは非対称）

- **症状**: `end port p4: ~P;`のように、connection/interface定義本体の`end`メンバーで
  conjugatedな型参照（`~TypeName`）を書くとパースできない。同じ「型の共役」記法は`portUsage`
  （`port p2: ~P;`）では既に対応済みであり、実装の非対称性が原因。
- **頻度**: **5ファイル・15件**。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:647-656`
  ```
  connectionEndMember
      : 'end' (endName=simpleName endMult=multiplicitySpec?)?
        kind=('occurrence' | 'port' | 'item')?
        isRef='ref'?
        innerName=simpleName?
        (':' ID)?                         // ← conjugated='~'? が無い
        multiplicitySpec?
        ...
  ```
  一方 `portUsage`（1858-1867行）は `(':' conjugated='~'? ID)?` と既に対応済み。
- **再現例**:
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/ConjugationTest.sysml:16`
    ```sysml
    interface def I {
        end p1: P;
        end p2: ~P;     // line 16
    }
    ```
    → ローカル: `extraneous input '~' expecting ID` (line 16, column 10)
  - `eval/sysml_samples/raw/sysml-v2-models/models/example_family/family.sysml:94`
    ```
    end communicationPartnerB : ~VerbalExchange;
    ```
- **修正方向の当たり**: `connectionEndMember`の`(':' ID)?`を`(':' conjugated='~'? ID)?`へ変更するだけの
  極めて小さな修正で直る見込み。

#### P1-5. `comment`/`doc` 文の `about <ref>` 節・`locale <string>` 節が未実装

- **症状**: `comment about C /* ... */`（コメント対象の明示）、`doc locale "en_US" /* ... */`
  （ロケール注釈）のいずれも文法に無い。
- **頻度**: `local_only_error`中で**6ファイル・9件**（ただし公式コーパスの`comment`/`doc`利用のかなりの
  割合がこれらの節を伴うため、実際の影響は「該当メッセージ数」以上に広い）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:255-265`
  ```
  commentStmt
      : 'comment' simpleName? DOC_COMMENT
      ;
  documentationStmt
      : 'doc' simpleName? DOC_COMMENT
      ;
  textualRepresentationStmt
      : ('rep' simpleName)? 'language' STRING_LITERAL DOC_COMMENT
      ;
  ```
  いずれも`about`/`locale`節を持たない（`locale`は文法コメントで「未対応」と明記済みだが、`about`は
  未実装であることの記述が無く見落とされていた可能性がある）。
- **再現例**:
  - `eval/sysml_samples/raw/sysml2-cli/tests/fixtures/official/phase2-basic/Comments.sysml:13`
    ```
    comment about Comments /* Comment about Package */
    ```
    → ローカル: `extraneous input 'Comments' expecting DOC_COMMENT` (line 13, column 16)
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/CommentTest.sysml:32`
    ```
    doc locale "en_US" /* Documentation about Package */
    ```
    → ローカル: `extraneous input '"en_US"' expecting DOC_COMMENT` (line 32, column 12)
- **修正方向の当たり**: `commentStmt`に`('about' about=namespacePath)?`を、
  `documentationStmt`/`textualRepresentationStmt`に`('locale' locale=STRING_LITERAL)?`を追加する。

---

### P2: 単一構文要素の欠落（影響ファイル数は少ないが再現性は高い）

#### P2-1. `messageUsage` に `of Type[mult]`（ペイロード型節）が無い

- **頻度**: 4ファイル・27件（`17-Sequence Modeling`系・`webshop`・`family.sysml`）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1379-1385`
  ```
  messageUsage
      : isAbstract='abstract'? 'message' simpleName?
        (':' ID)?
        multiplicitySpec?
        ...
  ```
  `'of' payloadType=namespacePath multiplicitySpec?`という代替形が無い。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/validation/17-Sequence Modeling/17b-Sequence-Modeling.sysml:26`
  ```
  message publish_message of Publish[1];
  ```
  → ローカル: `mismatched input 'of' expecting {'{', ';', ':', ':>', ':>>', 'subsets', 'redefines', '['}` (line 26, column 26)

#### P2-2. `succession flow NAME from A to B;`（succession + flow の複合キーワード形）が未実装

- **頻度**: 4ファイル・6件。
- **根本原因**: `successionUsage`（`sysml_v2_checker_advanced/antlr/SysMLMin.g4:1580-1585`）は
  `'succession' simpleName? multiplicitySpec? 'first' ... 'then' ...`という`first`/`then`形のみで、
  `'succession' 'flow' simpleName 'from' ... 'to' ...;`という別形（flowと succession を組み合わせた
  `SuccessionFlowUsage`)には対応していない。
- **再現例**: `eval/sysml_samples/raw/sysml2-cli/tests/fixtures/official/phase2-basic/FlashlightExample.sysml:48`
  ```
  succession flow onOffCmdFlow from sendOnOffCmd.onOffCmd to produceDirectedLight.onOffCmd;
  ```
  → ローカル: `extraneous input 'flow' expecting {'[', 'type', 'first', ID, QUOTED_NAME}` (line 48, column 13)

---

## 4. 参照実装側だけがエラーを検出するケース（`reference_only_error`, 26件）の内訳

### 4.1 本当にローカルのlintルールが未実装なもの（真の偽陰性）

`sysml_v2_checker_advanced/linter_rules/*.py`をgrepし、以下のルールがいずれも実装されていないことを確認した
（`state_machine_rules.py`にはentry/do/exit の**kindタグ検証**はあるが、「1つしか持てない」という
**重複数チェック**は無いなど、"似て非なる"チェックはあっても対象の意味検証そのものは無い）:

| 参照実装のメッセージ | 該当ファイル数 | 未実装の確認方法 |
|---|---:|---|
| `An attribute must be typed by attribute definitions.` 等 "must be typed by" 系 | 多数（ただし§4.2参照） | - |
| `Cannot override a binding feature value` | 7 | `linter_rules/`に該当ロジック無し |
| `Only one return parameter is allowed` | 2 | `linter_rules/definition_usage_rules.py`にreturn parameter数チェック無し |
| `A state may have at most one entry/do/exit action.` | 各2 | `state_machine_rules.py`はkindタグ検証のみ、重複数チェック無し |
| `Only one subject is allowed.` / `Subject must be first parameter.` | 各2 | `linter_rules/`に該当ロジック無し |
| `Subsetting/redefining feature cannot be nonunique if subsetted/redefined feature is unique` | 2 | `linter_rules/`に該当ロジック無し |
| `Must invoke a behavior or a behavioral feature` | 1 | `linter_rules/`に該当ロジック無し |
| `Must be an accessible feature (use dot notation for nesting)` | 3 | `linter_rules/`に該当ロジック無し |

これらはいずれも `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/.../validation/invalid/*.sysml`
という、公式Pilot Implementation自身が「1ファイル1ルール」の意図的invalidテストとして用意しているもの由来で、
頻度（1〜7件）は低いが、対応するSysML v2の意味制約が明確でテストケースも既製であるため、
実装難易度は比較的低いと考えられる。

代表例: `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/src/org/omg/sysml/xpect/tests/validation/invalid/RequirementSubject_Invalid.sysml`
（"Only one subject is allowed." / "Subject must be first parameter." を意図的に踏む最小fixture）。

### 4.2 単一ファイル解析の設計限界によるもの（意図的なスコープ外。バグではない）

`Couldn't resolve reference to Type/Feature/Namespace 'X'.`、`An attribute/usage must be typed by ... definitions.`、
`An occurrence, item or part must be typed by occurrence definitions.` 等は、いずれも
「標準ライブラリ型（`Real`/`Integer`/`String`/`Boolean`等）や他ファイルの型を`import`していない、
または他ファイルの要素を参照している」ことに起因する。例:

- `eval/sysml_samples/raw/sysml2-cli/tests/fixtures/modify/delete-basic.sysml`
  （フォーマッタ/編集操作のテストフィクスチャで、`ScalarValues`のimportを意図的に省略している）
- `eval/sysml_samples/raw/sysml-v2-lsp/test/fixtures/valid/camera.sysml`, `vehicle.sysml`
- `eval/sysml_samples/raw/sysml-v2-pilot-implementation/org.omg.sysml.xpect.tests/src/Vehicle.sysml`

ローカルチェッカーは単一ファイルの構文解析＋ヒューリスティックなlintに徹しており、標準ライブラリや
他ファイルに対するフル型解決を行わない設計になっている。これは仕様上の判断であり、直ちに「バグ」として
扱うべきではないが、**将来的にローカルライブラリのスタブ（`ScalarValues`等の主要な型名だけを
"既知の組み込み型"として許可するテーブル）を持たせる**ことで、この種の偽陰性の一部（および
`local_only_error`側での過剰な"Couldn't resolve"的誤検出があれば、それ）を減らせる可能性がある。

### 4.3 【重要・要フォローアップ】参照実装（比較ハーネス）が裸の `import` 文を一律で拒否する問題

`reference_only_error`のうち3件（`e3003_valid_import.sysml`, `Import_Visibility_Invalid.sysml`,
`CalculationExample.sysml`）は、いずれも一見単純な `import X::*;`（ビジビリティ修飾子
`public`/`private`/`protected`無し）が原因で、参照実装が
`mismatched input 'import' expecting '}'` → `no viable alternative at input '::'` →
（ファイル末尾で）`extraneous input '}' expecting EOF` という一連の構文エラーを返している。

**これは当初「ローカルの文法が緩すぎて`import X::`という不正構文を見逃している」という仮説だったが、
本調査で全く異なる、より根深い原因であることが判明した。**

#### 検証手順と結果

1. `.venv`のPythonから`eval/sysml_reference/reference_driver.py`の`run_reference_check`を直接呼び出し、
   最小の再現ケースを作成:
   ```python
   text = '''package Foo {
       import ISQ::*;
       part def Bar;
   }
   '''
   ```
   → 参照実装は `mismatched input 'import' expecting '}'` 等のエラーを返す（**再現可能**）。
2. `import`を`private import`に変えるだけで、上記エラーは**消える**（クリーンにパースされる）。
   `public import`/`protected import`でも同様に成功する。
3. 位置を変えても（ファイル先頭、`part def`の後、ファイル冒頭のimportなし版等）、
   ビジビリティ修飾子を伴わない`import`は**常に**失敗する。
4. コーパス全体（730件）を機械的に走査したところ、「ビジビリティ修飾子なしの`import`文を含むファイル」は
   **37件**存在し、そのうち**32件が`both_error`、5件が`reference_only_error`に分類され、
   `both_clean`または`local_only_error`に分類されたものは1件も無かった**（100%の再現率）。
5. `RefDriver.java`は内部で `SysMLInteractive.process(text, false)`（Jupyterカーネル用APIの
   第2引数`false`）を呼んでいる。この第2引数を`true`に変えて再コンパイル・再実行しても
   **同じエラーが再現した**ため、この引数が原因ではないことも確認済み。
6. コーパス全体では、ビジビリティ修飾子付きimportを使うファイルが407件あるのに対し、
   修飾子なしimportのみを使うファイルは25件（他に12件は両方のスタイルを混在）と、
   明らかに少数派のスタイルである。

#### 結論と推奨事項

- ローカルの`importStmt`文法（`visibilityIndicator? 'import' namespacePath ('::' '*')? ';'`、
  `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1878-1880`）は、ビジビリティ修飾子を任意
  （`?`）として扱っており、これはSysML v2の一般的なスタイル・他の"bare import"利用例と矛盾しない。
  **この点についてローカルの文法を「参照実装に合わせて修飾子必須にする」修正は推奨しない**
  （参照実装側の挙動の方が疑わしいため）。
- 原因は次のいずれかと推測される（本調査では特定until至らず）:
  (a) 評価に使っている `jupyter-sysml-kernel-0.61.0-all.jar` 固有の既知の不具合
  （**2026-09-24追記: 0.62.0 でも出力は同一だったので、少なくとも版を1つ上げただけでは
  解消しない**。§v4-1）、
  (b) `SysMLInteractive`というJupyterカーネル向けAPI（`next()`/`counter`フィールドを持つ、
  対話的セッション/セル評価を想定した設計）を「1ファイルまるごとの静的解析」目的で流用していることに
  起因する使い方の不整合。
- **今後の対応案**: (1) 同梱されているjarから`SysMLInteractive`以外のバッチ向けエントリポイント
  （もしあれば）を探して切り替える、(2) 別バージョンのPilot Implementation jarで同じ再現ケースを試す、
  (3) 少なくとも本レポートの`both_error`/`reference_only_error`の集計値を解釈する際は、
  「ビジビリティ修飾子なしimportを含むファイル37件」を別枠として扱う、のいずれか。
  **`both_error`215件のうち32件（約15%）はこの問題が(部分的に)混入していることに注意。**

---

## 5. `both_error`（両実装がエラーを検出、215件）のサンプリング調査

自動分類ツールは未整備のため、`random.seed(42)`で12件をランダム抽出し目視確認した
（`eval/sysml_results/*.json`を直接参照。作業に使ったスクリプトは
`C:\Users\...\scratchpad\both_error_sample.py`、内容は本文末尾の付記を参照）。

**結論: 12件中ほぼ全てで、ローカルと参照実装は「別々の理由」でエラーを検出しており、
"both_error"は「両方が同じ問題を見つけた」ことを意味しない。**

代表例:

| ファイル | ローカルの検出内容 | 参照実装の検出内容 | 一致度 |
|---|---|---|---|
| `AllocationUsage_Invalid.sysml`（xpect） | `extraneous input ':' expecting {...}`（構文） | `An allocation must be typed by allocation definitions.`（意味） | 不一致（別問題） |
| `apollo-11-sysml-v2/Technical/SystemPackage.sysml` | `individual`修飾子の構文ギャップ（P0-3） | 他ファイル未import起因の大量`Couldn't resolve reference`カスケード | 不一致（別問題） |
| `smart-home-complex.sysml` | `state def`のpartBodyElement未登録（P1-3）× 10箇所 | `ScalarValues`未import起因の`Couldn't resolve reference to Type 'Real'/'String'/...` | 不一致（別問題。このファイルはimport文自体を1つも持たない） |
| `TrafficLightIntersectionRequirements.sysml` | `actor driver`等のキーワード直後スペース欠落によるトークン化失敗の疑い（未分類、要個別調査） | §4.3の「裸のimport」問題＋型未解決カスケード | 不一致（別問題） |
| `.../training/12. Binding Connectors Example-1.sysml` | 独自ルールで `Import 'Port Example::*' が存在しないパッケージ 'Port Example' を参照しています` を検出 | `Couldn't resolve reference to Namespace ''Port Example''.`から始まる型解決カスケード | **一致（数少ない、実質同じ根本原因を検出できている好例）** |

最後の例（Binding Connectors Example-1.sysml）は、ローカルの「存在しないパッケージへのimportを検出する」
独自ルールが、参照実装の型解決失敗と実質的に同じ根本原因（存在しないパッケージ`'Port Example'`への
import）を捉えられている数少ない一致例であり、ローカルチェッカーの独自ルールにも一定の価値があることを
示している。

**示唆**: `both_error`を「両実装が合意した高信頼の問題」として扱うのは誤りである。今後の分析・改善では
`both_error`内の個々のケースについても、両者の診断メッセージを突き合わせて「同じ根本原因か」を
判定する仕組み（例えば行番号の近接度や意味カテゴリでのラフなマッチング）を用意すると、
より正確な「両実装一致率」が把握できる。

---

## 6. まとめ: 優先順位付き問題一覧（再掲）

| 優先度 | 問題 | 該当ファイル数(概算) | 種別 |
|---|---|---:|---|
| P0-1 | `qualifiedName`が`::`非対応（式/alias/transition/assign等広範） | 33+ | 文法カバレッジ（横断的） |
| P0-2 | Occurrence portion usage（snapshot/timeslice）が簡略化されすぎ | 8+ | 文法カバレッジ（大分類） |
| P0-3 | `individual`が独立構文でプレフィックス修飾子になっていない | 6+ | 文法カバレッジ（大分類） |
| P0-4 | メタデータ注釈 `#Type`/`@Type{}` が未実装（`@`はlexerにも無い） | 25+ | 文法カバレッジ（大分類） |
| P0-5 | transition/stateのaccept/do節が狭い、暗黙遷移形が無い、assign対象がdot path非対応 | 21+ | 文法カバレッジ（大分類） |
| P1-1 | ShortName `<name>` がusage系規則に無い | 14 | 個別ルール欠落 |
| P1-2 | `exhibit state`がpartBodyElement未登録＋型節無し | 2 | 個別ルール欠落 |
| P1-3 | `stateDef`がpartBodyElement未登録 | 1ファイルに集中(10箇所) | 個別ルール欠落（低コスト修正） |
| P1-4 | `connectionEndMember`がconjugation `~`非対応（portUsageとの非対称） | 5 | 個別ルール欠落（低コスト修正） |
| P1-5 | `comment`/`doc`の`about`/`locale`節が無い | 6 | 個別ルール欠落 |
| P2-1 | `messageUsage`に`of Type[mult]`節が無い | 4 | 単発 |
| P2-2 | `succession flow ... from ... to ...;`複合形が無い | 4 | 単発 |
| §4.1 | 意味検証ルール7種が未実装（return parameter数、entry/do/exit重複、subject制約、nonunique制約、behavior呼び出し制約、accessible feature制約、binding feature override制約） | 各1〜7 | lintルール欠落（reference_only_error） |
| §4.2 | 単一ファイル解析の設計限界による型未解決カスケード | 多数 | 意図的スコープ外（バグではない） |
| §4.3 | 参照実装が裸のimportを一律拒否する（ハーネス側の疑わしい挙動） | 37（both_error内32含む） | ハーネス/参照実装側の制約（要フォローアップ） |

---

## 7. 本レポートのスコープについて

本レポートは**問題の洗い出し（analyze_findings + report）までをスコープ**としており、
上記いずれの問題についても文法・lintルールの修正実装は行っていない。修正は別プランとして
今後着手されることを想定し、各問題について再現可能な最小限の情報（ファイルパス・行番号・
該当する文法規則の行番号・診断メッセージ）を記載した。

修正着手時の推奨順序は §6 の表の優先度（P0 > P1 > P2）に従うことを推奨するが、
P0-4（メタデータ注釈）はP0の中でも実装コストが大きい一方、P1-3・P1-4は1〜数行の修正で
解決できる可能性が高く「低コスト・即着手可能」なクイックウィンとして先に着手する価値がある。
また §4.3（参照実装が裸のimportを拒否する問題）は、ローカルの修正ではなく評価ハーネス自体の
検証・改善が必要な項目であるため、他の項目と並行して別途フォローアップすることを推奨する。
