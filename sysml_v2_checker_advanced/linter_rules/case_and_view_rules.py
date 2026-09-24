"""case_and_view_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

from typing import Dict

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue

# objective は1つまで(8.2.2.22-25)。この制約を適用するノード種別。
# 参照実装(jar 0.61.0)へ1種別ずつ問い合わせて確定（2026-09-04）:
# case / use case / analysis case / verification case の def・usage が対象。
# requirement def は `objective` を構文として受理しないため対象外。
_OBJECTIVE_LIMIT_NODE_TYPES = (
    "case_def", "case_usage",
    "use_case_def", "use_case_usage",
    "analysis_case_def", "analysis_case_usage",
    "verification_case_def", "verification_case_usage",
)

# view rendering は1つまで(8.2.2.26)。参照実装はdefとusageでメッセージを
# 書き分ける（"A view definition may have at most one view rendering." /
# "A view may have at most one view rendering."）ので、こちらも表記を分ける。
# 数えるのは`render`メンバー（AST: render_stmt）だけで、`rendering r;`という
# 素のrendering usageは対象外（参照実装で実測、2026-09-04）。
_VIEW_RENDERING_LIMIT_NODE_TYPES = ("view_def", "view_usage")

# snapshot / timeslice（portion usage）は occurrence の定義か使用が所有して
# いなければならない(8.2.2.9)。ここは「所有者として不正だと実測できた型」の
# 拒否リストにしてある。参照実装での実測（2026-09-04）:
#   package直下 → エラー / attribute def内 → エラー
#   package を書かないファイル直下（このパーサーでは `root` ノード）→ エラー
#   part usage内・part def内・timeslice内 → クリーン
# 「occurrenceか」を型階層から判定する実装にすると、列挙し漏れた所有者型を
# 一律エラーにして偽陽性を出す危険があるため、実測できた2つに限定する
# （検出漏れは許容する。PortionUsage_Invalid.sysmlはpackage直下なので拾える）。
_PORTION_USAGE_INVALID_OWNER_TYPES = ("root", "package", "attribute_def")

# `verify` が置ける唯一の場所は「verification case の objective の直下」
# (8.2.2.25)。参照実装で実測して確定（2026-09-05）。
_VERIFICATION_CASE_NODE_TYPES = ("verification_case_def", "verification_case_usage")


class CaseAndViewRulesMixin:
    def _check_occurrence_advanced_rules(self) -> None:
        """
        Occurrence 関連の高度ルールチェック (8.2.2.9)

        - OccurrenceDefinitionPrefix の isIndividual チェック
        - EventOccurrenceUsage の構造チェック

        OccurrenceUsage自体の固有チェックは無い（_check_occurrence_usageの
        docstring参照。PortionKind検証は構造的に到達不能なため削除済み）。

        IndividualDefinition の EmptyMultiplicityMember 検証は2026-09-07に
        削除した（そのような制約は参照実装に存在せず、`individual def` に
        多重度を書くこと自体が構文エラーになる。詳細はこのファイルの
        コミット履歴と、下の `individual_def` 分岐が消えている理由）。
        """
        for sym_name, sym_node in self.symbols.items():
            node_type = sym_node.get("type")
            
            if node_type == "occurrence_def":
                self._check_occurrence_definition(sym_node, sym_name)
            elif node_type == "occurrence_usage":
                self._check_occurrence_usage(sym_node, sym_name)
            elif node_type == "event_occurrence_usage":
                self._check_event_occurrence_usage(sym_node, sym_name)
    def _check_occurrence_definition(self, node: Dict, node_name: str) -> None:
        """OccurrenceDefinition の構造チェック"""
        is_individual = node.get("isIndividual", False)
        if is_individual:
            # Individual の場合は EmptyMultiplicity が必要
            multiplicity = node.get("multiplicity")
            if multiplicity and multiplicity.get("size") is not None:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.9] Individual occurrence '{node.get('name', node_name)}' は空の多重度である必要があります",
                    node
                ))
    # `_check_individual_definition` は2026-09-07に削除した。
    #
    # 「Individual definition は空の多重度を持つ必要がある」という制約を課し、
    # `not multiplicity` すなわち**多重度が書かれていないとき**に発火していた。
    # 730件コーパスのルール別一致率でconfidence 0.143（そのルールだけがerrorを
    # 出した7ファイル中6件で参照実装と不一致）と最下位群にあり、xpectの
    # **valid**フィクスチャ validation/valid/IndividualUsage.sysml
    # （`// XPECT noErrors`）の `individual def Vehicle_1 :> Vehicle { ... }` と
    # `individual def Wheel_1 :> Wheel;` を落としていた。
    #
    # 参照実装(jar 0.61.0)へ問い合わせて確定（2026-09-07、canaryを前後に挟んで実施）:
    #
    #   individual def V_1 :> V;        -> クリーン
    #   individual def V_1;             -> クリーン
    #   individual def V_1[] :> V;      -> 構文エラー no viable alternative at input '['
    #   individual def V_1[1] :> V;     -> 同上
    #   individual def V_1 :> V [];     -> 同上
    #   individual v1[2] : V_1;         -> クリーン（usage側は多重度を書ける）
    #
    # つまり**定義に多重度を書くこと自体が文法上できない**ため、この制約は
    # 参照実装に存在しない。「多重度が無い」は唯一の合法な状態であり、それを
    # 無条件にエラーにしていた。緩和ではなくルールごと削除するのが正しい。
    #
    # なお同ファイルの `_check_occurrence_definition` にも isIndividual 時の
    # 多重度チェックが残っているが、そちらは「多重度が有り、かつ size が
    # None でない」ときだけ発火する。上記のとおり参照実装は定義への多重度を
    # 構文段階で拒否するので、その条件は正当な入力では成立し得ず、730件でも
    # 一度も発火していない。害が無いため今回は触っていない。
    def _check_occurrence_usage(self, node: Dict, node_name: str) -> None:
        """
        OccurrenceUsage の構造チェック

        antlr_transformer.py の occurrence_usage ノードは isPortion=False /
        portionKind=None を常に固定出力する。portion セマンティクス
        （`snapshot X;` / `timeslice X;`）は occurrence_usage ではなく別ノード型
        portion_usage が担当するため、occurrence_usage が isPortion=True を持つ
        ことは現行パーサーの設計上ありえない。
        portion_usage 側の kind も文法上 'snapshot' | 'timeslice' の2択に
        限定されており（antlr/SysMLMin.g4 の portionUsageStmt）、不正な
        portionKind が生成されること自体が構造的に起こりえない。
        現時点で occurrence_usage について検証すべき固有ルールは無い。
        """
    def _check_event_occurrence_usage(self, node: Dict, node_name: str) -> None:
        """EventOccurrenceUsage の構造チェック。

        以前はここで「参照サブセッティングを持つことが推奨されます」という
        warning を出していたが、AST の ownedReferenceSubsetting は常に空で、
        **すべての event に出ていた**。しかもその勧めに従って
        `event occurrence sendM;`（正しい宣言。sequence ビューにはこれが要る）を
        `event sendM;` に書き換えると、参照先の無い参照になってエラーになる。
        参照実装にも対応する警告は無いので削除した（2026-09-24）。
        `event X;`（参照形）の参照先は linter._check_event_references が見る。
        """
    def _check_requirement_advanced_rules(self) -> None:
        """
        Requirement 高度ルールチェック (8.2.2.19)
        
        - RequirementBody の構造チェック
        - Assume/Require/Satisfy の関係性検証
        - RequirementConstraintMembership の検証
        """
        for requirement in self.requirements:
            self._check_requirement_structure(requirement)
            self._check_requirement_relationships(requirement)
    def _check_requirement_structure(self, requirement: Dict) -> None:
        """
        Requirement の構造チェック (8.2.2.19)

        現行文法の requirementBodyElement は docMember（`doc /* ... */`）
        のみをサポートし（subject/reqId等は未対応）、requirement_defノードに
        "reqBody"/"reqId" キーが設定されることはない。

        docMemberの出力は documentationStmt と同一のAST形状（"documentation"型、
        identification/body）に統一されているため、本文の空チェック等は
        _check_rulesの通常の再帰経由で_check_documentation_stmtが既に行う
        （二重実装しない）。ここでは requirementBodyElement自体にdoc（説明文）が
        1つも無いことの推奨警告のみ行う。
        """
        has_doc = any(
            isinstance(child, dict) and child.get("type") == "documentation"
            for child in requirement.get("children", [])
        )

        if not has_doc:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.19] Requirement '{requirement.get('name')}' はdoc（説明文）を持つことが推奨されます",
                requirement
            ))
    def _check_requirement_relationships(self, requirement: Dict) -> None:
        """Requirement の関係性チェック"""
        children = requirement.get("children", [])
        
        assume_count = 0
        require_count = 0
        
        for child in children:
            if isinstance(child, dict):
                child_type = child.get("type")
                if child_type == "assume_constraint":
                    assume_count += 1
                elif child_type == "require_constraint":
                    require_count += 1
        
        # Assume と Require の適切な組み合わせチェック
        if assume_count > 0 and require_count == 0:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.19] Requirement '{requirement.get('name')}' は assume を持つ場合、require も持つことが推奨されます",
                requirement
            ))
    def _check_analysis_case_advanced_rules(self) -> None:
        """
        Analysis Case 高度ルールチェック (8.2.2.20)
        
        - AnalysisCaseBody の構造チェック
        - Subject/Objective/Result の関係性検証
        - AnalysisAction の kind 検証
        """
        for analysis_case in self.analysis_cases:
            self._check_analysis_case_structure(analysis_case)
            self._check_analysis_actions(analysis_case)
    def _check_analysis_case_structure(self, analysis_case: Dict) -> None:
        """
        Analysis Case の構造チェック (8.2.2.20)

        現行文法の analysis_case_def は part_def 同様 partBodyElement を
        流用するのみで、AnalysisCaseBody/Subject に相当する専用構文を
        一切生成しない（"caseBody"/"subject" キーは存在しない）ため、
        現時点で検証すべき固有ルールは無い。
        """
    def _check_analysis_actions(self, analysis_case: Dict) -> None:
        """Analysis Actions の kind 検証"""
        children = analysis_case.get("children", [])
        
        for child in children:
            if isinstance(child, dict) and child.get("type") == "analysis_action":
                kind = child.get("kind")
                if kind not in ["analysis", "objective", "result"]:
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"[8.2.2.20] Analysis action の kind は 'analysis', 'objective', 'result' のいずれかである必要があります: {kind}",
                        child
                    ))
    def _check_verification_case_advanced_rules(self) -> None:
        """
        Verification Case 高度ルールチェック (8.2.2.21)
        
        - VerificationCaseBody の構造チェック
        - Verify/Objective の関係性検証
        - VerificationAction の kind 検証
        """
        for verification_case in self.verification_cases:
            self._check_verification_case_structure(verification_case)
            self._check_verification_actions(verification_case)
    def _check_verification_case_structure(self, verification_case: Dict) -> None:
        """
        Verification Case の構造チェック (8.2.2.21)

        現行文法の verification_case_def は part_def 同様 partBodyElement を
        流用するのみで、VerificationCaseBody/VerifiedRequirement に相当する
        専用構文を一切生成しない（"caseBody"/"verifiedRequirement" キーは
        存在しない）ため、現時点で検証すべき固有ルールは無い。
        """
    def _check_verification_actions(self, verification_case: Dict) -> None:
        """Verification Actions の kind 検証"""
        children = verification_case.get("children", [])
        
        for child in children:
            if isinstance(child, dict) and child.get("type") == "verification_action":
                kind = child.get("kind")
                if kind not in ["verification", "objective"]:
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"[8.2.2.21] Verification action の kind は 'verification', 'objective' のいずれかである必要があります: {kind}",
                        child
                    ))
    def _check_use_case_advanced_rules(self) -> None:
        """
        Use Case 高度ルールチェック (8.2.2.22)
        
        - UseCaseBody の構造チェック
        - Include/Extend の関係性検証
        - Actor の参照チェック
        """
        for use_case in self.use_cases:
            self._check_use_case_structure(use_case)
            self._check_use_case_relationships(use_case)
    def _check_use_case_structure(self, use_case: Dict) -> None:
        """
        Use Case の構造チェック (8.2.2.22)

        現行文法の use_case_def は part_def 同様 partBodyElement を
        流用するのみで、UseCaseBody/Actor に相当する専用構文を一切
        生成しない（"caseBody"/"actors" キーは存在しない）ため、
        現時点で検証すべき固有ルールは無い。
        """
    def _check_single_objective(self, node: Dict, namespace: str) -> None:
        """case系ノードの objective は1つまで（CaseSubjectObjective_Invalid.sysml）。

        参照実装との比較評価で見つかった偽陰性（比較レポートv2 §v2-3、
        `Only one objective is allowed.`）。対象ノード種別は
        `_OBJECTIVE_LIMIT_NODE_TYPES`（参照実装へ1種別ずつ問い合わせて確定）。

        **自ノードが直接持つ objective だけを数える。** 参照実装は
        `case def C1 :> C { objective o5; }`（Cが既にobjectiveを持つ）や
        `case c1 : C1;`（objectiveを一切書いていない）のように、継承された
        objectiveも合わせて数えてエラーにするが、こちらは型解決が必要で
        偽陽性リスクが高いため実装しない（同フィクスチャ内の直接宣言2件は
        検出できるので、ファイル単位の検出には足りる）。
        """
        objectives = [
            c for c in node.get("children", [])
            if isinstance(c, dict) and c.get("type") == "objective_usage"
        ]
        name = node.get("name", namespace)
        for extra in objectives[1:]:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.22] '{name}' にobjectiveが複数定義されています(1つのみ許可)",
                extra
            ))

    def _check_single_view_rendering(self, node: Dict, namespace: str) -> None:
        """view def / view usage の view rendering は1つまで
        （ViewRendering_invalid.sysml、参照実装の
        "A view definition may have at most one view rendering." /
        "A view may have at most one view rendering."）。

        数えるのは`render`メンバー（AST: `render_stmt`）だけ。
        `rendering r3;`のような素の rendering usage は何個あっても違反ではない
        （参照実装で実測して確認、2026-09-04。比較レポートv2 §v2-3）。
        """
        renders = [
            c for c in node.get("children", [])
            if isinstance(c, dict) and c.get("type") == "render_stmt"
        ]
        if len(renders) <= 1:
            return
        kind = "View definition" if node.get("type") == "view_def" else "View"
        name = node.get("name", namespace)
        for extra in renders[1:]:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.26] {kind} '{name}' のview renderingは1つのみ許可されます",
                extra
            ))

    def _check_portion_usage_owner(self, node: Dict, namespace: str) -> None:
        """snapshot / timeslice は occurrence の定義か使用が所有していなければ
        ならない (8.2.2.9)。

        参照実装との比較評価で見つかった偽陰性（PortionUsage_Invalid.sysml、
        比較レポートv2 §v2-3、`Must be owned by an occurrence definition or
        usage.`）。所有者側から見て判定する。対象の所有者型は
        `_PORTION_USAGE_INVALID_OWNER_TYPES`（実測できたものだけの拒否リスト）。
        """
        owner_name = node.get("name", namespace)
        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("type") == "portion_usage":
                kind = child.get("kind") or "snapshot/timeslice"
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.9] {kind} '{child.get('name')}' は "
                    f"occurrenceの定義または使用が所有していなければなりません"
                    f"（現在の所有者: '{owner_name}'）",
                    child
                ))

    def _check_verify_requirement_placement(self, ast: Dict) -> None:
        """`verify` は verification case の objective の直下にしか置けない
        (8.2.2.25)。

        参照実装との比較評価で見つかった偽陰性（Verification_invalid.sysml、
        比較レポートv2 §v2-3、`A requirement verification must be in the
        objective of a verification case.`）。

        参照実装(jar 0.61.0)への問い合わせで確定した境界（2026-09-05）:

        - `verification def VC { objective { verify r; } }` → クリーン。
        - `verification vc : VCD { objective { verify r; } }`（usage）→ クリーン。
        - `requirement def R { verify r; }` → エラー。
        - `verification def VC { requirement { verify r; } }` → エラー
          （verification case の中でも objective 以外はだめ）。
        - `case def VP { objective { verify r; } }` → エラー
          （objective でも所有者が verification case でなければだめ）。
        - `verification def VC { objective { requirement { verify r; } } }`
          → エラー（1段深いネストも不可。**直下**でなければならない）。

        所有チェーンはASTにそのまま出ているので型解決は要らない。ただし
        「直上がobjective」「その直上がverification case」という2段の関係な
        ため、ノード単位のディスパッチでは判定できない。ここだけ祖先の型を
        持ち回る再帰走査にしてある。
        """

        def walk(node: Dict, parent_type: str | None, grandparent_type: str | None) -> None:
            for child in node.get("children", []):
                if not isinstance(child, dict):
                    continue
                if child.get("type") == "verify_requirement_usage":
                    in_objective = node.get("type") == "objective_usage"
                    owner_is_verification = parent_type in _VERIFICATION_CASE_NODE_TYPES
                    if not (in_objective and owner_is_verification):
                        name = child.get("name") or child.get("type_name") or "(無名)"
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.25] verify '{name}' は verification case の "
                            f"objective の直下に置かなければなりません",
                            child
                        ))
                walk(child, node.get("type"), parent_type)

        walk(ast, None, None)

    def _check_case_def(self, node: Dict, namespace: str) -> None:
        """case定義のチェック (8.2.2.22)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.22] Case definition には名前が必要です",
                node
            ))
    def _check_case_usage(self, node: Dict, namespace: str) -> None:
        """case使用のチェック (8.2.2.22)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.22] Case usage には名前を指定することが推奨されます",
                node
            ))
    def _check_analysis_case_def(self, node: Dict, namespace: str) -> None:
        """analysis case定義のチェック (8.2.2.23)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.23] Analysis case definition には名前が必要です",
                node
            ))
    def _check_analysis_case_usage(self, node: Dict, namespace: str) -> None:
        """analysis case使用のチェック (8.2.2.23)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.23] Analysis case usage には名前を指定することが推奨されます",
                node
            ))
    def _check_verification_case_def(self, node: Dict, namespace: str) -> None:
        """verification case定義のチェック (8.2.2.24)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.24] Verification case definition には名前が必要です",
                node
            ))
    def _check_verification_case_usage(self, node: Dict, namespace: str) -> None:
        """verification case使用のチェック (8.2.2.24)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.24] Verification case usage には名前を指定することが推奨されます",
                node
            ))
    def _check_use_case_def(self, node: Dict, namespace: str) -> None:
        """use case定義のチェック (8.2.2.25)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.25] Use case definition には名前が必要です",
                node
            ))
    def _check_use_case_usage(self, node: Dict, namespace: str) -> None:
        """use case使用のチェック (8.2.2.25)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.25] Use case usage には名前を指定することが推奨されます",
                node
            ))
    def _check_include_use_case_usage(self, node: Dict, namespace: str) -> None:
        """include use case使用のチェック (8.2.2.25)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.25] Include use case usage には名前を指定することが推奨されます",
                node
            ))
    def _check_view_def(self, node: Dict, namespace: str) -> None:
        """view定義のチェック (8.2.2.26.1)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.26.1] View definition には名前が必要です",
                node
            ))
    def _check_view_usage(self, node: Dict, namespace: str) -> None:
        """view使用のチェック (8.2.2.26.2)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.26.2] View usage には名前を指定することが推奨されます",
                node
            ))
    def _check_viewpoint_def(self, node: Dict, namespace: str) -> None:
        """viewpoint定義のチェック (8.2.2.26.3)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.26.3] Viewpoint definition には名前が必要です",
                node
            ))
    def _check_viewpoint_usage(self, node: Dict, namespace: str) -> None:
        """viewpoint使用のチェック (8.2.2.26.3)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.26.3] Viewpoint usage には名前を指定することが推奨されます",
                node
            ))
    def _check_rendering_def(self, node: Dict, namespace: str) -> None:
        """rendering定義のチェック (8.2.2.26.4)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.26.4] Rendering definition には名前が必要です",
                node
            ))
    def _check_rendering_usage(self, node: Dict, namespace: str) -> None:
        """rendering使用のチェック (8.2.2.26.4)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.26.4] Rendering usage には名前を指定することが推奨されます",
                node
            ))
    def _check_metadata_def(self, node: Dict, namespace: str) -> None:
        """metadata定義のチェック (8.2.2.27)"""
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.27] Metadata definition には名前が必要です",
                node
            ))
    def _check_metadata_usage(self, node: Dict, namespace: str) -> None:
        """metadata使用のチェック (8.2.2.27)"""
        name = node.get("name")
        usage_decl = node.get("usage_declaration", {})
        type_spec = usage_decl.get("type_spec")
        if not name and not type_spec:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.27] Metadata usage には名前または型を指定することが推奨されます",
                node
            ))
    def _check_use_case_relationships(self, use_case: Dict) -> None:
        """Use Case の関係性チェック"""
        children = use_case.get("children", [])
        
        for child in children:
            if isinstance(child, dict):
                child_type = child.get("type")
                if child_type == "include_use_case":
                    included_case = child.get("includedCase")
                    if not included_case:
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            "[8.2.2.22] Include use case は includedCase を指定する必要があります",
                            child
                        ))
                elif child_type == "extend_use_case":
                    extended_case = child.get("extendedCase")
                    if not extended_case:
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            "[8.2.2.22] Extend use case は extendedCase を指定する必要があります",
                            child
                        ))
