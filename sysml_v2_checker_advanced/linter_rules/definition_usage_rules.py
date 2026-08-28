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

    def _check_subsetting_uniqueness_conformance(self, node: Dict) -> None:
        """
        Subsetting/redefining feature cannot be nonunique if subsetted/redefined
        feature is unique (KerML 8.4 Uniqueness Conformance)

        参照実装（OMG SysML v2 Pilot Implementation）との比較評価で発見した
        偽陰性（Subsetting_UniquenessConformance_Invalid.sysml参照）。
        `part rearWheel_1: Wheel[2] nonunique subsets rearWheel;`のように、
        subsets/redefines対象がシブリングスコープ（同じ親のchildren内）に
        いる場合のみ判定する（継承経由の解決は行わない。型解決なしで安全に
        判定できる範囲に限定し、偽陽性リスクを抑えるため）。`node`は任意の
        親ノード（`_check_rules`からchildrenを持つ全ノードに対して呼ばれる）。
        """
        children = node.get("children")
        if not isinstance(children, list):
            return
        sibling_by_name = {
            c.get("name"): c
            for c in children
            if isinstance(c, dict) and c.get("name")
        }
        for child in children:
            if not isinstance(child, dict):
                continue
            multiplicity = child.get("multiplicity")
            if not isinstance(multiplicity, dict) or multiplicity.get("is_unique") is not False:
                continue
            redefines = child.get("redefines")
            if not isinstance(redefines, list):
                continue
            for redefine in redefines:
                if not isinstance(redefine, dict) or redefine.get("kind") not in ("subsets", "redefines"):
                    continue
                target = sibling_by_name.get(redefine.get("target"))
                if target is None:
                    continue
                target_multiplicity = target.get("multiplicity")
                target_is_unique = (
                    target_multiplicity.get("is_unique", True)
                    if isinstance(target_multiplicity, dict)
                    else True
                )
                if target_is_unique:
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        "Subsetting/redefining feature cannot be nonunique if subsetted/redefined feature is unique",
                        child
                    ))

    def _resolve_type_node(self, type_name: str):
        """`type_name`が指す型定義ノードをself.symbols/self.element_refsから
        解決する（末尾セグメント一致のフォールバック込み。_find_type_in_symbols/
        _find_element_in_symbolsと同じ検索方針だが、真偽値ではなくノード自体を
        返す点が異なる）。`vehicle_1a :> vehicle_1 { attribute cylinders :>>
        vehicle_1::cylinders = 6; }`のように、redefine対象の修飾プレフィックスが
        def自体ではなく別のusage/instance（part_instance等）を指すケースが
        あるため、self.element_refsも検索対象に含める（Vehicle.sysml参照）。"""
        if not type_name:
            return None
        node = self.symbols.get(type_name)
        if node is not None:
            return node
        for sym_name, sym_node in self.symbols.items():
            if sym_name == type_name or sym_name.endswith(f"::{type_name}"):
                return sym_node
        node = self.element_refs.get(type_name)
        if node is not None:
            return node
        for sym_name, sym_node in self.element_refs.items():
            if sym_name == type_name or sym_name.endswith(f"::{type_name}"):
                return sym_node
        return None

    @staticmethod
    def _find_child_by_name(type_node, name: str):
        if not isinstance(type_node, dict) or not name:
            return None
        for child in type_node.get("children", []) or []:
            if isinstance(child, dict) and child.get("name") == name:
                return child
        return None

    def _resolve_redefine_target_node(self, target: str, fallback_type_name):
        """redefines/value_bindingの`target`（`"Vehicle::cylinders"`のような
        修飾名、または`fallback_type_name`（囲むusageの型名）に対する裸の
        フィーチャ名）が指す、ローカルに解決可能な基底フィーチャのノードを
        返す（解決できなければNone）。"""
        if not target:
            return None
        if "::" in target:
            prefix, feature_name = target.rsplit("::", 1)
        else:
            prefix, feature_name = fallback_type_name, target
        if not prefix:
            return None
        return self._find_child_by_name(self._resolve_type_node(prefix), feature_name)

    def _check_binding_feature_override(self, node: Dict) -> None:
        """
        Cannot override a binding feature value

        参照実装比較評価で発見した偽陰性（Vehicle.sysml/toaster-system.sysml
        参照）。あるフィーチャが既に値束縛（`= expr`）を持つ場合、それを
        redefine（明示的な`:>>`/`redefines`、`:>> name = value;`という
        ターゲット省略の値束縛ショートハンド形、または型付きusage本体内で
        継承フィーチャと同名のフィーチャを宣言する暗黙のredefine（KerMLの
        仕様上、同名なら自動的に継承フィーチャをredefineしたものとみなされる。
        `calc ms: MassSum { return totalMass = ...; }`がMassSum::totalMassを
        暗黙にredefineする例、CalculationExample.sysml参照）のいずれかで
        redefineしつつ、redefine側も自身の値束縛を新たに与えるのは不正
        （基底の値束縛をそのまま継承する以外の方法がない）。`node`は任意の
        親ノード（`_check_rules`からchildrenを持つ全ノードに対して呼ばれる）。
        """
        children = node.get("children")
        if not isinstance(children, list):
            return
        node_type_name = node.get("type_name")
        for child in children:
            if not isinstance(child, dict) or child.get("value") is None:
                continue

            if child.get("type") == "value_binding":
                if child.get("kind") != "redefines":
                    continue
                base = self._resolve_redefine_target_node(child.get("target", ""), node_type_name)
                if base is not None and base.get("value") is not None:
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR, "Cannot override a binding feature value", child
                    ))
                continue

            base = None
            redefines = child.get("redefines")
            if isinstance(redefines, list):
                for redefine in redefines:
                    if isinstance(redefine, dict) and redefine.get("kind") == "redefines":
                        base = self._resolve_redefine_target_node(redefine.get("target", ""), None)
                        if base is not None:
                            break
            if base is None and node_type_name and child.get("name"):
                base = self._find_child_by_name(self._resolve_type_node(node_type_name), child.get("name"))

            if base is not None and base is not child and base.get("value") is not None:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR, "Cannot override a binding feature value", child
                ))

    def _is_feature_only_name(self, name: str) -> bool:
        """`name`が型/パッケージとしては解決できず、feature/instance
        （self.element_refs）としてのみ解決できるかを判定する
        （_find_element_in_symbolsと同じ末尾一致方式）。型解決を優先する
        既存の設計方針に合わせ、型/パッケージとして解決できる場合は
        featureとはみなさない（同名衝突時に誤検出しないため）。"""
        if not name:
            return False
        if name in self.types:
            return False
        for pkg_name in self.packages:
            if pkg_name.endswith(f"::{name}") or pkg_name == name:
                return False
        for sym_name in self.element_refs:
            if sym_name.endswith(f"::{name}") or sym_name == name:
                return True
        return False

    def _check_accessible_feature_paths(self, ast: Dict) -> None:
        """
        Must be an accessible feature (use dot notation for nesting)
        （FeaturePath_Invalid.sysml/Connector_Invalid.sysml/
        BindingConnector_redefine.sysml参照）

        KerMLでは`::`は型/パッケージ限定の名前空間解決専用で、feature
        （usage）へのネストしたアクセスには`.`を使うべき、という制約。
        重要な点として、この制約は「パスの先頭セグメントが型かfeatureか」
        ではなく、「`::`の直後のセグメントがそのスコープのfeatureか型か」
        で決まる（`A::x`は`A`が型`part def A`であっても、`x`が
        `part x;`というfeatureであるため不正——Connector_Invalid.sysml
        で確認。逆に先頭で単純にfeature名を使うだけなら問題ない）。
        `children`等の決まったキーだけを辿る`_check_rules`の再帰では
        `expression`（`part g = f::a;`のname_ref）や`from_end`/`to_end`
        （`connect ... to c::aa;`のconnector_end）等のネストしたreference
        フィールドまで届かないため、AST全体を独自に走査する
        （2026-08-28、参照実装比較レポートで発見した偽陰性）。

        `reference`文字列自体は区切り文字を常に`::`へ正規化済みのため
        （`_namespace_path_text`）、区切り文字ごとの`.`/`::`の別を
        `segments`（`[(セグメント名, 直前の区切り文字), ...]`、
        antlr_transformer.py側で付与）から読む。

        730件回帰チェックで2種類の偽陽性を発見し、以下の除外条件を追加した:
        (1) 自己参照（`action dyn2 { calc acc { in dt = dyn2::dt; } }`、
        Dynamics.sysml/Action Decomposition.sysml等）— 自分自身を囲む
        スコープの名前を`::`で参照する形は参照実装でも許容されている
        （`_iter_reference_bearing_dicts`が辿った祖先ノードの名前と
        先頭セグメントが一致する場合は除外）。
        (2) `meta`式のbase（`system_of_systems::locclouds meta
        SysML::PartUsage;`、AHFProfileLib.sysml）— メタデータ注釈内で
        要素を記法上参照する慣用句であり、通常のfeature chainアクセスとは
        異なる規則で解決されるため対象外とする。

        `::`直後のセグメント名が確実にfeature/instanceとして解決でき、
        かつ型/パッケージとしては解決できない場合のみ判定する（型解決
        なしで安全に判定できる範囲に限定し、偽陽性リスクを抑えるため）。
        """
        for candidate, ancestor_names in self._iter_reference_bearing_dicts(ast):
            segments = candidate.get("segments")
            if not isinstance(segments, list) or len(segments) < 2:
                continue
            root_name = segments[0][0]
            if root_name in ancestor_names:
                continue
            reference = candidate.get("reference")
            # `ISQ::torque`（EVSample.sysml）のように、ルートが標準ライブラリ
            # パッケージや中身の見えないワイルドカードimport由来の可能性が
            # ある「単一ファイルlintでは検証不能」な参照は判定対象外にする
            # （`_find_type_in_symbols`と同じ既存の安全側の設計方針。
            # 2026-08-28、730件回帰チェックで発見）。
            if isinstance(reference, str) and self._is_unverifiable_reference(reference):
                continue
            for seg_name, separator in segments[1:]:
                if separator != "::":
                    continue
                if self._is_feature_only_name(seg_name):
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        "Must be an accessible feature (use dot notation for nesting)",
                        candidate
                    ))
                    break

    def _inheritance_base_names(self, type_name: str, _seen: set | None = None) -> set:
        """`type_name`の基底型を`self.symbols`経由でたどり、継承チェーン
        全体の型名集合を返す（循環防止に`_seen`で訪問済み集合を保持する）。
        accessible feature path制約の「サブタイプ本体内から基底型名で
        `::`参照するのは許容される」という除外判定にのみ使う軽量ヘルパー
        （2026-08-28、730件回帰チェックで発見）。"""
        if _seen is None:
            _seen = set()
        if type_name in _seen:
            return set()
        _seen.add(type_name)
        node = self.symbols.get(type_name)
        if node is None:
            for sym_name, sym_node in self.symbols.items():
                if sym_name.endswith(f"::{type_name}") or sym_name == type_name:
                    node = sym_node
                    break
        if node is None:
            return set()
        inheritance = node.get("inheritance")
        if not isinstance(inheritance, dict):
            return set()
        bases = inheritance.get("bases") or ([inheritance["base"]] if inheritance.get("base") else [])
        result = set(bases)
        for base in bases:
            result |= self._inheritance_base_names(base, _seen)
        return result

    _SCOPE_CONTAINMENT_KEYS = ("children", "params", "attributes", "exposes")

    def _iter_reference_bearing_dicts(self, node, ancestor_names: frozenset = frozenset()):
        """ASTを`children`等の決まったキーに限らず全フィールドにわたって
        再帰し、`"reference"`キーを持つ辞書（connector_end/name_ref等）を
        `(辞書, 祖先スコープ名の集合)`のペアで列挙する。祖先スコープ名は
        `_SCOPE_CONTAINMENT_KEYS`（`_check_rules`の再帰と同じキー集合）を
        辿って入れ子になった際に、その親ノード自身の`name`を積み上げた
        もの（自己参照の除外判定に使う）。`meta`式のbaseは通常の
        feature chainアクセスとは異なる記法上の慣用句のため、
        その内側は列挙対象から除外する。"""
        if isinstance(node, dict):
            if "reference" in node:
                yield node, ancestor_names
            if node.get("type") == "meta_expr":
                for key, value in node.items():
                    if key == "base":
                        continue
                    yield from self._iter_reference_bearing_dicts(value, ancestor_names)
                return
            own_name = node.get("name")
            child_ancestor_names = (
                ancestor_names | {own_name} if isinstance(own_name, str) and own_name else ancestor_names
            )
            # `item def RightTriangle :> Triangle { ... Triangle::width ... }`
            # （ShapeItems.sysml）のように、サブタイプの本体内から基底型の名前で
            # `::`参照するのも許容されている（継承済みfeatureは実質的に
            # 「アクセス可能」であるため、レキシカルな自己参照と同様に扱う。
            # 2026-08-28、730件回帰チェックで発見）。
            if isinstance(own_name, str) and own_name and isinstance(node.get("inheritance"), dict):
                child_ancestor_names = child_ancestor_names | self._inheritance_base_names(own_name)
            # `calc :>> getNextState: GetNextState { ... GetNextState::stateSpace
            # ... }`（StateSpaceRepresentation.sysml）のように、usageの
            # 「自分自身の型名」（`type_name`）による`::`自己参照も同様に
            # 許容されている（型名もその継承チェーンも含める。
            # 2026-08-28、730件回帰チェックで発見）。
            own_type_name = node.get("type_name")
            if isinstance(own_type_name, str) and own_type_name:
                child_ancestor_names = child_ancestor_names | {own_type_name} | self._inheritance_base_names(
                    own_type_name
                )
            for key, value in node.items():
                next_ancestor_names = child_ancestor_names if key in self._SCOPE_CONTAINMENT_KEYS else ancestor_names
                yield from self._iter_reference_bearing_dicts(value, next_ancestor_names)
        elif isinstance(node, list):
            for item in node:
                yield from self._iter_reference_bearing_dicts(item, ancestor_names)

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
