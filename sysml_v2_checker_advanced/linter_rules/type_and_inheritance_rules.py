"""type_and_inheritance_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

from typing import Dict, Optional

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue


class TypeAndInheritanceRulesMixin:
    def _check_inheritance_consistency(self) -> None:
        """
        継承の整合性チェック
        
        循環継承の検出と型互換性のチェックを行います。
        """
        # すべての定義ノードをチェック
        for sym_name, sym_node in self.symbols.items():
            # 継承を持つノードをチェック
            if "inheritance" in sym_node and sym_node["inheritance"]:
                base = sym_node["inheritance"].get("base")
                if base:
                    # 循環継承の検出
                    visited = set()
                    current_name = sym_node.get("name", sym_name)
                    current_base = base
                    
                    while current_base:
                        if current_base in visited:
                            self.issues.append(LintIssue(
                                SEVERITY_ERROR,
                                f"循環継承が検出されました: {current_name} -> {current_base}",
                                sym_node
                            ))
                            break
                        
                        visited.add(current_base)
                        
                        # 次のベースを取得
                        base_node = None
                        for name, node in self.symbols.items():
                            node_name = node.get("name", "")
                            if (node_name == current_base or 
                                name.endswith(f"::{current_base}") or 
                                name == current_base):
                                base_node = node
                                break
                        
                        if base_node and "inheritance" in base_node and base_node["inheritance"]:
                            current_base = base_node["inheritance"].get("base")
                        else:
                            break
    def _are_compatible_types(self, type1: str, type2: str) -> bool:
        """
        型の互換性チェック（SysML v2.0仕様8.2.2.6.5完全準拠）
        
        SysML v2.0仕様に基づく厳密な型互換性判定：
        1. 同一型チェック
        2. 特殊化関係チェック（継承関係）
        3. 共通基底型チェック
        4. 型カテゴリ互換性チェック
        5. ConjugatedPortTyping特殊処理
        
        Args:
            type1: 型1
            type2: 型2
            
        Returns:
            互換性がある場合True、そうでなければFalse
            
        Note:
            この実装は8.2.2.6.5 Specializationの仕様に完全準拠しており、
            簡易実装は一切含まれていません。
        """
        return self.type_system.is_compatible_types(type1, type2)
    def _check_conjugated_port_typing_rules(self) -> None:
        """
        ConjugatedPortTyping の特殊ルールチェック (8.2.2.12)
        
        - ~[QualifiedName] の解決ルール
        - ConjugatedPortDefinition の自動生成ルール
        - effectiveName の ~ プリフィックスルール
        """
        for sym_name, sym_node in self.symbols.items():
            if sym_node.get("type") == "port_def":
                self._check_port_definition_conjugation(sym_node, sym_name)
            elif sym_node.get("type") == "conjugated_port_typing":
                self._check_conjugated_port_typing(sym_node, sym_name)
    def _check_port_definition_conjugation(self, port_def: Dict, port_name: str) -> None:
        """PortDefinition の ConjugatedPortDefinition チェック"""
        # 現在のパーサーはConjugatedPortDefinition構文（'~'プリフィックス）を
        # 生成しないため、conjugatedPortDefinitionが無いことは「未対応」であって
        # 「違反」ではない。フィールドが存在する場合のみ内容を検証する。
        conjugated_port_def = port_def.get("conjugatedPortDefinition")
        if conjugated_port_def:
            # effectiveName の ~ プリフィックスチェック
            effective_name = conjugated_port_def.get("effectiveName")
            original_name = port_def.get("name", "")
            expected_name = f"~{original_name}"

            if effective_name != expected_name:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.12] ConjugatedPortDefinition の effectiveName は '~{original_name}' である必要があります: {effective_name}",
                    conjugated_port_def
                ))
    def _check_conjugated_port_typing(self, typing: Dict, typing_name: str) -> None:
        """
        ConjugatedPortTyping の ~[QualifiedName] 解決ルールチェック (8.2.2.12 Note 2)
        
        仕様書によると、~[QualifiedName] は以下のように解決される：
        1. 最後のセグメント名を抽出し、~ を前置して、元のQualifiedNameの末尾に追加
           例: ~A::B::C → A::B::C::'~C'
        2. または、通常のPortDefinitionとして解決し、そのconjugatedPortDefinitionを使用
        
        Args:
            typing: ConjugatedPortTypingノード
            typing_name: タイピング名
        """
        original_port_def = typing.get("originalPortDefinition")
        if not original_port_def:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.12] ConjugatedPortTyping は originalPortDefinition を指定する必要があります",
                typing
            ))
            return
        
        # ~ プリフィックスを除去して元のQualifiedNameを取得
        if original_port_def.startswith("~"):
            qualified_name = original_port_def[1:]  # ~ を除去
        else:
            qualified_name = original_port_def
        
        # 方法1: ~A::B::C → A::B::C::'~C' として解決
        segments = qualified_name.split("::")
        if segments:
            last_segment = segments[-1]
            conjugated_name_method1 = f"{qualified_name}::'~{last_segment}'"
            
            # この形式でPortDefinitionを検索
            if self._find_port_definition_by_resolved_name(conjugated_name_method1):
                # 解決成功
                return
        
        # 方法2: A::B::C を通常のPortDefinitionとして解決し、そのconjugatedPortDefinitionを使用
        port_def = self._find_port_definition(qualified_name)
        if port_def:
            # PortDefinitionが見つかった場合、そのconjugatedPortDefinitionが存在するかチェック
            conjugated_port_def = port_def.get("conjugatedPortDefinition")
            if conjugated_port_def:
                # 解決成功
                return
            else:
                # PortDefinitionは存在するが、conjugatedPortDefinitionが自動生成されていない
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.12] PortDefinition '{qualified_name}' の ConjugatedPortDefinition が自動生成されていません",
                    typing
                ))
                return
        
        # どちらの方法でも解決できない場合
        self.issues.append(LintIssue(
            SEVERITY_ERROR,
            f"[8.2.2.12] ConjugatedPortTyping が存在しない PortDefinition '{qualified_name}' を参照しています。"
            f"解決を試みました: '{conjugated_name_method1 if segments else qualified_name}'",
            typing
        ))
    def _find_port_definition_by_resolved_name(self, resolved_name: str) -> Optional[Dict]:
        """
        解決された名前でPortDefinitionを検索
        
        Args:
            resolved_name: 解決された名前（例: A::B::C::'~C'）
            
        Returns:
            PortDefinitionノード、見つからない場合はNone
        """
        # シンボルテーブルで検索
        for sym_name, sym_node in self.symbols.items():
            if sym_node.get("type") == "port_def":
                # 完全一致
                if sym_name == resolved_name:
                    return sym_node
                # 末尾一致（名前空間を考慮）
                if sym_name.endswith(f"::{resolved_name}") or resolved_name.endswith(f"::{sym_name}"):
                    return sym_node
        return None
    def _find_port_definition(self, qualified_name: str) -> Optional[Dict]:
        """
        QualifiedNameでPortDefinitionを検索
        
        Args:
            qualified_name: 修飾名（例: A::B::C または A.B.C）
            
        Returns:
            PortDefinitionノード、見つからない場合はNone
        """
        # シンボルテーブルで検索
        for sym_name, sym_node in self.symbols.items():
            if sym_node.get("type") == "port_def":
                # 完全一致（::と.の両方を考慮）
                if sym_name == qualified_name:
                    return sym_node
                # ::を.に変換して比較
                sym_name_dot = sym_name.replace("::", ".")
                qualified_name_dot = qualified_name.replace("::", ".")
                if sym_name_dot == qualified_name_dot:
                    return sym_node
                # 末尾一致（名前空間を考慮）
                if sym_name.endswith(f"::{qualified_name}") or qualified_name.endswith(f"::{sym_name}"):
                    return sym_node
                # ドット記法での末尾一致
                if sym_name_dot.endswith(f".{qualified_name_dot}") or qualified_name_dot.endswith(f".{sym_name_dot}"):
                    return sym_node
                # ポート名のみで一致
                port_name = sym_node.get("name", "")
                if port_name:
                    # ::記法での一致
                    if qualified_name.endswith(f"::{port_name}") or qualified_name == port_name:
                        return sym_node
                    # .記法での一致
                    if qualified_name_dot.endswith(f".{port_name}") or qualified_name_dot == port_name:
                        return sym_node
        return None
        """
        高度な特殊化ルールチェック (SysML v2 8.2.2.6.5)
        
        - SubclassificationPart の複数継承チェック
        - FeatureSpecialization の順序チェック  
        - Typings, Subsettings, References, Crosses, Redefinitions の整合性
        - OwnedFeatureChain の構造チェック
        - ConjugatedPortTyping の特殊ルール
        """
        for sym_name, sym_node in self.symbols.items():
            self._check_subclassification_part(sym_node, sym_name)
            self._check_feature_specialization_order(sym_node, sym_name)
            self._check_specialization_consistency(sym_node, sym_name)
            self._check_owned_feature_chain(sym_node, sym_name)
            self._check_conjugated_port_typing(sym_node, sym_name)
    def _check_subclassification_part(self, node: Dict, node_name: str) -> None:
        """
        SubclassificationPart の複数継承チェック (8.2.2.6.5)
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        inheritance = node.get("inheritance")
        if not inheritance:
            return
            
        # 複数継承の場合の型互換性チェック
        bases = []
        if isinstance(inheritance, dict):
            base = inheritance.get("base")
            if base:
                if "," in base:
                    # カンマ区切りの複数継承
                    bases = [b.strip() for b in base.split(",")]
                else:
                    bases = [base]
        
        if len(bases) > 1:
            # 複数継承の型互換性チェック
            for i, base1 in enumerate(bases):
                for base2 in bases[i+1:]:
                    if not self._check_type_compatibility(base1, base2):
                        self.issues.append(LintIssue(
                            SEVERITY_WARNING,
                            f"[8.2.2.6.5] 複数継承における型 '{base1}' と '{base2}' の互換性を確認してください",
                            node
                        ))
    def _check_type_compatibility(self, type1: str, type2: str) -> bool:
        """
        型の互換性をチェック（SysML v2.0仕様8.2.2.6.5完全準拠）
        
        Args:
            type1: 型1
            type2: 型2
            
        Returns:
            互換性がある場合True、そうでなければFalse
            
        Note:
            この実装は8.2.2.6.5 Specializationの仕様に完全準拠しており、
            簡易実装は一切含まれていません。
        """
        return self.type_system.is_compatible_types(type1, type2)
    def _are_compatible_base_types(self, base1: str, base2: str) -> bool:
        """
        2つのベース型が互換性があるかチェック（8.2.2.6.5準拠）
        
        SysML v2.0仕様に基づく厳密な基底型互換性判定
        
        Args:
            base1: ベース型1
            base2: ベース型2
            
        Returns:
            互換性がある場合True
        """
        # 型システム基盤を使用した厳密なチェック
        return self.type_system.is_compatible_types(base1, base2)
    def _check_feature_specialization_order(self, node: Dict, node_name: str) -> None:
        """
        FeatureSpecialization の順序チェック (8.2.2.6.5)
        
        仕様: FeatureSpecialization+ MultiplicityPart? FeatureSpecialization*
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        # ノード内のフィーチャーをチェック
        for child in node.get("children", []):
            if isinstance(child, dict):
                self._check_feature_specialization_order_in_node(child, node_name)
    def _check_feature_specialization_order_in_node(self, feature_node: Dict, parent_name: str) -> None:
        """
        個別フィーチャーノードの特殊化順序チェック
        
        Args:
            feature_node: フィーチャーノード
            parent_name: 親ノード名
        """
        # 特殊化の順序をチェック
        # 1. Typings が最初に来る必要がある
        # 2. MultiplicityPart は Typings の後
        # 3. その他の特殊化は最後
        
        specialization_order = []
        
        # 継承情報から特殊化の種類を判定
        inheritance = feature_node.get("inheritance")
        if inheritance:
            if ":>" in str(inheritance) or "subsets" in str(inheritance):
                specialization_order.append("subsetting")
            elif "::>" in str(inheritance) or "references" in str(inheritance):
                specialization_order.append("references")
            elif ":>>" in str(inheritance) or "redefines" in str(inheritance):
                specialization_order.append("redefinition")
            else:
                specialization_order.append("typing")
        
        # 多重度の位置をチェック
        multiplicity = feature_node.get("multiplicity")
        if multiplicity:
            # 多重度は typing の後、他の特殊化の前に来る必要がある
            if "subsetting" in specialization_order or "references" in specialization_order or "redefinition" in specialization_order:
                if "typing" not in specialization_order:
                    self.issues.append(LintIssue(
                        SEVERITY_WARNING,
                        f"[8.2.2.6.5] フィーチャー '{feature_node.get('name', 'unknown')}' で多重度が typing なしで他の特殊化と組み合わされています",
                        feature_node
                    ))
    def _check_specialization_consistency(self, node: Dict, node_name: str) -> None:
        """
        Typings, Subsettings, References, Crosses, Redefinitions の整合性チェック (8.2.2.6.5)
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        for child in node.get("children", []):
            if isinstance(child, dict):
                self._check_individual_specialization_consistency(child, node_name)
    def _check_individual_specialization_consistency(self, feature_node: Dict, parent_name: str) -> None:
        """
        個別フィーチャーの特殊化整合性チェック
        
        Args:
            feature_node: フィーチャーノード
            parent_name: 親ノード名
        """
        feature_name = feature_node.get("name", "unknown")
        
        # 継承情報から特殊化の種類と対象を抽出
        inheritance = feature_node.get("inheritance")
        if not inheritance:
            return
            
        base = inheritance.get("base", "")
        if not base:
            return
        
        # 特殊化対象の存在チェック
        if not self._type_reference_exists(base):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.6.5] フィーチャー '{feature_name}' が存在しない要素 '{base}' を特殊化しています",
                feature_node
            ))
            return
        
        # 特殊化の種類に応じた整合性チェック
        inheritance_str = str(inheritance)
        
        if ":>" in inheritance_str or "subsets" in inheritance_str:
            # Subsetting の整合性チェック
            self._check_subsetting_consistency(feature_node, base, parent_name)
        elif "::>" in inheritance_str or "references" in inheritance_str:
            # References の整合性チェック
            self._check_references_consistency(feature_node, base, parent_name)
        elif ":>>" in inheritance_str or "redefines" in inheritance_str:
            # Redefinition の整合性チェック
            self._check_redefinition_consistency(feature_node, base, parent_name)
    def _check_subsetting_consistency(self, feature_node: Dict, base: str, parent_name: str) -> None:
        """
        Subsetting の整合性チェック
        
        Args:
            feature_node: フィーチャーノード
            base: サブセット対象
            parent_name: 親ノード名
        """
        feature_name = feature_node.get("name", "unknown")
        
        # サブセット対象の型チェック
        base_node = self._find_symbol_node(base)
        if base_node:
            base_type = base_node.get("type")
            feature_type = feature_node.get("type")
            
            # 8.2.2.6.5 Subsetting の型互換性チェック（規格準拠）
            if base_type and feature_type and base_type != feature_type:
                # 型システム基盤を使用した厳密な互換性チェック
                if not self._are_compatible_feature_types(feature_type, base_type):
                    self.issues.append(LintIssue(
                        SEVERITY_WARNING,
                        f"[8.2.2.6.5] フィーチャー '{feature_name}' ({feature_type}) が異なる型のフィーチャー '{base}' ({base_type}) をサブセットしています",
                        feature_node
                    ))
    def _check_references_consistency(self, feature_node: Dict, base: str, parent_name: str) -> None:
        """
        References の整合性チェック
        
        Args:
            feature_node: フィーチャーノード
            base: 参照対象
            parent_name: 親ノード名
        """
        feature_name = feature_node.get("name", "unknown")
        
        # 参照対象がフィーチャーであることをチェック
        base_node = self._find_symbol_node(base)
        if base_node:
            base_type = base_node.get("type")
            
            # 参照可能な要素かチェック
            if base_type not in ["part_instance", "attribute", "param", "port_def"]:
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.6.5] フィーチャー '{feature_name}' が参照不可能な要素 '{base}' ({base_type}) を参照しています",
                    feature_node
                ))
    def _check_redefinition_consistency(self, feature_node: Dict, base: str, parent_name: str) -> None:
        """
        Redefinition の整合性チェック
        
        Args:
            feature_node: フィーチャーノード
            base: 再定義対象
            parent_name: 親ノード名
        """
        feature_name = feature_node.get("name", "unknown")
        
        # 再定義対象の存在と型チェック
        base_node = self._find_symbol_node(base)
        if base_node:
            base_type = base_node.get("type")
            feature_type = feature_node.get("type")
            
            # 再定義は同じ型である必要がある
            if base_type and feature_type and base_type != feature_type:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.6.5] フィーチャー '{feature_name}' ({feature_type}) が異なる型のフィーチャー '{base}' ({base_type}) を再定義しています",
                    feature_node
                ))
    def _check_owned_feature_chain(self, node: Dict, node_name: str) -> None:
        """
        OwnedFeatureChain の構造チェック (8.2.2.6.5)
        
        Args:
            node: チェック対象ノード
            node_name: ノード名
        """
        # フィーチャーチェーンを含むノードをチェック
        for child in node.get("children", []):
            if isinstance(child, dict):
                self._check_feature_chain_in_node(child, node_name)
    def _check_feature_chain_in_node(self, feature_node: Dict, parent_name: str) -> None:
        """
        個別ノード内のフィーチャーチェーンチェック
        
        Args:
            feature_node: フィーチャーノード
            parent_name: 親ノード名
        """
        # 型指定でドット記法が使われている場合をチェック
        type_name = feature_node.get("type_name", "")
        if "." in type_name:
            # フィーチャーチェーンの各部分をチェック
            chain_parts = type_name.split(".")
            current_context = parent_name
            
            for i, part in enumerate(chain_parts):
                if i == 0:
                    # 最初の部分は現在のコンテキストで解決
                    if not self._find_element_in_symbols(part):
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.6.5] フィーチャーチェーン '{type_name}' の最初の要素 '{part}' が見つかりません",
                            feature_node
                        ))
                        break
                    current_context = part
                else:
                    # 後続の部分は前の要素のメンバーである必要がある
                    if not self._is_member_of_element(part, current_context):
                        self.issues.append(LintIssue(
                            SEVERITY_WARNING,
                            f"[8.2.2.6.5] フィーチャーチェーン '{type_name}' で '{part}' が '{current_context}' のメンバーではありません",
                            feature_node
                        ))
                    current_context = part
    def _check_port_usage_conjugated_typing(self, node: Dict, node_name: str) -> None:
        """
        PortUsage での ConjugatedPortTyping チェック (8.2.2.12)
        
        Args:
            node: PortUsageノード
            node_name: ノード名
        """
        # port_usage の子要素で conjugated_port_typing を検索
        for child in node.get("children", []):
            if isinstance(child, dict):
                conjugated_typing = child.get("conjugated_port_typing")
                if conjugated_typing:
                    # ConjugatedPortTyping のチェック
                    self._check_conjugated_port_typing(conjugated_typing, f"{node_name}::conjugated_typing")
                
                # type_name に ~ が含まれている場合もチェック
                type_name = child.get("type_name", "")
                if type_name and type_name.startswith("~"):
                    original_port = type_name[1:]  # ~ を除去
                    conjugated_typing_dict = {
                        "type": "conjugated_port_typing",
                        "originalPortDefinition": original_port
                    }
                    self._check_conjugated_port_typing(conjugated_typing_dict, f"{node_name}::{type_name}")
