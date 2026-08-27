"""multiplicity_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

from typing import Dict

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue


class MultiplicityRulesMixin:
    def _check_multiplicity(self, multiplicity: Dict, context: str = "") -> None:
        """
        多重度の形式検証 (8.2.2.6.6 SysML v2.0 完全準拠)
        
        SysML v2.0 仕様:
        MultiplicityRange = '[' ( ownedRelationship += MultiplicityExpressionMember '..' )? 
                                ownedRelationship += MultiplicityExpressionMember ']'
        
        Args:
            multiplicity: multiplicityノード
            context: コンテキスト（要素名など）
        """
        if not multiplicity:
            return
        
        multiplicity_type = multiplicity.get("type")
        
        # 新しい8.2.2.6.6準拠の構造をチェック
        if multiplicity_type == "multiplicity":
            range_obj = multiplicity.get("range")
            if range_obj:
                self._check_multiplicity_range(range_obj, context)
        
        # 後方互換性のため、古い構造もサポート
        elif multiplicity_type == "multiplicity_range":
            self._check_multiplicity_range(multiplicity, context)
        
        # さらに古い構造のサポート
        else:
            size = multiplicity.get("size")
            if size is not None:
                self._check_legacy_multiplicity_size(size, context, multiplicity)
    def _check_multiplicity_part(self, node: Dict, context: str = "") -> None:
        """
        multiplicity_partのチェック (8.2.2.6.6)
        
        SysML v2.0 仕様:
        MultiplicityPart : Feature = 
          ownedRelationship += OwnedMultiplicity
          | ( ownedRelationship += OwnedMultiplicity )?
            ( isOrdered ?= 'ordered' ( { isUnique = false } 'nonunique' )?
            | { isUnique = false } 'nonunique' ( isOrdered ?= 'ordered' )? )
        
        Args:
            node: multiplicity_partノード
            context: コンテキスト
        """
        if not node or node.get("type") != "multiplicity_part":
            return
        
        owned_multiplicity = node.get("owned_multiplicity")
        if owned_multiplicity:
            self._check_owned_multiplicity(owned_multiplicity, context)
        
        is_ordered = node.get("is_ordered", False)
        is_unique = node.get("is_unique", True)
        
        # ordered/nonuniqueフラグの組み合わせチェック
        if is_ordered and not is_unique:
            # ordered nonunique は有効
            pass
        elif not is_ordered and not is_unique:
            # nonunique のみも有効
            pass
        elif is_ordered and is_unique:
            # ordered unique も有効（デフォルト）
            pass
    def _check_owned_multiplicity(self, node: Dict, context: str = "") -> None:
        """
        owned_multiplicityのチェック (8.2.2.6.6)
        
        SysML v2.0 仕様:
        OwnedMultiplicity : OwningMembership = ownedRelatedElement += MultiplicityRange
        
        Args:
            node: owned_multiplicityノード
            context: コンテキスト
        """
        if not node or node.get("type") != "owned_multiplicity":
            return
        
        multiplicity_range = node.get("multiplicity_range")
        if multiplicity_range:
            self._check_multiplicity_range(multiplicity_range, context)
    def _check_multiplicity_range(self, node: Dict, context: str = "") -> None:
        """
        multiplicity_rangeのチェック (8.2.2.6.6)
        
        SysML v2.0 仕様:
        MultiplicityRange = '[' ( ownedRelationship += MultiplicityExpressionMember '..' )? 
                                ownedRelationship += MultiplicityExpressionMember ']'
        
        Args:
            node: multiplicity_rangeノード
            context: コンテキスト
        """
        if not node or node.get("type") != "multiplicity_range":
            return
        
        lower = node.get("lower")
        upper = node.get("upper")
        
        if not lower and not upper:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.6.6] Multiplicity range には少なくとも1つの境界が必要です {context}",
                node
            ))
            return
        
        # 下限のチェック
        if lower:
            self._check_multiplicity_expression_member(lower, "lower bound", context)
        
        # 上限のチェック
        if upper:
            self._check_multiplicity_expression_member(upper, "upper bound", context)
        
        # 範囲の妥当性チェック（両方が数値の場合）
        if lower and upper and lower != upper:
            lower_val = self._extract_multiplicity_value(lower)
            upper_val = self._extract_multiplicity_value(upper)
            
            if (isinstance(lower_val, int) and isinstance(upper_val, int) and 
                lower_val > upper_val):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.6.6] Multiplicity range が無効です: 下限 {lower_val} が上限 {upper_val} を超えています {context}",
                    node
                ))
            
            # [*..n] のような無効な形式
            if lower_val == "*" and isinstance(upper_val, int):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.6.6] Multiplicity range が無効です: 下限に * は使用できません {context}",
                    node
                ))
    def _check_multiplicity_expression_member(self, node: Dict, bound_type: str, context: str = "") -> None:
        """
        multiplicity_expression_memberのチェック (8.2.2.6.6)
        
        SysML v2.0 仕様:
        MultiplicityExpressionMember : OwningMembership = 
          ownedRelatedElement += ( LiteralExpression | FeatureReferenceExpression )
        
        Args:
            node: multiplicity_expression_memberノード
            bound_type: "lower bound" または "upper bound"
            context: コンテキスト
        """
        if not node:
            return
        
        if node.get("type") == "multiplicity_expression_member":
            expression = node.get("expression")
            if expression:
                self._check_multiplicity_expression(expression, bound_type, context)
        elif node.get("type") == "multiplicity_bound":
            # 後方互換性
            self._check_multiplicity_bound(node, bound_type, context)
    def _check_multiplicity_expression(self, expression: Dict, bound_type: str, context: str = "") -> None:
        """
        multiplicity内の式のチェック (8.2.2.6.6)
        
        Args:
            expression: LiteralExpression または FeatureReferenceExpression
            bound_type: "lower bound" または "upper bound"
            context: コンテキスト
        """
        if not expression:
            return
        
        expr_type = expression.get("type")
        
        if expr_type == "literal_expression":
            literal_type = expression.get("literal_type")
            value = expression.get("value")
            
            if literal_type == "integer":
                if isinstance(value, int) and value < 0:
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"[8.2.2.6.6] Multiplicity {bound_type} は負の値にできません: {value} {context}",
                        expression
                    ))
            elif literal_type == "unbounded":
                if bound_type == "lower bound":
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"[8.2.2.6.6] Multiplicity {bound_type} に * は使用できません {context}",
                        expression
                    ))
        
        elif expr_type == "feature_reference_expression":
            reference = expression.get("reference")
            if reference and not self._find_element_in_symbols(reference):
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.6.6] Multiplicity {bound_type} で参照されている要素 '{reference}' が見つかりません {context}",
                    expression
                ))
    def _check_multiplicity_bound(self, node: Dict, bound_type: str, context: str = "") -> None:
        """
        multiplicity_boundのチェック（後方互換性）
        
        Args:
            node: multiplicity_boundノード
            bound_type: "lower bound" または "upper bound"
            context: コンテキスト
        """
        if not node:
            return
        
        bound_type_val = node.get("bound_type")
        value = node.get("value")
        
        if bound_type_val == "literal" and isinstance(value, int) and value < 0:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.6.6] Multiplicity {bound_type} は負の値にできません: {value} {context}",
                node
            ))
        elif bound_type_val == "unbounded" and bound_type == "lower bound":
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.6.6] Multiplicity {bound_type} に * は使用できません {context}",
                node
            ))
        elif bound_type_val == "reference" and isinstance(value, str):
            if not self._find_element_in_symbols(value):
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.6.6] Multiplicity {bound_type} で参照されている要素 '{value}' が見つかりません {context}",
                    node
                ))
    def _extract_multiplicity_value(self, node: Dict):
        """
        multiplicityノードから値を抽出
        
        Args:
            node: multiplicity関連ノード
            
        Returns:
            抽出された値（int, "*", または文字列）
        """
        if not node:
            return None
        
        if node.get("type") == "multiplicity_expression_member":
            expression = node.get("expression")
            if expression:
                if expression.get("type") == "literal_expression":
                    return expression.get("value")
                elif expression.get("type") == "feature_reference_expression":
                    return expression.get("reference")
        elif node.get("type") == "multiplicity_bound":
            return node.get("value")
        
        return None
    def _check_legacy_multiplicity_size(self, size, context: str, multiplicity: Dict) -> None:
        """
        古い形式のmultiplicity sizeのチェック（後方互換性）
        
        Args:
            size: サイズ値
            context: コンテキスト
            multiplicity: multiplicityノード
        """
        # sizeが辞書の場合（範囲形式: {min: n, max: m} または {min: n, max: "*"}）
        if isinstance(size, dict):
            min_val = size.get("min")
            max_val = size.get("max")
            
            if min_val is not None and max_val is not None:
                # [n..m] の形式
                if isinstance(min_val, (int, str)) and isinstance(max_val, (int, str)):
                    # 数値の場合
                    if isinstance(min_val, int) and isinstance(max_val, int):
                        if min_val > max_val:
                            self.issues.append(LintIssue(
                                SEVERITY_ERROR,
                                f"多重度の範囲が無効です: [{min_val}..{max_val}] (最小値が最大値を超えています) {context}",
                                multiplicity
                            ))
                    # [*..n] のような無効な形式
                    elif str(min_val) == "*" and isinstance(max_val, int):
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"多重度の形式が無効です: [*..{max_val}] (最小値に*は使用できません) {context}",
                            multiplicity
                        ))
        
        # 単一値の場合
        elif isinstance(size, int) and size < 0:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"多重度は負の値にできません: [{size}] {context}",
                multiplicity
            ))
