"""SysMLMin.g4（ANTLR4）のパース木を、AST dict へ変換するアダプタ。

package / part def / attribute、part usage、connect、flow（part本体内）、
action の item パラメータ、requirement の doc、state の entry、
port def / port usage、import など、生成するAST形状は本ファイルが正
（single source of truth）である。

linter.py は素の dict しか見ないため、ここで正しい形の dict を返せば
linter.py 側は無修正でパーサーの出力にも使える。
"""

from typing import Dict

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from .antlr.generated.SysMLMinLexer import SysMLMinLexer
from .antlr.generated.SysMLMinParser import SysMLMinParser
from .antlr.generated.SysMLMinVisitor import SysMLMinVisitor


class _CollectingErrorListener(ErrorListener):
    """構文エラーを例外にせず蓄積する（parse_sysml()のエラー辞書形式に合わせるため）。"""

    def __init__(self):
        super().__init__()
        self.errors = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"{msg} (line {line}, column {column})")


def _qualified_name_text(ctx) -> str:
    """QualifiedNameContext を 'a.b.c' 形式の文字列にする（feature chain用、`.`区切り）。
    各セグメントはIDまたはQUOTED_NAME（`'Boil Water'.w`のように単一引用符名も
    パスの一部に使える。引用符を外しエスケープを解除する）。"""
    parts = []
    for child in ctx.getChildren():
        text = child.getText()
        if text == ".":
            continue
        if text.startswith("'") and text.endswith("'"):
            parts.append(text[1:-1].replace("\\'", "'").replace("\\\\", "\\"))
        else:
            parts.append(text)
    return ".".join(parts)


def _namespace_path_text(ctx) -> str:
    """NamespacePathContext を 'a::b::c' 形式の文字列にする（KerMLの名前空間パス、`::`区切り）。

    各セグメントはIDだけでなくQUOTED_NAME（`DataFunctions::'*'`のような演算子名の
    引用形）も取りうる。`_qualified_name_text`と同じロジックで引用符を外し
    エスケープを解除する。`.`区切り（`interfacingPorts.incomingTransfersToSelf`）
    も受理するが、出力文字列表現は常に`::`区切りへ正規化する（区切り文字の違いに
    意味上の差は無いため）。"""
    parts = []
    for child in ctx.getChildren():
        text = child.getText()
        if text in ("::", "."):
            continue
        if text.startswith("'") and text.endswith("'"):
            parts.append(text[1:-1].replace("\\'", "'").replace("\\\\", "\\"))
        else:
            parts.append(text)
    return "::".join(parts)


def _optional_qualified_name_text(ctx):
    """QualifiedNameContext が省略可能な箇所用（entry;/do;/exit;のように名前無しもある）。"""
    return _qualified_name_text(ctx) if ctx is not None else None


def _optional_simple_name_text(ctx):
    """SimpleNameContext が省略可能な箇所用
    （`attribute :>> num: Real;`のようにローカル名を省略できるusageがある）。"""
    return _simple_name_text(ctx) if ctx is not None else None


def _simple_name_text(ctx) -> str:
    """SimpleNameContext(ID|QUOTED_NAME) をPythonの文字列にする。

    QUOTED_NAME（'Coffee Brewing Sequence' のような単一引用符名）は
    引用符を外し、`\\'` `\\\\` のエスケープを解除する
    （参照: KerMLExpressions.xtext の terminal UNRESTRICTED_NAME）。
    """
    text = ctx.getText()
    if text.startswith("'") and text.endswith("'"):
        inner = text[1:-1]
        return inner.replace("\\'", "'").replace("\\\\", "\\")
    return text


class SysMLMinASTVisitor(SysMLMinVisitor):
    """パース木の各ノードをAST dictに組み立てる。"""

    # --- フェーズ1 ---------------------------------------------------------

    def visitModel(self, ctx: SysMLMinParser.ModelContext) -> Dict:
        # .sysml ファイルは暗黙のルート名前空間（package でくくらなくてよい）。
        # トップレベル要素が package 単体1個だけならそれをそのままルートにし、
        # それ以外（0個、複数、package以外の単体）は {"type": "root", ...} で包む。
        elements = [self.visit(el) for el in ctx.topLevelElement()]
        if len(elements) == 1 and elements[0].get("type") == "package":
            return elements[0]
        return {"type": "root", "children": elements}

    def visitTopLevelElement(self, ctx: SysMLMinParser.TopLevelElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitPackageDef(self, ctx: SysMLMinParser.PackageDefContext) -> Dict:
        # `standard library package <USCU> USCustomaryUnits { ... }`という
        # ShortName注釈。
        children = [self.visit(el) for el in ctx.topLevelElement()]
        return {
            "type": "package",
            "name": _simple_name_text(ctx.simpleName()),
            "shortName": ctx.shortName.text if ctx.shortName is not None else None,
            "children": children,
        }

    def visitPackageBodyElement(self, ctx: SysMLMinParser.PackageBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitPartDef(self, ctx: SysMLMinParser.PartDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "part_def",
            "name": _simple_name_text(ctx.simpleName()),
            # `part def <xx> Name { ... }`のようなShortName注釈。
            "shortName": ctx.shortName.text if ctx.shortName is not None else None,
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "isIndividual": ctx.isIndividual is not None,
            "children": children,
        }

    def visitInheritanceClause(self, ctx: SysMLMinParser.InheritanceClauseContext) -> Dict:
        # "base"は先頭の基底1つだけを持たせる。理由: linter.pyの継承チェックの
        # 大半（_check_part_def/_check_interface_def等7箇所以上、linter.py:399等）
        # は`base`をそのまま`_find_type_in_symbols(base)`へ渡す単純な完全一致
        # 検索で、カンマ区切り文字列を分割する処理を持たない。カンマ+スペース
        # 区切り文字列（"A, B"）を渡すと、これらの箇所が実在する型の複数基底
        # 指定を「存在しない型 'A, B'」という誤検出にしてしまう。
        # `_check_subclassification_part`（linter.py:2302）だけがカンマ区切り
        # 文字列を分割する処理を持つが、多数派の単純な完全一致検索を壊してまで
        # 少数派に合わせる価値は無いと判断し、"base"は先頭の基底のみにする。
        # 複数基底の全リストは"bases"に別途持たせ、情報としては失わないようにする。
        #
        # 基底型リストは`::`区切りのnamespacePathList
        # （詳細はinheritanceClause規則のコメント参照）。
        bases = [_namespace_path_text(q) for q in ctx.base.namespacePath()]
        # ':>'はKerMLテキスト記法における'subsets'の略記（公式標準ライブラリは
        # attribute defのほぼ全てでこの略記を使う）。linter.py側は
        # kindの具体的な文字列値を分岐に使っていないが、AST上は正規のキーワード名に
        # 正規化しておく方が意味的に一貫する。
        kind_text = "subsets" if ctx.kind.text == ":>" else ctx.kind.text
        result = {"type": "inheritance", "kind": kind_text, "base": bases[0]}
        if len(bases) > 1:
            result["bases"] = bases
        return result

    def _inheritance_dict(self, ctx) -> Dict | None:
        """`inheritanceClause?`を持つ規則のctxから、あれば継承dictを、
        無ければNoneを返す共通ヘルパー。"""
        inheritance_ctx = ctx.inheritanceClause()
        return self.visit(inheritance_ctx) if inheritance_ctx is not None else None

    def visitPartBodyElement(self, ctx: SysMLMinParser.PartBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitItemDef(self, ctx: SysMLMinParser.ItemDefContext) -> Dict:
        # ItemDefinitionはPartDefinitionと完全に同型（公式文法確認済み）。
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "item_def",
            "name": _simple_name_text(ctx.simpleName()),
            # `item def <xxx> Name { ... }`のようなShortName注釈。
            "shortName": ctx.shortName.text if ctx.shortName is not None else None,
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "isIndividual": ctx.isIndividual is not None,
            "children": children,
        }

    def visitItemUsage(self, ctx: SysMLMinParser.ItemUsageContext) -> Dict:
        # `ref item :>> localClock : Clock[1] default Time::universalClock
        # { ... }`。partUsageと同型のredefinition機能一式に加え、
        # attributeUsageと同じ既定値節（`default expression`）も持つ。
        # `item :>> vertices [*] = edges.vertices;`のように`=`値代入も
        # 持つ（`default`とは排他）。
        node = self._usage_keyword_node("item_usage", ctx, ctx.partBodyElement())
        node["value"] = self.visit(ctx.value) if ctx.value is not None else None
        node["defaultValue"] = self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None
        # `derived ref item receiverArgument : Expression[0..1] ...`のように
        # `derived`修飾キーワードも持つ（SysML.sysml、177件）。
        node["isDerived"] = ctx.isDerived is not None
        # `individual item ii : II1;`のようなプレフィックス修飾子（2026-08-28、
        # 参照実装比較レポートP0-3で発見）。
        node["isIndividual"] = ctx.isIndividual is not None
        return node

    def visitRequirementUsage(self, ctx: SysMLMinParser.RequirementUsageContext) -> Dict:
        # `ref requirement :>> self: RequirementCheck;`・`requirement
        # originalRequirements[*] { ... }`のように、`requirement`キーワードの
        # usage形（defではない）。itemUsageと同型の設計に加え、subjectUsageと
        # 同じインライン`= expression`値代入も持つ（`ref requirement
        # requirementVerifications : RequirementCheck[0..*] = obj.
        # requirementVerifications { ... }`、VerificationCases.sysml）。
        node = self._usage_keyword_node("requirement_usage", ctx, ctx.partBodyElement())
        node["value"] = self.visit(ctx.value) if ctx.value is not None else None
        node["defaultValue"] = self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None
        return node

    def visitConcernUsage(self, ctx: SysMLMinParser.ConcernUsageContext) -> Dict:
        # `concern`は`requirement`と完全に同型の構造を持つ別キーワード
        # （Requirements.sysmlのみ）。
        node = self._usage_keyword_node("concern_usage", ctx, ctx.partBodyElement())
        node["defaultValue"] = self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None
        return node

    def visitConcernDef(self, ctx: SysMLMinParser.ConcernDefContext) -> Dict:
        # requirementDefと同型。
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "concern_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitSubjectUsage(self, ctx: SysMLMinParser.SubjectUsageContext) -> Dict:
        # `subject subj :>> Case::subj;`・`subject studyAlternatives :
        # Anything[1..*] { ... }`・`subject subj default Case::result;`・
        # `subject subj = VerificationCase::subj;`のように、itemUsageと
        # 同型の設計に加え、attributeUsageと同じインライン`= expression`
        # 値代入も持つ。
        node = self._usage_keyword_node("subject_usage", ctx, ctx.partBodyElement())
        node["value"] = self.visit(ctx.value) if ctx.value is not None else None
        node["defaultValue"] = self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None
        return node

    def visitObjectiveUsage(self, ctx: SysMLMinParser.ObjectiveUsageContext) -> Dict:
        node = self._usage_keyword_node("objective_usage", ctx, ctx.partBodyElement())
        node["value"] = self.visit(ctx.value) if ctx.value is not None else None
        node["defaultValue"] = self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None
        return node

    def visitEnumDef(self, ctx: SysMLMinParser.EnumDefContext) -> Dict:
        # `enum def X { ... }`。bodyは専用のenumBodyElement（enum-literal・doc）を持つ。
        children = [self.visit(el) for el in ctx.enumBodyElement()]
        return {
            "type": "enum_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "children": children,
        }

    def visitEnumBodyElement(self, ctx: SysMLMinParser.EnumBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitEnumLiteralValue(self, ctx: SysMLMinParser.EnumLiteralValueContext) -> Dict:
        # `low = 0.25;`という裸の名前+値代入形（`RiskMetadata.sysml`）。
        return {
            "type": "enum_literal",
            "name": _simple_name_text(ctx.simpleName()),
            "value": self.visit(ctx.value),
            "children": [],
        }

    def visitEnumLiteralBody(self, ctx: SysMLMinParser.EnumLiteralBodyContext) -> Dict:
        # `enum 'literal';`という明示的キーワード形、`open { doc ... }`という
        # 裸の名前+body形のいずれも同じ形状で扱う（`enum`キーワードの有無は
        # AST上区別しない。意味的にどちらも同じenum-literal宣言のため）。
        return {
            "type": "enum_literal",
            "name": _simple_name_text(ctx.simpleName()),
            "value": None,
            "children": [self.visit(el) for el in ctx.enumBodyElement()],
        }

    def visitAttributeDef(self, ctx: SysMLMinParser.AttributeDefContext) -> Dict:
        # AttributeDefinitionはPartDefinition/ItemDefinitionと同型。
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "attribute_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitAttributeUsage(self, ctx: SysMLMinParser.AttributeUsageContext) -> Dict:
        # 型節（`:` namespacePathList）は常に省略可能（bareのリデファイン宣言が
        # 型を持たないため）。型節はQUOTED_NAME形式（記号を含む型名、例:
        # `'HedströmNumberValue'`）も取りうる。また`attribute <K> kelvin :
        # ThermodynamicTemperatureUnit, TemperatureDifferenceUnit { ... }`の
        # ように、型節がカンマ区切りの複数型を取ることがある
        # （`typeList=namespacePathList`という専用ラベルのため、shortName
        # のQUOTED_NAMEとの混同は起きない）。
        type_names: list[str] = []
        if ctx.typeList is not None:
            type_names = [_namespace_path_text(p) for p in ctx.typeList.namespacePath()]
        elif ctx.typeQuoted is not None:
            type_names = [ctx.typeQuoted.text]
        type_name = type_names[0] if type_names else None
        # 1宣言に複数のredefine/subsets節を連続して書ける形に対応するため、
        # redefinesは常にリスト（0件含む）。redefine対象は`::`修飾名にも
        # なり得るためnamespacePathList版を使う（part/port/featureUsageと
        # 同じ扱い）。
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        visibility_ctx = ctx.visibilityIndicator()
        # 専用のattributeBodyElementは持たず、part/portと共有するpartBodyElement
        # を使う（partBodyElementはvalueBindingStmtも含むため、この統一で
        # 表現力は失われない）。
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "attribute_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            # `attribute <isq> ...`のような短縮名注釈（KerMLのShortName、
            # 公式コーパスで5ファイル使用）。
            "shortName": ctx.shortName.text if ctx.shortName is not None else None,
            "type_name": type_name,
            **({"type_names": type_names} if len(type_names) > 1 else {}),
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "inheritance": None,
            "isAbstract": ctx.isAbstract is not None,
            "isConstant": ctx.isConstant is not None,
            # `derived attribute isReference : Boolean[1] ...`のように
            # `derived`修飾キーワードも持つ（SysML.sysml）。
            "isDerived": ctx.isDerived is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "redefines": redefines,
            # `attribute x : T = expr;`というインライン値代入
            # （body内のvalueBindingStmtとは別）。
            "value": self.visit(ctx.value) if ctx.value is not None else None,
            # `attribute x : T default expr;`という既定値節（`=`の固定値代入とは
            # 異なり、再定義や継承先で上書き可能な既定値という意味）。
            "defaultValue": self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None,
            "children": children,
        }

    def _redefine_dict(self, kind_token, targets: list[str] | None) -> Dict | None:
        """`:>'/':>>'`（記号形）または`subsets`/`redefines`（textual形）という
        redefine/subsets節1個分をASTへ変換する共通ヘルパー。`kind`は正規の
        キーワード名へ正規化する（inheritanceClauseと同じ考え方。linter.pyは
        kindの文字列値を分岐に使っていないが、AST上の意味を仕様に合わせて
        一貫させるため）。呼び出し側でqualifiedNameList/namespacePathList
        いずれからでもテキストのリストへ変換してから渡す（対象の書き方が
        usage種別によって異なるため）。"""
        if not targets:
            return None
        # case/analysis/verification/use case usageのみ`specializes`（bareの
        # 完全な分類、`case c specializes Case1;`）も取りうるため区別する。
        # 他の呼び出し元ではkind_token.textが"specializes"になることはない。
        if kind_token.text in (":>>", "redefines"):
            kind = "redefines"
        elif kind_token.text == "specializes":
            kind = "specializes"
        else:
            kind = "subsets"
        result = {"kind": kind, "target": targets[0]}
        if len(targets) > 1:
            result["targets"] = targets
        return result

    def _redefine_list_namespace(self, kind_tokens, target_ctxs) -> list:
        """`preKind+=.../preTarget+=...`のように`+=`で収集された複数の
        redefine/subsets節（namespacePathList、`::`区切り）を、出現順の
        リストへ変換する。1宣言に`:>>`/`:>`を複数連続して書ける形
        （`causes[1..*] :>> causes :> participant`）に対応するため、
        redefinesは「最大1個」ではなく「0個以上」のリストとして扱う。
        attributeUsageもこの版を使うよう統一している。"""
        result = []
        for kind_token, target_ctx in zip(kind_tokens, target_ctxs):
            targets = [_namespace_path_text(q) for q in target_ctx.namespacePath()]
            redefine = self._redefine_dict(kind_token, targets)
            if redefine:
                result.append(redefine)
        return result

    def visitValueBindingStmt(self, ctx: SysMLMinParser.ValueBindingStmtContext) -> Dict:
        kind = "redefines" if ctx.kind.text == ":>>" else "subsets"
        return {
            "type": "value_binding",
            "kind": kind,
            "target": _qualified_name_text(ctx.target),
            "value": self.visit(ctx.value),
            "children": [],
        }

    # --- フェーズ2: part usage ----------------------------------------------

    def visitPartUsage(self, ctx: SysMLMinParser.PartUsageContext) -> Dict:
        # attributeUsageと同じredefinition機能一式（visibility・ref・
        # 名前省略・redefine節）を持つ。型節は`namespacePath`
        # （`Parts::'OnOffスイッチ'`のような`::`区切り型参照に対応。
        # 単一セグメントの場合はそのままの文字列を返す）。
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        visibility_ctx = ctx.visibilityIndicator()
        children = [self.visit(el) for el in ctx.partBodyElement()]
        # `ref part this : Part :>> Action::this, ownedPerformances::this =
        # that as Part { ... }`（Parts.sysml）という`=`値代入も持つ。既存の
        # `expression`プレースホルダーフィールドをそのまま使う。
        return {
            "type": "part_instance",
            "name": _optional_simple_name_text(ctx.simpleName()),
            # `part <'1'> b: B;`のようなShortName注釈（2026-08-28、
            # 参照実装比較レポートP1-1で発見）。
            "shortName": ctx.shortName.text if ctx.shortName is not None else None,
            "type_name": _namespace_path_text(ctx.typeRef) if ctx.typeRef is not None else None,
            "role": None,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "inheritance": None,
            "isAbstract": ctx.isAbstract is not None,
            "isConstant": ctx.isConstant is not None,
            "isRef": ctx.isRef is not None,
            # `individual part p : IP1;`のようなプレフィックス修飾子
            # （2026-08-28、参照実装比較レポートP0-3で発見）。
            "isIndividual": ctx.isIndividual is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "redefines": redefines,
            "expression": self.visit(ctx.value) if ctx.value is not None else None,
            "children": children,
        }

    # --- フェーズ2: connect --------------------------------------------------

    def visitConnectUsage(self, ctx: SysMLMinParser.ConnectUsageContext) -> Dict:
        ends = ctx.connectorEndPath()
        return {
            "type": "connect_usage",
            "from_end": self.visit(ends[0]),
            "to_end": self.visit(ends[1]),
            "children": [],
        }

    def visitConnectionUsage(self, ctx: SysMLMinParser.ConnectionUsageContext) -> Dict:
        # `connection :MatesWith connect [1] be to [1] be;`（ShapeItems.sysml）
        # のように、`connectUsage`（キーワード無し型）とは別の、`connection`
        # キーワード+型節+connectorEnd側multiplicityを伴う形。
        if ctx.typeRef is not None:
            return {
                "type": "connection_usage",
                "type_name": _namespace_path_text(ctx.typeRef),
                "firstMultiplicity": self._multiplicity_dict(ctx.firstMult),
                "firstEnd": self.visit(ctx.firstEnd),
                "thenMultiplicity": self._multiplicity_dict(ctx.thenMult),
                "thenEnd": self.visit(ctx.thenEnd),
                "children": [self.visit(el) for el in ctx.partBodyElement()],
            }
        # `abstract connection connections: Connection[0..*] nonunique :>
        # linkObjects, parts { ... }`という、`connect`を伴わない裸の形
        # （itemUsage/partUsage等と同型）。
        id_ctx = ctx.ID()
        redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
        mult_list = ctx.multiplicitySpec()
        return {
            "type": "connection_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_name": id_ctx.getText() if id_ctx is not None else None,
            "multiplicity": self._multiplicity_dict(mult_list[0] if mult_list else None),
            "isAbstract": ctx.isAbstract is not None,
            "redefines": redefines,
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitConnectorEnd(self, ctx: SysMLMinParser.ConnectorEndContext) -> Dict:
        declared_name = ctx.ID().getText() if ctx.ID() is not None else None
        return {
            "type": "connector_end",
            "declared_name": declared_name,
            "reference": _qualified_name_text(ctx.qualifiedName()),
        }

    def visitConnectorEndPath(self, ctx: SysMLMinParser.ConnectorEndPathContext) -> Dict:
        # `connectorEnd`と同じ出力shapeだが、`connectUsage`専用に
        # `.`/`::`混在パスを受理する`namespacePath`を使う。
        declared_name = ctx.ID().getText() if ctx.ID() is not None else None
        return {
            "type": "connector_end",
            "declared_name": declared_name,
            "reference": _namespace_path_text(ctx.namespacePath()),
        }

    def _binary_part(self, part_type: str, from_ctx, to_ctx) -> Dict:
        """interface_usage/allocation_usageの `interface_part`/`connector_part` を組み立てる。

        linter.pyの _check_interface_usage / _check_allocation_usage が読む
        `{"type": part_type, "from_end": {"reference_subsetting": {"referenced_feature": str}}, "to_end": {...}}`
        の形に合わせる（connect_usageのconnectorEndとは別の、より深い入れ子）。
        """

        def _end(ctx):
            return {"reference_subsetting": {"referenced_feature": _qualified_name_text(ctx.qualifiedName())}}

        return {"type": part_type, "from_end": _end(from_ctx), "to_end": _end(to_ctx)}

    # --- フェーズ2: flow -------------------------------------------------------

    def visitFlowUsage(self, ctx: SysMLMinParser.FlowUsageContext) -> Dict:
        # `abstract flow flows: Flow[0..*] nonunique :> messages,
        # flowTransfers { ... }`という、`of`/`from...to`を伴わない裸のflow
        # usage形（connection/allocation/message等と同型）。
        if ctx.simpleName() is not None or ctx.multiplicitySpec() is not None or len(ctx.postKind) > 0 or ctx.partBodyElement():
            id_ctx = ctx.ID()
            redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
            return {
                "type": "flow_usage",
                "name": _optional_simple_name_text(ctx.simpleName()),
                "type_name": id_ctx.getText() if id_ctx is not None else None,
                "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
                "isAbstract": ctx.isAbstract is not None,
                "redefines": redefines,
                "children": [self.visit(el) for el in ctx.partBodyElement()],
            }
        # fromEnd/toEndは`.`/`::`混在パスを受理する`namespacePath`
        # （`_namespace_path_text`は区切り文字を常に`::`へ正規化する）。
        from_end = _namespace_path_text(ctx.fromEnd) if ctx.fromEnd is not None else None
        to_end = _namespace_path_text(ctx.toEnd) if ctx.toEnd is not None else None
        return {
            "type": "flow_usage",
            "item_type": ctx.ID().getText() if ctx.ID() is not None else None,
            "from_end": from_end,
            "to_end": to_end,
            "children": [],
        }

    def visitFlowDef(self, ctx: SysMLMinParser.FlowDefContext) -> Dict:
        # `abstract flow def MessageAction :> Action, Link { ... }`
        # （Flows.sysml）。partDefと同型。
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "flow_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    # --- フェーズ2: action の item パラメータ -----------------------------------

    def visitActionDef(self, ctx: SysMLMinParser.ActionDefContext) -> Dict:
        # "param"型の子だけをparamsへ、それ以外(decision_node/send_action/
        # assignment_stmt等)はchildrenへ分離する。linter.pyの
        # _check_control_nodes_in_action等はaction_node["children"]しか
        # 見ないため、この分離を維持する必要がある。
        params = []
        children = []
        for el in ctx.actionBodyElement():
            node = self.visit(el)
            if isinstance(node, dict) and node.get("type") == "param":
                params.append(node)
            else:
                children.append(node)
        return {
            "type": "action_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "isIndividual": ctx.isIndividual is not None,
            "params": params,
            "children": children,
        }

    def visitActionBodyElement(self, ctx: SysMLMinParser.ActionBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitCalcParameter(self, ctx: SysMLMinParser.CalcParameterContext) -> Dict:
        # `constraint def`/`calc def`本体内の`in`/`out`/`inout`パラメータ宣言
        # （`in x : T[*] ordered;`）と、名前付き制約参照時のパラメータ束縛
        # （`in x = value;`）の両方を1つのノードで表す。`return`キーワード
        # （`direction()`が無いため`dirReturn`ラベルから読む）と、値代入後の
        # `{ ... }`本体（`return result = ... { doc ... }`）にも対応する。
        # 型節・値節は`return : Boolean[1] = ...;`のように同時に持つ形もある
        # ため、それぞれ独立に任意（両方Noneも両方指定も可）。
        direction_ctx = ctx.direction()
        direction_text = direction_ctx.getText() if direction_ctx is not None else ctx.dirReturn.text
        type_ctx = ctx.namespacePath()
        value_ctx = ctx.expression()
        return {
            "type": "calc_parameter",
            "direction": direction_text,
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_name": _namespace_path_text(type_ctx) if type_ctx is not None else None,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "value": self.visit(value_ctx) if value_ctx is not None else None,
            "children": [self.visit(el) for el in ctx.calcBodyElement()],
        }

    def visitActionParameter(self, ctx: SysMLMinParser.ActionParameterContext) -> Dict:
        # actionParameterは`attribute`/`ref`/`calc`/`action`という複数の型
        # キーワード・`::`修飾型・多重度・redefine節・値代入・doc本体を受理する。
        # `type_spec`/`is_item`は既存のlinter.py（_check_action_def/
        # _check_activity_def）がそのまま読むため後方互換のため残しつつ、
        # kind/type_name/multiplicity/redefines/value/childrenも提供する。
        direction_ctx = ctx.direction()
        direction_text = direction_ctx.getText() if direction_ctx is not None else ctx.dirReturn.text
        kind_text = ctx.kind.text if ctx.kind is not None else None
        type_ctx = ctx.namespacePath()
        type_name = _namespace_path_text(type_ctx) if type_ctx is not None else None
        # `out xxx : ~xxxx;`のような共役ポート参照。portUsageと同じ
        # `~`合成規則（linter.pyのtype_name.startswith("~")前提）を適用する。
        if type_name is not None and ctx.conjugated is not None:
            type_name = "~" + type_name
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        return {
            "type": "param",
            "direction": direction_text,
            "is_item": kind_text == "item",
            "kind": kind_text,
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_spec": {"name": type_name} if type_name is not None else None,
            "type_name": type_name,
            # 多重度は型節の前(`preMult`、逆順)・後(`postMult`、通常順)の
            # どちらか一方にのみ現れる（両方同時に現れる実例は無い）。
            "multiplicity": self._multiplicity_dict(ctx.preMult if ctx.preMult is not None else ctx.postMult),
            "redefines": redefines,
            "value": self.visit(ctx.value) if ctx.value is not None else None,
            # `in clock : Clock[1] default enclosingItem.localClock;`のように、
            # `default`キーワードも受理する（`=`とは排他）。
            "defaultValue": self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None,
            # `in calc calculation { in x; }`のように、actionParameter自身が
            # body内にネストされることがあるため、ActionParameterContextも
            # 子として拾う。
            "children": [
                self.visit(child)
                for child in ctx.getChildren()
                if isinstance(
                    child,
                    (
                        SysMLMinParser.DocumentationStmtContext,
                        SysMLMinParser.BareDocCommentContext,
                        SysMLMinParser.ActionParameterContext,
                    ),
                )
            ],
        }

    # --- decision/fork/join/merge/assignment/send action ------------------------

    def visitFlowControlNode(self, ctx: SysMLMinParser.FlowControlNodeContext) -> Dict:
        node_type = f"{ctx.kind.text}_node"
        name_ctx = ctx.simpleName()
        children = [self.visit(el) for el in ctx.actionBodyElement()]
        return {
            "type": node_type,
            "name": _simple_name_text(name_ctx) if name_ctx is not None else None,
            "children": children,
        }

    def visitAssignmentStmt(self, ctx: SysMLMinParser.AssignmentStmtContext) -> Dict:
        visibility_ctx = ctx.visibilityIndicator()
        return {
            "type": "assignment_stmt",
            "name": _namespace_path_text(ctx.target),
            "operator": ctx.op.text,
            "value": self.visit(ctx.value),
            **({"isThen": True} if ctx.isThen is not None else {}),
            **({"visibility": visibility_ctx.getText()} if visibility_ctx is not None else {}),
            **({"actionName": _simple_name_text(ctx.actionName)} if ctx.actionName is not None else {}),
        }

    def visitSendActionNamed(self, ctx: SysMLMinParser.SendActionNamedContext) -> Dict:
        return {
            "type": "send_action",
            "name": _simple_name_text(ctx.name),
            "payload": _namespace_path_text(ctx.payload),
            "receiver": _qualified_name_text(ctx.receiver),
        }

    def visitSendActionAnonymous(self, ctx: SysMLMinParser.SendActionAnonymousContext) -> Dict:
        if ctx.toTarget is not None:
            target, target_type = ctx.toTarget, "to"
        else:
            target, target_type = ctx.viaTarget, "via"
        return {
            "type": "send_action",
            "name": None,
            "payload": _namespace_path_text(ctx.payload),
            "target": _qualified_name_text(target),
            "target_type": target_type,
        }

    def visitAcceptActionStmt(self, ctx: SysMLMinParser.AcceptActionStmtContext) -> Dict:
        visibility_ctx = ctx.visibilityIndicator()
        return {
            "type": "accept_action",
            "message": _qualified_name_text(ctx.message),
            "message_type": _namespace_path_text(ctx.messageType) if ctx.messageType is not None else None,
            "port": _qualified_name_text(ctx.port),
            **({"isThen": True} if ctx.isThen is not None else {}),
            **({"visibility": visibility_ctx.getText()} if visibility_ctx is not None else {}),
            **({"actionName": _simple_name_text(ctx.actionName)} if ctx.actionName is not None else {}),
        }

    def visitPerformActionStmt(self, ctx: SysMLMinParser.PerformActionStmtContext) -> Dict:
        npath_ctx = ctx.namespacePath()
        if npath_ctx is not None:
            return {
                "type": "perform_action",
                "reference": _namespace_path_text(npath_ctx),
                **({"isThen": True} if ctx.isThen is not None else {}),
            }
        # `perform action <名前> redefines <対象> { ... }`という、
        # actionUsageStmtと同型の名前付き・redefines付き・body付き形。
        params = []
        children = []
        for el in ctx.actionBodyElement():
            node = self.visit(el)
            if isinstance(node, dict) and node.get("type") == "param":
                params.append(node)
            else:
                children.append(node)
        redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
        return {
            "type": "perform_action",
            "name": _optional_simple_name_text(ctx.actionName),
            "redefines": redefines,
            "params": params,
            "children": children,
            **({"isThen": True} if ctx.isThen is not None else {}),
        }

    def visitMessageStmt(self, ctx: SysMLMinParser.MessageStmtContext) -> Dict:
        name_ctx = ctx.simpleName()
        return {
            "type": "message",
            "name": _simple_name_text(name_ctx) if name_ctx is not None else None,
            "from_end": _qualified_name_text(ctx.fromEnd),
            "to_end": _qualified_name_text(ctx.toEnd),
        }

    def visitIfActionStmt(self, ctx: SysMLMinParser.IfActionStmtContext) -> Dict:
        has_else = any(child.getText() == "else" for child in ctx.getChildren())
        return {
            "type": "if_stmt",
            "condition": self.visit(ctx.condition),
            "then": [self.visit(el) for el in ctx.thenElement],
            "else": [self.visit(el) for el in ctx.elseElement] if has_else else None,
        }

    def visitActionUsageStmt(self, ctx: SysMLMinParser.ActionUsageStmtContext) -> Dict:
        # actionDef同様、param型の子だけをparamsへ、それ以外はchildrenへ分離する。
        params = []
        children = []
        for el in ctx.actionBodyElement():
            node = self.visit(el)
            if isinstance(node, dict) and node.get("type") == "param":
                params.append(node)
            else:
                children.append(node)
        # `abstract ref action performedActions: Action[0..*] :> actions,
        # enactedPerformances { ... }`（Parts.sysml）のように、他のusage
        # キーワード規則と同型のredefinition機能一式を持つ。
        # `typeRef`はshortName（ID|QUOTED_NAME）とは別のラベルなので、
        # ctx.ID()（無ラベル参照が2箇所になり複数トークンのリストを返す
        # ようになった）ではなくこちらを使う。
        type_ref_ctx = ctx.typeRef
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        visibility_ctx = ctx.visibilityIndicator()
        return {
            "type": "action_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            # `action <'xxx'> Name { ... }`のようなShortName注釈。
            "shortName": ctx.shortName.text if ctx.shortName is not None else None,
            "type_name": type_ref_ctx.text if type_ref_ctx is not None else None,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            # `private ref action thisConnection = self;`（Flows.sysml）
            # という`=`値代入。
            "value": self.visit(ctx.value) if ctx.value is not None else None,
            "guard": self.visit(ctx.guard) if ctx.guard is not None else None,
            "isAbstract": ctx.isAbstract is not None,
            "isRef": ctx.isRef is not None,
            # `individual action a : AP1;`のようなプレフィックス修飾子
            # （2026-08-28、参照実装比較レポートP0-3で発見）。
            "isIndividual": ctx.isIndividual is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "redefines": redefines,
            "params": params,
            "children": children,
            **({"isThen": True} if ctx.isThen is not None else {}),
        }

    # --- フェーズ2続き: calculation usage / constraint usage ------------------------

    def visitCalculationUsage(self, ctx: SysMLMinParser.CalculationUsageContext) -> Dict:
        # partUsage/featureUsageと同型のredefinition機能一式（visibility・
        # ref・名前省略・pre/post redefine節）を持つ（`ref calc self:
        # Calculation :>> Action::self, Evaluation::self;`等）。
        return self._usage_keyword_node("calculation_usage", ctx, ctx.calcBodyElement())

    def visitConstraintUsage(self, ctx: SysMLMinParser.ConstraintUsageContext) -> Dict:
        return self._usage_keyword_node("constraint_usage", ctx, ctx.calcBodyElement())

    def _usage_keyword_node(self, node_type: str, ctx, children_ctxs) -> Dict:
        """case/analysis/verification/use case/calc/constraint usageの6規則が
        共有する、partUsage/featureUsageと同型のAST組み立てロジック（型節は
        `: ID`単体、bodyのルールだけが規則ごとに異なるため引数で受け取る）。
        `typeRef`という専用ラベルを持つ規則（requirementUsage。shortNameの
        `ID|QUOTED_NAME`代替と合わせて無ラベル`ctx.ID()`がリストを返すように
        なるため）ではそちらを優先し、無い規則では従来通り`ctx.ID()`を使う。
        `hasattr`で判定する（値がNoneかどうかではなく属性自体の有無を見る）
        必要がある。値で判定すると、`typeRef`が実際に省略された（値がNone）
        requirementUsageインスタンスで`ctx.ID()`にフォールバックしてしまい、
        そちらもshortNameのID代替を含むリストを返すため同じ問題が再発する。"""
        if hasattr(ctx, "typeRef"):
            id_ctx = ctx.typeRef
        else:
            id_ctx = ctx.ID()
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        visibility_ctx = ctx.visibilityIndicator()
        # `requirement <C1> ...`のようなShortName注釈は一部の規則（例:
        # requirementUsage）にしか無いため、getattrで安全に読む（無い規則は
        # ctx.shortName属性自体が無い。_named_simple_nodeと同じ方針）。
        short_name_token = getattr(ctx, "shortName", None)
        # `typeRef`ラベル経由の場合は生のToken（`.text`）、無ラベル`ctx.ID()`
        # 経由の場合はTerminalNode（`.getText()`）と型が異なるため、両対応する。
        if id_ctx is not None:
            type_name = id_ctx.getText() if hasattr(id_ctx, "getText") else id_ctx.text
        else:
            type_name = None
        return {
            "type": node_type,
            "name": _optional_simple_name_text(ctx.simpleName()),
            "shortName": short_name_token.text if short_name_token is not None else None,
            "type_name": type_name,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "isAbstract": ctx.isAbstract is not None,
            "isRef": ctx.isRef is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "redefines": redefines,
            "children": [self.visit(el) for el in children_ctxs],
        }

    # --- フェーズ2続き: satisfy requirement usage ------------------------------------

    def visitSatisfyRequirementUsage(self, ctx: SysMLMinParser.SatisfyRequirementUsageContext) -> Dict:
        # `satisfy requirement viewpointConformance by that { ... }`
        # （Views.sysml）というbodyありの代替がある。`ctx.by`（この代替のみで
        # 設定される`by=namespacePath`ラベル）の有無で2つの代替を区別する。
        is_negated = any(child.getText() == "not" for child in ctx.getChildren())
        by_ctx = getattr(ctx, "by", None)
        if by_ctx is not None:
            return {
                "type": "satisfy_requirement_usage",
                "is_negated": is_negated,
                "name": _simple_name_text(ctx.simpleName()),
                "type_name": None,
                "by": _namespace_path_text(by_ctx),
                "children": [self.visit(el) for el in ctx.partBodyElement()],
            }
        type_ctx = ctx.ID()
        return {
            "type": "satisfy_requirement_usage",
            "is_negated": is_negated,
            "name": _simple_name_text(ctx.simpleName()),
            "type_name": type_ctx.getText() if type_ctx is not None else None,
            "by": None,
            "children": [],
        }

    def visitRequireUsage(self, ctx: SysMLMinParser.RequireUsageContext) -> Dict:
        # `require viewpointSatisfactions { ... }`（`constraint`キーワードを
        # 伴わない、`satisfyRequirementUsage`のbody内にネストして使われる形、
        # Views.sysmlのみ1件）。
        return {
            "type": "require_usage",
            "name": _simple_name_text(ctx.simpleName()),
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    # --- フェーズ2: requirement の doc ------------------------------------------

    def visitRequirementDef(self, ctx: SysMLMinParser.RequirementDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.requirementBodyElement()]
        return {
            "type": "requirement_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitRequirementBodyElement(self, ctx: SysMLMinParser.RequirementBodyElementContext) -> Dict:
        # requirementBodyElementはdocumentationStmtのみ。専用のvisitメソッドは
        # 不要。
        return self.visit(ctx.getChild(0))

    # --- フェーズ2: state の entry -----------------------------------------------

    def visitStateDef(self, ctx: SysMLMinParser.StateDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.stateBodyElement()]
        return {
            "type": "state_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitStateBodyElement(self, ctx: SysMLMinParser.StateBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitStateUsage(self, ctx: SysMLMinParser.StateUsageContext) -> Dict:
        # bodyの中身（entry/do/exit等）はchildrenへそのまま反映する。
        # _find_state_in_symbolsはtype=="state_def"しか見ないため、
        # transitionからは参照できない。
        # `ref`修飾子・型節・redefine節も持つ（itemUsage/partUsage等と同型）。
        children = [self.visit(el) for el in ctx.stateBodyElement()]
        id_ctx = ctx.ID()
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        return {
            "type": "state_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_name": id_ctx.getText() if id_ctx is not None else None,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "inheritance": None,
            "isAbstract": ctx.isAbstract is not None,
            "isRef": ctx.isRef is not None,
            "redefines": redefines,
            "children": children,
        }

    # --- binding connector / succession (8.2.2.13) ------------------------------

    def visitBindingConnector(self, ctx: SysMLMinParser.BindingConnectorContext) -> Dict:
        # `binding [1] bind [0..*] base.edges = [0..*] be;`のように、名前・
        # コネクタ自体の多重度・各end側の多重度・bodyを持つ。
        return {
            "type": "binding_connector",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "multiplicity": self._multiplicity_dict(ctx.connMult),
            "leftMultiplicity": self._multiplicity_dict(ctx.leftMult),
            "leftEnd": self.visit(ctx.leftEnd),
            "rightMultiplicity": self._multiplicity_dict(ctx.rightMult),
            "rightEnd": self.visit(ctx.rightEnd),
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitSuccessionStmt(self, ctx: SysMLMinParser.SuccessionStmtContext) -> Dict:
        return {
            "type": "succession",
            "firstEnd": self.visit(ctx.firstEnd),
            "thenEnd": self.visit(ctx.thenEnd),
            "children": [],
        }

    def visitSuccessionUsage(self, ctx: SysMLMinParser.SuccessionUsageContext) -> Dict:
        # `succession causalOrdering first [nCauses] causes.startShot then
        # [nEffects] effects { ... }`のように、`succession`キーワード自体・
        # 名前・先頭多重度・connectorEnd側の多重度・bodyを持つ形。先頭多重度は
        # firstMult/thenMultのどちらでもない`multiplicitySpec()`要素として
        # 区別する（ANTLRはラベル無しの出現もctx.multiplicitySpec()の一覧に
        # 含める）。
        leading_mult_ctx = None
        for m in ctx.multiplicitySpec():
            if m is not ctx.firstMult and m is not ctx.thenMult:
                leading_mult_ctx = m
                break
        visibility_ctx = ctx.visibilityIndicator()
        return {
            "type": "succession_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "multiplicity": self._multiplicity_dict(leading_mult_ctx),
            "firstMultiplicity": self._multiplicity_dict(ctx.firstMult),
            "firstEnd": self.visit(ctx.firstEnd),
            "thenMultiplicity": self._multiplicity_dict(ctx.thenMult),
            "thenEnd": self.visit(ctx.thenEnd),
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitBareFirstStmt(self, ctx: SysMLMinParser.BareFirstStmtContext) -> Dict:
        return {"type": "first_stmt", "name": _qualified_name_text(ctx.target)}

    def visitBareThenStmt(self, ctx: SysMLMinParser.BareThenStmtContext) -> Dict:
        return {"type": "then_stmt", "name": _qualified_name_text(ctx.target)}

    def visitGuardedTargetSuccessionStmt(
        self, ctx: SysMLMinParser.GuardedTargetSuccessionStmtContext
    ) -> Dict:
        return {
            "type": "guarded_then_stmt",
            "guard": self.visit(ctx.guard),
            "name": _namespace_path_text(ctx.target),
        }

    def visitDefaultTargetSuccessionStmt(
        self, ctx: SysMLMinParser.DefaultTargetSuccessionStmtContext
    ) -> Dict:
        return {"type": "else_stmt", "name": _namespace_path_text(ctx.target)}

    def visitActionFlowFrom(self, ctx: SysMLMinParser.ActionFlowFromContext) -> Dict:
        flow_node = {
            "type": "flow_from_stmt",
            "from_port": _qualified_name_text(ctx.fromPath),
            "to_port": _qualified_name_text(ctx.toPath),
            "children": [],
        }
        return {"type": "flow_stmt", "children": [flow_node]}

    def visitActionFlowShort(self, ctx: SysMLMinParser.ActionFlowShortContext) -> Dict:
        flow_node = {
            "type": "flow_short_stmt",
            "from_port": _qualified_name_text(ctx.fromPath),
            "to_port": _qualified_name_text(ctx.toPath),
            "children": [],
        }
        return {"type": "flow_stmt", "children": [flow_node]}

    def visitEntryActionMember(self, ctx: SysMLMinParser.EntryActionMemberContext) -> Dict:
        # `entry action entryAction :>> 'entry';`（States.sysml）のように
        # 型節・redefine節も持つ（対象は`entry`自体が予約語のためQUOTED_NAME
        # で囲む）。
        id_ctx = ctx.ID()
        return {
            "type": "entry_action",
            "kind": "entry",
            "action_reference": _optional_qualified_name_text(ctx.qualifiedName()),
            "type_name": id_ctx.getText() if id_ctx is not None else None,
            "redefines": self._redefine_list_namespace(ctx.postKind, ctx.postTarget),
            "children": [],
        }

    # --- フェーズ2続き: state の do / exit --------------------------------------
    # 参照: SysML.xtext の `DoActionMember`/`ExitActionMember`。
    # `_check_state_actions`（linter.py:3535）が読む `kind` フィールド
    # （"do"/"exit"）を持たせる。entryActionMemberと同様、'action'キーワードと
    # 参照先アクション名はどちらも省略可。

    def visitDoActionMember(self, ctx: SysMLMinParser.DoActionMemberContext) -> Dict:
        id_ctx = ctx.ID()
        return {
            "type": "do_action",
            "kind": "do",
            "action_reference": _optional_qualified_name_text(ctx.qualifiedName()),
            "type_name": id_ctx.getText() if id_ctx is not None else None,
            "redefines": self._redefine_list_namespace(ctx.postKind, ctx.postTarget),
            "children": [],
        }

    def visitExitActionMember(self, ctx: SysMLMinParser.ExitActionMemberContext) -> Dict:
        id_ctx = ctx.ID()
        return {
            "type": "exit_action",
            "kind": "exit",
            "action_reference": _optional_qualified_name_text(ctx.qualifiedName()),
            "type_name": id_ctx.getText() if id_ctx is not None else None,
            "redefines": self._redefine_list_namespace(ctx.postKind, ctx.postTarget),
            "children": [],
        }

    # --- フェーズ2続き: transition ---------------------------------------------------
    # `_check_transition`（linter.py:1346）は`source`/`target` のみ必須。
    # `_check_transition_advanced`/
    # `_check_transition_advanced_structure`（linter.py:1694,3577）は
    # trigger/guard/effectそれぞれに正しい`kind`タグを要求するため付与する。

    def visitTransitionStmt(self, ctx: SysMLMinParser.TransitionStmtContext) -> Dict:
        trigger = None
        trigger_ctx = ctx.transitionTrigger()
        if trigger_ctx is not None:
            if trigger_ctx.triggerKind is not None:
                # `accept when EXPR`（変化トリガー）/`accept at EXPR`
                # （時刻トリガー）。2026-08-28、参照実装比較レポートP0-5で発見。
                trigger = {
                    "kind": "trigger",
                    "trigger_kind": trigger_ctx.triggerKind.text,
                    "expression": self.visit(trigger_ctx.triggerExpr),
                }
            else:
                trigger = {"kind": "trigger", "reference": _namespace_path_text(trigger_ctx.trigger)}
                # `accept apayload: Anything via receiver`のように、型節・
                # via節を伴うことがある（Actions.sysml）。
                if trigger_ctx.triggerType is not None:
                    trigger["type_name"] = _namespace_path_text(trigger_ctx.triggerType)
                if trigger_ctx.via is not None:
                    trigger["via"] = _namespace_path_text(trigger_ctx.via)

        guard = None
        if ctx.guard is not None:
            guard = {"kind": "guard", "expression": self.visit(ctx.guard)}

        effect = None
        effect_ctx = ctx.transitionEffect()
        if effect_ctx is not None:
            if effect_ctx.payload is not None:
                # `do send new 'Start Signal'() to vehicle1_c1.vehicleController`
                # というインラインsendアクション。2026-08-28、参照実装比較
                # レポートP0-5で発見。
                effect = {
                    "kind": "effect",
                    "send": {
                        "payload": self.visit(effect_ctx.payload),
                        "to": _namespace_path_text(effect_ctx.sendTarget)
                        if effect_ctx.sendTarget is not None
                        else None,
                        "via": _namespace_path_text(effect_ctx.sendVia)
                        if effect_ctx.sendVia is not None
                        else None,
                    },
                }
            elif effect_ctx.effect is not None:
                effect = {"kind": "effect", "action_reference": _namespace_path_text(effect_ctx.effect)}

        return {
            "type": "transition",
            "name": _simple_name_text(ctx.simpleName()) if ctx.simpleName() is not None else None,
            "source": _namespace_path_text(ctx.source),
            "target": _namespace_path_text(ctx.target),
            "trigger": trigger,
            "guard": guard,
            "effect": effect,
            "children": [],
        }

    def visitInitialTransitionMember(self, ctx: SysMLMinParser.InitialTransitionMemberContext) -> Dict:
        # `entry; then Off;`のうち`then Off;`側。sourceを持たない暗黙の
        # 初期遷移として、既存のtransitionノード形状を再利用する
        # （_check_transitionはsource=Noneの場合チェックをスキップする）。
        return {
            "type": "transition",
            "name": None,
            "source": None,
            "target": _qualified_name_text(ctx.target),
            "trigger": None,
            "guard": None,
            "effect": None,
            "children": [],
        }

    # --- フェーズ2続き: port def / port usage ------------------------------------

    def visitPortDef(self, ctx: SysMLMinParser.PortDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "port_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitPortUsage(self, ctx: SysMLMinParser.PortUsageContext) -> Dict:
        # partUsageと同様のredefinition機能一式（visibility・ref・名前省略・
        # redefine節）とbodyを持つ。
        id_ctx = ctx.ID()
        # `port xxx : ~xxxx;`という共役ポート参照。linter.py
        # （_check_conjugated_port_typing）はtype_nameが`~`始まりであることを
        # 前提に意味チェックするため、ここで`~`を先頭に合成する。
        type_name = None
        if id_ctx is not None:
            type_name = ("~" + id_ctx.getText()) if ctx.conjugated is not None else id_ctx.getText()
        # redefinesは常にリスト（0件含む）。
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        visibility_ctx = ctx.visibilityIndicator()
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "port_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_name": type_name,
            # `port xxx[xx] : xxxx;`（多重度が型節より先）・`port xxx : xxxx[xx];`
            # （通常順）の両方があるため、preMult/postMultという別ラベルの
            # どちらか一方（両方同時に現れる実例は無い）を読む。
            "multiplicity": self._multiplicity_dict(ctx.preMult if ctx.preMult is not None else ctx.postMult),
            "inheritance": None,
            "isAbstract": ctx.isAbstract is not None,
            "isConstant": ctx.isConstant is not None,
            "isRef": ctx.isRef is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "redefines": redefines,
            "children": children,
        }

    def visitFeatureUsage(self, ctx: SysMLMinParser.FeatureUsageContext) -> Dict:
        # part/port/attribute等の型種別キーワードを一切伴わない裸のfeature
        # 宣言(`ref self: Part :>> Item::self;`等)。attributeUsage/partUsageと
        # 同じ設計を再利用する。型節はattributeUsageと同様、`SysML::Usage`
        # のような修飾名を許すためnamespacePathを使う（part/portUsageの
        # `: ID`とは異なる）。`ref sentMessage :>> sentTransfer:
        # MessageTransfer, MessageAction { ... }`のように型節がカンマ区切りの
        # 複数型を取ることもある。
        type_names = [_namespace_path_text(p) for p in ctx.typeList.namespacePath()] if ctx.typeList is not None else []
        type_name = type_names[0] if type_names else None
        # redefinesは常にリスト（0件含む）。
        redefines = self._redefine_list_namespace(ctx.preKind, ctx.preTarget) + self._redefine_list_namespace(
            ctx.postKind, ctx.postTarget
        )
        visibility_ctx = ctx.visibilityIndicator()
        children = [self.visit(el) for el in ctx.partBodyElement()]
        # `default expression`値節（itemUsage/subjectUsage/requirementUsage
        # 等と同型）と、`ref :>> baseType = causes as SysML::Usage;`
        # （CauseAndEffect.sysml）という`=`値代入の両方を持つ。
        return {
            "type": "feature_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_name": type_name,
            **({"type_names": type_names} if len(type_names) > 1 else {}),
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "inheritance": None,
            "isAbstract": ctx.isAbstract is not None,
            "isConstant": ctx.isConstant is not None,
            "isRef": ctx.isRef is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "redefines": redefines,
            "value": self.visit(ctx.value) if ctx.value is not None else None,
            "defaultValue": self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None,
            "children": children,
        }

    # --- フェーズ2続き: import -----------------------------------------------------

    # --- フェーズ2続き: interface def ------------------------------------------

    def visitInterfaceDef(self, ctx: SysMLMinParser.InterfaceDefContext) -> Dict:
        # 公式のInterfaceBody（'end'メンバーが第一級市民）は未対応。
        # part defと同じpartBodyElementを暫定的に流用する簡略形。
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "interface_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitInterfaceUsage(self, ctx: SysMLMinParser.InterfaceUsageContext) -> Dict:
        # `abstract interface interfaces: Interface[0..*] nonunique :>
        # connections { ... }`という、`connect`を伴わない裸のinterface
        # usage形（connection/allocation/message/flow等と同型）。
        if ctx.multiplicitySpec() is not None or len(ctx.postKind) > 0 or ctx.partBodyElement() or ctx.simpleName() is None:
            id_ctx = ctx.ID()
            redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
            return {
                "type": "interface_usage",
                "name": _optional_simple_name_text(ctx.simpleName()),
                "type_name": id_ctx.getText() if id_ctx is not None else None,
                "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
                "isAbstract": ctx.isAbstract is not None,
                "redefines": redefines,
                "children": [self.visit(el) for el in ctx.partBodyElement()],
            }
        ends = ctx.connectorEnd()
        interface_part = self._binary_part("binary_interface_part", ends[0], ends[1]) if len(ends) == 2 else None
        return {
            "type": "interface_usage",
            "name": _simple_name_text(ctx.simpleName()),
            "type_name": ctx.ID().getText(),
            "interface_part": interface_part,
            "isAbstract": ctx.isAbstract is not None,
            "children": [],
        }

    def visitExposeStmt(self, ctx: SysMLMinParser.ExposeStmtContext) -> Dict:
        # exposeノードは{"type": "special_stmt", "children": [{"type":
        # "expose", ...}]}という入れ子で返す。
        is_wildcard = any(child.getText() == "*" for child in ctx.getChildren())
        expose_node = {
            "type": "expose",
            "qualified_name": _namespace_path_text(ctx.namespacePath()),
            "wildcard": is_wildcard,
            "children": [],
        }
        return {"type": "special_stmt", "children": [expose_node]}

    # --- フェーズ2続き: type def --------------------------------------------------

    def visitTypeDef(self, ctx: SysMLMinParser.TypeDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "type_def",
            "name": _simple_name_text(ctx.simpleName()),
            "attributes": [],
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    # --- フェーズ2続き: connection def / allocation def / activity def -------------

    def visitConnectionDef(self, ctx: SysMLMinParser.ConnectionDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.connectionBodyElement()]
        return {
            "type": "connection_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitConnectionBodyElement(self, ctx: SysMLMinParser.ConnectionBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitConnectionEndMember(self, ctx: SysMLMinParser.ConnectionEndMemberContext) -> Dict:
        # `end occurrence source: Occurrence :>> Message::source,
        # FlowTransfer::source;`・`end theCauses [*] occurrence theCause :>
        # causes :>> source { ... }`のように、`occurrence`/`port`/`item`
        # キーワード・`ref`修飾子・redefine節・body・connector end自体の
        # 別名（`endName [mult]`）を持つ。`name`は常に内側featureの実際の
        # 宣言名（キーワード無し形では`endName`がそれを兼ねる）を優先する。
        inner_mult_ctx = None
        for m in ctx.multiplicitySpec():
            if m is not ctx.endMult:
                inner_mult_ctx = m
                break
        id_ctx = ctx.ID()
        redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
        end_name = _optional_simple_name_text(ctx.endName)
        inner_name = _optional_simple_name_text(ctx.innerName)
        # `end p2: ~P;`という共役ポート参照。portUsageと同じく、`~`を
        # type_nameの先頭に合成する（2026-08-28、参照実装比較レポートP1-4で
        # 発見）。
        type_name = None
        if id_ctx is not None:
            type_name = ("~" + id_ctx.getText()) if ctx.conjugated is not None else id_ctx.getText()
        return {
            "type": "connection_end_member",
            "name": inner_name or end_name,
            "endName": end_name,
            "kind": ctx.kind.text if ctx.kind is not None else None,
            "isRef": ctx.isRef is not None,
            "type_name": type_name,
            "multiplicity": self._multiplicity_dict(inner_mult_ctx),
            "endMultiplicity": self._multiplicity_dict(ctx.endMult),
            "redefines": redefines,
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitAllocationDef(self, ctx: SysMLMinParser.AllocationDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "allocation_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": children,
        }

    def visitAllocationUsage(self, ctx: SysMLMinParser.AllocationUsageContext) -> Dict:
        # `abstract allocation allocations: Allocation[0..*] nonunique :>
        # binaryConnections { ... }`のように、`allocate`節を伴わない
        # multiplicity・redefine節・bodyの形も持つ。
        ends = ctx.connectorEnd()
        connector_part = self._binary_part("binary_connector_part", ends[0], ends[1]) if len(ends) == 2 else None
        name_ctx = ctx.simpleName()
        type_ctx = ctx.ID()
        redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
        return {
            "type": "allocation_usage",
            "name": _simple_name_text(name_ctx) if name_ctx is not None else None,
            "type_name": type_ctx.getText() if type_ctx is not None else None,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "redefines": redefines,
            "connector_part": connector_part,
            "isAbstract": ctx.isAbstract is not None,
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitMessageUsage(self, ctx: SysMLMinParser.MessageUsageContext) -> Dict:
        # `abstract message messages: Message[0..*] nonunique :> transfers,
        # actions { ... }`（Flows.sysml）という、`from`/`to`を伴わない
        # 裸の`message`usage形。
        id_ctx = ctx.ID()
        redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
        # `of Publish[1]`というペイロード型節（2026-08-28、参照実装比較
        # レポートP2-1で発見）。`: ID`形との排他的代替。
        if ctx.payloadType is not None:
            type_name = _namespace_path_text(ctx.payloadType)
        elif id_ctx is not None:
            type_name = id_ctx.getText()
        else:
            type_name = None
        return {
            "type": "message_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_name": type_name,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "isAbstract": ctx.isAbstract is not None,
            "redefines": redefines,
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitActivityDef(self, ctx: SysMLMinParser.ActivityDefContext) -> Dict:
        params = [self.visit(el) for el in ctx.actionBodyElement()]
        return {
            "type": "activity_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "params": params,
            "children": [],
        }

    # --- フェーズ2続き: 式 ---------------------------------------------------------
    #
    # linter.py はcalculation_def/constraint_def/assert_constraint_usageの
    # 式の中身までは検証しない（name/inheritance/type_nameしか読まない）ため、
    # ここで定義する形は「新パーサーが構文的に式を受理できる」ことだけが目的で、
    # linter.pyとの契約は無い。

    def visitPowerExpr(self, ctx: SysMLMinParser.PowerExprContext) -> Dict:
        # `^`べき乗演算子（例: `s^-1`、`Triangle::length^2`）。
        return self._binary_expr(ctx)

    def visitMulDivExpr(self, ctx: SysMLMinParser.MulDivExprContext) -> Dict:
        return self._binary_expr(ctx)

    def visitAddSubExpr(self, ctx: SysMLMinParser.AddSubExprContext) -> Dict:
        return self._binary_expr(ctx)

    def visitQuantityLiteralExpr(self, ctx: SysMLMinParser.QuantityLiteralExprContext) -> Dict:
        # `0 [m]`・`273.15 [K]`・`229835/900 [K]`のように、数値リテラル
        # （または算術式）に単位を角括弧で付与するquantity literal記法。
        # `num#(1) [mRef.mRefs#(1)]`のように、単位節が`#()`インデックス
        # アクセスを伴う式のこともあるため単位節の型は`expression`。
        # `unit`ラベルの有無に関わらず`ctx.expression()`は両方（本体・単位）を
        # 含むリストを返すため、先頭（本体）を明示的に選ぶ。
        return {
            "type": "quantity_literal",
            "value": self.visit(ctx.expression(0)),
            "unit": self.visit(ctx.unit),
            "children": [],
        }

    def visitRelationalExpr(self, ctx: SysMLMinParser.RelationalExprContext) -> Dict:
        return self._binary_expr(ctx)

    def visitEqualityExpr(self, ctx: SysMLMinParser.EqualityExprContext) -> Dict:
        return self._binary_expr(ctx)

    def visitLogicalAndExpr(self, ctx: SysMLMinParser.LogicalAndExprContext) -> Dict:
        # `and`/`or`論理演算子。
        return self._binary_expr(ctx)

    def visitLogicalOrExpr(self, ctx: SysMLMinParser.LogicalOrExprContext) -> Dict:
        return self._binary_expr(ctx)

    def visitImpliesExpr(self, ctx: SysMLMinParser.ImpliesExprContext) -> Dict:
        # `implies`論理演算子。
        return self._binary_expr(ctx)

    def visitConditionalExpr(self, ctx: SysMLMinParser.ConditionalExprContext) -> Dict:
        # `if cond ? then else elseExpr`。elseExprが`expression`を再帰参照
        # するため、else-if連鎖
        # （elseExprに別のconditionalExprが入れ子になる形）は自動的に
        # 表現できる。
        return {
            "type": "conditional_expr",
            "condition": self.visit(ctx.cond),
            "then": self.visit(ctx.thenExpr),
            "else": self.visit(ctx.elseExpr),
            "children": [],
        }

    def _binary_expr(self, ctx) -> Dict:
        left, right = ctx.expression(0), ctx.expression(1)
        return {
            "type": "binary_expr",
            "op": ctx.op.text,
            "left": self.visit(left),
            "right": self.visit(right),
        }

    def visitUnaryMinusExpr(self, ctx: SysMLMinParser.UnaryMinusExprContext) -> Dict:
        return {"type": "unary_expr", "op": "-", "operand": self.visit(ctx.expression())}

    def visitNotExpr(self, ctx: SysMLMinParser.NotExprContext) -> Dict:
        return {"type": "unary_expr", "op": "not", "operand": self.visit(ctx.expression())}

    def visitParenExpr(self, ctx: SysMLMinParser.ParenExprContext) -> Dict:
        # 括弧はグルーピングのみの意味なので、内側の式をそのまま返す。
        return self.visit(ctx.expression())

    def visitRangeExpr(self, ctx: SysMLMinParser.RangeExprContext) -> Dict:
        # `(1..size(seq))`という範囲式（KerMLのRangeExpression、
        # `multiplicityBracket`の`..`とは別）。
        return {
            "type": "range_expr",
            "lower": self.visit(ctx.lower),
            "upper": self.visit(ctx.upper),
            "children": [],
        }

    def visitSequenceExpr(self, ctx: SysMLMinParser.SequenceExprContext) -> Dict:
        # `(a, b, c)`という括弧+カンマ区切りの列挙式（例:
        # `:>> quantityPowerFactors = (lengthPF, massPF, durationPF);`。
        # 公式コーパスで11ファイルが使用）。
        return {
            "type": "sequence",
            "elements": [self.visit(e) for e in ctx.expression()],
            "children": [],
        }

    def visitEmptySequenceExpr(self, ctx: SysMLMinParser.EmptySequenceExprContext) -> Dict:
        # 空の列挙式`()`。
        return {"type": "sequence", "elements": [], "children": []}

    def visitIndexExpr(self, ctx: SysMLMinParser.IndexExprContext) -> Dict:
        # KerMLのインデックスアクセス式`base#(index)`（例: `mRefs#(1)`、
        # `mRef.mRefs#(1)`。公式コーパスで6ファイル・99件使用）。
        base_ctx, index_ctx = ctx.expression()
        return {
            "type": "index_access",
            "base": self.visit(base_ctx),
            "index": self.visit(index_ctx),
            "children": [],
        }

    def visitMemberAccessExpr(self, ctx: SysMLMinParser.MemberAccessExprContext) -> Dict:
        # 任意の式に対する後置`.member`アクセス（例: `(that as Action).this`、
        # `(edges#(i).vertices#(2) as Item).matingOccurrences`）。裸の名前
        # 参照（`a.b.c`）はqualifiedNameが貪欲に消費するためnameRefExprが
        # 担い、本規則はそれ以外の式（cast結果・関数呼び出し結果等）にのみ
        # 実際に使われる。
        return {
            "type": "member_access",
            "base": self.visit(ctx.expression()),
            "member": _simple_name_text(ctx.member),
            "children": [],
        }

    def visitAsCastExpr(self, ctx: SysMLMinParser.AsCastExprContext) -> Dict:
        # KerMLの型キャスト式（`expr as Type`。例: `that as Occurrence`、
        # `causes as SysML::Usage`）。
        return {
            "type": "as_cast",
            "base": self.visit(ctx.expression()),
            "type_name": _namespace_path_text(ctx.typeRef),
            "children": [],
        }

    def visitMetaExpr(self, ctx: SysMLMinParser.MetaExprContext) -> Dict:
        # KerMLの`meta`式（`expr meta Type`。例: `multicausations meta
        # SysML::Usage`）。`asCastExpr`と同型。
        return {
            "type": "meta_expr",
            "base": self.visit(ctx.expression()),
            "type_name": _namespace_path_text(ctx.typeRef),
            "children": [],
        }

    def visitFunctionCallExpr(self, ctx: SysMLMinParser.FunctionCallExprContext) -> Dict:
        # `size(x)`、`getDifference(a, b)`のような関数呼び出し式（引数0個以上）。
        # 呼び出し先は`::`修飾名（`NumericalFunctions::isZero(x.num)`）も
        # 取りうる。`tradeStudyObjective(selectedAlternative = a)`のように
        # 名前付き引数も取れるよう`newArgument`（`new_instance`と同じ位置
        # 引数/名前付き引数の判別ロジック）を使う。そのため各引数要素は
        # 生の式ではなく`{"type": "positional_argument"/"named_argument", ...}`
        # でラップされる（`new_instance`と同型）。
        return {
            "type": "function_call",
            "name": _namespace_path_text(ctx.namespacePath()),
            "arguments": [self.visit(a) for a in ctx.newArgument()],
            "children": [],
        }

    def visitArrowCallExpr(self, ctx: SysMLMinParser.ArrowCallExprContext) -> Dict:
        # `->`演算子の丸括弧呼び出し形（例:
        # `derivedRequirements->excludes(originalRequirement)`、
        # `seq->excludingAt(position)`）。`ctx.expression()`は先頭がreceiver、
        # 残りが引数（indexExprと同様、2箇所以上での出現のためlistで返る）。
        exprs = ctx.expression()
        receiver_ctx, arg_ctxs = exprs[0], exprs[1:]
        return {
            "type": "arrow_call",
            "receiver": self.visit(receiver_ctx),
            "name": _simple_name_text(ctx.opName),
            "arguments": [self.visit(e) for e in arg_ctxs],
            "children": [],
        }

    def visitArrowLambdaExpr(self, ctx: SysMLMinParser.ArrowLambdaExprContext) -> Dict:
        # `->forAll { in x : T; expr }`のような波括弧ラムダ式風本体を持つ
        # 反復系collection operation。パラメータ宣言（`lambdaParam`）は
        # 省略可能（`->minimize { doc ... expr }`
        # のように無い場合もある）。doc comment（bareDocComment）は構文サポート
        # のみが目的のため出力には含めない。
        body_ctx = ctx.arrowLambdaBody()
        param_ctx = body_ctx.lambdaParam()
        param = None
        if param_ctx is not None:
            type_ctx = param_ctx.namespacePath()
            param = {
                "name": _simple_name_text(param_ctx.simpleName()),
                "isRef": param_ctx.isRef is not None,
                "typeName": _namespace_path_text(type_ctx) if type_ctx is not None else None,
            }
        return {
            "type": "arrow_lambda",
            "receiver": self.visit(ctx.expression()),
            "name": _simple_name_text(ctx.opName),
            "param": param,
            "body": self.visit(body_ctx.expression()),
            "children": [],
        }

    def visitNewExpr(self, ctx: SysMLMinParser.NewExprContext) -> Dict:
        # `new TypeName(name = expr, ...)`というKerMLのインスタンス生成式。
        return {
            "type": "new_instance",
            "name": _qualified_name_text(ctx.qualifiedName()),
            "arguments": [self.visit(a) for a in ctx.newArgument()],
            "children": [],
        }

    def visitNewArgument(self, ctx: SysMLMinParser.NewArgumentContext) -> Dict:
        # `new SamplePair(x, calculation(x))`のように、名前無しの位置引数
        # （bare expression）も受理する。
        name_ctx = ctx.simpleName()
        if name_ctx is None:
            return {
                "type": "positional_argument",
                "value": self.visit(ctx.expression()),
                "children": [],
            }
        return {
            "type": "named_argument",
            "name": _simple_name_text(name_ctx),
            "value": self.visit(ctx.expression()),
            "children": [],
        }

    def visitNameRefExpr(self, ctx: SysMLMinParser.NameRefExprContext) -> Dict:
        return {"type": "name_ref", "reference": _qualified_name_text(ctx.qualifiedName())}

    def visitNamespacePathRefExpr(self, ctx: SysMLMinParser.NamespacePathRefExprContext) -> Dict:
        # `::`修飾名（`MeasurementUnit::unitPowerFactors`）による式。
        # nameRefExprと同形状のASTを返す（reference文字列は`::`区切りの
        # まま保持）。
        return {"type": "name_ref", "reference": _namespace_path_text(ctx.namespacePath())}

    def visitLiteralExpr(self, ctx: SysMLMinParser.LiteralExprContext) -> Dict:
        return self.visit(ctx.literal())

    def visitLiteral(self, ctx: SysMLMinParser.LiteralContext) -> Dict:
        if ctx.INT_LITERAL() is not None:
            # `1E-24`は仮数部に小数点が無くてもINT_LITERALとして字句解析
            # される（指数部は両トークンで任意扱い）が、負の指数を伴う場合は
            # 整数値ではなく実数値になるため、指数記号の有無でPythonの
            # int()/float()を使い分ける。
            text = ctx.INT_LITERAL().getText()
            if "e" in text or "E" in text:
                return {"type": "literal", "literal_type": "real", "value": float(text)}
            return {"type": "literal", "literal_type": "int", "value": int(text)}
        if ctx.REAL_LITERAL() is not None:
            return {"type": "literal", "literal_type": "real", "value": float(ctx.REAL_LITERAL().getText())}
        if ctx.STRING_LITERAL() is not None:
            raw = ctx.STRING_LITERAL().getText()
            return {"type": "literal", "literal_type": "string", "value": raw[1:-1]}
        # 'true' / 'false'
        return {"type": "literal", "literal_type": "boolean", "value": ctx.getText() == "true"}

    # --- フェーズ2続き: calculation def / constraint def / assert constraint usage --

    def visitCalculationDef(self, ctx: SysMLMinParser.CalculationDefContext) -> Dict:
        # `private calc def ...`のようにvisibilityIndicatorを持ちうる。
        visibility_ctx = ctx.visibilityIndicator()
        children = [self.visit(el) for el in ctx.calcBodyElement()]
        return {
            "type": "calculation_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "children": children,
        }

    def visitConstraintDef(self, ctx: SysMLMinParser.ConstraintDefContext) -> Dict:
        # `private abstract constraint def ...`のようにvisibilityIndicatorを
        # 持ちうる。
        visibility_ctx = ctx.visibilityIndicator()
        children = [self.visit(el) for el in ctx.calcBodyElement()]
        return {
            "type": "constraint_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "children": children,
        }

    def visitCalcBodyElement(self, ctx: SysMLMinParser.CalcBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitResultExpressionMember(self, ctx: SysMLMinParser.ResultExpressionMemberContext) -> Dict:
        return {"type": "result_expression_member", "expression": self.visit(ctx.expression())}

    def visitAssertConstraintUsage(self, ctx: SysMLMinParser.AssertConstraintUsageContext) -> Dict:
        # `assert constraint c;`のようなbare形は
        # {"type":"constraint_stmt","children":[{"type":"assert_constraint_usage",...}]}
        # という入れ子で返す。simpleNameが省略された形（`assert constraint
        # { expr }`）・bodyが単一の真偽式のみの形（`resultExpr`）にも対応する。
        # 名前付きconstraint defを型として参照する形（`assert constraint 名前 :
        # 型参照 { in param = value; ... }`）ではtypeRefがあれば`type_name`へ
        # 反映する（`_check_assert_constraint_usage`が既存の存在チェックに
        # そのまま使う）。`private assert constraint ...`のように、
        # visibilityIndicatorを持つ形にも対応する（calculationDef/
        # constraintDefと同じ`visibility`フィールド）。
        is_negated = any(child.getText() == "not" for child in ctx.getChildren())
        # `resultExpr`代替の前には`documentationStmt*`が付きうるため、
        # `calcBodyElement`だけでなくそちらも`children`へ含める。
        children = [self.visit(el) for el in ctx.calcBodyElement()] + [
            self.visit(el) for el in ctx.documentationStmt()
        ]
        result_expression = self.visit(ctx.resultExpr) if ctx.resultExpr is not None else None
        visibility_ctx = ctx.visibilityIndicator()
        inner = {
            "type": "assert_constraint_usage",
            "is_negated": is_negated,
            "name": _optional_simple_name_text(ctx.simpleName()),
            "type_name": _namespace_path_text(ctx.typeRef) if ctx.typeRef is not None else "",
            "result_expression": result_expression,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "children": children,
        }
        return {"type": "constraint_stmt", "children": [inner]}

    # --- フェーズ2続き: case / analysis case / verification case / use case ---------
    # --- view / viewpoint / rendering / metadata (8.2.2.22-27) ---------------------
    #
    # 17構文すべてが `{"type": <node_type>, "name": str,
    # "inheritance": {...} | None, "children": [...]}` という同一の形
    # （part_defと同型）で、linter.pyの対応するチェック関数
    # （_check_case_def等、linter.py:1923-2101）もいずれもnameしか読まない
    # ため、共通ヘルパーでまとめて処理する（inheritanceは_check_
    # subclassification_part等の汎用チェック(linter.py:2302)向け）。

    def _named_simple_node(self, node_type: str, ctx) -> Dict:
        # `metadata def <cause> ...`/`view def <gv> ...`のようにShortName
        # 注釈を取りうる規則(metadataDef/viewDef)と取らない規則(この共通
        # ヘルパーを使う残り15規則)が混在するため、`getattr`で安全に読む
        # （無い規則はctx.shortName属性自体が無い）。
        short_name_token = getattr(ctx, "shortName", None)
        return {
            "type": node_type,
            "name": _simple_name_text(ctx.simpleName()),
            "shortName": short_name_token.text if short_name_token is not None else None,
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitCaseDef(self, ctx: SysMLMinParser.CaseDefContext) -> Dict:
        return self._named_simple_node("case_def", ctx)

    def visitCaseUsage(self, ctx: SysMLMinParser.CaseUsageContext) -> Dict:
        # 公式コーパスでは`ref case ...`/`case :>> name ...`のように
        # partUsage/featureUsageと同型のredefinition機能一式が必要なため、
        # `_named_simple_node`（inheritanceClause前提）ではなく
        # `_usage_keyword_node`（redefine節前提）を使う。`_def`側は
        # inheritanceClause前提のままでよい。
        return self._usage_keyword_node("case_usage", ctx, ctx.partBodyElement())

    def visitAnalysisCaseDef(self, ctx: SysMLMinParser.AnalysisCaseDefContext) -> Dict:
        return self._named_simple_node("analysis_case_def", ctx)

    def visitAnalysisCaseUsage(self, ctx: SysMLMinParser.AnalysisCaseUsageContext) -> Dict:
        return self._usage_keyword_node("analysis_case_usage", ctx, ctx.partBodyElement())

    def visitVerificationCaseDef(self, ctx: SysMLMinParser.VerificationCaseDefContext) -> Dict:
        return self._named_simple_node("verification_case_def", ctx)

    def visitVerificationCaseUsage(self, ctx: SysMLMinParser.VerificationCaseUsageContext) -> Dict:
        return self._usage_keyword_node("verification_case_usage", ctx, ctx.partBodyElement())

    def visitUseCaseDef(self, ctx: SysMLMinParser.UseCaseDefContext) -> Dict:
        return self._named_simple_node("use_case_def", ctx)

    def visitUseCaseUsage(self, ctx: SysMLMinParser.UseCaseUsageContext) -> Dict:
        return self._usage_keyword_node("use_case_usage", ctx, ctx.partBodyElement())

    def visitIncludeUseCaseUsage(self, ctx: SysMLMinParser.IncludeUseCaseUsageContext) -> Dict:
        return {
            "type": "include_use_case_usage",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": None,
            "children": [],
        }

    def visitViewDef(self, ctx: SysMLMinParser.ViewDefContext) -> Dict:
        return self._named_simple_node("view_def", ctx)

    def visitViewUsage(self, ctx: SysMLMinParser.ViewUsageContext) -> Dict:
        # `ref view :>> self : View;`等、他のusageキーワード規則と同型の
        # redefinition機能一式を持つ。
        return self._usage_keyword_node("view_usage", ctx, ctx.partBodyElement())

    def visitViewpointDef(self, ctx: SysMLMinParser.ViewpointDefContext) -> Dict:
        return self._named_simple_node("viewpoint_def", ctx)

    def visitViewpointUsage(self, ctx: SysMLMinParser.ViewpointUsageContext) -> Dict:
        return self._usage_keyword_node("viewpoint_usage", ctx, ctx.partBodyElement())

    def visitRenderingDef(self, ctx: SysMLMinParser.RenderingDefContext) -> Dict:
        return self._named_simple_node("rendering_def", ctx)

    def visitRenderingUsage(self, ctx: SysMLMinParser.RenderingUsageContext) -> Dict:
        # `rendering :>> subrenderings[0..*] = columnView.viewRendering;`
        # （Views.sysml）のように、redefine対象へ`=`で直接式を代入する形も
        # ある。requirementUsageと同じインライン`= expression`値代入を持つ。
        node = self._usage_keyword_node("rendering_usage", ctx, ctx.partBodyElement())
        node["value"] = self.visit(ctx.value) if ctx.value is not None else None
        return node

    def visitMetadataDef(self, ctx: SysMLMinParser.MetadataDefContext) -> Dict:
        return self._named_simple_node("metadata_def", ctx)

    def visitMetadataUsageKeyword(self, ctx: SysMLMinParser.MetadataUsageKeywordContext) -> Dict:
        return self._named_simple_node("metadata_usage", ctx)

    def visitMetadataUsageShorthand(self, ctx: SysMLMinParser.MetadataUsageShorthandContext) -> Dict:
        # `@Classified { ... }`/`@Security;`という`metadata`キーワード省略形。
        return {
            "type": "metadata_usage",
            "name": _namespace_path_text(ctx.typeRef),
            "shortName": None,
            "inheritance": None,
            "isAbstract": False,
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    # --- フェーズ2続き: comment / documentation / textual representation (8.2.2.4) --
    #
    # `_check_comment_stmt`/`_check_documentation_stmt`/`_check_textual_representation_stmt`
    # （linter.py。同名メソッドが2箇所あり後方の定義が有効）が読む
    # `identification`/`body`/`language` に合わせる。
    #
    # requirementBodyElement内のdocMember（`doc` DOC_COMMENT、名前無し）とは別の
    # 規則。docMemberは意図的にidentification無しのままにしてある。

    def _doc_comment_body_text(self, token) -> str:
        raw = token.getText()
        return raw[2:-2].strip()

    def _identification(self, simple_name_ctx):
        if simple_name_ctx is None:
            return None
        return {"type": "identification", "name": _simple_name_text(simple_name_ctx)}

    def visitCommentStmt(self, ctx: SysMLMinParser.CommentStmtContext) -> Dict:
        return {
            "type": "comment",
            "identification": self._identification(ctx.simpleName()),
            # `comment about C /* ... */`のようなコメント対象の明示
            # （2026-08-28、参照実装比較レポートP1-5で発見）。
            "about": _namespace_path_text(ctx.about) if ctx.about is not None else None,
            "locale": ctx.locale.text[1:-1] if ctx.locale is not None else None,
            "body": self._doc_comment_body_text(ctx.DOC_COMMENT()),
            "children": [],
        }

    def visitDocumentationStmt(self, ctx: SysMLMinParser.DocumentationStmtContext) -> Dict:
        return {
            "type": "documentation",
            "identification": self._identification(ctx.simpleName()),
            # `doc locale "en_US" /* ... */`のようなロケール注釈
            # （2026-08-28、参照実装比較レポートP1-5で発見）。
            "locale": ctx.locale.text[1:-1] if ctx.locale is not None else None,
            "body": self._doc_comment_body_text(ctx.DOC_COMMENT()),
            "children": [],
        }

    def visitBareDocComment(self, ctx: SysMLMinParser.BareDocCommentContext) -> Dict:
        # `doc`/`comment`キーワードを伴わない裸の`/* ... */`。
        # documentationStmtの名前無し形と同じAST形状で出力する
        # （_check_documentation_stmtはidentification=Noneを許容する）。
        return {
            "type": "documentation",
            "identification": None,
            "locale": ctx.locale.text[1:-1] if ctx.locale is not None else None,
            "body": self._doc_comment_body_text(ctx.DOC_COMMENT()),
            "children": [],
        }

    def visitAliasStmt(self, ctx: SysMLMinParser.AliasStmtContext) -> Dict:
        # KerMLの`alias`文（別名宣言）。`alias name for target;`のname/target
        # 双方ともQUOTED_NAME形式（記号を含む名前）を取りうるため、両方
        # simpleNameで受ける。`;`終端に加え、bodyを持つ形（`alias X for Y
        # { doc /* ... */ }`）も許容する。
        return {
            "type": "alias",
            "name": _simple_name_text(ctx.simpleName()),
            "target": _namespace_path_text(ctx.target),
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitTextualRepresentationStmt(self, ctx: SysMLMinParser.TextualRepresentationStmtContext) -> Dict:
        language_raw = ctx.language.text
        return {
            "type": "textual_representation",
            "identification": self._identification(ctx.simpleName()),
            "language": language_raw[1:-1],
            # `language "OCL" locale "en_US" /* ... */`のようなロケール注釈
            # （2026-08-28、参照実装比較レポートP1-5で発見）。
            "locale": ctx.locale.text[1:-1] if ctx.locale is not None else None,
            "body": self._doc_comment_body_text(ctx.DOC_COMMENT()),
            "children": [],
        }

    # --- フェーズ2続き: multiplicity (8.2.2.6.6) ------------------------------------
    #
    # `_check_rules`（linter.py:301）は `node["multiplicity"]` があれば
    # `_check_multiplicity` を呼ぶ。3種類ある対応形式のうち、最も単純な
    # レガシーsize辞書形式（{"size": {"min":..., "max":...}}）を使う
    # （owned_multiplicity等の深い入れ子は未対応）。

    def _multiplicity_bound_value(self, ctx):
        # `[nCauses]`のような、数値リテラルではなく同一body内のattributeを
        # 指す識別子（記号的多重度）の場合はテキストのまま返す。
        if ctx is None:
            return None
        text = ctx.getText()
        if text == "*":
            return "*"
        try:
            return int(text)
        except ValueError:
            return text

    def _multiplicity_dict(self, spec_ctx):
        """MultiplicitySpecContext(bracket + 任意のordered/nonunique修飾子)から
        `node["multiplicity"]` の値を組み立てる。

        `ordered`/`nonunique`はpart_instance等の"multiplicity"型dictへ直接
        （8.2.2.6.6準拠の"multiplicity_part"という別の深い入れ子ではなく）
        is_ordered/is_uniqueとして埋め込む。ただし`_check_multiplicity`は
        is_ordered/is_uniqueを一切読まないため、装飾的なフィールドとして
        レガシーsize辞書に追加するだけになっている。
        """
        if spec_ctx is None:
            return None
        bracket_ctx = spec_ctx.multiplicityBracket()
        if bracket_ctx.bound is not None:
            value = self._multiplicity_bound_value(bracket_ctx.bound)
            size = {"min": value, "max": value}
        else:
            size = {
                "min": self._multiplicity_bound_value(bracket_ctx.lower),
                "max": self._multiplicity_bound_value(bracket_ctx.upper),
            }

        modifiers_ctx = spec_ctx.multiplicityModifiers()
        is_ordered = modifiers_ctx is not None and modifiers_ctx.ordered is not None
        is_unique = modifiers_ctx is None or modifiers_ctx.nonunique is None
        return {"size": size, "is_ordered": is_ordered, "is_unique": is_unique}

    def visitImportStmt(self, ctx: SysMLMinParser.ImportStmtContext) -> Dict:
        is_wildcard = any(child.getText() == "*" for child in ctx.getChildren())
        visibility_ctx = ctx.visibilityIndicator()
        return {
            "type": "import",
            "name": _namespace_path_text(ctx.namespacePath()),
            "wildcard": is_wildcard,
            "visibility": visibility_ctx.getText() if visibility_ctx is not None else None,
            "children": [],
        }

    # --- dependency / event occurrence usage / exhibit state usage / portion usage --

    def visitDependencyStmt(self, ctx: SysMLMinParser.DependencyStmtContext) -> Dict:
        # {"type":"special_stmt","children":[{"type":"dependency",...}]}という
        # 入れ子で返す。identification（名前部分）は無視する。
        clients = [_namespace_path_text(q) for q in ctx.clients.namespacePath()]
        suppliers = [_namespace_path_text(q) for q in ctx.suppliers.namespacePath()]
        # `#refinement dependency X to Y;`のような#Typeプレフィックス注釈
        # （2026-08-28、参照実装比較レポートP0-4で発見）。
        prefix_metadata = [
            _namespace_path_text(a.namespacePath()) for a in ctx.prefixMetadataAnnotation()
        ]
        dependency_node = {
            "type": "dependency",
            "clients": clients,
            "suppliers": suppliers,
            "prefixMetadata": prefix_metadata,
            "children": [],
        }
        return {"type": "special_stmt", "children": [dependency_node]}

    def visitEventOccurrenceUsageStmt(self, ctx: SysMLMinParser.EventOccurrenceUsageStmtContext) -> Dict:
        direction_ctx = ctx.direction()
        type_ctx = ctx.namespacePath()
        return {
            "type": "event_occurrence_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "direction": direction_ctx.getText() if direction_ctx is not None else None,
            "type_name": _namespace_path_text(type_ctx) if type_ctx is not None else None,
            "defaultValue": self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None,
            "ownedReferenceSubsetting": None,
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitExhibitStateUsageStmt(self, ctx: SysMLMinParser.ExhibitStateUsageStmtContext) -> Dict:
        type_ctx = ctx.namespacePath()
        return {
            "type": "exhibit_state_usage",
            "name": _simple_name_text(ctx.simpleName()),
            # `exhibit state 'vehicle states': 'Vehicle States';`のような型節
            # （2026-08-28、参照実装比較レポートP1-2で発見）。
            "type_name": _namespace_path_text(type_ctx) if type_ctx is not None else None,
            "children": [],
        }

    def visitPortionUsageStmt(self, ctx: SysMLMinParser.PortionUsageStmtContext) -> Dict:
        return {
            "type": "portion_usage",
            "kind": ctx.kind.text,
            "name": _optional_simple_name_text(ctx.simpleName()),
            "isThen": ctx.isThen is not None,
            "value": self.visit(ctx.value) if ctx.value is not None else None,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "children": [self.visit(el) for el in ctx.partBodyElement()],
        }

    def visitOccurrenceDef(self, ctx: SysMLMinParser.OccurrenceDefContext) -> Dict:
        children = [self.visit(el) for el in ctx.partBodyElement()]
        return {
            "type": "occurrence_def",
            "name": _simple_name_text(ctx.simpleName()),
            "isIndividual": ctx.isIndividual is not None,
            "isAbstract": ctx.isAbstract is not None,
            "inheritance": self._inheritance_dict(ctx),
            "children": children,
        }

    def visitOccurrenceUsage(self, ctx: SysMLMinParser.OccurrenceUsageContext) -> Dict:
        children = [self.visit(el) for el in ctx.partBodyElement()]
        direction_ctx = ctx.direction()
        redefines = self._redefine_list_namespace(ctx.postKind, ctx.postTarget)
        return {
            "type": "occurrence_usage",
            "name": _optional_simple_name_text(ctx.simpleName()),
            "isPortion": False,
            "portionKind": None,
            "isAbstract": ctx.isAbstract is not None,
            "isConstant": ctx.isConstant is not None,
            "isRef": ctx.isRef is not None,
            "direction": direction_ctx.getText() if direction_ctx is not None else None,
            "redefines": redefines,
            "value": self.visit(ctx.value) if ctx.value is not None else None,
            "defaultValue": self.visit(ctx.defaultValue) if ctx.defaultValue is not None else None,
            "multiplicity": self._multiplicity_dict(ctx.multiplicitySpec()),
            "children": children,
        }

    def visitIndividualDef(self, ctx: SysMLMinParser.IndividualDefContext) -> Dict:
        # `[]`（EmptyMultiplicityMember）は省略されることがある（`individual
        # def IO1;`、IndividualTest.sysml。2026-08-28、参照実装比較レポート
        # P0-3で発見）。省略時は"multiplicity": Noneとし、
        # `_check_individual_definition`（case_and_view_rules.py）が
        # 既存の「空の多重度が必要」というLintIssueとして報告する。
        children = [self.visit(el) for el in ctx.partBodyElement()]
        multiplicity = {"size": None, "is_ordered": False, "is_unique": True} if ctx.emptyMult is not None else None
        return {
            "type": "individual_def",
            "name": _simple_name_text(ctx.simpleName()),
            "multiplicity": multiplicity,
            "isAbstract": ctx.isAbstract is not None,
            "inheritance": self._inheritance_dict(ctx),
            "children": children,
        }

    def visitIndividualUsage(self, ctx: SysMLMinParser.IndividualUsageContext) -> Dict:
        type_ctx = ctx.ID()
        return {
            "type": "individual_usage",
            "name": _simple_name_text(ctx.simpleName()),
            "type_name": type_ctx.getText() if type_ctx is not None else None,
            "isAbstract": ctx.isAbstract is not None,
            "children": [],
        }

    # --- interaction / sequence diagram notation --------------------------------

    def visitInteractionDef(self, ctx: SysMLMinParser.InteractionDefContext) -> Dict:
        # actionDef同様、param型の子だけをparamsへ、それ以外はchildrenへ分離する。
        params = []
        children = []
        for el in ctx.interactionBodyElement():
            node = self.visit(el)
            if isinstance(node, dict) and node.get("type") == "param":
                params.append(node)
            else:
                children.append(node)
        return {
            "type": "interaction_def",
            "name": _simple_name_text(ctx.simpleName()),
            "inheritance": self._inheritance_dict(ctx),
            "isAbstract": ctx.isAbstract is not None,
            "params": params,
            "children": children,
        }

    def visitInteractionBodyElement(self, ctx: SysMLMinParser.InteractionBodyElementContext) -> Dict:
        return self.visit(ctx.getChild(0))

    def visitParticipantMember(self, ctx: SysMLMinParser.ParticipantMemberContext) -> Dict:
        return {
            "type": "participant",
            "name": _simple_name_text(ctx.simpleName()),
            "type_name": ctx.ID().getText(),
            "children": [],
        }

    def visitFragmentStmt(self, ctx: SysMLMinParser.FragmentStmtContext) -> Dict:
        name_ctx = ctx.simpleName()
        return {
            "type": "fragment",
            "kind": ctx.kind.text,
            "name": _simple_name_text(name_ctx) if name_ctx is not None else None,
            "operands": [self.visit(op) for op in ctx.operandBlock()],
        }

    def visitOperandBlock(self, ctx: SysMLMinParser.OperandBlockContext) -> Dict:
        is_else = any(child.getText() == "else" for child in ctx.getChildren())
        children = [self.visit(el) for el in ctx.interactionBodyElement()]
        return {
            "type": "operand",
            "guard": self.visit(ctx.guard) if ctx.guard is not None else None,
            "is_else": is_else,
            "children": children,
        }


def parse_sysml_antlr(text: str) -> Dict:
    """ANTLR4（SysMLMin.g4）でパースする。

    範囲外の構文はparse_sysml()と同じ{"type": "error", "message": "..."}形式で
    失敗を報告する。
    """
    input_stream = InputStream(text)
    error_listener = _CollectingErrorListener()

    lexer = SysMLMinLexer(input_stream)
    lexer.removeErrorListeners()
    lexer.addErrorListener(error_listener)

    token_stream = CommonTokenStream(lexer)
    parser = SysMLMinParser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(error_listener)

    tree = parser.model()

    if error_listener.errors:
        return {"type": "error", "message": "; ".join(error_listener.errors)}

    return SysMLMinASTVisitor().visit(tree)
