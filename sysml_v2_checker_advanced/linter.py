"""
SysML v2 Advanced Checker Linter

高度なルールチェッカー
"""

from typing import Dict, List, Set

from .constants import (
    BUILTIN_TYPES,
    ELEMENT_REFERENCE_ONLY_USAGE_TYPES,
    SEVERITY_ERROR,
    STANDARD_LIBRARY_PACKAGES,
)
from .expression_type_inference import ExpressionTypeInference
from .lint_issue import LintIssue
from .linter_rules.action_behavior_rules import ActionBehaviorRulesMixin
from .linter_rules.case_and_view_rules import CaseAndViewRulesMixin
from .linter_rules.connection_and_annotation_rules import ConnectionAndAnnotationRulesMixin
from .linter_rules.definition_usage_rules import DefinitionUsageRulesMixin
from .linter_rules.multiplicity_rules import MultiplicityRulesMixin
from .linter_rules.state_machine_rules import StateMachineRulesMixin
from .linter_rules.type_and_inheritance_rules import TypeAndInheritanceRulesMixin
from .linter_rules.usage_and_expression_rules import UsageAndExpressionRulesMixin
from .type_system import TypeSystemFoundation

# ============================================================================
# リンター（高度なルールチェック）
# ============================================================================

class SysMLAdvancedLinter(DefinitionUsageRulesMixin, MultiplicityRulesMixin, StateMachineRulesMixin, CaseAndViewRulesMixin, TypeAndInheritanceRulesMixin, UsageAndExpressionRulesMixin, ActionBehaviorRulesMixin, ConnectionAndAnnotationRulesMixin):
    """
    SysML v2高度ルールチェッカー
    
    ASTを解析して、以下のルールをチェックします：
    - 参照整合性（存在しない型・要素の参照）
    - 型チェック（型の一貫性）
    - 接続チェック（from/toの参照）
    - 要件定義の参照チェック（satisfiedBy）
    - 継承チェック
    - 高度な特殊化ルール（8.2.2.6.5 Specialization）
    - 使用法ルール（8.2.2.6.2 Usages）
    - フロー高度ルール（8.2.2.16 Flows）
    """
    
    def __init__(self):
        """リンターを初期化"""
        self.issues: List[LintIssue] = []
        self.symbols: Dict[str, Dict] = {}  # 名前 -> 定義ノード（型解決専用。_find_type_in_symbolsのみが参照する）
        self.element_refs: Dict[str, Dict] = {}  # 名前 -> usage/instanceノード（要素参照専用。_find_element_in_symbolsのみが参照する）
        # packageノードをself.symbols（型解決専用）へ混ぜるとパッケージ名が
        # 型名として有効扱いされてしまうため、self.element_refsと同じ考え方で
        # 専用の集合に分離する（_find_element_in_symbolsからのみ参照し、
        # _find_type_in_symbolsからは決して参照しない）。これにより
        # `package Outer { package Inner {...} import Inner::*; }`のような
        # 同一ファイル内のネストpackage参照も正しく解決できる。
        self.packages: Dict[str, Dict] = {}  # 名前 -> packageノード（パッケージ参照専用）
        # import文で明示的に持ち込まれたが、このファイル単体では中身を確認できない
        # 名前（例: `private import Collections::KeyValuePair;`の`KeyValuePair`）。
        self.opaque_import_names: Set[str] = set()
        # 同: `import Objects::*;`のように中身の見えないパッケージからの
        # ワイルドカードimportがあるか（あれば未解決の非修飾名の不在は証明できない）。
        self.has_opaque_wildcard_import: bool = False
        self.types: Set[str] = BUILTIN_TYPES.copy()  # 組み込み型
        self.connections: List[Dict] = []
        self.requirements: List[Dict] = []
        self.analysis_cases: List[Dict] = []  # analysis_case_def定義
        self.verification_cases: List[Dict] = []  # verification_case_def定義
        self.use_cases: List[Dict] = []  # use_case_def定義
        self.states: List[Dict] = []  # ステート定義
        self.transitions: List[Dict] = []  # 遷移定義
        self.initial_nodes: List[Dict] = []  # 初期状態ノード
        self.final_nodes: List[Dict] = []  # 終了状態ノード
        
        # 型システム基盤を初期化
        self.type_system = TypeSystemFoundation()
        
        # 式の型推論エンジンを初期化
        self.expression_inference = ExpressionTypeInference(self.type_system)
        
        # 高度ルール用の追加データ構造（後方互換性のため保持）
        self.specializations: Dict[str, List[str]] = {}  # 要素名 -> 特殊化リスト
        self.feature_typings: Dict[str, List[str]] = {}  # フィーチャー名 -> 型リスト
        self.feature_subsettings: Dict[str, List[str]] = {}  # フィーチャー名 -> サブセットリスト
        self.feature_redefinitions: Dict[str, List[str]] = {}  # フィーチャー名 -> 再定義リスト
    
    def lint(self, ast: Dict, known_external_types: Set[str] | None = None) -> List[LintIssue]:
        """
        ASTをチェックして問題を返す

        Args:
            ast: パース済みのAST
            known_external_types: 他ファイル（`import`経由）に実在する型名の集合。1ファイル単位の
                チェックでは解決できないクロスファイル型参照を、既知の外部型名
                として扱うことで「存在しない型」の誤検出を避ける。渡された名前は
                「ライブラリ内のどこかに実在する」ことのみを示す意図的な近似で、
                そのファイルが実際に正しくimportしているかまでは検証しない
                （既存のSTANDARD_LIBRARY_PACKAGES方式と同種のトレードオフ）。
                省略時（デフォルトNone）は単体ファイル動作のままとなる。

        Returns:
            検出された問題のリスト
        """
        # 状態をリセット
        self.issues = []
        self.symbols = {}
        self.element_refs = {}
        self.types = BUILTIN_TYPES.copy()
        if known_external_types:
            self.types.update(known_external_types)
        self.connections = []
        self.requirements = []
        self.analysis_cases = []
        self.verification_cases = []
        self.use_cases = []
        self.states = []
        self.transitions = []
        self.initial_nodes = []
        self.final_nodes = []

        # 型システムをリセット
        self.type_system = TypeSystemFoundation()

        # 高度ルール用データ構造をリセット（後方互換性のため保持）
        self.specializations = {}
        self.feature_typings = {}
        self.feature_subsettings = {}
        self.feature_redefinitions = {}

        # `private import Collections::KeyValuePair;`のように**明示的にimportした
        # メンバー名**は、そのファイルのスコープに入る正当な名前である。標準
        # ライブラリのように中身が見えないパッケージからimportした型
        # （`KeyValuePair`・`SemanticMetadata`・`LinkObject`等）を「存在しない型」
        # として誤検出しないよう、ここでimport文から「解決できないが確かに
        # スコープにある名前」を収集し、known_external_types相当の扱い（実在
        # することのみを示す近似登録）に合流させる。
        self.opaque_import_names = self._collect_opaque_import_names(ast)
        self.has_opaque_wildcard_import = self._has_opaque_wildcard_import(ast)
        self.types.update(self.opaque_import_names)

        # 第0パス: 型システム基盤の構築
        # ローカル定義の抽出を先に行い、その後に外部型名を「未登録のものだけ」
        # 補完する（先に外部型を登録すると、ローカルで同名の型が定義されている場合に
        # register_typeの名前空間衝突チェックでローカル定義が失われてしまうため）。
        self.type_system.build_specialization_graph(ast)
        if known_external_types:
            self.type_system.register_external_types(known_external_types)
        # importで持ち込まれた名前も型システム側へ同様に登録する
        # （category=UNKNOWNで登録されるため、カテゴリ互換性チェックで
        # 誤って非互換と判定されることはない）。
        if self.opaque_import_names:
            self.type_system.register_external_types(self.opaque_import_names)

        # 型システムの整合性検証
        # importで持ち込まれた名前・中身の見えない名前空間のメンバーは
        # 検証不能なため「存在しない型」として報告しない（判定はlinter側が持つ）。
        type_system_issues = self.type_system.validate_type_system(
            is_unverifiable=self._is_unverifiable_reference
        )
        for issue in type_system_issues:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[型システム] {issue}",
                None
            ))
        
        # 第1パス: シンボル収集
        self._collect_symbols(ast)
        
        # 第2パス: ルールチェック
        self._check_rules(ast)
        
        # 第3パス: ステートマシン関連の整合性チェック
        self._check_state_machine_consistency()
        
        # 第4パス: 継承の整合性チェック
        self._check_inheritance_consistency()
        
        # 第5パス: 高度な特殊化ルールチェック (8.2.2.6.5)
        # Note: 特殊化ルールのチェックは _check_rules に統合済み
        
        # 第6パス: 使用法ルールチェック (8.2.2.6.2)
        self._check_usage_rules()
        
        # 第7パス: アクション高度ルールチェック (8.2.2.17)
        self._check_action_advanced_rules()
        
        # 第8パス: ステート高度ルールチェック (8.2.2.18)
        self._check_state_advanced_rules()

        # 第9パス: Requirement 高度ルールチェック (8.2.2.19)
        self._check_requirement_advanced_rules()

        # 第10パス: Occurrence 高度ルールチェック (8.2.2.9)
        self._check_occurrence_advanced_rules()

        # 第11パス: Connection 高度ルールチェック (8.2.2.13)
        self._check_connection_advanced_rules()

        # 第12パス: Analysis/Verification/Use Case 高度ルールチェック (8.2.2.20-22)
        self._check_analysis_case_advanced_rules()
        self._check_verification_case_advanced_rules()
        self._check_use_case_advanced_rules()

        # 第13パス: ConjugatedPortTyping 特殊ルールチェック (8.2.2.12)
        self._check_conjugated_port_typing_rules()
        
        return self.issues
    
    def _collect_symbols(self, node: Dict, namespace: str = "") -> None:
        """
        シンボルテーブルを構築
        
        ASTを走査して、定義されているシンボル（part, action, type等）を収集します。
        
        Args:
            node: 現在のASTノード
            namespace: 現在の名前空間（パッケージ名）
        """
        node_type = node.get("type")
        full_name = f"{namespace}::{node.get('name')}" if namespace else node.get("name", "")
        
        if node_type == "package":
            # packageの完全修飾名を構築して、子要素の名前空間として使用
            package_full_name = f"{namespace}::{node.get('name')}" if namespace else node.get("name", "")
            # package自体も「参照可能な要素」として登録する（import/exposeの解決に必要）。
            if node.get("name"):
                self.packages[package_full_name] = node
            for child in node.get("children", []):
                if isinstance(child, dict):
                    self._collect_symbols(child, package_full_name)
        
        # `enum_def`をこのリストに含めないと、`enum def Foo { A; B; }
        # attribute y : Foo;`のように**同一ファイル内で定義済み**のenum型への
        # 参照が「存在しない型」と誤検出される（enum defの名前がself.symbols/
        # self.typesに登録されなくなるため）。
        elif node_type in ["part_def", "action_def", "activity_def", "type_def", "port_def", "state_def", "state_usage", "interface_def", "allocation_def", "calculation_def", "constraint_def", "item_def", "attribute_def", "enum_def", "case_def", "analysis_case_def", "verification_case_def", "use_case_def", "view_def", "viewpoint_def", "rendering_def", "metadata_def", "event_occurrence_usage", "occurrence_def", "individual_def", "occurrence_usage", "requirement_def", "concern_def"]:
            name = node.get("name")
            if name:
                self.symbols[full_name] = node
                if node_type == "type_def":
                    self.types.add(full_name)
                    self.types.add(name)  # 短縮名も追加
                elif node_type == "enum_def":
                    # enum defも型として扱う（attributeの型参照先になる）。
                    self.types.add(full_name)
                    self.types.add(name)  # 短縮名も追加
                elif node_type == "item_def":
                    # item_defも型として扱う
                    self.types.add(full_name)
                    self.types.add(name)  # 短縮名も追加
                elif node_type == "attribute_def":
                    # attribute_defも型として扱う（他のattributeがこの型を参照できるように）
                    self.types.add(full_name)
                    self.types.add(name)  # 短縮名も追加
                elif node_type == "state_def":
                    # ステートもシンボルとして収集
                    pass
                elif node_type == "requirement_def":
                    # requirementもシンボルとして収集しつつ、要件固有チェック用のリストにも積む
                    self.requirements.append(node)
                elif node_type == "analysis_case_def":
                    self.analysis_cases.append(node)
                elif node_type == "verification_case_def":
                    self.verification_cases.append(node)
                elif node_type == "use_case_def":
                    self.use_cases.append(node)

        elif node_type == "alias":
            # alias文（`alias name for target;`）は既存の型/要素に対する同義語を
            # 導入する。nameを型シンボルとして登録しないと、他の場所でnameを
            # 基底型として参照した際に「存在しない型」と誤検出される。
            name = node.get("name")
            if name:
                self.types.add(full_name)
                self.types.add(name)  # 短縮名も追加

        elif node_type in ELEMENT_REFERENCE_ONLY_USAGE_TYPES:
            # part_instance等のusage/instanceノード。型解決用のself.symbols/self.typesには
            # 登録せず、要素参照専用のself.element_refsにのみ登録する
            # (インスタンス名を型名として誤って有効扱いしないため)。
            name = node.get("name")
            if name:
                self.element_refs[full_name] = node

        elif node_type == "connection_def":
            self.connections.append(node)

        elif node_type == "transition":
            self.transitions.append(node)
        
        elif node_type == "initial_node":
            self.initial_nodes.append(node)
        
        elif node_type == "final_node":
            self.final_nodes.append(node)
        
        # 再帰的に子ノードを処理
        # packageは上のif節で既に正しい名前空間(package_full_name)を使って
        # 子要素を再帰済みなので、ここで再度たどると誤った名前空間・重複登録
        # (self.symbols/self.requirements/self.connections等への二重登録)を招く。
        if node_type != "package":
            for key in ["children", "params", "attributes"]:
                if key in node:
                    for child in node[key]:
                        if isinstance(child, dict):
                            self._collect_symbols(child, namespace)
    
    def _check_rules(self, node: Dict, namespace: str = "") -> None:
        """
        ルールチェックを実行
        
        ASTを走査して、各種ルール違反を検出します。
        
        Args:
            node: 現在のASTノード
            namespace: 現在の名前空間（パッケージ名）
        """
        node_type = node.get("type")
        
        # ノードタイプに応じたチェック関数を呼び出し
        check_functions = {
            "package": lambda n, ns: self._check_package_children(n, ns),
            "part_def": self._check_part_def,
            "part_instance": self._check_part_instance,
            "action_def": self._check_action_def,
            "activity_def": self._check_activity_def,
            "type_def": self._check_type_def,
            "item_def": self._check_item_def,
            "attribute_def": self._check_attribute_definition,
            "attribute_usage": self._check_attribute_def,
            "connection_def": self._check_connection_def,
            "requirement_def": self._check_requirement_def,
            "port_def": self._check_port_def,
            "port_usage": self._check_port_usage,
            "state_def": self._check_state_def,
            "transition": self._check_transition,
            "interface_def": self._check_interface_def,
            "interface_usage": self._check_interface_usage,
            "allocation_def": self._check_allocation_def,
            "allocation_usage": self._check_allocation_usage,
            "calculation_def": self._check_calculation_def,
            "calculation_usage": self._check_calculation_usage,
            "constraint_def": self._check_constraint_def,
            "constraint_usage": self._check_constraint_usage,
            "assert_constraint_usage": self._check_assert_constraint_usage,
            "satisfy_requirement_usage": self._check_satisfy_requirement_usage,
            # Cases (8.2.2.22-25)
            "case_def": self._check_case_def,
            "case_usage": self._check_case_usage,
            "analysis_case_def": self._check_analysis_case_def,
            "analysis_case_usage": self._check_analysis_case_usage,
            "verification_case_def": self._check_verification_case_def,
            "verification_case_usage": self._check_verification_case_usage,
            "use_case_def": self._check_use_case_def,
            "use_case_usage": self._check_use_case_usage,
            "include_use_case_usage": self._check_include_use_case_usage,
            # Views and Viewpoints (8.2.2.26)
            "view_def": self._check_view_def,
            "view_usage": self._check_view_usage,
            "viewpoint_def": self._check_viewpoint_def,
            "viewpoint_usage": self._check_viewpoint_usage,
            "rendering_def": self._check_rendering_def,
            "rendering_usage": self._check_rendering_usage,
            # Metadata (8.2.2.27)
            "metadata_def": self._check_metadata_def,
            "metadata_usage": self._check_metadata_usage,
            # Phase 2: 8.2.2.4 Annotations (SysML v2.0 完全準拠)
            "annotation": self._check_annotation_stmt,
            "annotating_element": self._check_annotation_stmt,  # annotating_elementもannotation_stmtとして処理
            "comment": self._check_comment_stmt,
            "documentation": self._check_documentation_stmt,
            "textual_representation": self._check_textual_representation_stmt,
            "metadata_feature": self._check_metadata_feature_stmt,
            # Phase 2: 8.2.2.6.6 Multiplicity (SysML v2.0 完全準拠)
            "multiplicity_part": self._check_multiplicity_part,
            "owned_multiplicity": self._check_owned_multiplicity,
            "multiplicity_range": self._check_multiplicity_range,
            "multiplicity_expression_member": lambda n, ns: self._check_multiplicity_expression_member(n, "expression member", ns),
        }
        
        if node_type in check_functions:
            check_functions[node_type](node, namespace)
        
        # 多重度のチェック（後方互換性）
        if "multiplicity" in node:
            self._check_multiplicity(node["multiplicity"], node.get("name", "unknown"))
        
        # 新しいmultiplicity_partのチェック (8.2.2.6.6)
        if "multiplicity_part" in node:
            self._check_multiplicity_part(node["multiplicity_part"], node.get("name", "unknown"))
        
        # import/exposeのチェック
        if node_type == "import":
            self._check_import(node, namespace)
        elif node_type == "expose":
            self._check_expose(node, namespace)
        
        # port_usage のチェック（conjugated_port_typing を含む）
        if node_type == "port_usage":
            self._check_port_usage_conjugated_typing(node, node.get("name", "unknown"))
        
        # usage_named で conjugated_port_typing が含まれている場合もチェック
        if "conjugated_port_typing" in node:
            conjugated_typing = node.get("conjugated_port_typing")
            if isinstance(conjugated_typing, dict):
                typing_name = node.get("name", "unknown")
                self._check_conjugated_port_typing(conjugated_typing, f"{typing_name}::conjugated_typing")
        
        # type_name に ~ が含まれている場合もチェック（port_usage の場合）
        # type_nameキーが存在しつつ値がNoneのport_usageノード（型節省略形）で
        # AttributeErrorにならないよう、`or ""`でフォールバックする。
        if node_type == "port_usage" and (node.get("type_name") or "").startswith("~"):
            original_port = (node.get("type_name") or "")[1:]  # ~ を除去
            conjugated_typing_dict = {
                "type": "conjugated_port_typing",
                "originalPortDefinition": original_port
            }
            self._check_conjugated_port_typing(conjugated_typing_dict, f"{node.get('name', 'unknown')}::{node.get('type_name', '')}")
        
        # 再帰的に子ノードをチェック
        # package は _check_package_children が children を再帰済みのため、
        # ここで再度辿ると同じ事実に対する診断が二重に生成されてしまう。
        if node_type != "package":
            for key in ["children", "params", "attributes", "exposes"]:
                if key in node:
                    for child in node[key]:
                        if isinstance(child, dict):
                            self._check_rules(child, namespace)
    
    def _check_package_children(self, node: Dict, namespace: str) -> None:
        """パッケージの子ノードをチェック"""
        for child in node.get("children", []):
            if isinstance(child, dict):
                self._check_rules(child, node.get("name", ""))
    
    def _iter_import_nodes(self, node: Dict):
        """AST全体からimportノードを再帰的に列挙する。"""
        if not isinstance(node, dict):
            return
        if node.get("type") == "import":
            yield node
        for key in ("children", "params", "attributes"):
            for child in node.get(key, []) or []:
                yield from self._iter_import_nodes(child)

    def _collect_opaque_import_names(self, ast: Dict) -> Set[str]:
        """`import A::B;`という明示的なメンバーimportのうち、`A`の中身が
        このファイルからは確認できないもの（標準ライブラリ等）の`B`を集める。

        SysML v2では明示importした名前はそのスコープに入るため、`B`への型参照は
        正当である。`A`がローカルに実在する場合は通常のシンボル解決で扱えるため
        ここでは対象にしない（ローカルの誤りを見逃さないため）。
        """
        names: Set[str] = set()
        for node in self._iter_import_nodes(ast):
            if node.get("wildcard"):
                continue
            import_name = node.get("name") or ""
            if "::" not in import_name:
                continue
            root, member = import_name.split("::")[0], import_name.split("::")[-1]
            # ローカルに解決できるimportは通常のシンボル解決に任せる。
            if root in self.packages or self._find_element_in_symbols(root):
                continue
            if member:
                names.add(member)
        return names

    def _has_opaque_wildcard_import(self, ast: Dict) -> bool:
        """中身の見えないパッケージからのワイルドカードimport（`import
        Objects::*;`等）があるか。ある場合、未解決の非修飾名は「そのパッケージに
        由来する可能性」を排除できないため、不在を根拠にした誤検出を避ける。"""
        for node in self._iter_import_nodes(ast):
            if not node.get("wildcard"):
                continue
            package_name = node.get("name") or ""
            if not package_name:
                continue
            if package_name in self.packages or self._find_element_in_symbols(package_name):
                continue
            return True
        return False

    def _is_unverifiable_reference(self, type_name: str) -> bool:
        """「解決できないが、存在しないとも言い切れない」参照かどうかを判定する。

        - 修飾名で、その先頭セグメントが標準ライブラリパッケージ、あるいは
          importで持ち込まれた（中身の見えない）名前の場合。配下のメンバーは
          単一ファイルlintの範囲では検証できない
          （例: `SpatialFrames::PositionOf`・`StructuredSpaceObject::StructuredCurve`）。
        - 非修飾名で、中身の見えないワイルドカードimportがある場合。
          その名前がそこに由来する可能性を排除できない。
        """
        if "::" in type_name:
            root = type_name.split("::")[0]
            if root in STANDARD_LIBRARY_PACKAGES or root in self.opaque_import_names:
                return True
            # 先頭セグメント自体がローカルに解決できず、かつ中身の見えない
            # ワイルドカードimportがある場合、その名前はワイルドカード由来で
            # ある可能性がある（例: ShapeItems.sysmlの
            # `item def Path :> StructuredSpaceObject::StructuredCurve;`は
            # `private import Objects::*;`由来）。名前自体が検証不能なら、
            # その配下のメンバーも同様に検証不能である。
            if self.has_opaque_wildcard_import and not self._find_element_in_symbols(root):
                return True
            return False
        return self.has_opaque_wildcard_import

    def _find_type_in_symbols(self, type_name: str) -> bool:
        """
        シンボルテーブルで型を検索
        
        Args:
            type_name: 検索する型名
            
        Returns:
            型が見つかった場合True
        """
        if type_name in self.types:
            return True

        # 標準ライブラリの修飾名（例: "ScalarValues::Real"）は、末尾セグメントが
        # 組み込み型と一致すれば有効な参照として扱う。ローカルに再定義されていない
        # 標準ライブラリ型を「存在しない型」と誤検出しないため。
        short_name = type_name.split("::")[-1]
        if short_name in self.types and "::" in type_name:
            prefix = type_name.rsplit("::", 1)[0]
            if prefix.split("::")[-1] in STANDARD_LIBRARY_PACKAGES:
                return True

        for sym_name in self.symbols:
            if sym_name.endswith(f"::{type_name}") or sym_name == type_name:
                return True

        # 解決できなかった参照のうち、「単一ファイルlintの範囲では検証不能」な
        # ものは存在しないと断定できないため有効扱いにする（誤検出の回避）。
        if self._is_unverifiable_reference(type_name):
            return True

        return False
    
    def _find_element_in_symbols(self, element_name: str) -> bool:
        """
        シンボルテーブルで要素を検索

        型定義（self.symbols）に加え、part_instance等のusage/instanceノード
        （self.element_refs）とpackageノード（self.packages）も要素参照の
        解決対象に含める。
        こちらは「参照可能な要素として存在するか」の判定専用であり、
        self.element_refs/self.packagesは_find_type_in_symbolsからは決して
        参照しない（インスタンス名・パッケージ名を型名として誤って有効扱い
        しないため）。

        Args:
            element_name: 検索する要素名

        Returns:
            要素が見つかった場合True
        """
        # packageノードも参照解決対象に含める（同一ファイル内のネストpackage参照が
        # 解決できるように）。
        for registry in (self.symbols, self.element_refs, self.packages):
            for sym_name in registry:
                if (sym_name.endswith(f"::{element_name}") or
                    sym_name == element_name or
                    sym_name.split("::")[-1] == element_name):
                    return True

        # 注意: 「検証不能なら存在扱い」とする緩和ルールをここに入れてはならない。
        # `import NoSuchPackage::*;`自身が「中身の見えないワイルドカード
        # import」を立てるため、その存在チェックが自分自身によって常に成功
        # してしまう（循環）。この関数は純粋な存在判定に保つ（golden setの
        # sysml-broken-04がこの回帰を検出する）。
        # 型/継承参照側の緩和は_type_reference_existsで行う。
        return False

    def _type_reference_exists(self, type_name: str) -> bool:
        """「型・継承の参照先」用の存在判定。

        要素としての実在（_find_element_in_symbols）に加えて、importで
        持ち込まれた名前や中身の見えない名前空間のメンバーも有効扱いにする
        （例: `private import Objects::LinkObject;`した`LinkObject`の継承）。
        import文自体の存在チェック（_check_import）には使わない——そちらは
        「未知のパッケージを報告する」ことが役割であり、緩和すると自己参照的に
        常に成功してしまう。
        """
        if self._find_element_in_symbols(type_name):
            return True
        if type_name in self.opaque_import_names:
            return True
        return self._is_unverifiable_reference(type_name)
    

        # 子パート（part_instance）の型チェックは _check_rules の走査経由で
        # _check_part_instance が一元的に行う（ここで重複実装しない）。



    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    


    
        # その他の組み合わせも基本的に有効
    
    
    
    
    
    
    
    
    def _check_import(self, node: Dict, namespace: str) -> None:
        """
        インポートの解決チェック
        
        インポートされた要素が存在するかチェックします。
        
        Args:
            node: importノード
            namespace: 現在の名前空間
        """
        import_name = node.get("name", "")
        is_wildcard = node.get("wildcard", False)
        
        if not import_name:
            return
        
        # ワイルドカードの場合は、パッケージの存在のみチェック
        if is_wildcard:
            # パッケージ名を取得（最後の::*を除く）
            package_name = import_name
            # `import KerML::Kernel::*;`のように「標準ライブラリパッケージ配下の
            # ネストしたパッケージ」を参照する形も判定できるよう、先頭・末尾
            # 両方のセグメントを標準ライブラリ判定に使う。先頭セグメントが
            # 標準ライブラリなら配下は検証不能なのでスキップする。
            segments = package_name.split("::") if package_name else []
            if (
                package_name
                and segments[0] not in STANDARD_LIBRARY_PACKAGES
                and segments[-1] not in STANDARD_LIBRARY_PACKAGES
                and not self._find_element_in_symbols(package_name)
            ):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Import '{import_name}::*' が存在しないパッケージ '{package_name}' を参照しています",
                    node
                ))
        else:
            # 特定の要素をインポートする場合。標準ライブラリパッケージ配下
            # （例: "ScalarValues::Real"）はローカル未定義でも有効な参照とする。
            top_level = import_name.split("::")[0]
            if (
                top_level not in STANDARD_LIBRARY_PACKAGES
                and not self._find_element_in_symbols(import_name)
            ):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Import '{import_name}' が存在しない要素を参照しています",
                    node
                ))
    
    def _check_expose(self, node: Dict, namespace: str) -> None:
        """
        エクスポーズの解決チェック
        
        エクスポーズされた要素が存在するかチェックします。
        
        Args:
            node: exposeノード
            namespace: 現在の名前空間
        """
        qualified_name = node.get("qualified_name", "")
        
        if not qualified_name:
            return
        
        # エクスポーズされた要素が存在するかチェック
        if not self._find_element_in_symbols(qualified_name):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Expose '{qualified_name}' が存在しない要素を参照しています",
                node
            ))
    
    
    # transitionのsource/targetとして正当な参照先のノード種別。
    # SysML v2ではTransitionUsageのsource/targetはOccurrenceUsageであり、
    # ステートに限らずaction/occurrence usageも参照できる（公式標準
    # ライブラリのActions.sysmlが実際に`transition aTransition first start
    # ... then done;`で`action start: Action :>> startShot`を参照している）。
    # 一方、属性やポート等まで許すと「存在しないステート名」の検出力が
    # 落ちるため、occurrence系に限定する。
    TRANSITION_ENDPOINT_NODE_TYPES = (
        "state_def",
        "state_usage",
        "action_def",
        "action_usage",
        "occurrence_def",
        "occurrence_usage",
        "event_occurrence_usage",
    )

    
    
        
        # 終了状態は複数存在可能なので、チェック不要
    

    
    
    
    
    
    
    
    
    
    

    
    
    
    
    
    
    # ============================================================================
    # Cases (8.2.2.22-25) Linter Methods
    # ============================================================================
    
    
    
    
    
    
    
    
    
    
    # ============================================================================
    # Views and Viewpoints (8.2.2.26) Linter Methods
    # ============================================================================
    
    
    
    
    
    
    
    # ============================================================================
    # Metadata (8.2.2.27) Linter Methods
    # ============================================================================
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    # ============================================================================
    # 使用法ルール実装 (8.2.2.6.2 Usage Rules)
    # ============================================================================
    
    
    
        # アクションは少なくとも1つの in または out パラメータを持つべき
        # これは _check_action_def で既にチェックされているが、より詳細にチェック
        
        # inout パラメータは SysML v2 仕様で正当な構文のため、警告は不要
        # 設計ガイダンスとしては in/out の分離が推奨されるが、仕様違反ではない
    
    
    
    
    
    
    
    # ============================================================================
    # ヘルパーメソッド
    # ============================================================================
    
    
    
    
    
    
    # ============================================================================
    # 中優先度ルール実装 (8.2.2.17 Action Advanced Rules)
    # ============================================================================
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    # ============================================================================
    # 中優先度ルール実装 (8.2.2.18 State Advanced Rules)
    # ============================================================================
    
    
    
    
    
    # ============================================================================
    # 中優先度ルール実装 (8.2.2.13 Connection Advanced Rules)
    # ============================================================================
    
    
    
        # connector_endsはconnection_end_memberの「名前」（=ここで新規に宣言される
        # ローカルなエンド名）であり、他のシンボルを参照するものではないため、
        # シンボルテーブルでの存在チェックは対象外。各エンドの型参照チェックは
        # _check_connection_def が担当する。

    
    
    

    # ============================================================================
    # Phase 2: 8.2.2.4 Annotations Textual Notation (SysML v2.0 完全準拠)
    # ============================================================================
    
    
    

    

    
    
    
    
    
