"""definition_usage_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

from typing import Dict

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue


class DefinitionUsageRulesMixin:
    @staticmethod
    def _conjugated_lookup_name(type_name: str) -> str:
        """`~PortType`（共役ポート参照、KerMLのPortConjugation）の型存在チェックでは
        `~`を除いた元の型名で symbols を検索する必要があるため、ここで正規化する。
        エラーメッセージ自体は元の`type_name`（`~`付き）をそのまま表示する。"""
        return type_name[1:] if type_name.startswith("~") else type_name

    def _check_part_def(self, node: Dict, namespace: str) -> None:
        """
        パート定義のチェック
        
        継承と子パートの型参照を検証します。
        
        Args:
            node: part_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")

        # 継承チェック
        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._find_type_in_symbols(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Part '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
    def _check_item_def(self, node: Dict, namespace: str) -> None:
        """
        アイテム定義のチェック

        継承の型参照を検証します（part_defと同型のためロジックも準拠）。

        Args:
            node: item_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")

        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._find_type_in_symbols(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Item '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
    def _check_attribute_definition(self, node: Dict, namespace: str) -> None:
        """
        属性定義のチェック (8.2.2.6)

        継承の型参照を検証します（part_def/item_defと同型のためロジックも準拠）。

        メソッド名を`_check_attribute_def`ではなく`_check_attribute_definition`に
        しているのは、既存の`_check_attribute_def`（attribute_usageの型参照を
        チェックする、命名は紛らわしいが既存の関数）と名前が衝突し、Pythonの
        クラス属性は後勝ちで上書きされるため、どちらかがサイレントに消える
        事故を避けるため。

        Args:
            node: attribute_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")

        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._find_type_in_symbols(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Attribute definition '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
    def _check_part_instance(self, node: Dict, namespace: str) -> None:
        """
        パートインスタンスのチェック

        型参照の存在を検証します。

        Args:
            node: part_instanceノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name")
        if type_name and not self._find_type_in_symbols(type_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Part instance '{node.get('name')}' が存在しない型 '{type_name}' を参照しています",
                node
            ))
    def _check_action_def(self, node: Dict, namespace: str) -> None:
        """
        アクション定義のチェック
        
        パラメータの型参照とパラメータの存在を検証します。
        
        Args:
            node: action_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        params = node.get("params", [])
        
        # パラメータの型チェック
        for param in params:
            type_spec = param.get("type_spec")
            if type_spec:
                type_name = type_spec.get("name")
                if type_name and not self._find_type_in_symbols(self._conjugated_lookup_name(type_name)):
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"Action '{name}' のパラメータ '{param.get('name')}' が存在しない型 '{type_name}' を参照しています",
                        param
                    ))
        
        # in/out/inoutの存在チェック
        if not params:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"Action '{name}' にパラメータがありません",
                node
            ))
    def _check_activity_def(self, node: Dict, namespace: str) -> None:
        """
        アクティビティ定義のチェック
        
        パラメータの型参照を検証します。
        
        Args:
            node: activity_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        params = node.get("params", [])
        
        # パラメータの型チェック
        for param in params:
            type_spec = param.get("type_spec")
            if type_spec:
                type_name = type_spec.get("name")
                if type_name and not self._find_type_in_symbols(self._conjugated_lookup_name(type_name)):
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"Activity '{name}' のパラメータ '{param.get('name')}' が存在しない型 '{type_name}' を参照しています",
                        param
                    ))
    def _check_type_def(self, node: Dict, namespace: str) -> None:
        """
        型定義のチェック
        
        属性の型参照を検証します。
        
        Args:
            node: type_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        attributes = node.get("attributes", [])
        
        # 属性の型チェック
        for attr in attributes:
            type_name = attr.get("type_name")
            if type_name and not self._find_type_in_symbols(type_name):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Type '{name}' の属性 '{attr.get('name')}' が存在しない型 '{type_name}' を参照しています",
                    attr
                ))
    def _check_attribute_def(self, node: Dict, namespace: str) -> None:
        """
        属性定義のチェック
        
        型参照の存在を検証します。
        
        Args:
            node: attribute_defノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name")
        if type_name and not self._find_type_in_symbols(type_name):
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"Attribute '{node.get('name')}' が存在しない型 '{type_name}' を参照しています",
                node
            ))
    def _check_connection_def(self, node: Dict, namespace: str) -> None:
        """
        接続定義のチェック

        各end member（connection_end_member）の型参照を検証します。

        Args:
            node: connection_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")

        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("type") == "connection_end_member":
                type_name = child.get("type_name")
                if type_name and not self._find_type_in_symbols(type_name):
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"Connection '{name}' の end '{child.get('name')}' が存在しない型 '{type_name}' を参照しています",
                        child
                    ))
    def _check_requirement_def(self, node: Dict, namespace: str) -> None:
        """
        要件定義のチェック (8.2.2.19)

        現行ANTLR4パーサーの visitRequirementDef は 'satisfied_by' キーを
        一切生成しないため、requirement_defノード自体に対する充足検証ロジックは
        不要である。要件充足の検証は `assert satisfiedBy ...` 構文由来の
        satisfy_requirement_usage ノード（_check_satisfy_requirement_usage）で
        行われている。
        """
        self._check_requirement_subject(node, namespace)

    def _check_requirement_usage(self, node: Dict, namespace: str) -> None:
        """要件使用のチェック (8.2.2.19)。subject制約のみ（型検証は無し）。"""
        self._check_requirement_subject(node, namespace)

    def _check_requirement_subject(self, node: Dict, namespace: str) -> None:
        """
        subject usage は1つまで、かつ最初の子要素でなければならない (8.2.2.21)

        参照実装（OMG SysML v2 Pilot Implementation）との比較評価
        （2026-08-28、eval/SYSML_LINTER_REFERENCE_COMPARISON_REPORT.md §4.1）で
        発見した偽陰性（RequirementSubject_Invalid.sysml参照）。requirement_def/
        requirement_usageの両方から呼ばれる。

        「最初のパラメータ」は`doc`やredefinition専用の`ref requirement :>>
        self: ...;`（requirement_usage）等の非パラメータ宣言を無視した、
        パラメータ相当の要素（`param`/`subject_usage`）だけの並びの先頭を指す。
        全子要素の先頭で判定すると、公式標準ライブラリのRequirementCheck等
        （`doc`の後に`ref requirement :>> self: ...;`を経てから`subject`が
        続く）を誤検出する（2026-08-28の730件回帰チェックで発見・修正）。
        """
        name = node.get("name", namespace)
        children = node.get("children", [])
        param_like = [
            c for c in children
            if isinstance(c, dict) and c.get("type") in ("param", "subject_usage")
        ]
        subjects = [c for c in param_like if c.get("type") == "subject_usage"]
        for extra in subjects[1:]:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.21] '{name}' にsubjectが複数定義されています(1つのみ許可)",
                extra
            ))
        if len(subjects) == 1 and param_like and param_like[0] is not subjects[0]:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.21] '{name}' のsubjectは最初のパラメータでなければなりません",
                subjects[0]
            ))
    def _check_interface_def(self, node: Dict, namespace: str) -> None:
        """
        インターフェース定義のチェック (8.2.2.14)
        
        Args:
            node: interface_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.14] Interface definition には名前が必要です",
                node
            ))
            return
        
        # 継承チェック
        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._type_reference_exists(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.14] Interface '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
        
        # InterfaceBodyItemのチェック
        for child in node.get("children", []):
            if isinstance(child, dict):
                child_type = child.get("type")
                if child_type == "interface_non_occurrence_usage_member":
                    element = child.get("element")
                    if element and element.get("type") in ["reference_usage", "attribute_usage", "enumeration_usage"]:
                        type_name = element.get("type_name", "")
                        if type_name and not self._find_type_in_symbols(type_name):
                            self.issues.append(LintIssue(
                                SEVERITY_ERROR,
                                f"[8.2.2.14] Interface '{name}' の要素が存在しない型 '{type_name}' を参照しています",
                                child
                            ))
    def _check_interface_usage(self, node: Dict, namespace: str) -> None:
        """
        インターフェース使用のチェック (8.2.2.14)
        
        Args:
            node: interface_usageノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name", "")
        # usage の type_name は「型」参照なので、importで持ち込まれた名前も
        # 解決できる_type_reference_existsを使う（要素用の
        # _find_element_in_symbolsではなく型解決用のこちらを使う）。
        if type_name and not self._type_reference_exists(type_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.14] Interface usage '{node.get('name', 'unknown')}' が存在しないインターフェース '{type_name}' を参照しています",
                node
            ))
        
        # InterfacePartのチェック
        interface_part = node.get("interface_part")
        if interface_part:
            if interface_part.get("type") == "binary_interface_part":
                from_end = interface_part.get("from_end")
                to_end = interface_part.get("to_end")
                if from_end and to_end:
                    # エンドの参照チェック
                    from_ref = from_end.get("reference_subsetting")
                    to_ref = to_end.get("reference_subsetting")
                    if from_ref and not self._find_element_in_symbols(from_ref.get("referenced_feature", "")):
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.14] Interface usage '{node.get('name', 'unknown')}' の from エンドが存在しない要素を参照しています",
                            from_end
                        ))
                    if to_ref and not self._find_element_in_symbols(to_ref.get("referenced_feature", "")):
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.14] Interface usage '{node.get('name', 'unknown')}' の to エンドが存在しない要素を参照しています",
                            to_end
                        ))
    def _check_allocation_def(self, node: Dict, namespace: str) -> None:
        """
        アロケーション定義のチェック (8.2.2.15)
        
        Args:
            node: allocation_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.15] Allocation definition には名前が必要です",
                node
            ))
            return
        
        # 継承チェック
        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._type_reference_exists(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.15] Allocation '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
    def _check_allocation_usage(self, node: Dict, namespace: str) -> None:
        """
        アロケーション使用のチェック (8.2.2.15)
        
        Args:
            node: allocation_usageノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name", "")
        # usage の type_name は「型」参照なので、importで持ち込まれた名前も
        # 解決できる_type_reference_existsを使う（要素用の
        # _find_element_in_symbolsではなく型解決用のこちらを使う）。
        if type_name and not self._type_reference_exists(type_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.15] Allocation usage '{node.get('name', 'unknown')}' が存在しないアロケーション '{type_name}' を参照しています",
                node
            ))
        
        # ConnectorPartのチェック
        connector_part = node.get("connector_part")
        if connector_part:
            # BinaryConnectorPartまたはNaryConnectorPartのチェック
            if connector_part.get("type") == "binary_connector_part":
                from_end = connector_part.get("from_end")
                to_end = connector_part.get("to_end")
                if from_end and to_end:
                    # エンドの参照チェック
                    from_ref = from_end.get("reference_subsetting")
                    to_ref = to_end.get("reference_subsetting")
                    if from_ref and not self._find_element_in_symbols(from_ref.get("referenced_feature", "")):
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.15] Allocation usage '{node.get('name', 'unknown')}' の from エンドが存在しない要素を参照しています",
                            from_end
                        ))
                    if to_ref and not self._find_element_in_symbols(to_ref.get("referenced_feature", "")):
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.15] Allocation usage '{node.get('name', 'unknown')}' の to エンドが存在しない要素を参照しています",
                            to_end
                        ))
    def _check_calculation_def(self, node: Dict, namespace: str) -> None:
        """
        計算定義のチェック (8.2.2.19)
        
        Args:
            node: calculation_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.19] Calculation definition には名前が必要です",
                node
            ))
            return
        
        # 継承チェック
        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._type_reference_exists(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.19] Calculation '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
        
        # ReturnParameterMemberのチェック
        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("type") == "return_parameter_member":
                usage_element = child.get("usage_element")
                if usage_element:
                    type_name = usage_element.get("type_name", "")
                    if type_name and not self._find_type_in_symbols(type_name):
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.19] Calculation '{name}' の return parameter が存在しない型 '{type_name}' を参照しています",
                            child
                        ))
        self._check_return_parameter_count(node, name)

    def _check_return_parameter_count(self, node: Dict, name: str) -> None:
        """
        return parameter は1つまで (8.2.2.19)

        参照実装（OMG SysML v2 Pilot Implementation）との比較評価
        （2026-08-28、eval/SYSML_LINTER_REFERENCE_COMPARISON_REPORT.md §4.1）で
        発見した偽陰性。`return X;`/`return r1: X;`は`calc_parameter`ノード
        （direction="return"）として現れる（`return_parameter_member`という
        別のノード型は現行パーサーが生成しない旧想定のもので、この関数とは
        独立）。calculation_def/calculation_usageの両方から呼ばれる。
        """
        return_params = [
            c for c in node.get("children", [])
            if isinstance(c, dict) and c.get("type") == "calc_parameter" and c.get("direction") == "return"
        ]
        for extra in return_params[1:]:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.19] Calculation '{name}' にreturn parameterが複数定義されています(1つのみ許可)",
                extra
            ))

    def _check_calculation_usage(self, node: Dict, namespace: str) -> None:
        """
        計算使用のチェック (8.2.2.19)

        Args:
            node: calculation_usageノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name", "")
        # usage の type_name は「型」参照なので、importで持ち込まれた名前も
        # 解決できる_type_reference_existsを使う（要素用の
        # _find_element_in_symbolsではなく型解決用のこちらを使う）。
        if type_name and not self._type_reference_exists(type_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.19] Calculation usage '{node.get('name', 'unknown')}' が存在しない計算 '{type_name}' を参照しています",
                node
            ))
        self._check_return_parameter_count(node, node.get("name", "unknown"))
    def _check_constraint_def(self, node: Dict, namespace: str) -> None:
        """
        制約定義のチェック (8.2.2.20)
        
        Args:
            node: constraint_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        if not name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.20] Constraint definition には名前が必要です",
                node
            ))
            return
        
        # 継承チェック
        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._type_reference_exists(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.20] Constraint '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
    def _check_constraint_usage(self, node: Dict, namespace: str) -> None:
        """
        制約使用のチェック (8.2.2.20)
        
        Args:
            node: constraint_usageノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name", "")
        # usage の type_name は「型」参照なので、importで持ち込まれた名前も
        # 解決できる_type_reference_existsを使う（要素用の
        # _find_element_in_symbolsではなく型解決用のこちらを使う）。
        if type_name and not self._type_reference_exists(type_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.20] Constraint usage '{node.get('name', 'unknown')}' が存在しない制約 '{type_name}' を参照しています",
                node
            ))
    def _check_assert_constraint_usage(self, node: Dict, namespace: str) -> None:
        """
        アサート制約使用のチェック (8.2.2.20)
        
        Args:
            node: assert_constraint_usageノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name", "")
        # usage の type_name は「型」参照なので、importで持ち込まれた名前も
        # 解決できる_type_reference_existsを使う（要素用の
        # _find_element_in_symbolsではなく型解決用のこちらを使う）。
        if type_name and not self._type_reference_exists(type_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.20] Assert constraint usage '{node.get('name', 'unknown')}' が存在しない制約 '{type_name}' を参照しています",
                node
            ))
    def _check_satisfy_requirement_usage(self, node: Dict, namespace: str) -> None:
        """
        要件満足使用のチェック (8.2.2.21.2)
        
        Args:
            node: satisfy_requirement_usageノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name", "")
        # usage の type_name は「型」参照なので、importで持ち込まれた名前も
        # 解決できる_type_reference_existsを使う（要素用の
        # _find_element_in_symbolsではなく型解決用のこちらを使う）。
        if type_name and not self._type_reference_exists(type_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.21.2] Satisfy requirement usage '{node.get('name', 'unknown')}' が存在しない要件 '{type_name}' を参照しています",
                node
            ))
        
        # SatisfactionSubjectMemberのチェック
        satisfaction_subject = node.get("satisfaction_subject")
        if satisfaction_subject:
            parameter = satisfaction_subject.get("parameter")
            if parameter:
                feature_chain = parameter.get("feature_chain")
                if feature_chain:
                    qualified_id = feature_chain.get("qualified_id")
                    if qualified_id:
                        target_name = qualified_id.get("name", "")
                        if target_name and not self._find_element_in_symbols(target_name):
                            self.issues.append(LintIssue(
                                SEVERITY_ERROR,
                                f"[8.2.2.21.2] Satisfy requirement usage '{node.get('name', 'unknown')}' の satisfaction subject が存在しない要素 '{target_name}' を参照しています",
                                satisfaction_subject
                            ))
    def _check_port_def(self, node: Dict, namespace: str) -> None:
        """
        ポート定義のチェック
        
        継承の型参照を検証します。
        
        Args:
            node: port_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        
        # 継承チェック
        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._find_type_in_symbols(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Port '{name}' が存在しない型 '{base}' を継承しています",
                    node
                ))
    def _check_port_usage(self, node: Dict, namespace: str) -> None:
        """
        ポート使用のチェック

        型参照の存在を検証します。

        Args:
            node: port_usageノード
            namespace: 現在の名前空間
        """
        type_name = node.get("type_name")
        if type_name and not self._find_type_in_symbols(self._conjugated_lookup_name(type_name)):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Port '{node.get('name')}' が存在しない型 '{type_name}' を参照しています",
                node
            ))
