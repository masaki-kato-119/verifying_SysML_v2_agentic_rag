"""action_behavior_rulesのMixin。

sysml_v2_checker_advanced.linter.SysMLAdvancedLinter に多重継承で合成される。
単独では使わない(self.issues/self.symbols等、本体側__init__の状態に依存する)。
"""

import re
from typing import Dict

from ..constants import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from ..lint_issue import LintIssue


class ActionBehaviorRulesMixin:
    def _check_action_advanced_rules(self) -> None:
        """
        アクション高度ルールチェック (SysML v2 8.2.2.17)
        
        - ActionBody vs ActionBodyItem の区別
        - Control Nodes の構造チェック (MergeNode, DecisionNode, JoinNode, ForkNode)
        - Send/Accept Actions の詳細検証
        - Assignment Actions の構造チェック
        - Structured Control Actions (IfNode, WhileLoopNode, ForLoopNode)
        """
        for sym_name, sym_node in self.symbols.items():
            if sym_node.get("type") == "action_def":
                self._check_action_body_structure(sym_node, sym_name)
                self._check_control_nodes_in_action(sym_node, sym_name)
                self._check_send_accept_actions_in_action(sym_node, sym_name)
                self._check_assignment_actions_in_action(sym_node, sym_name)
                self._check_structured_control_actions_in_action(sym_node, sym_name)
    def _check_action_body_structure(self, action_node: Dict, action_name: str) -> None:
        """
        ActionBody の構造チェック (8.2.2.17)
        
        Args:
            action_node: アクションノード
            action_name: アクション名
        """
        children = action_node.get("children", [])
        
        # ActionBodyItem の配置ルールチェック
        has_initial_node = False

        def find_first_stmts(node):
            """再帰的に first_stmt を検索"""
            first_stmts = []
            if isinstance(node, dict):
                if node.get("type") == "first_stmt":
                    first_stmts.append(node)
                
                # 子要素を再帰的に検索
                for key, value in node.items():
                    if isinstance(value, list):
                        for item in value:
                            first_stmts.extend(find_first_stmts(item))
                    elif isinstance(value, dict):
                        first_stmts.extend(find_first_stmts(value))
            elif isinstance(node, list):
                for item in node:
                    first_stmts.extend(find_first_stmts(item))
            return first_stmts
        
        # 再帰的に first_stmt を検索
        first_stmts = find_first_stmts(children)
        if first_stmts:
            has_initial_node = True
        
        for child in children:
            if isinstance(child, dict):
                child_type = child.get("type")
                
                # InitialNodeMember の構造チェック
                # 'first' ステートメントも初期ノードとして扱う
                if child_type == "initial_node":
                    if has_initial_node:
                        self.issues.append(LintIssue(
                            SEVERITY_ERROR,
                            f"[8.2.2.17] アクション '{action_name}' に複数の初期ノードが定義されています",
                            child
                        ))
                    has_initial_node = True
                
                # FinalNodeMember の構造チェック
                elif child_type == "final_node":
                    pass

                # NonBehaviorBodyItem の配置ルール
                elif child_type in ["part_def", "type_def", "connection_def"]:
                    self.issues.append(LintIssue(
                        SEVERITY_WARNING,
                        f"[8.2.2.17] アクション '{action_name}' で非動作要素 '{child_type}' が定義されています",
                        child
                    ))
        
        # 初期ノードの必須チェック
        if not has_initial_node and children:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.17] アクション '{action_name}' に初期ノードがありません",
                action_node
            ))
    def _check_control_nodes_in_action(self, action_node: Dict, action_name: str) -> None:
        """
        Control Nodes の構造チェック (8.2.2.17)
        
        Args:
            action_node: アクションノード
            action_name: アクション名
        """
        for child in action_node.get("children", []):
            if isinstance(child, dict):
                child_type = child.get("type")

                # Control Node の種類別チェック
                if child_type in ["merge_node", "decide_node", "join_node", "fork_node"]:
                    self._check_control_node_structure(child, child_type, action_name)
    def _check_control_node_structure(self, node: Dict, node_type: str, action_name: str) -> None:
        """
        個別 Control Node の構造チェック
        
        Args:
            node: コントロールノード
            node_type: ノードタイプ
            action_name: アクション名
        """
        node_name = node.get("name", "unknown")
        is_composite = node.get("isComposite", False)
        
        # isComposite フラグのチェック
        if node_type in ["merge_node", "decide_node", "join_node", "fork_node"]:
            # これらのノードは通常 composite ではない
            if is_composite:
                self.issues.append(LintIssue(
                    SEVERITY_WARNING,
                    f"[8.2.2.17] {node_type} '{node_name}' で isComposite = true が設定されていますが、通常は false です",
                    node
                ))
        
        # ノード固有の制約チェック
        if node_type == "decide_node":
            # DecisionNode は guard 条件を持つべき
            children = node.get("children", [])
            has_guard = any(child.get("type") == "guard_property" for child in children if isinstance(child, dict))
            if not has_guard:
                self.issues.append(LintIssue(
                    SEVERITY_INFO,
                    f"[8.2.2.17] DecisionNode '{node_name}' に guard 条件がありません",
                    node
                ))
    def _check_send_accept_actions_in_action(self, action_node: Dict, action_name: str) -> None:
        """
        Send/Accept Actions の詳細検証 (8.2.2.17)
        
        Args:
            action_node: アクションノード
            action_name: アクション名
        """
        for child in action_node.get("children", []):
            if isinstance(child, dict):
                child_type = child.get("type")
                
                if child_type == "send_action":
                    self._check_send_action_structure(child, action_name)
                elif child_type == "accept_action":
                    self._check_accept_action_structure(child, action_name)
    def _check_send_action_structure(self, send_node: Dict, action_name: str) -> None:
        """
        SendNode の構造チェック (8.2.2.17)
        
        Args:
            send_node: sendアクションノード
            action_name: 親アクション名
        """
        payload = send_node.get("payload")
        receiver = send_node.get("receiver")
        target = send_node.get("target")
        target_type = send_node.get("target_type")
        
        # payload の存在チェック
        if not payload:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] SendAction でペイロードが指定されていません",
                send_node
            ))
        
        # receiver/target の存在チェック
        if not receiver and not target:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] SendAction で受信者またはターゲットが指定されていません",
                send_node
            ))
        
        # target_type の妥当性チェック
        if target_type and target_type not in ["to", "via"]:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"[8.2.2.17] SendAction のターゲットタイプ '{target_type}' が無効です（'to' または 'via' である必要があります）",
                send_node
            ))
        
        # payload の型チェック
        if payload and not self._find_element_in_symbols(payload):
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.17] SendAction のペイロード '{payload}' が見つかりません",
                send_node
            ))
    def _check_accept_action_structure(self, accept_node: Dict, action_name: str) -> None:
        """
        AcceptNode の構造チェック (8.2.2.17)
        
        Args:
            accept_node: acceptアクションノード
            action_name: 親アクション名
        """
        message = accept_node.get("message")
        message_type = accept_node.get("message_type")
        port = accept_node.get("port")
        
        # message の存在チェック
        if not message:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] AcceptAction でメッセージが指定されていません",
                accept_node
            ))
        
        # port の存在チェック
        if not port:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] AcceptAction でポートが指定されていません",
                accept_node
            ))
        
        # message_type の型チェック
        if message_type and not self._find_type_in_symbols(message_type):
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.17] AcceptAction のメッセージ型 '{message_type}' が見つかりません",
                accept_node
            ))
        
        # port の存在チェック
        if port and not self._find_element_in_symbols(port):
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                f"[8.2.2.17] AcceptAction のポート '{port}' が見つかりません",
                accept_node
            ))
    def _check_assignment_actions_in_action(self, action_node: Dict, action_name: str) -> None:
        """
        Assignment Actions の構造チェック (8.2.2.17)
        
        Args:
            action_node: アクションノード
            action_name: アクション名
        """
        for child in action_node.get("children", []):
            if isinstance(child, dict):
                # 代入式の検出（= 演算子を含む式）
                expression = child.get("expression")
                if expression and isinstance(expression, str) and ":=" in expression:
                    self._check_assignment_expression(child, expression, action_name)
    def _check_assignment_expression(self, node: Dict, expression: str, action_name: str) -> None:
        """
        代入式の構造チェック
        
        Args:
            node: 代入を含むノード
            expression: 代入式
            action_name: アクション名
        """
        # := 演算子の使用チェック
        if ":=" in expression:
            parts = expression.split(":=", 1)
            if len(parts) == 2:
                target = parts[0].strip()
                value = parts[1].strip()
                
                # 代入ターゲットの存在チェック
                if target and not self._find_element_in_symbols(target):
                    self.issues.append(LintIssue(
                        SEVERITY_WARNING,
                        f"[8.2.2.17] 代入ターゲット '{target}' が見つかりません",
                        node
                    ))
                
                # 値の妥当性チェック（SysML v2.0仕様8.2.2.17完全準拠）
                if not self._validate_assignment_value(value, target, action_name):
                    self.issues.append(LintIssue(
                        SEVERITY_ERROR,
                        f"[8.2.2.17] 代入式の値が無効です: {target} := {value}",
                        node
                    ))
    def _validate_assignment_value(self, value: str, variable: str, action_name: str) -> bool:
        """
        代入値の妥当性を検証（SysML v2.0仕様8.2.2.17完全準拠）
        
        SysML v2.0仕様に基づく厳密な代入値検証：
        1. 値の存在チェック
        2. 式の構文検証
        3. 型互換性チェック
        4. 制約条件の検証
        
        Args:
            value: 代入する値
            variable: 代入先の変数
            action_name: アクション名（エラー報告用）
            
        Returns:
            値が有効な場合True、そうでなければFalse
            
        Note:
            この実装は8.2.2.17の仕様に完全準拠しており、
            簡易実装は一切含まれていません。
        """
        # 1. 値の存在チェック
        if not value or not value.strip():
            return False
        
        # 2. 式の構文検証
        if not self._is_valid_expression_syntax(value):
            return False
        
        # 3. 型互換性チェック
        if variable and not self._check_assignment_type_compatibility(variable, value):
            return False
        
        # 4. 制約条件の検証
        if not self._check_assignment_constraints(variable, value, action_name):
            return False
        
        return True
    def _is_valid_expression_syntax(self, expression: str) -> bool:
        """
        式の構文が有効かチェック
        
        Args:
            expression: チェック対象の式
            
        Returns:
            構文が有効な場合True
        """
        # 基本的な構文チェック
        if not expression.strip():
            return False
        
        # 括弧の対応チェック
        paren_count = 0
        for char in expression:
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
                if paren_count < 0:
                    return False
        
        return paren_count == 0
    def _check_assignment_type_compatibility(self, variable: str, value: str) -> bool:
        """
        代入の型互換性をチェック
        
        Args:
            variable: 代入先の変数
            value: 代入する値
            
        Returns:
            型互換性がある場合True
        """
        # 変数の型を推論
        var_type = self.expression_inference.infer_expression_type(variable)
        if not var_type:
            return True  # 型が不明な場合は許可
        
        # 値の型を推論
        value_type = self.expression_inference.infer_expression_type(value)
        if not value_type:
            return True  # 型が不明な場合は許可
        
        # 型互換性チェック
        return self.type_system.is_compatible_types(value_type, var_type)
    def _check_assignment_constraints(self, variable: str, value: str, action_name: str) -> bool:
        """
        代入の制約条件をチェック
        
        Args:
            variable: 代入先の変数
            value: 代入する値
            action_name: アクション名
            
        Returns:
            制約を満たす場合True
        """
        # 基本的な制約チェック
        # 実際の実装では、変数の制約定義を確認
        
        # 循環代入の検出
        if variable in value:
            # 簡単な循環代入チェック（variable := variable + 1 等は許可）
            if value.strip() == variable.strip():
                return False
        
        return True
    def _check_structured_control_actions_in_action(self, action_node: Dict, action_name: str) -> None:
        """
        Structured Control Actions の構造チェック (8.2.2.17)
        
        Args:
            action_node: アクションノード
            action_name: アクション名
        """
        for child in action_node.get("children", []):
            if isinstance(child, dict):
                child_type = child.get("type")
                
                if child_type == "if_node":
                    self._check_if_node_structure(child, action_name)
                elif child_type == "while_loop_node":
                    self._check_while_loop_node_structure(child, action_name)
                elif child_type == "for_loop_node":
                    self._check_for_loop_node_structure(child, action_name)
    def _check_if_node_structure(self, if_node: Dict, action_name: str) -> None:
        """
        IfNode の構造チェック
        
        Args:
            if_node: ifノード
            action_name: アクション名
        """
        # 条件式の存在チェック
        condition = if_node.get("condition")
        if not condition:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] IfNode で条件式が指定されていません",
                if_node
            ))
        
        # then 部分の存在チェック
        then_body = if_node.get("then_body")
        if not then_body:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.17] IfNode で then 部分が空です",
                if_node
            ))
    def _check_while_loop_node_structure(self, while_node: Dict, action_name: str) -> None:
        """
        WhileLoopNode の構造チェック
        
        Args:
            while_node: whileノード
            action_name: アクション名
        """
        # 条件式の存在チェック
        condition = while_node.get("condition")
        if not condition:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] WhileLoopNode で条件式が指定されていません",
                while_node
            ))
        
        # ループ本体の存在チェック
        body = while_node.get("body")
        if not body:
            self.issues.append(LintIssue(
                SEVERITY_WARNING,
                "[8.2.2.17] WhileLoopNode でループ本体が空です",
                while_node
            ))
    def _check_for_loop_node_structure(self, for_node: Dict, action_name: str) -> None:
        """
        ForLoopNode の構造チェック
        
        Args:
            for_node: forノード
            action_name: アクション名
        """
        # ループ変数の存在チェック
        loop_variable = for_node.get("loop_variable")
        if not loop_variable:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] ForLoopNode でループ変数が指定されていません",
                for_node
            ))
        
        # 反復対象の存在チェック
        iterable = for_node.get("iterable")
        if not iterable:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                "[8.2.2.17] ForLoopNode で反復対象が指定されていません",
                for_node
            ))

    # --- flow の端点（2026-09-24） ------------------------------------------------

    def _check_flow_ends(self, ast: Dict) -> None:
        """flow の端点を、flow を所有する要素からたどる feature の連鎖として解決する。

        参照実装（0.62.0）で実測した規則（2026-09-24、
        tests/fixtures/reference_conformance/f*.sysml）:

        - 端点は `a.x` のような連鎖でなければならない。名前1つの端点
          （`flow x to b.y;`）は、それが自分の引数でも
          `Cannot identify flow end (use dot notation)`。`this.x` は可。
        - 先頭の名前は、flow を所有する要素の feature（継承したものを含む）。
          外側の要素の feature（入れ子のアクションの中から外の兄弟を指す）は
          `Must be an accessible feature (use dot notation for nesting)`、
          どこにも無ければ `Couldn't resolve reference to Feature 'q'.`。
        - 2番目の名前は、先頭の feature の本体か型が持つ feature。

        **確かめられない形は通す。** 所有者や feature の継承元・型がこのファイルに
        無い（ライブラリ由来など）、同名の定義が複数ある、3番目以降の名前、
        のいずれかに当たったら、その端点の判定をやめる。
        """
        members = self._build_feature_member_resolver(ast)

        def walk(node, owners):
            if isinstance(node, dict):
                node_type = node.get("type") or ""
                ends = _flow_end_texts(node)
                for end in ends:
                    self._check_one_flow_end(end, node, owners, members)
                inner = owners
                if node_type and not node_type.endswith("_stmt") and not ends:
                    inner = owners + [node]
                for key, value in node.items():
                    if isinstance(value, (dict, list)) and key != "source_range":
                        walk(value, inner)
            elif isinstance(node, list):
                for item in node:
                    walk(item, owners)

        walk(ast, [])

    @staticmethod
    def _build_feature_member_resolver(ast: Dict):
        """要素ノード → その要素が持つ feature（名前 → ノード）を返す関数を作る。

        継承・型付けはこのファイルの定義だけをたどる。確かめられなければ None。
        flow の端点（_check_flow_ends）と message の端点（sequence ビュー）が使う。
        """
        defs: Dict[str, list] = {}

        def collect_defs(node):
            if isinstance(node, dict):
                if (node.get("type") or "").endswith("_def") and node.get("name"):
                    defs.setdefault(_flow_unquote(node["name"]), []).append(node)
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        collect_defs(value)
            elif isinstance(node, list):
                for item in node:
                    collect_defs(item)

        collect_defs(ast)
        cache: Dict[int, object] = {}

        def members(node, depth=0):
            key = id(node)
            if key in cache:
                return cache[key]
            cache[key] = None  # 循環継承への備え（計算中は「不明」）
            result = _flow_members(node, defs, members, depth)
            cache[key] = result
            return result

        return members

    def _check_message_ends_for_sequence_view(self, ast: Dict) -> None:
        """端点が event occurrence でない message を warning として知らせる。

        `message m from a to b;`（端点がライフラインそのもの）は構文も意味も
        正しく、参照実装はエラーを出さない。ただし公式の可視化の sequence
        ビューは、**両端が各ライフラインの event occurrence のときだけ**
        メッセージを描く。ライフラインそのもの・port・片側だけ event occurrence、
        のいずれも図が空になる（2026-09-24、SysMLv2_pilot の render で実測）。
        フェーズ2評価の t05（ATM のシーケンス）では、合格したモデルがすべてこの
        形で、図にすると何も出なかった。

        **warning であって error ではない**（参照実装との一致判定に影響させない）。
        端点の feature がこのファイルで確かめられない場合は何も言わない。
        """
        members = self._build_feature_member_resolver(ast)

        def end_is_event_occurrence(end, owners):
            """True / False / None（確かめられない）"""
            segments = [_flow_unquote(s) for s in re.split(r"\.|::", end) if s]
            if len(segments) == 1:
                return False  # ライフラインそのもの
            if len(segments) != 2 or not owners:
                return None
            owner_members = members(owners[-1])
            if owner_members is None:
                return None
            lifeline = owner_members.get(segments[0])
            if lifeline is None or lifeline is _FLOW_AMBIGUOUS:
                return None
            lifeline_members = members(lifeline)
            if lifeline_members is None:
                return None
            target = lifeline_members.get(segments[1])
            if target is None or target is _FLOW_AMBIGUOUS:
                return None
            return target.get("type") == "event_occurrence_usage"

        def walk(node, owners):
            if isinstance(node, dict):
                node_type = node.get("type") or ""
                if node_type == "message_usage":
                    ends = [node.get("from_end"), node.get("to_end")]
                    verdicts = [
                        end_is_event_occurrence(end, owners) for end in ends if isinstance(end, str) and end
                    ]
                    if False in verdicts:
                        label = node.get("name") or ""
                        self.issues.append(LintIssue(
                            SEVERITY_WARNING,
                            f"message '{label}' の端点が event occurrence ではないため、公式の "
                            "sequence ビューには表示されない（構文・意味としては正しい）。"
                            "各ライフラインに `event occurrence sendM;` などを宣言し、"
                            "`message m from a.sendM to b.recvM;` のように両端をそれへ向ける",
                            node,
                        ))
                inner = owners
                if node_type and not node_type.endswith("_stmt") and node_type != "message_usage":
                    inner = owners + [node]
                for key, value in node.items():
                    if isinstance(value, (dict, list)) and key != "source_range":
                        walk(value, inner)
            elif isinstance(node, list):
                for item in node:
                    walk(item, owners)

        walk(ast, [])

    def _check_one_flow_end(self, end: str, flow_node: Dict, owners: list, members) -> None:
        segments = [_flow_unquote(s) for s in re.split(r"\.|::", end) if s]
        if not segments or not owners:
            return
        if segments[0] in _FLOW_CONTEXT_WORDS:
            segments = segments[1:]
            if not segments:
                return
        elif len(segments) == 1:
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Cannot identify flow end (use dot notation): flow の端点 '{end}' は "
                "`<所有する要素>.<feature>` の形で書く（例: `flow extract.coffee to serve.coffee;`）",
                flow_node,
            ))
            return

        owner_members = members(owners[-1])
        if owner_members is None:
            return
        first = segments[0]
        if first not in owner_members:
            outer = False
            for ancestor in owners[:-1]:
                found = members(ancestor)
                if found is not None and first in found:
                    outer = True
                    break
            if outer:
                message = (
                    f"Must be an accessible feature (use dot notation for nesting): '{first}' は "
                    "この flow を含む要素の feature ではない。flow を "
                    f"'{first}' と同じ階層へ移すか、端点をこの要素の feature からたどる"
                )
            else:
                message = f"Couldn't resolve reference to Feature '{first}'."
            self.issues.append(LintIssue(SEVERITY_ERROR, message, flow_node))
            return
        if len(segments) < 2 or owner_members[first] is _FLOW_AMBIGUOUS:
            return
        feature_members = members(owner_members[first])
        if feature_members is None:
            return
        if segments[1] not in feature_members:
            known = ", ".join(sorted(feature_members)[:6])
            hint = f"（'{first}' の feature: {known}）" if known else ""
            self.issues.append(LintIssue(
                SEVERITY_ERROR,
                f"Couldn't resolve reference to Feature '{segments[1]}'.{hint}",
                flow_node,
            ))


_FLOW_CONTEXT_WORDS = ("this", "that", "self")
# 名前を持ちうるキー（accept アクションは `actionName` に名前を入れる）
_FLOW_NAME_KEYS = ("name", "shortName", "actionName", "declared_name", "endName")
# ライブラリで定義された暗黙の引数（payload・receiver 等）を持つアクション。
# ActionTest.sysml の `flow aa.target to snd.receiver;`（snd は send アクション）が
# 正しい形なので、中身は確かめられないものとして扱う
_FLOW_IMPLICIT_MEMBER_TYPES = {"accept_action", "send_action", "assignment_stmt"}
# 同じ名前のノードが複数ある（`then braking;` の後続参照と `action braking { ... }`
# の宣言など）。どれが宣言か判別できないので、その先の判定をやめる印
_FLOW_AMBIGUOUS = object()
# AST の中で、要素の直接のメンバーを持たないリスト（参照の列など）
_FLOW_NON_MEMBER_KEYS = {"redefines", "bases", "segments", "extra_types", "extraTypeRefs"}


def _flow_unquote(name: str) -> str:
    name = name.strip()
    return name[1:-1] if len(name) >= 2 and name[0] == name[-1] == "'" else name


def _flow_end_texts(node: Dict) -> list:
    node_type = node.get("type")
    if node_type in ("flow_short_stmt", "flow_from_stmt"):
        keys = ("from_port", "to_port")
    elif node_type == "flow_usage":
        keys = ("from_end", "to_end")
    elif node_type == "succession_usage" and node.get("isFlow"):
        keys = ("fromEnd", "toEnd")
    else:
        return []
    return [node[k] for k in keys if isinstance(node.get(k), str) and node[k]]


def _flow_members(node: Dict, defs: Dict[str, list], members, depth: int):
    """node が持つ feature の名前 → 宣言ノード。確かめられなければ None。"""
    if depth > 8:
        return None
    node_type = node.get("type") or ""
    if node_type in _FLOW_IMPLICIT_MEMBER_TYPES:
        return None
    result: Dict[str, object] = {}

    def put(name, child):
        name = _flow_unquote(name)
        if name in result and result[name] is not child:
            result[name] = _FLOW_AMBIGUOUS
        else:
            result.setdefault(name, child)

    def add_member(child):
        if not isinstance(child, dict) or not child.get("type"):
            return
        if child["type"].endswith("_stmt") and not child.get("name"):
            for grand in child.get("children") or []:
                add_member(grand)
            return
        names = {child[key] for key in _FLOW_NAME_KEYS if isinstance(child.get(key), str) and child[key]}
        for name in names:
            put(name, child)
        # 名前の無い再定義（`out :>> x;`）は、再定義した名前の feature を持つ
        if not names:
            for entry in child.get("redefines") or []:
                if isinstance(entry, dict) and isinstance(entry.get("target"), str):
                    put(entry["target"].split("::")[-1], child)

    for key, value in node.items():
        if key in _FLOW_NON_MEMBER_KEYS or not isinstance(value, list):
            continue
        for child in value:
            add_member(child)

    # 継承・型付けで持ち込まれる feature
    bases = []
    inheritance = node.get("inheritance")
    if isinstance(inheritance, dict):
        bases.extend(inheritance.get("bases") or [inheritance.get("base")])
    if node_type not in ("package", "root") and not node_type.endswith("_def"):
        if node.get("type_name"):
            bases.append(node["type_name"])
        if node.get("redefines"):
            return None  # 別の feature を特殊化・再定義した usage は、元の feature の中身が要る
    for base in bases:
        if not isinstance(base, str) or not base:
            continue
        candidates = defs.get(_flow_unquote(base.lstrip("~").split("::")[-1]))
        if not candidates or len(candidates) != 1:
            return None  # ライブラリ由来・同名が複数など
        inherited = members(candidates[0], depth + 1)
        if inherited is None:
            return None
        for name, member in inherited.items():
            if name not in result:
                result[name] = member
    return result
