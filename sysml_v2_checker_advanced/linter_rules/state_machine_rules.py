"""state_machine_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

from typing import Dict

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue


class StateMachineRulesMixin:
    def _check_state_def(self, node: Dict, namespace: str) -> None:
        """
        ステート定義のチェック
        
        型参照と遷移を検証します。
        
        Args:
            node: state_defノード
            namespace: 現在の名前空間
        """
        name = node.get("name")
        
        # 継承チェック（型参照）
        if "inheritance" in node and node["inheritance"]:
            base = node["inheritance"].get("base")
            if base and not self._find_type_in_symbols(base):
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"State '{name}' が存在しない型 '{base}' を参照しています",
                    node
                ))
    def _find_state_in_symbols(self, state_name: str) -> bool:
        """
        シンボルテーブルでtransitionの参照先（ステート等）を検索

        `self.symbols`（型解決用）だけでなく`self.element_refs`（要素参照用）
        も走査する。`action_usage`のようなoccurrence系の参照先は
        `self.element_refs`に登録されるため、両方を見ないと誤って
        「存在しません」と検出してしまう。

        Args:
            state_name: 検索する参照先の名前

        Returns:
            参照先が見つかった場合True
        """
        for registry in (self.symbols, self.element_refs):
            for sym_name, sym_node in registry.items():
                if (sym_node.get("type") in self.TRANSITION_ENDPOINT_NODE_TYPES and
                    (sym_name.endswith(f"::{state_name}") or
                     sym_name == state_name or
                     sym_name.split("::")[-1] == state_name)):
                    return True
        return False
    def _check_transition(self, node: Dict, namespace: str) -> None:
        """
        遷移のチェック
        
        ソース/ターゲットステートの存在を検証します。
        
        Args:
            node: transitionノード
            namespace: 現在の名前空間
        """
        source = node.get("source")
        target = node.get("target")
        
        if source and not self._find_state_in_symbols(source):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Transition のソースステート '{source}' が存在しません",
                node
            ))
        
        if target and not self._find_state_in_symbols(target):
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Transition のターゲットステート '{target}' が存在しません",
                node
            ))
    def _check_state_machine_consistency(self) -> None:
        """
        ステートマシン関連の整合性チェック
        
        初期状態が1つだけか、遷移の整合性などをチェックします。
        """
        # 初期状態の一意性チェック
        if len(self.initial_nodes) > 1:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"初期状態が{len(self.initial_nodes)}個定義されています。初期状態は1つだけである必要があります。",
                self.initial_nodes[1] if len(self.initial_nodes) > 1 else None
            ))
    def _check_state_advanced_rules(self) -> None:
        """
        ステート高度ルールチェック (SysML v2 8.2.2.18)
        
        - StateDefBody の isParallel フラグチェック
        - Entry/Do/Exit Actions の kind 検証
        - Transition の複雑な構造チェック
        """
        for sym_name, sym_node in self.symbols.items():
            if sym_node.get("type") == "state_def":
                self._check_state_def_body_structure(sym_node, sym_name)
                self._check_state_actions(sym_node, sym_name)
            if sym_node.get("type") in ("state_def", "state_usage"):
                self._check_state_action_duplicates(sym_node, sym_name)

        # 遷移の詳細チェック
        for transition in self.transitions:
            self._check_transition_advanced_structure(transition)
    def _check_state_def_body_structure(self, state_node: Dict, state_name: str) -> None:
        """
        StateDefBody の構造チェック (8.2.2.18)
        
        Args:
            state_node: ステートノード
            state_name: ステート名
        """
        is_parallel = state_node.get("isParallel", False)
        children = state_node.get("children", [])
        
        # isParallel フラグの整合性チェック
        if is_parallel:
            # パラレルステートは複数の子ステートを持つべき
            child_states = [child for child in children if isinstance(child, dict) and child.get("type") == "state_def"]
            if len(child_states) < 2:
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.18] パラレルステート '{state_name}' に子ステートが {len(child_states)} 個しかありません（2個以上推奨）",
                    state_node
                ))
        
        # EntryTransitionMember の構造チェック
        entry_transitions = [child for child in children if isinstance(child, dict) and child.get("type") == "entry_transition"]
        if len(entry_transitions) > 1:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.18] ステート '{state_name}' に複数のエントリ遷移が定義されています",
                state_node
            ))
    def _check_state_actions(self, state_node: Dict, state_name: str) -> None:
        """
        Entry/Do/Exit Actions の kind 検証 (8.2.2.18)
        
        Args:
            state_node: ステートノード
            state_name: ステート名
        """
        children = state_node.get("children", [])
        
        for child in children:
            if isinstance(child, dict):
                child_type = child.get("type")
                kind = child.get("kind")
                
                # EntryActionMember の kind チェック
                if child_type == "entry_action":
                    if kind != "entry":
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.18] EntryAction で kind = '{kind}' が設定されていますが、'entry' である必要があります",
                            child
                        ))
                
                # DoActionMember の kind チェック
                elif child_type == "do_action":
                    if kind != "do":
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.18] DoAction で kind = '{kind}' が設定されていますが、'do' である必要があります",
                            child
                        ))
                
                # ExitActionMember の kind チェック
                elif child_type == "exit_action":
                    if kind != "exit":
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.18] ExitAction で kind = '{kind}' が設定されていますが、'exit' である必要があります",
                            child
                        ))
    def _check_state_action_duplicates(self, state_node: Dict, state_name: str) -> None:
        """
        Entry/Do/Exit Actions はそれぞれ最大1つまで (8.2.2.18)

        参照実装（OMG SysML v2 Pilot Implementation）との比較評価
        （2026-08-28、eval/SYSML_LINTER_REFERENCE_COMPARISON_REPORT.md §4.1）で
        発見した偽陰性。state_def/state_usageの両方に適用する
        （StateSubactions_invalid.sysmlが両方でテストしているため）。

        Args:
            state_node: ステートノード（state_defまたはstate_usage）
            state_name: ステート名
        """
        labels = {"entry_action": "entry", "do_action": "do", "exit_action": "exit"}
        counts: Dict[str, int] = {}
        for child in state_node.get("children", []):
            if not isinstance(child, dict):
                continue
            child_type = child.get("type")
            if child_type not in labels:
                continue
            counts[child_type] = counts.get(child_type, 0) + 1
            if counts[child_type] > 1:
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.18] ステート '{state_name}' に{labels[child_type]}アクションが複数定義されています(1つのみ許可)",
                    child
                ))
    def _check_transition_advanced_structure(self, transition: Dict) -> None:
        """
        Transition の複雑な構造チェック (8.2.2.18)
        
        Args:
            transition: 遷移ノード
        """
        # TriggerActionMember の kind チェック
        trigger = transition.get("trigger")
        if trigger and isinstance(trigger, dict):
            trigger_kind = trigger.get("kind")
            if trigger_kind != "trigger":
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.18] TriggerAction で kind = '{trigger_kind}' が設定されていますが、'trigger' である必要があります",
                    trigger
                ))
        
        # GuardExpressionMember の kind チェック
        guard = transition.get("guard")
        if guard and isinstance(guard, dict):
            guard_kind = guard.get("kind")
            if guard_kind != "guard":
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.18] GuardExpression で kind = '{guard_kind}' が設定されていますが、'guard' である必要があります",
                    guard
                ))
        
        # EffectBehaviorMember の kind チェック
        effect = transition.get("effect")
        if effect and isinstance(effect, dict):
            effect_kind = effect.get("kind")
            if effect_kind != "effect":
                self.issues.append(LintIssue(
                    SEVERITY_ERROR,
                    f"[8.2.2.18] EffectBehavior で kind = '{effect_kind}' が設定されていますが、'effect' である必要があります",
                    effect
                ))
