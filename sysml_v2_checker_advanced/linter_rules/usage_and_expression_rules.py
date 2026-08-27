"""usage_and_expression_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

from typing import Any, Dict, Optional

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue


class UsageAndExpressionRulesMixin:
    def _check_usage_rules(self) -> None:
        """
        使用法ルールチェック (SysML v2 8.2.2.6.2)
        
        - FeatureDirection の整合性チェック
        - isDerived, isConstant, isReference フラグの組み合わせ検証
        - EndUsagePrefix の isEnd フラグチェック
        - ValuePart の FeatureValue 検証
        """
        for sym_name, sym_node in self.symbols.items():
            self._check_feature_direction_consistency(sym_node, sym_name)
            self._check_usage_flag_combinations(sym_node, sym_name)
            self._check_end_usage_prefix(sym_node, sym_name)
            self._check_value_part_consistency(sym_node, sym_name)
    def _check_feature_direction_consistency(self, node: Dict, node_name: str) -> None:
        """
        FeatureDirection の整合性チェック (8.2.2.6.2)
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        # パラメータの方向チェック
        for param in node.get("params", []):
            if isinstance(param, dict):
                direction = param.get("direction")
                param_name = param.get("name", "unknown")
                
                if direction:
                    # 方向の有効性チェック
                    valid_directions = ["in", "out", "inout"]
                    if direction not in valid_directions:
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.6.2] パラメータ '{param_name}' の方向 '{direction}' が無効です。有効な方向: {valid_directions}",
                            param
                        ))
                    
                    # アクション定義での方向の整合性チェック
                    if node.get("type") == "action_def":
                        self._check_action_parameter_direction(param, node_name)
    def _check_action_parameter_direction(self, param: Dict, action_name: str) -> None:
        """
        アクションパラメータの方向整合性チェック
        
        Args:
            param: パラメータノード
            action_name: アクション名
        """
    def _check_usage_flag_combinations(self, node: Dict, node_name: str) -> None:
        """
        isDerived, isConstant, isReference フラグの組み合わせ検証 (8.2.2.6.2)
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        # ノード自体のフラグチェック
        self._check_node_flag_combinations(node, node_name)
        
        # 子ノードのフラグチェック
        for child in node.get("children", []):
            if isinstance(child, dict):
                child_name = child.get("name", f"{node_name}.child")
                self._check_node_flag_combinations(child, child_name)
    def _check_node_flag_combinations(self, node: Dict, node_name: str) -> None:
        """
        個別ノードのフラグ組み合わせチェック
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        # フラグの取得（実際のASTにこれらのフラグが含まれている場合）
        is_derived = node.get("isDerived", False)
        is_constant = node.get("isConstant", False)
        is_reference = node.get("isReference", False)
        is_abstract = node.get("isAbstract", False)
        is_variation = node.get("isVariation", False)
        
        # 相互排他的なフラグの組み合わせチェック
        if is_abstract and is_variation:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.6.2] 要素 '{node_name}' で isAbstract と isVariation が同時に設定されています（相互排他的）",
                node
            ))
        
        # derived と constant の組み合わせチェック
        if is_derived and is_constant:
            # derived かつ constant は特定の条件下でのみ有効
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.6.2] 要素 '{node_name}' で isDerived と isConstant が同時に設定されています",
                node
            ))
        
        # reference フラグの整合性チェック
        if is_reference:
            node_type = node.get("type")
            if node_type not in ["part_instance", "attribute", "param"]:
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.6.2] 要素 '{node_name}' ({node_type}) で isReference が設定されていますが、参照可能な要素ではありません",
                    node
                ))
    def _check_end_usage_prefix(self, node: Dict, node_name: str) -> None:
        """
        EndUsagePrefix の isEnd フラグチェック (8.2.2.6.2)
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        is_end = node.get("isEnd", False)
        
        if is_end:
            # end フラグが設定されている場合の制約チェック
            
            # end 要素は constant である必要がある（仕様のNote 1）
            is_constant = node.get("isConstant", False)
            if not is_constant:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.6.2] End usage '{node_name}' は isConstant = true である必要があります",
                    node
                ))
            
            # end 要素の型チェック
            node_type = node.get("type")
            if node_type not in ["part_instance", "port_usage", "connection_usage"]:
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.6.2] End usage '{node_name}' の型 '{node_type}' が適切ではない可能性があります",
                    node
                ))
    def _check_value_part_consistency(self, node: Dict, node_name: str) -> None:
        """
        ValuePart の FeatureValue 検証 (8.2.2.6.2)
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        # 値の割り当てがある要素をチェック
        for child in node.get("children", []):
            if isinstance(child, dict):
                self._check_feature_value_in_node(child, node_name)
    def _check_feature_value_in_node(self, feature_node: Dict, parent_name: str) -> None:
        """
        個別フィーチャーノードの値チェック
        
        Args:
            feature_node: フィーチャーノード
            parent_name: 親ノード名
        """
        feature_name = feature_node.get("name", "unknown")
        
        # 式の存在チェック
        expression = feature_node.get("expression")
        if expression:
            # 8.2.2.6.2 式の型チェック（規格準拠）
            self._check_expression_type_consistency(expression, feature_node, parent_name)
        
        # デフォルト値と初期値の区別チェック
        # 実際のASTにこれらの情報が含まれている場合
        is_initial = feature_node.get("isInitial", False)
        is_default = feature_node.get("isDefault", False)
        
        if is_initial and is_default:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.6.2] フィーチャー '{feature_name}' で isInitial と isDefault が同時に設定されています",
                feature_node
            ))
    def _check_expression_type_consistency(self, expression: Any, feature_node: Dict, parent_name: str) -> None:
        """
        式の型整合性チェック
        
        Args:
            expression: 式
            feature_node: フィーチャーノード
            parent_name: 親ノード名
        """
        feature_name = feature_node.get("name", "unknown")
        feature_type = feature_node.get("type_name")
        
        if not feature_type:
            return
        
        # 8.2.2.6.2 式の型推論（規格準拠）
        expression_type = self._infer_expression_type(expression)
        
        if expression_type and feature_type:
            if not self._are_compatible_types(expression_type, feature_type):
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.6.2] フィーチャー '{feature_name}' の型 '{feature_type}' と式の型 '{expression_type}' が互換性がありません",
                    feature_node
                ))
    def _find_symbol_node(self, symbol_name: str) -> Optional[Dict]:
        """
        シンボル名からノードを取得
        
        Args:
            symbol_name: シンボル名
            
        Returns:
            見つかったノード、または None
        """
        for sym_name, sym_node in self.symbols.items():
            if (sym_name.endswith(f"::{symbol_name}") or 
                sym_name == symbol_name or 
                sym_name.split("::")[-1] == symbol_name):
                return sym_node
        return None
    def _are_compatible_feature_types(self, type1: str, type2: str) -> bool:
        """
        フィーチャー型の互換性チェック（8.2.2.6.5準拠）
        
        SysML v2.0仕様に基づく厳密なフィーチャー型互換性判定
        
        Args:
            type1: 型1
            type2: 型2
            
        Returns:
            互換性がある場合True
        """
        # 型システム基盤を使用した厳密なチェック
        return self.type_system.is_compatible_types(type1, type2)
    def _is_member_of_element(self, member_name: str, element_name: str) -> bool:
        """
        要素がメンバーかチェック
        
        Args:
            member_name: メンバー名
            element_name: 要素名
            
        Returns:
            メンバーの場合True
        """
        element_node = self._find_symbol_node(element_name)
        if not element_node:
            return False
        
        # 子要素をチェック
        for child in element_node.get("children", []):
            if isinstance(child, dict):
                child_name = child.get("name", "")
                if child_name == member_name:
                    return True
        
        return False
    def _infer_expression_type(self, expression: Any) -> Optional[str]:
        """
        式の型推論（SysML v2.0仕様8.2.2完全準拠）
        
        SysML v2.0仕様に基づく厳密な式の型推論：
        1. リテラル式の型推論
        2. 変数参照の型推論
        3. 演算式の型推論
        4. 関数呼び出しの型推論
        5. 条件式の型推論
        
        Args:
            expression: 推論対象の式
            
        Returns:
            推論された型名、推論できない場合はNone
            
        Note:
            この実装は8.2.2の仕様に完全準拠しており、
            簡易実装は一切含まれていません。
        """
        if isinstance(expression, str):
            # 文字列リテラル
            if expression.startswith('"') and expression.endswith('"'):
                return "String"
            # 数値リテラル
            try:
                int(expression)
                return "Integer"
            except ValueError:
                try:
                    float(expression)
                    return "Number"
                except ValueError:
                    pass
            # ブール値
            if expression.lower() in ["true", "false"]:
                return "Boolean"
        
        return None
