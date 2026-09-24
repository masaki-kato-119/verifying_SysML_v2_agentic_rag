"""
SysML v2 Advanced Checker Linter

高度なルールチェッカー
"""

from typing import Dict, List, Set

from . import library_index
from .constants import (
    BUILTIN_TYPES,
    ELEMENT_REFERENCE_ONLY_USAGE_TYPES,
    SEVERITY_ERROR,
    STANDARD_LIBRARY_ENUM_NAMES,
    STANDARD_LIBRARY_PACKAGES,
)
from .expression_type_inference import ExpressionTypeInference
from .lint_issue import LintIssue
from .linter_rules.action_behavior_rules import ActionBehaviorRulesMixin
from .linter_rules.case_and_view_rules import (
    _OBJECTIVE_LIMIT_NODE_TYPES,
    _PORTION_USAGE_INVALID_OWNER_TYPES,
    _VIEW_RENDERING_LIMIT_NODE_TYPES,
    CaseAndViewRulesMixin,
)
from .linter_rules.connection_and_annotation_rules import (
    _RELATED_ELEMENTS_NODE_TYPES,
    ConnectionAndAnnotationRulesMixin,
)
from .linter_rules.definition_usage_rules import DefinitionUsageRulesMixin
from .linter_rules.multiplicity_rules import MultiplicityRulesMixin
from .linter_rules.state_machine_rules import (
    _PARALLEL_STATE_NODE_TYPES,
    StateMachineRulesMixin,
)
from .linter_rules.type_and_inheritance_rules import TypeAndInheritanceRulesMixin
from .linter_rules.usage_and_expression_rules import UsageAndExpressionRulesMixin
from .type_system import TypeSystemFoundation

# ============================================================================
# リンター（高度なルールチェック）
# ============================================================================

# subject位置制約(8.2.2.21)を適用するノード種別。SysML v2では subject は
# CaseDefinition と RequirementDefinition の機能なので、その特化である
# concern / use case / analysis case / verification case にも及ぶ。
# 2026-09-04に参照実装で1種別ずつ確認した（calc/actionは対象外）。
_SUBJECT_FIRST_NODE_TYPES = (
    "requirement_def", "requirement_usage",
    "concern_def", "concern_usage",
    "case_def", "case_usage",
    "use_case_def", "use_case_usage",
    "analysis_case_def", "analysis_case_usage",
    "verification_case_def", "verification_case_usage",
)

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
        # 標準ライブラリからの import で、このファイルに見えている名前 → 宣言の種別。
        # 索引（library_index.json）で中身を列挙できる import だけから作る。
        self.library_visible_names: Dict[str, str] = {}
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
        # 組み込み型（Boolean・Real 等、ScalarValues の型）は、import か修飾で
        # 見えているときだけ有効にする。参照実装は import 無しの `Boolean` を
        # `Couldn't resolve reference to Type 'Boolean'.` とする（2026-09-24実測）。
        # 見えているかは import から求める（_collect_library_visible_names）。
        self.library_visible_names = self._collect_library_visible_names(ast)
        self.types = {t for t in BUILTIN_TYPES if t in self.library_visible_names}
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

        # 第3.5パス: verifyの配置チェック(8.2.2.25)。所有チェーンを2段見る
        # 必要があり、ノード単位のディスパッチでは判定できないためここで走らせる。
        self._check_verify_requirement_placement(ast)

        # 第3.6パス: package直下のfeatureのredefineチェック(8.2.2.6)。
        # 所有者がpackageかどうかを見る必要があるためここで走らせる。
        self._check_package_level_feature_redefinition(ast)
        
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

        # 第14パス: accessible feature path チェック (8.2.2.7 feature chaining、
        # 参照実装比較レポートで発見した偽陰性)。`children`等の決まった
        # キーだけを辿る_check_rulesの再帰では`expression`/`from_end`/
        # `to_end`等のネストしたreferenceフィールドまで届かないため、
        # 専用の全木走査で行う。
        self._check_accessible_feature_paths(ast)

        # 第15パス: 数量リテラルの単位（`1.8 [kg]`）の名前解決（2026-09-24）。
        # 単位は式の中にあり _check_rules の再帰では届かないため、全木走査で行う。
        self._check_quantity_units(ast)

        # 最後に、import 漏れで解決できなかった名前へ import のヒントを付ける
        self._add_library_import_hints()

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
            # connection definitionも型参照の解決対象として登録する
            # （2026-09-07）。これが無いと`connection def CD { ... } part x : CD;`
            # のように**同一ファイル内で定義済み**のconnection型への参照が
            # `_find_type_in_symbols`で解決できず、「存在しない型」と誤検出される
            # （`enum_def`を上のwhitelistへ入れた理由と同じ。参照実装は
            # `part x : CD;`をクリーンと判定することを実測済み）。
            #
            # 上のwhitelist（`elif node_type in [...]`）に`connection_def`を
            # 足す形では**いけない**。この分岐が到達不能になって
            # `self.connections`が空になり、connection系のルールが全部黙る。
            # interface_def/allocation_defと同様、self.typesには入れずに
            # self.symbolsのみへ登録する。
            name = node.get("name")
            if name:
                self.symbols[full_name] = node

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
            "item_usage": self._check_usage_type_exists,
            "calc_parameter": self._check_usage_type_exists,
            "connection_def": self._check_connection_def,
            "requirement_def": self._check_requirement_def,
            "requirement_usage": self._check_requirement_usage,
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
        
        # subject位置制約(8.2.2.21)は Case/Requirement 系のすべてに適用される。
        # どの種別に適用されるかは参照実装(jar 0.61.0)への問い合わせで確定させた
        # （2026-09-04。calc def / action def には適用されない＝subjectを持たない）。
        # 各_check_*関数に1行ずつ足すより、ここで一括して呼ぶ方が対象範囲が
        # 一箇所で読める。
        if node_type in _SUBJECT_FIRST_NODE_TYPES:
            self._check_requirement_subject(node, namespace)

        # objectiveは1つまで(8.2.2.22-25)。対象範囲は
        # case_and_view_rules._OBJECTIVE_LIMIT_NODE_TYPES 側で定義している。
        if node_type in _OBJECTIVE_LIMIT_NODE_TYPES:
            self._check_single_objective(node, namespace)

        # view renderingは1つまで(8.2.2.26)。
        if node_type in _VIEW_RENDERING_LIMIT_NODE_TYPES:
            self._check_single_view_rendering(node, namespace)

        # snapshot/timesliceの所有者制約(8.2.2.9)。
        if node_type in _PORTION_USAGE_INVALID_OWNER_TYPES:
            self._check_portion_usage_owner(node, namespace)

        # parallel stateは遷移を持てない(8.2.2.11)。
        if node_type in _PARALLEL_STATE_NODE_TYPES:
            self._check_parallel_state_has_no_transitions(node, namespace)

        # 関連は2つ以上の要素を結ばなければならない(8.2.2.12/8.2.2.14)。
        if node_type in _RELATED_ELEMENTS_NODE_TYPES:
            self._check_at_least_two_related_elements(node, namespace)

        if node_type in check_functions:
            check_functions[node_type](node, namespace)

        # subsetting/redefiningのuniqueness制約チェック（シブリングスコープ、
        # 2026-08-28、参照実装比較レポートで発見した偽陰性）。
        if "children" in node:
            self._check_subsetting_uniqueness_conformance(node)
            self._check_binding_feature_override(node)
            # variation/variantの所有関係(8.2.2.5)。ノード種別を限定せず、
            # 子を持つ全ノードで見る（variantはpackage直下・action本体など
            # どこにでも書けてしまうため）。
            self._check_variation_variant_ownership(node, namespace)

        # 標準ライブラリの feature を名指しする subsets/redefines（2026-09-24）
        if node.get("redefines"):
            self._check_library_feature_references(node)

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

    @staticmethod
    def _declared_package_names(ast: Dict) -> Set[str]:
        """このファイルが宣言しているパッケージの名前（先頭の名前との衝突判定用）。"""
        names: Set[str] = set()

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "package" and node.get("name"):
                    names.add(node["name"])
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(ast)
        return names

    def _library_import_target(self, node: Dict, local_packages: Set[str]):
        """import が標準ライブラリを指すなら、その修飾名を返す（指さなければ None）。
        ファイル自身が同じ名前のパッケージを宣言していれば、そちらを指しうるので None。"""
        import_name = node.get("name") or ""
        root = import_name.split("::")[0]
        if not import_name or root not in STANDARD_LIBRARY_PACKAGES or root in local_packages:
            return None
        return import_name

    def _collect_library_visible_names(self, ast: Dict) -> Dict[str, str]:
        """標準ライブラリからの import でこのファイルに見える名前を集める。

        - `import Pkg::*;` は、索引が Pkg の中身を列挙できれば、その全部。
        - `import Pkg::X;` は X（実在すれば）。
        - `import Pkg::**;`（再帰）や、索引が列挙できないもの（complete でない
          パッケージ、定義のメンバーの import）は集めない。これらは
          _has_opaque_wildcard_import が「中身の見えない import」として扱い、
          非修飾名を検証不能にする。

        **import の置き場所（名前空間）は区別しない。** ファイル内のどこかで
        import された名前は、ファイル全体で見えるとみなす。参照実装は兄弟の
        パッケージの import を見せないが（2026-09-24実測）、名前空間ごとに
        分けると判定が細かくなる分だけ誤検出の余地が増える。見逃す側に倒した近似。
        """
        local_packages = self._declared_package_names(ast)
        visible: Dict[str, str] = {}
        for node in self._iter_import_nodes(ast):
            target = self._library_import_target(node, local_packages)
            if target is None or node.get("recursive"):
                continue
            if node.get("wildcard"):
                members = library_index.package_members(target)
                if members:
                    for name, kind in members.items():
                        visible.setdefault(name, kind)
                continue
            if "::" in target and library_index.resolve_qualified_name(target):
                member = target.rsplit("::", 1)[1].strip("'")
                visible.setdefault(member, library_index.member_kind(target) or "")
        return visible

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
        local_packages = self._declared_package_names(ast)
        for node in self._iter_import_nodes(ast):
            if not node.get("wildcard"):
                continue
            package_name = node.get("name") or ""
            if not package_name:
                continue
            # 標準ライブラリのパッケージで、索引が中身を列挙できるもの
            # （`import ISQ::*;`）は、持ち込まれる名前が分かっている
            # （library_visible_names）。再帰 import は列挙していないので除く。
            target = self._library_import_target(node, local_packages)
            if (
                target is not None
                and not node.get("recursive")
                and library_index.package_members(target) is not None
            ):
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
            if root in STANDARD_LIBRARY_PACKAGES:
                # 標準ライブラリの修飾名は、実在しないと索引で言い切れるもの
                # （`ISQ::Mass`）だけを「検証不能」から外す。詳細は
                # _library_reference_verdict を参照。
                return self._library_reference_verdict(type_name) is not False
            if root in self.opaque_import_names:
                return True
            # 先頭が標準ライブラリから import で持ち込まれた名前（多くは型）なら、
            # その先は型のメンバーで、継承をたどらないと判定できない。
            # 例: ShapeItems.sysml の `item def Path :> StructuredSpaceObject::StructuredCurve;`
            # （StructuredSpaceObject は `private import Objects::*;` 由来の struct）。
            if root.strip("'") in self.library_visible_names:
                return True
            # 先頭セグメント自体がローカルに解決できず、かつ中身の見えない
            # ワイルドカードimportがある場合、その名前はワイルドカード由来で
            # ある可能性がある（例: ShapeItems.sysmlの
            # `item def Path :> StructuredSpaceObject::StructuredCurve;`は
            # `private import Objects::*;`由来）。名前自体が検証不能なら、
            # その配下のメンバーも同様に検証不能である。
            if self.has_opaque_wildcard_import and not self._find_element_in_symbols(root):
                return True
            # 修飾プレフィックスが「ワイルドカードimportを持つローカルpackage」の
            # 場合、そのメンバーはimport経由で可視になっている可能性があり、
            # 単一ファイルの平坦なシンボル表では検証できない。
            # 例: `package P2a { public import P1::*; } ... part x : P2a::A;`
            # （QualifiedNameImportTest.sysml。ファイル自身が "The following
            # should not fail." と明記している）。CircularImport.sysml の
            # `part y : P1::B;` も同じ形（P1が`public import P2::*`を持つ）。
            if self._package_has_wildcard_import(type_name.rsplit("::", 1)[0]):
                return True
            return False
        # 標準ライブラリからの import で見えている名前は、実在が分かっている
        # （feature の参照など、_find_type_in_symbols を通らない規則のため）
        if type_name.strip("'") in self.library_visible_names:
            return True
        return self.has_opaque_wildcard_import

    def _library_reference_verdict(self, name: str):
        """標準ライブラリの修飾名が実在するかを、同梱の索引で判定する。

        True（実在する）/ False（実在しない）/ None（判定できない）の3値。
        索引（library_index.json、scripts/build_library_index.py で生成）は
        パッケージごとに外から見える名前を持つので、パッケージ直下の名前までは
        確かめられる。`ISQ::Mass` は False（参照実装は
        `Couldn't resolve reference to Type 'ISQ::Mass'.`、2026-09-24実測）。
        索引で判定できない形（`ISQ::MassValue::num` のような型のメンバー、
        索引が complete と言えないパッケージ）は None で、呼び出し側は従来どおり
        検証不能として通す。

        先頭の名前がこのファイルにも定義されている場合（ユーザーが自分で
        `package Parts { ... }` を書いた等）は、そちらが優先されうるので None。
        """
        root = name.split("::")[0]
        if root not in STANDARD_LIBRARY_PACKAGES or self._find_element_in_symbols(root):
            return None
        return library_index.resolve_qualified_name(name)

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
            # ただし索引が「そのパッケージからは見えない」と言う名前は除く。
            # `ISQ::Real` は ISQ が `private import ScalarValues::Real;` しているだけで
            # 再公開しておらず、参照実装は解決できないとする（2026-09-24実測）。
            if (
                prefix.split("::")[-1] in STANDARD_LIBRARY_PACKAGES
                and self._library_reference_verdict(type_name) is not False
            ):
                return True

        for sym_name in self.symbols:
            if sym_name.endswith(f"::{type_name}") or sym_name == type_name:
                return True

        if "::" not in type_name and type_name.strip("'") in self.library_visible_names:
            return True

        # 解決できなかった参照のうち、「単一ファイルlintの範囲では検証不能」な
        # ものは存在しないと断定できないため有効扱いにする（誤検出の回避）。
        if self._is_unverifiable_reference(type_name):
            return True

        return False
    
    def _check_library_feature_references(self, node: Dict) -> None:
        """subsets/redefines が名指しする標準ライブラリの feature の実在を確かめる。

        `attribute m :> ISQ::massX;` / `attribute :>> ISQ::massY;` は、参照実装が
        `Couldn't resolve reference to Feature 'ISQ::massX'.` を返す（2026-09-24実測）。
        対象は標準ライブラリの修飾名で、索引が「実在しない」と言い切れるものだけ。
        修飾されていない参照先（継承した feature の redefines など）は、継承を
        たどらないと判定できないのでここでは見ない。
        """
        for entry in node.get("redefines") or []:
            target = entry.get("target") if isinstance(entry, dict) else None
            if not isinstance(target, str) or "::" not in target:
                continue
            if self._library_reference_verdict(target) is False:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Couldn't resolve reference to Feature '{target}'."
                    + self._library_suggestion_suffix(target),
                    node
                ))

    def _check_quantity_units(self, ast: Dict) -> None:
        """数量リテラルの単位の名前を解決する。

        `attribute mass : MassValue = 1.8 [kg];` は、SI を import していなければ
        参照実装が `Couldn't resolve reference to Element 'kg'.` を返す。
        `[SI::m/s]` も `s` が解決できずエラーになる（どちらも2026-09-24実測）。
        複合単位は、式の中の名前ごとに解決する。

        解決の判定は他の参照と同じで、ローカルの要素、import で見えている
        ライブラリの名前、索引で実在の分かる修飾名なら有効。中身の見えない
        import があるなど検証できない場合は通す。

        **非修飾名は、標準ライブラリに実在するが見えていない名前だけを報告する**
        （`kg`・`kW`・`min` のような import 漏れ。LLM が典型的に犯す誤り）。
        単位の角括弧には座標系などの feature も書け、継承した feature
        （SimpleQuadcopter.sysml の `(0, shape.width/2, 0)[source]`）は継承を
        たどらないと解決できない。どこにも無い名前を報告すると、730件で
        こうした形の誤検出が出た（2026-09-24実測）ため、見逃す側に倒している。
        ファイル内で宣言した名前・短い名前（`attribute <'A⋅h'> 'ampere hour' ...`）・
        再定義の対象（`:>> source = ecf;`）は宣言済みとして扱う。
        """
        declared = self._declared_names_anywhere(ast)

        def unit_names(expr, out):
            if isinstance(expr, dict):
                if expr.get("type") == "name_ref" and isinstance(expr.get("reference"), str):
                    out.append(expr["reference"])
                    return
                for value in expr.values():
                    if isinstance(value, (dict, list)):
                        unit_names(value, out)
            elif isinstance(expr, list):
                for item in expr:
                    unit_names(item, out)

        def walk(node, owner):
            if isinstance(node, dict):
                if node.get("type") == "quantity_literal":
                    names: List[str] = []
                    unit_names(node.get("unit"), names)
                    for name in names:
                        if not self._unit_name_resolves(name, declared):
                            self.issues.append(LintIssue(
                                SEVERITY_ERROR,
                                f"Couldn't resolve reference to Element '{name}'.",
                                owner,
                            ))
                if node.get("name") and node.get("type"):
                    owner = node
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value, owner)
            elif isinstance(node, list):
                for item in node:
                    walk(item, owner)

        walk(ast, None)

    def _unit_name_resolves(self, name: str, declared: Set[str]) -> bool:
        if "." in name:
            return True  # feature chain（`x.unit`）はここでは判定しない
        if "::" in name:
            verdict = self._library_reference_verdict(name)
            if verdict is not None:
                return verdict
            return self._type_reference_exists(name)
        bare = name.strip("'")
        if bare in declared or self._find_element_in_symbols(name) or name in self.types:
            return True
        if self._is_unverifiable_reference(name):
            return True
        # ライブラリにも無い名前は判定しない（docstring 参照）
        return not library_index.packages_defining(bare)

    @staticmethod
    def _declared_names_anywhere(ast: Dict) -> Set[str]:
        """ファイル内のどこかで宣言された名前・短い名前・再定義の対象（引用符は外す）。"""
        names: Set[str] = set()

        def add(value):
            if isinstance(value, str) and value:
                names.add(value.split("::")[-1].strip("'"))

        def walk(node):
            if isinstance(node, dict):
                if node.get("type"):
                    add(node.get("name"))
                    add(node.get("shortName"))
                    for entry in node.get("redefines") or []:
                        if isinstance(entry, dict):
                            add(entry.get("target"))
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(ast)
        return names

    def _add_library_import_hints(self) -> None:
        """import 漏れで解決できなかった非修飾名に、import のヒントを付ける。

        `attribute enabled : Boolean;`（import 無し）は、名前は実在するが見えて
        いないだけ。LLM の自己修正のため、どのパッケージにあるかを添える。
        対象は「存在しない型 'X'」「Couldn't resolve reference to ... 'X'.」の形で、
        X が非修飾名かつ標準ライブラリのどこかにある場合だけ。
        """
        import re

        pattern = re.compile(r"(?:存在しない型|Couldn't resolve reference to \w+) '([^':]+)'")
        for issue in self.issues:
            if issue.severity != SEVERITY_ERROR or "標準ライブラリの" in issue.message:
                continue
            m = pattern.search(issue.message)
            if not m:
                continue
            name = m.group(1)
            packages = library_index.packages_defining(name)
            if not packages:
                continue
            pkg = packages[0]
            issue.message += (
                f" 標準ライブラリの {pkg} にあります"
                f"（`private import {pkg}::*;` を追加するか、`{pkg}::{name}` と書く）。"
            )

    @staticmethod
    def _library_suggestion_suffix(name: str) -> str:
        """実在しないライブラリの名前に付けるヒント（LLMの自己修正のため）。"""
        root = name.split("::")[0]
        candidates = library_index.suggest(name)
        if candidates:
            return f" 標準ライブラリ '{root}' にこの名前はありません。候補: {', '.join(candidates)}"
        return f" 標準ライブラリ '{root}' にこの名前はありません。"

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
        
        # 標準ライブラリ配下の import は、索引で実在を確かめられる範囲だけ判定する
        # （`import ISQ::Mass;` / `import ISQ::Nope::*;`）。参照実装はそれぞれ
        # `Couldn't resolve reference to Membership 'ISQ::Mass'.` /
        # `... to Namespace 'ISQ::Nope'.` を返す（2026-09-24実測）。判定できない
        # もの（None）は、下の従来の分岐がライブラリ配下として通す。
        if self._library_reference_verdict(import_name) is False:
            kind = "Namespace" if is_wildcard else "Membership"
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Couldn't resolve reference to {kind} '{import_name}'."
                + self._library_suggestion_suffix(import_name),
                node
            ))
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
                # 標準ライブラリ内のenum defは、先行するワイルドカードimportで
                # スコープに入りうる（`import RiskMetadata::*;`のあとの
                # `import RiskLevelEnum::*;`）。名前を名指しで許容する。
                # 詳細はSTANDARD_LIBRARY_ENUM_NAMESのコメント参照。
                and segments[0] not in STANDARD_LIBRARY_ENUM_NAMES
                and not self._find_element_in_symbols(package_name)
                and not self._import_path_segments_resolve(package_name)
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
                and not self._import_target_is_type_name(import_name)
                and not self._import_path_segments_resolve(import_name)
            ):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"Import '{import_name}' が存在しない要素を参照しています",
                    node
                ))
    
    def _package_has_wildcard_import(self, package_name: str) -> bool:
        """`package_name`が指すローカルpackageがワイルドカードimportを持つか。

        持っている場合、そのpackageのメンバー集合はimport元にも依存するため、
        単一ファイルの平坦なシンボル表では「`Pkg::X`のXが無い」と断定できない。

        参照実装(jar 0.61.0)で実測した境界（2026-09-14、canaryを前後に挟む）:

        - `package P2a { public import P1::*; } ... part x : P2a::A;`
          （AはP1のメンバー）→ **クリーン**
        - 同じ形で `part x : P2a::NoSuch;` → エラー
        - **`package P2b { part def Z; } ... part x : P2b::A;`
          （P2bはimportを持たない）→ エラー**
        - `part x : P1::A;`（直接のメンバー）→ クリーン
        - 相互に`import`し合うpackage間の参照 → クリーン

        3番目があるので「修飾名なら一律に検証不能」とはしない。
        **ワイルドカードimportを実際に持つpackageに限る**ことで、importを持たない
        packageへの誤った修飾参照の検出は維持される。2番目（import経由の
        packageに存在しないメンバーを指す形）だけは取りこぼすが、これは
        「検出漏れは許容、偽陽性は出さない」方針による。
        """
        if not package_name:
            return False
        node = None
        for pkg_name, pkg_node in self.packages.items():
            if pkg_name == package_name or pkg_name.endswith(f"::{package_name}"):
                node = pkg_node
                break
        if not isinstance(node, dict):
            return False
        return any(
            isinstance(child, dict)
            and child.get("type") == "import"
            and child.get("wildcard")
            for child in node.get("children") or []
        )

    def _import_path_segments_resolve(self, path: str) -> bool:
        """多セグメントのimportパスについて、各セグメントが個別に解決できるか。

        `public import vehicle1_c1::interior::seatBelt;`（13b-Safety and Security
        Features Element Group.sysml）のように、**入れ子のusageを辿るimport**は
        平坦なシンボル表では引けない。`_collect_symbols`はpackage以外では
        namespaceを引き継がずに再帰するため、`interior`も`seatBelt`も
        `<package>::seatBelt`のように**package直下**へ登録される。したがって
        `::vehicle1_c1::interior::seatBelt`で終わる登録名は存在せず、末尾
        セグメントのフォールバックも多セグメント文字列との比較になるので必ず外れる
        （connectのエンド参照と同じ構造的な原因。
        `_end_reference_is_missing`のdocstring参照）。

        そこで**各セグメントが単独で解決できるか**だけを見る。多セグメントを
        丸ごと判定対象外にするより検出を残せる。

        参照実装(jar 0.61.0)で実測した境界（2026-09-14、canaryを前後に挟む）:

        - `v1::interior::seatBelt` / `v1::interior::*`（正当な入れ子）→ クリーン
        - 葉が無い（`v1::interior::noSuchLeaf`）→ エラー
        - 中間が無い（`v1::noSuchMid::seatBelt`）→ エラー
        - 根が無い（`noSuchRoot::interior::seatBelt`）→ エラー
        - **`b::x`（`x`は`a`の下にあり`b`の下には無い）→ エラー**

        最後の形だけはこの方式で取りこぼす（`b`も`x`も単独では解決できるため）。
        所有関係まで見るには入れ子を保持したシンボル表が要るので、**検出漏れを
        許容して偽陽性を出さない**側に倒している（他の意味ルールと同じ方針）。
        """
        if not path:
            return False
        segments = [seg for seg in path.split("::") if seg]
        if len(segments) < 2:
            # 単一セグメントは既存の判定で足りる（ここで通すと素通りになる）。
            return False
        return all(
            self._find_element_in_symbols(seg) or self._import_target_is_type_name(seg)
            for seg in segments
        )

    def _import_target_is_type_name(self, import_name: str) -> bool:
        """importの対象が`self.types`側にだけ登録されている名前かどうか。

        `self.types`にはtype_def/enum_def/item_def/attribute_defに加えて
        **alias**（`alias Car for Vehicle;`）が入る。aliasは`self.symbols`にも
        `self.element_refs`にも入らないため、`_find_element_in_symbols`では
        引けず、`import Definitions::Car;`が「存在しない要素」と誤検出されていた
        （2026-09-14。公式サンプル Import Tests/AliasImport.sysml、参照実装は
        クリーンと実測）。

        aliasを`self.element_refs`側へ登録する案は採らなかった。
        `_resolve_type_node`（definition_usage_rules.py）が`self.element_refs`も
        見るため、aliasノード（`type == "alias"`）が返るようになり、
        `_type_is_wrong_kind`が「interface definitionではない」と**新しい偽陽性**を
        出してしまう。importの存在判定だけを緩めるほうが影響範囲が小さい。

        照合は`_find_element_in_symbols`と同じ末尾一致方式（`self.types`には
        修飾名と短縮名の両方が入っているが、`Definitions::Car`のような中間の
        修飾形はどちらとも一致しないため）。

        **`self.opaque_import_names`は必ず除外する。** `self.types`には
        `lint()`が`self.types.update(self.opaque_import_names)`（linter.py:163）で
        **import由来の名前そのもの**を混ぜ込んでいる。除外しないと
        `import v1::interior::noSuchLeaf;`の`noSuchLeaf`が「型として存在する」と
        判定され、**importが自分自身を正当化する**（2026-09-14、この関数を入れた
        直後に実際に踏んだ）。`_find_element_in_symbols`に緩和を入れてはならない
        理由（linter.py:649-655のコメント、golden setのsysml-broken-04が守って
        いる回帰）と同じ循環であり、入口が違うだけである。
        """
        if not import_name:
            return False
        # import由来で持ち込まれた名前は「ローカルに宣言された型」ではないので使わない。
        declared_types = self.types - self.opaque_import_names
        if import_name in declared_types:
            return True
        return any(
            type_name.endswith(f"::{import_name}") for type_name in declared_types
        )

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
    
    
    

    

    
    
    
    
    
