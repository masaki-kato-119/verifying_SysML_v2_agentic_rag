"""connection_and_annotation_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

import re
from typing import Dict, List

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue

# 「関連は2つ以上の要素を結ばなければならない」(8.2.2.12/8.2.2.14)を検査する
# ノード種別。`end` メンバーで端点を宣言する形だけが対象で、`connect a to b;`
# のように端点をインラインで書く形は常に2つ揃うので含めない。
_RELATED_ELEMENTS_NODE_TYPES = (
    "connection_def", "connection_usage",
    "interface_def", "interface_usage",
)



def _count_related_elements(node: Dict) -> int:
    """connection / interface が結んでいる端点の数を数える。

    端点は書き方によってASTの入り方が違うので全部見る（2026-09-05、
    `connection frontLeftPin connect deck to frontLeftWheel;`
    （lawnmowerPackage.sysml:35）をendが0個と数えて誤検出したため追加）:

    - `connection { end ::> a; end ::> b; }` → `connection_end_member` の子。
    - `connection fp connect a to b;` → `firstEnd` / `thenEnd`。
    - `connect a to b;` 系 → `from_end` / `to_end`。
    - `interface i connect a to b;` → `interface_part` の中の from_end/to_end。
    - `connection fp connect (a, b, c);` （n項）→ `ends` リスト。
    """
    count = sum(
        1 for c in node.get("children", [])
        if isinstance(c, dict) and c.get("type") == "connection_end_member"
    )
    for key in ("firstEnd", "thenEnd", "from_end", "to_end"):
        if node.get(key):
            count += 1
    for part_key in ("interface_part", "connector_part"):
        part = node.get(part_key)
        if isinstance(part, dict):
            count += sum(1 for k in ("from_end", "to_end") if part.get(k))
    ends = node.get("ends")
    if isinstance(ends, list):
        count += len(ends)
    return count


class ConnectionAndAnnotationRulesMixin:
    def _check_at_least_two_related_elements(self, node: Dict, namespace: str) -> None:
        """connection / interface は2つ以上の要素を結ばなければならない
        （Relationship_invalid_relatedElement0.sysml、参照実装の
        "Must have at least two related elements"）。

        参照実装(jar 0.61.0)への問い合わせで確定した境界（2026-09-05）:

        - `connection { end ::> b0; }`（end 1つ）→ エラー。end 0個・名前付きでも同じ。
        - `connection { end ::> b0; end ::> b1; }`（end 2つ）→ クリーン。
        - `connection def CD;` / `interface def ID;`（本体なし＝end 0個）→ エラー。
        - **`abstract` が付いていると常にクリーン**（end 0個でも1個でも）。
        - **`interface def ID :> Base;`（Baseがendを2つ持つ）→ クリーン。**
          つまり参照実装は継承した端点も数える。
        - `connect a to b;` は端点がインラインなので常に2つ揃い、対象外。

        最後の2点があるため、判定は「自ノードが直接持つ end が2つ未満」だけでは
        できない。継承や型指定で端点を得ているケースを誤検出しないよう、
        **abstract でなく、継承節も型指定も持たないノードだけ**を対象にする
        （検出漏れは許容し、偽陽性は出さない。他の実装済み意味ルールと同じ方針）。
        """
        if node.get("isAbstract"):
            return
        # 継承・型指定があると端点を外から得ている可能性がある。解決せずに
        # 判断できないので、そういうノードには触れない。
        if node.get("inheritance") or node.get("type_name") or node.get("redefines"):
            return
        end_count = _count_related_elements(node)
        if end_count >= 2:
            return
        name = node.get("name") or "(無名)"
        kind = "Interface" if node.get("type", "").startswith("interface") else "Connection"
        self.issues.append(LintIssue(
            SEVERITY_ERROR,
            f"[8.2.2.12] {kind} '{name}' は2つ以上の要素を結ばなければなりません"
            f"（endが{end_count}個）",
            node
        ))

    def _check_connection_advanced_rules(self) -> None:
        """
        接続高度ルールチェック (SysML v2 8.2.2.13)
        
        - Binary vs Nary Connector の区別
        - Binding Connectors の等価性チェック
        - Succession の順序チェック
        """
        for connection in self.connections:
            self._check_connection_structure_advanced(connection)
            self._check_binding_connector_structure(connection)
            self._check_succession_structure(connection)
    def _check_connection_structure_advanced(self, connection: Dict) -> None:
        """
        Connection の高度な構造チェック (8.2.2.13)
        
        Args:
            connection: 接続ノード
        """
        connection_name = connection.get("name", "unknown")

        # Binary vs Nary Connector の区別（connection_defのendメンバー = connection_end_member）
        connector_ends = []
        children = connection.get("children", [])
        for child in children:
            if isinstance(child, dict) and child.get("type") == "connection_end_member":
                connector_ends.append(child.get("name", ""))

        # Binary Connector (2つのエンド)
        if len(connector_ends) == 2:
            self._check_binary_connector_structure(connection, connector_ends)
        # Nary Connector (3つ以上のエンド)
        elif len(connector_ends) > 2:
            self._check_nary_connector_structure(connection, connector_ends)
        # 「endが2個未満」の検査はここから削除した（2026-09-07）。
        #
        # 同じ事実を`_check_at_least_two_related_elements`（このファイル）が
        # 検査しており、そちらの方が厳密に優れている:
        #
        # - 端点の数え方が`_count_related_elements`で一般化されている
        #   （`connection_end_member`の子だけでなく firstEnd/thenEnd/
        #   from_end/to_end/ends/interface_part も数える）。こちらは
        #   `connection_end_member`しか数えていなかった。
        # - `inheritance`/`type_name`/`redefines`を持つノードには触らない
        #   ガードがある。こちらは`isAbstract`しか除外していなかったため、
        #   `connection def CD2 :> CD;`（endを基底から継承する形）を
        #   「end 0個」として落としていた。参照実装はこれをクリーンと判定する
        #   （2026-09-07実測。一方`connection def CD;`のようにendが本当に
        #   0個の形は参照実装も`Must have at least two related elements`を
        #   返すので、そちらの検出は`_check_at_least_two_related_elements`が
        #   引き続き担う）。
        # - connection_def以外（connection_usage/interface_def/interface_usage）も
        #   対象にしている。こちらは`self.connections`しか見ていない。
        #
        # 加えて両者が発火すると、参照実装が1件しか返さない事実を**二重に
        # 報告**していた。劣っている側を落とすことで偽陽性と二重報告の両方が
        # 解消する。
    def _check_binary_connector_structure(self, connection: Dict, connector_ends: List[str]) -> None:
        """
        Binary Connector の構造チェック

        Args:
            connection: 接続ノード
            connector_ends: コネクターエンドのリスト
        """
    def _check_nary_connector_structure(self, connection: Dict, connector_ends: List[str]) -> None:
        """
        Nary Connector の構造チェック

        Args:
            connection: 接続ノード
            connector_ends: コネクターエンドのリスト
        """
        connection_name = connection.get("name", "unknown")

        # Nary Connector の特別な制約チェック
        if len(connector_ends) > 10:  # 実用的な上限
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.13] Nary Connector '{connection_name}' のエンド数が {len(connector_ends)} 個と多すぎます",
                connection
            ))
    def _check_binding_connector_structure(self, connection: Dict) -> None:
        """
        Binding Connectors の等価性チェック (8.2.2.13)
        
        Args:
            connection: 接続ノード
        """
        connection_name = connection.get("name", "unknown")
        
        # bind = 構文の検出
        children = connection.get("children", [])
        for child in children:
            if isinstance(child, dict):
                expression = child.get("expression", "")
                if "bind" in str(expression) and "=" in str(expression):
                    self._check_binding_equivalence(child, connection_name)
    def _check_binding_equivalence(self, binding_node: Dict, connection_name: str) -> None:
        """
        Binding の等価性チェック
        
        Args:
            binding_node: バインディングノード
            connection_name: 接続名
        """
        expression = str(binding_node.get("expression", ""))
        
        if "bind" in expression and "=" in expression:
            # bind = の両辺を抽出
            parts = expression.split("=", 1)
            if len(parts) == 2:
                left = parts[0].replace("bind", "").strip()
                right = parts[1].strip()
                
                # 両辺の要素の存在チェック
                if left and not self._find_element_in_symbols(left):
                    self.issues.append(LintIssue(
                        SEVERITY_WARNING,
                        f"[8.2.2.13] Binding '{connection_name}' の左辺 '{left}' が見つかりません",
                        binding_node
                    ))
                
                if right and not self._find_element_in_symbols(right):
                    self.issues.append(LintIssue(
                        SEVERITY_WARNING,
                        f"[8.2.2.13] Binding '{connection_name}' の右辺 '{right}' が見つかりません",
                        binding_node
                    ))
    def _check_succession_structure(self, connection: Dict) -> None:
        """
        Succession の順序チェック (8.2.2.13)
        
        Args:
            connection: 接続ノード
        """
        connection_name = connection.get("name", "unknown")
        
        # succession の first/then 順序チェック
        children = connection.get("children", [])
        succession_items = []
        
        for child in children:
            if isinstance(child, dict):
                child_type = child.get("type")
                if child_type in ["first_stmt", "then_stmt"]:
                    succession_items.append(child)
        
        # first が then より前に来ることをチェック
        first_found = False
        for item in succession_items:
            item_type = item.get("type")
            if item_type == "first_stmt":
                first_found = True
            elif item_type == "then_stmt" and not first_found:
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.13] Succession '{connection_name}' で 'then' が 'first' より前に定義されています",
                    item
                ))
    def _check_annotation_stmt(self, node: Dict, namespace: str) -> None:
        """
        annotation_stmtのチェック (8.2.2.4.1)
        
        SysML v2.0 仕様:
        Annotation = annotatedElement = [QualifiedName]
        OwnedAnnotation : Annotation = ownedRelatedElement += AnnotatingElement
        AnnotatingElement = Comment | Documentation | TextualRepresentation | MetadataFeature
        
        Args:
            node: annotationノード
            namespace: 現在の名前空間
        """
        annotating_element = node.get("annotating_element")
        if not annotating_element:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.4.1] Annotation に AnnotatingElement が指定されていません",
                node
            ))
            return
        
        element_type = annotating_element.get("type")
        
        if element_type == "comment":
            self._check_comment_stmt(annotating_element, namespace)
        elif element_type == "documentation":
            self._check_documentation_stmt(annotating_element, namespace)
        elif element_type == "textual_representation":
            self._check_textual_representation_stmt(annotating_element, namespace)
        elif element_type == "metadata_feature":
            self._check_metadata_feature_stmt(annotating_element, namespace)
        else:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.4.1] 不正な AnnotatingElement 型: {element_type}",
                node
            ))
    def _check_comment_stmt(self, node: Dict, namespace: str) -> None:
        """
        comment_stmtのチェック (8.2.2.4.2)
        
        SysML v2.0 仕様:
        Comment = ( 'comment' Identification 
                   ( 'about' ownedRelationship += Annotation ( ',' ownedRelationship += Annotation )* )? 
                 )? 
                 ( 'locale' locale = STRING_VALUE )? 
                 body = REGULAR_COMMENT
        
        Args:
            node: commentノード
            namespace: 現在の名前空間
        """
        # Identification の検証
        identification = node.get("identification")
        if identification and not self._is_valid_identification(identification):
            # デバッグ用の詳細情報
            id_type = type(identification).__name__
            id_content = str(identification)[:100]  # 長すぎる場合は切り詰め
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.4.2] Comment の Identification が無効です (type: {id_type}): {id_content}",
                node
            ))
        
        # ownedRelationship += Annotation の検証
        owned_relationships = node.get("owned_relationship", [])
        for annotation in owned_relationships:
            self._check_annotation_reference(annotation, namespace)
        
        # locale = STRING_VALUE の検証
        locale = node.get("locale")
        if locale and not self._is_valid_locale_string(locale):
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.4.2] Comment の locale 値が不正です: {locale}",
                node
            ))
        
        # body = REGULAR_COMMENT の検証
        body = node.get("body", "")
        if not body:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.4.2] Comment の body が空です",
                node
            ))
        elif not self._is_valid_regular_comment(body):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.4.2] Comment の body が REGULAR_COMMENT 形式ではありません",
                node
            ))
    def _check_annotation_reference(self, annotation: Dict, namespace: str) -> None:
        """
        annotation_referenceのチェック (8.2.2.4.2)
        
        SysML v2.0 仕様: [QualifiedName] resolution
        
        Args:
            annotation: annotation_referenceノード
            namespace: 現在の名前空間
        """
        if not isinstance(annotation, dict):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.4.2] annotation_reference が不正な形式です",
                annotation
            ))
            return
        
        qualified_name = annotation.get("qualified_name")
        if not qualified_name:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.4.2] annotation_reference に qualified_name が指定されていません",
                annotation
            ))
            return
        
        # QualifiedNameの解決チェック
        name = qualified_name.get("name", "") if isinstance(qualified_name, dict) else str(qualified_name)
        if not self._is_valid_qualified_name(name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.4.2] 不正な qualified_name: {name}",
                annotation
            ))
    def _is_valid_identification(self, identification: Dict) -> bool:
        """
        Identification の妥当性をチェック
        
        Args:
            identification: identificationノード
            
        Returns:
            妥当性
        """
        if not isinstance(identification, dict):
            return False
        
        # identificationノードの場合
        if identification.get("type") == "identification":
            # 複数のフィールドをチェック（空文字列も考慮）
            name = identification.get("name") or identification.get("declaredName") or identification.get("declaredShortName")
            if name and isinstance(name, str) and name.strip():
                return True
            return False
        
        # 文字列の場合
        name = identification.get("name", "")
        return bool(name and isinstance(name, str) and name.strip())
    def _is_valid_regular_comment(self, body: str) -> bool:
        """
        REGULAR_COMMENT の妥当性をチェック
        
        SysML v2.0 仕様: body = REGULAR_COMMENT
        
        Args:
            body: コメント本文
            
        Returns:
            妥当性
        """
        if not isinstance(body, str):
            return False
        
        # 空文字列は有効（空のコメント）
        if not body:
            return True
        
        # 基本的な文字列チェック（制御文字を除く）
        return all(ord(c) >= 32 or c in '\t\n\r' for c in body)
    def _check_documentation_stmt(self, node: Dict, namespace: str) -> None:
        """
        documentation_stmtのチェック (8.2.2.4.2)

        Documentation（AnnotatingElement）の識別子は仕様上任意であり必須ではない。
        公式SysML v2標準ライブラリのパッケージ・要素は、ほぼ全てが名前無しの
        `doc /* ... */`で説明文を書くのが通常の書き方であるため、名前が付いて
        いる場合のみ、その妥当性を検証する。

        Args:
            node: documentationノード
            namespace: 現在の名前空間
        """
        # identification の検証（任意。付いている場合のみ妥当性をチェック）
        identification = node.get("identification")
        if identification and not self._is_valid_identification(identification):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.4.2] Documentation の identification '{identification}' が無効です",
                node
            ))
        
        # locale の検証
        locale = node.get("locale")
        if locale and not self._is_valid_locale_string(locale):
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.4.2] Documentation の locale '{locale}' が無効な形式です",
                node
            ))
        
        # body の検証
        body = node.get("body", "")
        if not body.strip():
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.4.2] Documentation の body が空です",
                node
            ))
    def _check_textual_representation_stmt(self, node: Dict, namespace: str) -> None:
        """
        textual_representation_stmtのチェック (8.2.2.4.3)
        
        Args:
            node: textual_representationノード
            namespace: 現在の名前空間
        """
        # identification の検証（オプション）
        identification = node.get("identification")
        if identification and not self._is_valid_identification(identification):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.4.3] TextualRepresentation の identification '{identification}' が無効です",
                node
            ))
        
        # language の検証（必須）
        language = node.get("language")
        if not language:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.4.3] TextualRepresentation には language が必要です",
                node
            ))
        elif not self._is_valid_language_string(language):
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.4.3] TextualRepresentation の language '{language}' が無効な形式です",
                node
            ))
        
        # body の検証
        body = node.get("body", "")
        if not body.strip():
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.4.3] TextualRepresentation の body が空です",
                node
            ))
    def _check_metadata_feature_stmt(self, node: Dict, namespace: str) -> None:
        """
        metadata_feature_stmtのチェック (8.2.2.4.4)
        
        Args:
            node: metadata_featureノード
            namespace: 現在の名前空間
        """
        metadata_type = node.get("metadata_type", "unknown")
        
        # 既存のmetadata検証ロジックを活用
        if metadata_type == "metadata_def":
            # metadata定義の検証
            name = node.get("name", "")
            if not name:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    "[8.2.2.4.4] MetadataFeature 定義には名前が必要です",
                    node
                ))
        elif metadata_type == "metadata_usage":
            # metadata使用の検証
            typing = node.get("typing")
            if typing and not self._find_element_in_symbols(typing):
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.4.4] MetadataFeature の型 '{typing}' が見つかりません",
                    node
                ))
        elif metadata_type == "prefix_metadata":
            # prefix metadata の検証
            typing = node.get("typing")
            if typing and not self._find_element_in_symbols(typing):
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.4.4] Prefix metadata の型 '{typing}' が見つかりません",
                    node
                ))
    def _is_valid_locale_string(self, locale: str) -> bool:
        """
        locale 文字列の妥当性をチェック
        
        Args:
            locale: ロケール文字列
            
        Returns:
            妥当性の真偽値
        """
        if not locale or not isinstance(locale, str):
            return False
        
        # 基本的なロケール形式をチェック（例: "en", "en-US", "ja-JP"）
        import re
        return re.match(r'^[a-z]{2}(-[A-Z]{2})?$', locale) is not None
    def _is_valid_language_string(self, language: str) -> bool:
        """
        language 文字列の妥当性をチェック
        
        Args:
            language: 言語文字列
            
        Returns:
            妥当性の真偽値
        """
        if not language or not isinstance(language, str):
            return False
        
        # 基本的な言語識別子をチェック
        # 一般的なプログラミング言語やマークアップ言語
        valid_languages = {
            'sysml', 'uml', 'java', 'python', 'c++', 'c', 'javascript', 'typescript',
            'html', 'xml', 'json', 'yaml', 'markdown', 'text', 'plain'
        }
        
        return language.lower() in valid_languages or language.startswith('text/')
    def _is_valid_qualified_name(self, name: str) -> bool:
        """
        qualified name の妥当性をチェック (8.2.2.4.2)
        
        Args:
            name: qualified name 文字列
            
        Returns:
            妥当性の真偽値
        """
        if not name or not isinstance(name, str):
            return False
        
        # 基本的な識別子パターンをチェック
        # QualifiedName = NAME ('::' NAME)*
        parts = name.split('::')
        for part in parts:
            if not part or not part.strip():
                return False
            # 基本的な識別子の規則をチェック
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', part.strip()):
                return False
        
        return True