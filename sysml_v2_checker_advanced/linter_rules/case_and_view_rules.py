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


class CaseAndViewRulesMixin:
    def _check_occurrence_advanced_rules(self) -> None:
        """
        Occurrence 関連の高度ルールチェック (8.2.2.9)

        - OccurrenceDefinitionPrefix の isIndividual チェック
        - IndividualDefinition の EmptyMultiplicityMember 検証
        - EventOccurrenceUsage の構造チェック

        OccurrenceUsage自体の固有チェックは無い（_check_occurrence_usageの
        docstring参照。PortionKind検証は構造的に到達不能なため削除済み）。
        """
        for sym_name, sym_node in self.symbols.items():
            node_type = sym_node.get("type")
            
            if node_type == "occurrence_def":
                self._check_occurrence_definition(sym_node, sym_name)
            elif node_type == "individual_def":
                self._check_individual_definition(sym_node, sym_name)
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
    def _check_individual_definition(self, node: Dict, node_name: str) -> None:
        """IndividualDefinition の EmptyMultiplicityMember 検証"""
        # Individual は常に EmptyMultiplicity を持つ必要がある
        multiplicity = node.get("multiplicity")
        if not multiplicity or multiplicity.get("size") is not None:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.9] Individual definition '{node.get('name', node_name)}' は空の多重度を持つ必要があります",
                node
            ))
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
        """EventOccurrenceUsage の構造チェック"""
        # Event occurrence は特定の構造を持つ必要がある
        reference_subsetting = node.get("ownedReferenceSubsetting")
        if not reference_subsetting:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.9] Event occurrence usage '{node.get('name', node_name)}' は参照サブセッティングを持つことが推奨されます",
                node
            ))
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
