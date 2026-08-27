// SysMLMin.g4
//
// SysML v2の全構文を網羅する文法ではなく、実務でよく使われる構文を優先して
// 段階的に広げている。各規則には、参照した公式文法
// （Systems-Modeling/SysML-v2-Pilot-Implementation の KerML.xtext / SysML.xtext）の
// 対応規則名をコメントで残す（そのまま転記はせず、素のANTLR4構文に書き直している）。

grammar SysMLMin;

// KerML.xtext の `RootNamespace`（`start: top_level_stmt*` に相当）を反映。
// .sysml ファイルそのものが暗黙のルート名前空間であり、`package { }` で
// 包む必要はない（`private import ...;` などがファイル先頭に直接書けるのはこのため）。
model
    : topLevelElement* EOF
    ;

// package はネスト可能（bodyが再び topLevelElement* を持つ）。
topLevelElement
    : packageDef
    | packageBodyElement
    ;

// LibraryPackage修飾子（KerML.xtext PackageDeclaration相当）。公式標準ライブラリの
// 全ファイルが `standard library package X { ... }` から始まり、他に
// `library package X { ... }` の形も実在する（公式SysML v2 Pilot
// Implementationのsysml.libraryで確認済み）。
// `standard library package <USCU> USCustomaryUnits { ... }`のように、
// packageもKerMLのShortName注釈（attributeUsageと同じ仕組み）を
// 取りうる（公式コーパスで1件）。
packageDef
    : ('standard')? ('library')? 'package' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName '{' topLevelElement* '}'
    ;

packageBodyElement
    : partDef
    | partUsage
    | attributeUsage
    | attributeDef
    | itemDef
    // `abstract item items : Item[0..*] nonunique :> objects { doc ... }`
    // （Items.sysml）のように、`itemUsage`はpackage直下にも書ける。
    | itemUsage
    | enumDef
    | typeDef
    | actionDef
    // `abstract flow def MessageAction :> Action, Link { ... }`（Flows.sysml）。
    | flowDef
    | requirementDef
    // `requirement originalRequirements[*] { ... }`（DerivationConnections.sysml）
    // のように、パッケージ直下の裸のrequirement/concern usageも存在する。
    | requirementUsage
    | concernDef
    | concernUsage
    | stateDef
    // `abstract state stateActions: StateAction[0..*] nonunique :> actions
    // { doc ... }`（States.sysml）のように、`stateUsage`はpackage直下にも
    // 書ける。
    | stateUsage
    | connectUsage
    | connectionUsage
    | portDef
    // `abstract port ports : Port[0..*] nonunique :> objects { doc ... }`
    // （Ports.sysml）のように、`portUsage`はpackage直下にも書ける。
    | portUsage
    | importStmt
    | exposeStmt
    | interfaceDef
    | interfaceUsage
    | connectionDef
    | allocationDef
    | allocationUsage
    // `abstract message messages: Message[0..*] ... { ... }`（Flows.sysml）。
    | messageUsage
    // `abstract flow flows: Flow[0..*] nonunique :> messages,
    // flowTransfers { ... }`（Flows.sysml）のように、`flowUsage`は
    // package直下にも書ける。
    | flowUsage
    | activityDef
    | calculationDef
    | calculationUsage
    | constraintDef
    | constraintUsage
    | assertConstraintUsage
    | satisfyRequirementUsage
    | requireUsage
    | caseDef
    | caseUsage
    | analysisCaseDef
    | analysisCaseUsage
    | verificationCaseDef
    | verificationCaseUsage
    | useCaseDef
    | useCaseUsage
    | includeUseCaseUsage
    | viewDef
    | viewUsage
    | viewpointDef
    | viewpointUsage
    | renderingDef
    | renderingUsage
    | metadataDef
    | metadataUsage
    | commentStmt
    | documentationStmt
    | textualRepresentationStmt
    | bindingConnector
    | successionStmt
    | actionUsageStmt
    | dependencyStmt
    | eventOccurrenceUsageStmt
    | exhibitStateUsageStmt
    | portionUsageStmt
    | occurrenceDef
    | occurrenceUsage
    | individualDef
    | individualUsage
    | interactionDef
    | bareDocComment
    | aliasStmt
    ;

// --- dependency (8.2.2.3) ------------------------------------------------------
// `dependency A to B;`・`dependency D from A to B;`のいずれも受理する。
// visitor側でidentification（`D`部分）は無視する。
// client/supplier参照は`::`区切り（他パッケージ参照）を伴うことがある
// （例: `dependency '意図しない車線逸脱の予防' to '事故の予防'::'車線逸脱
// による事故の予防';`、adas-sysmlv2-main）ため、`.`/`::`両方を受理できる
// `namespacePathList`を使う（単一セグメント名の出力は不変）。
dependencyStmt
    : 'dependency' ( simpleName 'from' )? clients=namespacePathList 'to' suppliers=namespacePathList ';'
    ;

// --- event occurrence usage (8.2.2.9) -------------------------------------------
// `_collect_symbols`にも`event_occurrence_usage`のシンボル収集対象が無いため、
// 対応する`_check_event_occurrence_usage`（linter.py:1496）は現状発火しない。
// `event occurrence zeroCrossingEvents[0..*] : ZeroCrossingEventDef
// { /* ... */ }`（StateSpaceRepresentation.sysml）・`in event occurrence
// sourceEvent [1] default thisConnection.start { doc /* ... */ }`
// （Flows.sysml、メッセージ接続本体内にネスト）のように、direction接頭辞・
// 多重度・型節・default節・bodyを持つ。実際のコーパスでは「名前[多重度] :
// 型」の順（itemUsage等の「: 型 多重度」とは逆順）のため、多重度を
// type節より先に置く。package直下だけでなくpartBodyElementにも登録する
// （action/flow本体内にもネストしうるため）。
eventOccurrenceUsageStmt
    : direction? 'event' 'occurrence' simpleName?
      multiplicitySpec?
      (':' namespacePath)?
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// --- exhibit state usage (8.2.2.18) ---------------------------------------------
// 構文的完全性のためのみ実装。linter.py側に対応するチェック関数は無い。
exhibitStateUsageStmt
    : 'exhibit' 'state' simpleName ';'
    ;

// --- portion usage: snapshot/timeslice (8.2.2.9) --------------------------------
// 構文的完全性のためのみ実装。linter.py側に対応するチェック関数は無い。
portionUsageStmt
    : kind=('snapshot' | 'timeslice') simpleName ';'
    ;

// --- occurrence def / occurrence usage / individual def / individual usage (8.2.2.9) --
// 公式仕様通りの単一`def`形で実装する（`occurrence def X;`/
// `individual def X;`）。
//
// `_collect_symbols`（linter.py:167）のシンボル収集whitelistには
// `occurrence_def`/`individual_def`/`occurrence_usage`のいずれも含まれて
// いないため、対応する`_check_occurrence_definition`/
// `_check_individual_definition`/`_check_occurrence_usage`
// （linter.py:1432-1494、`_check_occurrence_advanced_rules`経由）は
// いずれも現状発火しない（event_occurrence_usageと同種のlinter.py側の
// 制約）。
occurrenceDef
    : isAbstract='abstract'? 'occurrence' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `abstract constant ref occurrence causes[1..*] :>> causes :> participant
// { ... }`（CausationConnections.sysml）・`ref occurrence :>> Action::this,
// actions::this, subperformances::this = (that as Action).this { ... }`
// （Actions.sysml）・`in occurrence terminatedOccurrence[1] { ... }`/
// `in occurrence terminatedOccurrence default that as Occurrence { ... }`
// （Actions.sysml、action def本体内にネスト）のように、direction接頭辞・
// constant修飾子・ref修飾子・名前省略・postKind redefineリスト・`=`値
// 代入・default節を持つ（他のusage規則と同型の設計）。`packageBodyElement`
// だけでなく`partBodyElement`にも登録する（action本体内にもネストしうる
// ため）。
occurrenceUsage
    : direction? isAbstract='abstract'? isConstant='constant'? isRef='ref'? 'occurrence' simpleName?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('=' value=expression)?
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// IndividualDefinitionはEmptyMultiplicityMember（`[]`、上下限を持たない
// 明示的な空の多重度）を必須で持つ（`_check_individual_definition`が
// multiplicityの存在とsize=Noneの両方を要求するため）。既存の
// multiplicityBracketは上下限の記述を必須とするため再利用せず、
// 空の`[]`をこの規則専用に直接書く。
individualDef
    : isAbstract='abstract'? 'individual' 'def' simpleName inheritanceClause? '[' ']' ( '{' partBodyElement* '}' | ';' )
    ;

individualUsage
    : isAbstract='abstract'? 'individual' simpleName ( ':' ID )? ';'
    ;

// --- interaction / sequence diagram notation ---------------------------------
// SysML v2のInteraction/Sequence Diagram記法（`interaction def 'Coffee
// Brewing Sequence' { ... participant ... ; message ... from ... to ...;
// fragment alt X { operand when cond { ... } operand else { ... } } }`）の
// うち、実際に使われている範囲（パラメータ・participant・message・
// fragment/operand）のみ実装する。linter.py側に対応するチェック関数は
// 無い（構文的完全性のみ）。
interactionDef
    : isAbstract='abstract'? 'interaction' 'def' simpleName inheritanceClause? ( '{' interactionBodyElement* '}' | ';' )
    ;

interactionBodyElement
    : actionParameter
    | participantMember
    | messageStmt
    | fragmentStmt
    ;

participantMember
    : 'participant' simpleName ':' ID ';'
    ;

// kindは"alt"/"par"/"opt"等を想定するが、予約語化せず任意のIDを許容する
// （将来の拡張・誤字を過度に制限しないため）。
fragmentStmt
    : 'fragment' kind=ID simpleName? '{' operandBlock+ '}'
    ;

operandBlock
    : 'operand' ( 'when' guard=expression | 'else' )? '{' interactionBodyElement* '}'
    ;

// --- comment / documentation / textual representation (8.2.2.4.2, 8.2.2.4.3) ---
// `_check_comment_stmt`/`_check_documentation_stmt`/`_check_textual_representation_stmt`
// （linter.py）が読む `identification`/`body`/`language` フィールドに合わせる。
// `identification` は `{"type": "identification", "name": str}` 形。
// `locale` 節は未対応（`_is_valid_locale_string` の検証対象になるため、
// 実装しても実質的な価値が低いと判断）。
//
// documentationStmt の simpleName（identification）は仕様上任意であり、公式
// SysML v2標準ライブラリはほぼ全ての要素で名前無しの `doc /* ... */` を使う。
// requirementBodyElement 内の名前無しdocMember（`doc` DOC_COMMENT）とは
// 同じAST形状（type:"documentation", identification/body）に統一しており、
// docMemberの出力も同じ _check_documentation_stmt でチェックできる。
commentStmt
    : 'comment' simpleName? DOC_COMMENT
    ;

documentationStmt
    : 'doc' simpleName? DOC_COMMENT
    ;

textualRepresentationStmt
    : ('rep' simpleName)? 'language' STRING_LITERAL DOC_COMMENT
    ;

// 公式コーパスは`doc`/`comment`キーワードを一切伴わない裸の`/* ... */`
// ブロックコメント（DOC_COMMENT）を、通常のコード中コメントと同じ感覚で
// 常用する（例: `/* Quantity definitions referenced from other ISQ
// packages */`がパッケージ本体直下に単独で置かれる）。`DOC_COMMENT`は
// SKIP/HIDDENチャンネルに置かれておらず`doc`/`comment`/`rep`経由でのみ
// 消費されるため、このキーワード無し形をpartBodyElement/packageBodyElement
// の代替として明示的に扱う必要がある。documentationStmtの名前無し形
// （`doc /* ... */`）と同じAST形状（type:"documentation",
// identification:None）で出力する。
bareDocComment
    : DOC_COMMENT
    ;

// KerMLの`alias`文（別名宣言）。公式コーパスでは`alias Box for
// RectangularCuboid;`のように単純だが、名前・対象どちらも記号を含む名前
// （`'3dVectorQuantityValue'`、`'m/s²'`、`'*'`等）をQUOTED_NAME形式で書く
// ケースが多い（`simpleName`はID/QUOTED_NAME両方を包含済みのためそのまま
// 再利用できる）。公式コーパスに`::`修飾された対象は無いため、対象も
// qualifiedName等の複合規則ではなく単純なsimpleNameで十分。`alias`は`;`
// 終端だけでなく、`alias AttributeValue for DataValue { doc /* ... */ }`
// のようにbodyを持てる形も公式コーパスに存在する（`Attributes.sysml`）。
aliasStmt
    : 'alias' simpleName 'for' target=simpleName ( '{' partBodyElement* '}' | ';' )
    ;

// --- case / analysis case / verification case / use case (8.2.2.22-25) --------
// "analysis case def" ではなく "analysis def"、"verification case def"
// ではなく "verification def" である点に注意。
// `_check_case_def`等（linter.py:1923-2011）はいずれも `name` しか読まないため
// （_usageは無ければWARNING、_defは無ければERROR）、全て同じ簡略形で実装する。
// 型付け（`: Type`）は無し（constraint_usage_declaration相当の一般形は
// 未対応）。
// この17構文は全て`inheritanceClause?`を持つ（_def/_usage問わず。共有
// ヘルパー`_named_simple_node`側で一括対応する）。
caseDef
    : isAbstract='abstract'? 'case' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `ref analysis self : AnalysisCase :>> Case::self;`（AnalysisCases.sysml）
// のように、この4つの裸usage規則（case/analysis/verification/use case）は、
// attributeUsage/partUsage/portUsage/featureUsageと同じredefinition機能
// 一式（visibility・ref・名前省略・型節+多重度・pre/post redefine節）を
// 持つ（`inheritanceClause?`ではなくpartUsageと同型の規則を使う）。`_def`側は
// `inheritanceClause?`のままでよい。
caseUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'case' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

analysisCaseDef
    : isAbstract='abstract'? 'analysis' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

analysisCaseUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'analysis' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

verificationCaseDef
    : isAbstract='abstract'? 'verification' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

verificationCaseUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'verification' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

useCaseDef
    : isAbstract='abstract'? 'use' 'case' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

useCaseUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'use' 'case' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

includeUseCaseUsage
    : 'include' 'use' 'case' simpleName ';'
    ;

// --- view / viewpoint / rendering (8.2.2.26) -----------------------------------
// `view def <gv> GeneralView { ... }`のように、view defもShortName注釈を
// 取りうる（公式コーパスで8件、`StandardViewDefinitions.sysml`）。
viewDef
    : isAbstract='abstract'? 'view' 'def' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `ref view :>> self : View;`・`abstract ref view subviews : View[0..*] :>
// views { ... }`（Views.sysml）のように、他のusageキーワード規則と同じ
// redefinition機能一式（visibility・ref・名前省略・型節+多重度・pre/post
// redefine節）を持つ。`view vw specializes V1;`のように`specializes`
// キーワードも使うため、case等の規則と同様`specializes`を含める。
viewUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'view' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

viewpointDef
    : isAbstract='abstract'? 'viewpoint' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

viewpointUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'viewpoint' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

renderingDef
    : isAbstract='abstract'? 'rendering' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `rendering :>> subrenderings[0..*] = columnView.viewRendering;`
// （Views.sysml）のように、redefine対象へ`default`ではなく`=`で直接式を
// 代入する形もある（他のusage規則(attribute/item/ref等)と同じ`=`値代入）。
renderingUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'rendering' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('=' value=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// --- metadata (8.2.2.27) --------------------------------------------------------
// `_check_metadata_usage`（linter.py:2091）はnameかusage_declaration.type_spec
// のどちらかがあればよいが、ここではnameのみ実装する（typeSpecは未対応）。
// `metadata def <cause> CauseMetadata :> SemanticMetadata { ... }`のように、
// metadata defもShortName注釈を取りうる（公式コーパスで10件、最頻出）。
metadataDef
    : isAbstract='abstract'? 'metadata' 'def' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

metadataUsage
    : isAbstract='abstract'? 'metadata' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// --- calculation def / constraint def (8.2.2.19, 8.2.2.20) --------------------
// キーワードは"calculation"ではなく"calc"。本体（calculation_body）は
// `';' | '{' ... '}'`。中身は他のdefと同じpartBodyElementに加えて、
// 計算/制約の結果を表す式文（resultExpression）を許可する。
// `private calc def excludingOnce { ... }`（Interfaces.sysml）・`private
// abstract constraint def RequirementConstraintCheck { ... }`
// （Requirements.sysml）のように、visibilityIndicator（private/public/
// protected）が付く形がある（公式コーパス全体で3件のみ、attributeUsage等と
// 同じ順序でabstractより前）。
calculationDef
    : visibilityIndicator? isAbstract='abstract'? 'calc' 'def' simpleName inheritanceClause? ( '{' calcBodyElement* '}' | ';' )
    ;

constraintDef
    : visibilityIndicator? isAbstract='abstract'? 'constraint' 'def' simpleName inheritanceClause? ( '{' calcBodyElement* '}' | ';' )
    ;

calcBodyElement
    : calcParameter
    | partBodyElement
    | resultExpressionMember
    ;

// `seq->excludingAt(position)`（Interfaces.sysml、calc def本体の最後の
// 文）のように、`return`キーワードも終端の`;`も伴わない裸の暗黙戻り値式
// （KerMLのFunctionExpressionの末尾式相当）も受理する。終端の`;`は省略可能
// （本来は本体の最後の文のみ許容されるが、この文法は厳密なspec準拠
// バリデータではないため、そこまでの制約は設けない）。
resultExpressionMember
    : expression ';'?
    ;

// `constraint def`本体内の`in`/`out`/`inout`パラメータ宣言（例:
// `in unitPowerFactors: UnitPowerFactor[*] ordered;`、
// `MeasurementReferences.sysml`の`VerifyUnitPowerFactors`）と、名前付き
// 制約を型として参照する`assertConstraintUsage`側でのパラメータ束縛
// （例: `in unitPowerFactors = MeasurementUnit::unitPowerFactors;`）を
// 1つの規則で受理する。型節と値節はどちらも省略可能で、宣言側は型節のみ、
// 束縛側は値節のみを使う。公式コーパス全体でこのパターンは
// `MeasurementReferences.sysml`の1ファイルのみで確認されている。
// `return sampling = new SampledFunction(...);`・`return result =
// allTrue(assumptions()) implies allTrue(constraints()) { doc ... }`の
// ように、`return`キーワードを伴う値代入付きパラメータも受理する
// （`direction`は`in`/`out`/`inout`のみのため、この規則専用に`'return'`を
// 並列で追加。他の`direction`利用箇所[actionParameter]には影響しない）。
// `return`は`return : MeasurementUnit[1];`という名前省略形でも使われる
// ため、simpleNameも任意化してある。値代入後は既存のセミコロン終了に
// 加え、`{ ... }`という本体も選択できる。
// `return : Boolean[1] = NumericalFunctions::isZero(x.num);`のように、
// 型節+多重度+値代入を同時に持つ形（公式コーパス全体で`return`のみ6件・
// 2ファイル、SampledFunctions.sysml/QuantityCalculations.sysml）もある
// ため、型節・値節はそれぞれ独立に任意である。
calcParameter
    : (direction | dirReturn='return') simpleName?
      (':' namespacePath multiplicitySpec?)?
      ('=' expression)?
      ( '{' calcBodyElement* '}' | ';' )
    ;

// --- assert constraint usage (8.2.2.20) ----------------------------------------
// bare形（`assert constraint c;`）は
// {"type":"constraint_stmt","children":[{"type":"assert_constraint_usage",
// "is_negated":bool,"name":str,"type_name":"","result_expression":None,
// "children":[]}]}という入れ子で返す（owned_reference_subsetting経由の
// 代替形は未対応）。
// 公式コーパスでは名前が省略される形（`assert constraint { expr }`）と、
// bodyが単一の真偽式のみで末尾の`;`を伴わない形（`assert constraint
// boundMatch { (isBound == mRef.isBound) or (not isBound and
// mRef.isBound) }`）が多用されている（9ファイル）ため、simpleNameを
// 任意化し、単一式のみのbody（`resultExpr=expression`）を既存の
// calcBodyElement*形と並列の代替として持つ。
// `assert constraint 名前 : 型参照 { in param = value; ... }`という、
// 名前付きconstraint defを型として参照しつつパラメータを束縛する形
// （`MeasurementReferences.sysml`）にも対応する。型参照節
// `(':' typeRef=namespacePath)?`を持ち、body側は既存の
// `calcBodyElement*`（`calcParameter`経由で`in param = value;`を受理）を
// そのまま再利用する。
// `require constraint { eval(selectedAlternative) == best }`
// （TradeStudies.sysml）のように、`assert`と全く同じ位置・形状で
// `require`キーワードも使われる（KerMLの要求済み制約：`assert`は
// 「表明」、`require`は「要求」という意味の違いだが構文は同一）。
// `assertKind`ラベル付きトークンとして並列に持つ。
// `private assert constraint originalNotDerived { ... }`
// （DerivationConnections.sysml/CausationConnections.sysml、3件すべて
// `private`）のように、`visibilityIndicator`を持つ（calculationDef/
// constraintDefと同じ設計、キーワードの前に`visibilityIndicator?`）。
// `private assert constraint originalNotDerived { doc /* ... */
// derivedRequirements->excludes(originalRequirement) }`のように、単一の
// 真偽式のみのbody（`resultExpr`）の前に`doc`コメントが先行することが
// ある（3件すべてで確認）ため、`documentationStmt*`を`resultExpr`の前に
// 持つ。
assertConstraintUsage
    : visibilityIndicator? assertKind=('assert' | 'require') ('not')? 'constraint' simpleName?
      ( ':' typeRef=namespacePath )?
      ( '{' documentationStmt* resultExpr=expression '}' | '{' calcBodyElement* '}' | ';' )
    ;

// --- calculation usage / constraint usage (8.2.2.19, 8.2.2.20) -----------------
// `_check_calculation_usage`/`_check_constraint_usage`（linter.py:808,851）
// は`type_name`のみ読む。
// `ref calc self: Calculation :>> Action::self, Evaluation::self;`
// （Calculations.sysml）・`calc :>> getNextState: GetNextState { ... }`
// （StateSpaceRepresentation.sysml、名前省略形）のように、partUsage等と
// 同型のredefinition機能一式（visibility・ref・名前省略・pre/post
// redefine節）を持つ。
calculationUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'calc' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' calcBodyElement* '}' | ';' )
    ;

// `constraint { stateSpace.order == order }`（StateSpaceRepresentation.
// sysml）のように、名前もキーワード修飾子も伴わない裸のconstraint usage
// が、括弧内に単一の真偽式のみを持つ形（セミコロン無し）を取ることが
// ある。`assertConstraintUsage`が持つ`resultExpr=expression`代替と同型の
// 代替を持つ。
constraintUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'constraint' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' resultExpr=expression '}' | '{' calcBodyElement* '}' | ';' )
    ;

// --- satisfy requirement usage (8.2.2.21.2) -------------------------------------
// 参照: SysML.xtext の `satisfy_requirement_usage_stmt`。キーワードは
// "satisfiedBy"（camelCase）。
// bare参照形（`assert satisfiedBy x;`、type_name無し）と名前付き型付き形
// （`assert satisfiedBy requirement x : R;`）の両方を実装する。
// `_check_satisfy_requirement_usage`（linter.py:883）は `type_name` のみ読む
// （無ければチェックをスキップするだけで、エラーにはならない）。
// `satisfy requirement viewpointConformance by that { doc ... require
// viewpointSatisfactions { ... } }`（Views.sysml）のように、`satisfy
// requirement <名前> by <参照> { ... }`というbodyありの形も、既存の
// セミコロン終端形（`assert ... satisfiedBy ...;`）とは別の代替として持つ。
satisfyRequirementUsage
    : 'assert' ('not')? 'satisfiedBy' ( 'requirement' simpleName ':' ID | simpleName ) ';'
    | 'satisfy' 'requirement' simpleName 'by' by=namespacePath ( '{' partBodyElement* '}' | ';' )
    ;

// `require viewpointSatisfactions { ref :>> ownedPerformances::this,
// subperformances::this default that.that; }`（Views.sysml、
// `satisfyRequirementUsage`のbody内にネスト）のように、`require`単体
// （`constraint`キーワード無し）で名前+bodyを導入する形が別途存在する
// （`require constraint { expr }`とは`constraint`キーワードの有無で異なる
// 別形）。公式コーパスでこの1箇所のみ確認。
requireUsage
    : 'require' simpleName ( '{' partBodyElement* '}' | ';' )
    ;

// --- interface usage (8.2.2.14) -----------------------------------------------
// `_check_interface_usage`（linter.py:662）が読む `type_name`/
// `interface_part.{type,from_end,to_end}.reference_subsetting.
// referenced_feature` に合わせて実装する。
interfaceUsage
    : isAbstract='abstract'? 'interface' simpleName ':' ID ( 'connect' connectorEnd 'to' connectorEnd )? ';'
    // `abstract interface interfaces: Interface[0..*] nonunique :>
    // connections { doc ... }`（Interfaces.sysml）のように、`connect`を
    // 伴わない裸のinterface usage形（connection/allocation/message/flow等と
    // 同型）も第2代替として持つ（connectionUsage/flowUsageのbare形と
    // 同じ設計）。
    | isAbstract='abstract'? 'interface' simpleName?
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// --- allocation usage (8.2.2.15) ------------------------------------------------
// 名前付き形（`allocation x : A allocate a to b;`）と bare 形
// （`allocate a to b;`）の両方を実装する。`_check_allocation_usage`
// （linter.py:728）が読む`type_name`/`connector_part.{...}`に合わせる。
// `abstract allocation allocations: Allocation[0..*] nonunique :>
// binaryConnections { ... }`（Allocations.sysml）のように、`allocate`
// 節を伴わない裸の`allocation`usage形（multiplicity・redefine節・body
// を伴う、itemUsage/partUsage等と同型）も持つ。
allocationUsage
    : isAbstract='abstract'? 'allocation' simpleName
      ( ':' ID )?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( 'allocate' connectorEnd 'to' connectorEnd )?
      ( '{' partBodyElement* '}' | ';' )
    | 'allocate' connectorEnd 'to' connectorEnd ';'
    ;

// 本体は他の全ての_def（part_def, item_def, port_def, interface_def等）と
// 同じフラットなchildrenリストで表す（特殊な入れ子構造は使わない）。
// `_check_connection_def`（linter.py:528）は`from`/`to`フィールドを読むが、
// body形式ではどちらも設定されない。
connectionDef
    : isAbstract='abstract'? 'connection' 'def' simpleName inheritanceClause? ( '{' connectionBodyElement* '}' | ';' )
    ;

connectionBodyElement
    : partBodyElement
    | connectionEndMember
    ;

// connection_defの他の要素同様、フラットなchildrenリストで表す（特殊な
// 入れ子構造は使わない）。`_check_connection_def`（linter.py:528）はend
// memberの型を直接検証しないため（name/from/to/connectorのみ）、意味検証上
// の価値は主に構文的完全性。
// `end occurrence source: Occurrence :>> Message::source,
// FlowTransfer::source;`（Flows.sysml、8件）・`end theCauses [*]
// occurrence theCause :> causes :>> source { ... }`
// （CausationConnections.sysml）・`end touchesToo [0..*] item
// touchedItemToo :>> ...;`（Items.sysml）・`end port source: Port :>>
// ...;`（Interfaces.sysml）・`end ref source;`（Ports.sysml）・`end
// source: Anything :>> ...;`（キーワード無し、Allocations.sysml/
// Connections.sysml）のように、`occurrence`/`port`/`item`キーワード・
// `ref`修飾子・redefine節（複数可）・body・connector end自体の別名
// （`endName [mult]`、内側featureの名前とは別）を持つ。
// `occurrence`/`port`/`item`はリテラルキーワードのため`endName`
// （`simpleName`はID/QUOTED_NAMEのみ）と衝突せず、ANTLRの通常の
// 先読みで曖昧性なく解決される。
connectionEndMember
    : 'end' (endName=simpleName endMult=multiplicitySpec?)?
      kind=('occurrence' | 'port' | 'item')?
      isRef='ref'?
      innerName=simpleName?
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// part_defと同じ簡略形のみ実装する。`allocation_usage`
// （`allocate x to y;`、connector_partを使う複雑な形）は未対応。
allocationDef
    : isAbstract='abstract'? 'allocation' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `_check_activity_def`（linter.py:462）はaction_defと全く同じフィールド
// （name, params[].type_spec.name）を読むため、action_defと同型で実装する。
activityDef
    : isAbstract='abstract'? 'activity' 'def' simpleName inheritanceClause? ( '{' actionBodyElement* '}' | ';' )
    ;

// 参照: KerML.xtext の `Type`（`TypePrefix 'type' TypeDeclaration TypeBody`）。
// type_def のみ対応する（`type T { ... }`という'def'無し形のtype_usageは
// 実サンプルで必要性が確認できていないため未対応）。`attributes` は常に
// 空リスト（body の中身は `children` に入る）。
typeDef
    : isAbstract='abstract'? 'type' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `specializes`/`subsets`両キーワードと複数基底（カンマ区切り、
// namespacePathListを使う）に対応し、`kind`フィールドで演算子の種類を
// 保持する（`str(inheritance)`に"subsets"という部分文字列を含ませることで、
// linter.pyの`_check_individual_specialization_consistency`
// （linter.py:2440）等のディスパッチを発火させる）。
// `subsets ... specializes ...`という両方を1文で組み合わせる形
// （`inheritance_both`）は対象外とする。
//
// 構文上は複数基底を全て受け付けるが、AST上の"base"フィールドは先頭の
// 基底のみを持つ（`_check_part_def`等の大半のlinter.pyチェック関数が
// "base"を単純な完全一致検索に使っており、カンマ区切り文字列を渡すと
// 実在する型でも「存在しない型」という誤検出になるため）。全基底は別途
// "bases"リストに保持する（antlr_transformer.pyのvisitInheritanceClause
// 参照）。
// `:>`は`subsets`の、`:>>`は`redefines`のテキスト記法における略記
// （KerML.xtext）。公式SysML v2標準ライブラリでは`attribute def`の
// ほぼ全て（800件超）が`specializes`/`subsets`キーワードではなくこの
// `:>`略記を使う。`:>>`（redefines）は公式ライブラリで未確認のため、
// 実際の使用が確認できるまで追加しない。
// 基底型は`calc def '*' specializes DataFunctions::'*' { ... }`のように
// `::`修飾名を取りうる（公式コーパスで242件・8ファイル使用）。`.`区切りの
// 実例は公式コーパス全体に無いため、`namespacePathList`（`::`区切り、
// attributeUsage等のredefine対象と同じ）を使う。
inheritanceClause
    : kind=('specializes' | 'subsets' | ':>') base=namespacePathList
    ;

// `part def <xx> Name { ... }`のように、他のdef系規則（package/view def/
// metadata def/item def/attribute usage）と同じShortName注釈を取りうる。
partDef
    : isAbstract='abstract'? 'part' 'def' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// 参照: SysML.xtext の `ItemDefinition`（`OccurrenceDefinitionPrefix
// ItemDefKeyword Definition`）。PartDefinitionと完全に同型（bodyも同じ
// DefinitionBodyフラグメント経由）なので、partDefと同じpartBodyElementを流用する。
// `item def <xxx> Name { ... }`のように、他のdef系規則
// （package/view def/metadata def/attribute usage）と同じShortName注釈
// （KerMLの一般的な短縮名機能）を取りうる。
itemDef
    : isAbstract='abstract'? 'item' 'def' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `ref item :>> localClock : Clock[1] default Time::universalClock { ... }`
// （SpatialItems.sysml）のように、partUsageと同型の設計（visibility・
// ref・名前省略・pre/post redefine節）に加え、attributeUsageと同じ既定値節
// （`default expression`）も許す。
// `item :>> vertices [*] = edges.vertices;`（ShapeItems.sysml/
// SpatialItems.sysml、多数件）のように、`=`値代入も持つ（既存の`default`
// 既定値節とは排他、同時使用例なし）。
// `derived ref item receiverArgument : Expression[0..1] subsets
// Metadata::metadataItems;`（SysML.sysml、177件）のように、`derived`
// 修飾キーワード（他の修飾子と同じ位置、visibilityの後・abstract/refより
// 前）も持つ。
itemUsage
    : visibilityIndicator? isDerived='derived'? isAbstract='abstract'? isRef='ref'? 'item' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( 'default' defaultValue=expression | '=' value=expression )?
      ( '{' partBodyElement* '}' | ';' )
    ;

// `requirement`キーワードをusageとして使う形（`requirementDef`ではない）。
// 例: `ref requirement :>> self: RequirementCheck;`・`abstract
// requirement subrequirements[0..*] :> requirementChecks, constraints
// { ... }`（Requirements.sysml）、`requirement originalRequirements[*]
// { ... }`（パッケージ直下の裸usage、DerivationConnections.sysml）。
// itemUsageと同型の設計を使う。`concern`キーワード（`concern def
// ConcernCheck { ref concern :>> self: ConcernCheck; }`、Requirements.sysml
// のみ・2件）も構造が完全に同一。
requirementUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'requirement' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      // `ref requirement requirementVerifications : RequirementCheck[0..*]
      // = obj.requirementVerifications { ... }`（VerificationCases.sysml）
      // のようにインライン値代入を伴う形も存在する（subjectUsageと同じ位置）。
      ('=' value=expression)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

concernUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'concern' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// `subject subj :>> Case::subj;`（AnalysisCases.sysml/UseCases.sysml/
// VerificationCases.sysml等）・`subject studyAlternatives : Anything[1..*]
// { ... }`（TradeStudies.sysml）・`subject subj default Case::result;`
// （Cases.sysml、objective本体内のネスト）・`subject subj =
// VerificationCase::subj;`（VerificationCases.sysml、同じくネスト）の
// ように、`subject`/`objective`はitemUsageと同型の設計に加え、
// attributeUsageと同じインライン`= expression`値代入も持つ。
subjectUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'subject' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      ('=' value=expression)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

objectiveUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'objective' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      ('=' value=expression)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// `enum def X { ... }`（4ファイルで使用: ModelingMetadata.sysml/
// RiskMetadata.sysml/SysML.sysml/VerificationCases.sysml）。他の_defと
// 同じくinheritanceClause?を許すが（`enum def LevelEnum :> Level { ... }`)、
// bodyは`partBodyElement`ではなく専用のenum-literal（3種類の形状が
// 混在）を持つ。
enumDef
    : 'enum' 'def' simpleName inheritanceClause? ( '{' enumBodyElement* '}' | ';' )
    ;

enumBodyElement
    : documentationStmt
    | bareDocComment
    | enumLiteral
    ;

// (a) `enum 'literal';`という明示的キーワード形、(b)/(c) 裸の名前に
// 値代入または本体が続く形、のいずれも受理する。
enumLiteral
    : 'enum'? simpleName '=' value=expression ';'               # enumLiteralValue
    | 'enum'? simpleName ( '{' enumBodyElement* '}' | ';' )      # enumLiteralBody
    ;

// --- attribute definition (8.2.2.6) ---------------------------------------------
// 参照: SysML.xtext の`AttributeDefinition`。PartDefinition/ItemDefinitionと同型
// （bodyも同じDefinitionBodyフラグメント経由）なので、partBodyElementを流用する。
attributeDef
    : isAbstract='abstract'? 'attribute' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

partBodyElement
    : attributeUsage
    | attributeDef
    | partUsage
    | flowUsage
    | connectUsage
    | connectionUsage
    | portUsage
    | bindingConnector
    | successionStmt
    | bareFirstStmt
    | bareThenStmt
    | documentationStmt
    | valueBindingStmt
    | featureUsage
    | bareDocComment
    | aliasStmt
    | assertConstraintUsage
    // `satisfy requirement viewpointConformance by that { ... }`
    // （`view def`本体内にネスト、Views.sysml）のように、
    // `satisfyRequirementUsage`/`requireUsage`はpartBodyElement内にも
    // 書ける。
    | satisfyRequirementUsage
    | requireUsage
    | enumDef
    // `analysis def`/`calc def`/`constraint def`等の本体（partBodyElement）
    // 内に、対応するusageキーワード（`ref analysis self ...;`等）を書く形が
    // 公式コーパスで広く使われているため、この6規則はpartBodyElementにも
    // 登録する。itemUsage・actionUsageStmtも同様にpart本体内で使われる。
    | caseUsage
    | analysisCaseUsage
    | verificationCaseUsage
    | useCaseUsage
    | calculationUsage
    | constraintUsage
    // `private calc def Linear { ... }`（SampledFunctions.sysml、別のcalc
    // def本体内にネスト）のように、calculationDef/constraintDefは
    // calcBodyElementが委譲するpartBodyElementにも登録する。
    | calculationDef
    | constraintDef
    | itemUsage
    | actionUsageStmt
    // `subject`/`objective`は常に別のcase/analysis/requirement/objective
    // 定義の本体内にネストして使われる（公式コーパスに例外なし）ため、
    // partBodyElementのみに登録する。
    | subjectUsage
    | objectiveUsage
    // `view def V { ref view :>> self : View; ... }`（Views.sysml）のように、
    // view/viewpoint/renderingの各定義本体内にネストして使われるため
    // partBodyElementにも登録する。
    | viewUsage
    | viewpointUsage
    | renderingUsage
    // `in ref :>> alternatives = studyAlternatives;`（TradeStudies.sysml）
    // のように、direction付きのパラメータ宣言がobjective/subject usage
    // 本体にネストして使われる。
    | actionParameter
    // `requirement`/`concern` usage・definitionがrequirement def本体
    // （partBodyElementへ委譲済み）内にネストして使われる。
    | requirementUsage
    | concernDef
    | concernUsage
    // `in event occurrence sourceEvent [1] default thisConnection.start
    // { ... }`（Flows.sysml）のようにメッセージ接続本体（partBodyElement）
    // 内にネストして使われる形もあるため、ここにも登録する。
    | eventOccurrenceUsageStmt
    // `in occurrence terminatedOccurrence[1] { ... }`（Actions.sysml、
    // action def本体内にネスト）のように、occurrenceUsageはpartBodyElement
    // 内にも書ける。
    | occurrenceUsage
    // `succession causalOrdering first [nCauses] ... then [nEffects] ...
    // { ... }`（connectionDef本体内にネスト）。
    | successionUsage
    // `end occurrence source: Occurrence :>> Message::source,
    // FlowTransfer::source;`（Flows.sysml、flow def本体内にネスト）の
    // ように、connectionEndMemberはconnectionBodyElementだけでなく
    // partBodyElement内にも書ける。
    | connectionEndMember
    // `abstract ref state exhibitedStates: StateAction[0..*] :>
    // stateActions, performedActions { ... }`（Parts.sysml、part def
    // 本体内にネスト）のように、stateUsageはstateBodyElementだけでなく
    // partBodyElement内にも書ける。
    | stateUsage
    // allocationUsage/messageUsageもpackage直下だけでなくpartBodyElement内
    // に書けるため登録する。
    | allocationUsage
    | messageUsage
    // interfaceUsageも同様にpartBodyElement内に書けるため登録する。
    | interfaceUsage
    // `part 'フロントカメラ' { perform action '外界の映像を出力する'
    // { ... } }`（adas-sysmlv2-main、実モデル）のように、part usageは
    // 直接performActionUsageを持てる（公式仕様）ため登録する。
    | performActionStmt
    // `requirement '意図しない車線逸脱の予防' { dependency ... to
    // ...::...; }`（adas-sysmlv2-main、実モデル）のように、
    // dependencyStmtはpartBodyElement（requirementBodyElementが委譲する
    // 先）内にも書ける。
    | dependencyStmt
    ;

// 公式コーパスには`ref self: Part :>> Item::self;`や`ref stateSpace:
// StateSpace;`のように、part/port/attribute/item等の型種別キーワードを
// 一切伴わない裸のfeature宣言が多数存在する(58ファイル中18〜23ファイルで
// 使用)。attributeUsage/partUsage/portUsageと同じ設計(visibility・ref・
// 名前省略・型節前後の:>/:>>節)をキーワード無しでも使えるよう、他のusage
// 規則と並列の独立した規則にしてある(alt順序上はfeatureUsageを最後に
// 置いているが、他の規則がいずれも固有のキーワードを要求するため、ANTLRの
// full-context予測により曖昧性は生じない)。型節は`SysML::Usage`のような
// 修飾名を許すためID単体ではなくnamespacePathを使う。`as Type`型キャスト・
// `meta`式を伴う値束縛(`ref :>> baseType = causes as SysML::Usage;`)は
// 本規則のスコープ外(既存のexpression規則が対応していないため)。
// featureUsage/partUsage/portUsage/attributeUsageの4規則共通で、
// (1) redefine/subsets節をtextualキーワード(`redefines`/`subsets`。
// `:>`/`:>>`の記号形の同義語)でも書ける、(2) 1宣言に複数のredefine/
// subsets節を連続して書ける形(例: `causes[1..*] :>> causes :>
// participant { ... }`)に対応するため、preKind/preTarget・
// postKind/postTargetは`*`(0個以上、`+=`によるリスト収集)、
// (3) `abstract`のきょうだいである`constant`修飾子も持つ。
// `ref :>> ownedPerformances::this, subperformances::this default
// that.that;`（Views.sysml、`requireUsage`本体内にネスト）のように、
// itemUsage/subjectUsage/requirementUsage等と同じ`default`値節も
// 同じ位置に持つ。
// `ref :>> baseType = causes as SysML::Usage;`（CauseAndEffect.sysml）
// のように、他のusage規則（item/attribute/requirement等）と同じ`=`値代入
// も持つ。
// `ref sentMessage :>> sentTransfer: MessageTransfer, MessageAction
// { ... }`（Actions.sysml）のように、型節がカンマ区切りの複数型を取る
// ことがあるため、専用ラベル`typeList=namespacePathList`を使う。
featureUsage
    : visibilityIndicator? isAbstract='abstract'? isConstant='constant'? isRef='ref'?
      simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeList=namespacePathList)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('=' value=expression)?
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// KerML.xtext の Feature 系usage宣言（`part a : A;`）。part def同様、
// 本体（ネストしたusage/connect等）を持てる（`part x : A { part y : B; }`）。
// attributeUsageと同じredefinition機能一式（visibility・名前省略・型節
// 前後の:>/:>>節・body内の値束縛リデファイン文）を持つ。加えて`ref`
// （非所有・参照意味の修飾子。`ref part actors : Part[0..*] :> parts;`の
// ように使う）も持つ。redefine対象は`SpatialItem::localClock`のように
// `::`修飾名で書かれることが多いため、qualifiedNameListではなく
// namespacePathListを使う。
// `ref part this : Part :>> Action::this, ownedPerformances::this =
// that as Part { ... }`（Parts.sysml）のように、他のusage規則と同じ
// `=`値代入も持つ。
// `part 'LDW制御スイッチ' : Parts::'OnOffスイッチ' { ... }`
// （adas-sysmlv2-main、実モデル、7件）のように、型節が`::`区切り
// （他パッケージ参照）を伴う場合もある（公式コーパスでは0件、実モデル
// 特有）ため、型節は`ID`単体ではなく`namespacePath`（`.`/`::`両方受理）
// を使う。
partUsage
    : visibilityIndicator? isAbstract='abstract'? isConstant='constant'? isRef='ref'?
      'part' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=namespacePath)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('=' value=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// 型参照は`::`区切りの`namespacePath`を許可する（例:
// `attribute powerLevel : ScalarValues::Real;`。namespacePathは
// `ID ('::' ID)*`でID単体も含む）。
// attribute usageは以下の要素を自由に組み合わせて使う（同一行で複数同時に
// 使われるケースが大半）:
// - visibilityIndicator（`private attribute lengthPF: ...`。現状importにしか無かった）
// - ローカル名の省略（`attribute :>> num: Real;`。1,143件）
// - `:>`/`:>>`（サブセット/リデファイン）節。名前の前（`attribute :>> num: Real;`）にも
//   型の後（`attribute staticPressure: PressureValue :> scalarQuantities { ... }`）にも
//   現れうるため、型節の前後どちらにも独立したスロットを設ける（両方同時に現れる実例は
//   確認していないが、文法上どちらか一方だけが埋まる分には曖昧性は生じない）
// - body内の値束縛リデファイン文（`:>> quantity = isq.L;`。2,319件、最多）。これは
//   既存のどの規則にも対応が無い新規のbody要素種別のため、attributeBodyElementとして
//   新設し、通常のネストしたattributeUsageと併用できるようにする。
// 公式コーパス（`ISQBase.sysml`等5ファイル）に`attribute <isq>
// 'International System of Quantities': SystemOfQuantities`のように、
// 'attribute'キーワード直後・名前の前に`<shortName>`という短縮名注釈が
// 付く形がある（attributeUsage限定で観測）。型節も同様に、`attribute
// 'hedströmNumber': 'HedströmNumberValue' :> ...`のようにQUOTED_NAME形式の
// 型名（記号を含む型名）を使う例があるためnamespacePathと並列で許容する。
// 型節・多重度に続けて`= expression`というインライン値代入を書ける形
// （例: `attribute xUnit : LengthUnit = mRefs#(1);`。公式コーパスで
// 8ファイル使用）。既存のvalueBindingStmt（body内の`:>> name = expr;`と
// いう値束縛"リデファイン"文）とは別に、宣言と同時に値を代入する単純な形。
// `default`値節（例: `attribute isBound: Boolean[1] default false;`）は
// 既存のインライン`= expr`（固定値の代入）とは意味が異なる（既定値。
// 再定義や継承先で上書きできる）ため別のスロットとして持つ。公式コーパスで
// post-redefine節の後に置かれる実例（`... :> scalarQuantities default 0
// [m]`）があるため、この位置に置く。
// redefine対象は`attribute unit :>> UnitPowerFactor::unit = ...;`のように
// `::`修飾名も取りうる（`.`修飾の実例は0件）ため、`namespacePathList`
// （`::`区切り、part/port/featureUsageと同じ）を使う。
// `attribute <K> kelvin : ThermodynamicTemperatureUnit,
// TemperatureDifferenceUnit { ... }`（SI.sysml/USCustomaryUnits.sysml）の
// ように、型節（`:`の後）でカンマ区切りの複数型を取ることがあるため、
// `typeList=namespacePathList`という専用ラベルを使う（`namespacePathList`は
// 既にカンマリスト対応済み。preTarget/postTargetの`+=namespacePathList`
// とは別ラベルのため干渉しない）。
// `derived attribute isReference : Boolean[1] ...`（SysML.sysml）のように、
// attributeUsageにも`derived`修飾キーワードが付く実例がある（itemUsageと
// 同じ位置）。
attributeUsage
    : visibilityIndicator? isDerived='derived'? isAbstract='abstract'? isConstant='constant'?
      'attribute' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' (typeList=namespacePathList | typeQuoted=QUOTED_NAME))?
      multiplicitySpec?
      ('=' value=expression)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;
// 専用のattributeBodyElement規則は持たず、他のusage（part/port）と同じ
// partBodyElementを共有する（partBodyElementはvalueBindingStmtも含むため、
// ネストしたattributeUsage/値束縛リデファイン文のいずれも書ける）。

// 値束縛リデファイン文（例: `:>> quantity = isq.L;`）。継承した機能を
// 再定義しつつ具体的な値を束縛する、KerMLの一般的なイディオム。
// linter.py側の対応チェックは無い（構文サポートのみ）。
valueBindingStmt
    : kind=(':>' | ':>>') target=qualifiedName '=' value=expression ';'
    ;

// `[n..m]` に続けて `ordered`/`nonunique` 修飾子を付けられる
// （`part b : B[0..1] ordered nonunique;`）。`is_ordered`/`is_unique`は
// （8.2.2.6.6準拠の`multiplicity_part`/`owned_multiplicity`という深い
// 入れ子ではなく）既存の「レガシーsize辞書」にフラットに追加するだけの
// 単純な形にする（`_check_multiplicity`はis_ordered/is_uniqueを一切
// 読まないため、検証されない装飾的フィールドにとどまる）。
// `multiplicity_part`という別フィールド・別の深い入れ子構造
// （`_check_multiplicity_part`が読む形）は使用実績が無いため実装しない。
multiplicitySpec
    : multiplicityBracket multiplicityModifiers?
    ;

multiplicityModifiers
    : ordered='ordered' nonunique='nonunique'?
    | nonunique='nonunique' ordered='ordered'?
    ;

// --- multiplicity (8.2.2.6.6) ---------------------------------------------------
// 参照: KerML.xtext の `MultiplicityRange = '[' (MultiplicityExpressionMember
// '..')? MultiplicityExpressionMember ']'`。
// `_check_rules`（linter.py:301）は `node["multiplicity"]` があれば
// `_check_multiplicity` を呼ぶ。同関数は3種類の入れ子形式に対応しているが
// （"multiplicity"型、"multiplicity_range"型、レガシーの"size"辞書型）、
// 最も単純な「レガシーsize辞書」形式（`{"size": {"min": ..., "max": ...}}`）を
// 使う。owned_multiplicity/multiplicity_range/multiplicity_expression_member
// という深い入れ子を作る `multiplicity_part` 経路（"ordered"/"nonunique"
// 修飾子も含む、より複雑な8.2.2.6.6準拠形式）は実装しない
// （ordered/nonuniqueは`_check_multiplicity_part`でも実質的な検証がなく、
// 実装コストに見合わないと判断）。
// `[n]`（単一値）は `min=max=n` として扱う。
multiplicityBracket
    : '[' lower=multiplicityBound '..' upper=multiplicityBound ']'
    | '[' bound=multiplicityBound ']'
    ;

// `succession [seBeforeNum] first ... then ...;`（Flows.sysml）・
// `succession causalOrdering first [nCauses] ... then [nEffects] ...;`
// （CausationConnections.sysml）のように、多重度の上下限が数値リテラルでは
// なく同一body内で宣言されたattributeを指す識別子（記号的多重度）である
// 形が実在する。
multiplicityBound
    : INT_LITERAL
    | '*'
    | ID
    ;

// --- フェーズ2: connect (8.2.2.13) -----------------------------------------
// 参照: KerML.xtext の `fragment BinaryConnectorDeclaration` / `ConnectorEnd`。
// 公式文法では OwnedReferenceSubsetting は
// `referencedFeature = [SysML::Feature | QualifiedName]` であり、
// キーワードなしの qualifiedName をそのまま受け付ける（`connect a to b;`）。
// `connect 'ハンドルスイッチ'::'LDW制御スイッチ'.'LDW出力' to 'ADASコント
// ローラ'.'ADAS設定入力';`（adas-sysmlv2-main、実モデル）のように、
// 端点が`::`（パッケージ限定）と`.`（フィーチャアクセス）を混在させる
// 場合もあるため、共有規則`connectorEnd`（bindingConnector/
// successionStmt/successionUsage等でも使われ`qualifiedName`前提の既存
// 出力に依存するため変更しない）とは別に、`connectUsage`専用の
// `::`/`.`両対応版`connectorEndPath`を使う。
connectUsage
    : 'connect' connectorEndPath 'to' connectorEndPath ';'
    ;

// `connection :MatesWith connect [1] be to [1] be;`（ShapeItems.sysml、
// 20件超）・`connection :HappensDuring connect sourceEvent to [1]
// source;`（Flows.sysml）のように、`connectUsage`（キーワード無し型）とは
// 別に、`connection`キーワード+型節+connectorEnd側multiplicityを伴う形が
// ある。
// `abstract connection connections: Connection[0..*] nonunique :>
// linkObjects, parts { ... }`（Connections.sysml/
// CausationConnections.sysml）のように、`connect`を伴わない裸の
// `connection`usage形（itemUsage/partUsage等と同型）も第2の代替として
// 持つ。既存の`connect`形とは語順が異なる（`connection`の直後が`:`
// `typeRef`か`simpleName`かでANTLRの通常の先読みにより曖昧性なく解決
// される）。
connectionUsage
    : 'connection' ':' typeRef=namespacePath 'connect'
      firstMult=multiplicitySpec? firstEnd=connectorEnd
      'to' thenMult=multiplicitySpec? thenEnd=connectorEnd
      ( '{' partBodyElement* '}' | ';' )
    | isAbstract='abstract'? 'connection' simpleName?
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// ConnectorEnd の `(declaredName=Name ReferencesKeyword)? OwnedReferenceSubsetting` を
// 反映。名前付き end (`end1 references a`) と素の参照 (`a`) の両方を許可する。
connectorEnd
    : (ID 'references')? qualifiedName
    ;

// `connectorEnd`と同型だが、`connectUsage`専用に`.`/`::`両対応の
// `namespacePath`を使う（`connectorEnd`自体は他の共有箇所の既存出力に
// 影響するため変更しない）。
connectorEndPath
    : (ID 'references')? namespacePath
    ;

// 各セグメントはIDまたはQUOTED_NAME（例: `'Boil Water'.w`）。単一引用符名は
// 宣言位置だけでなく参照位置でも使われる（`'Boil Water' then join1;`）ため、
// qualifiedNameを再利用する全ての規則（connect/flow/transition/message/
// dependency等）で参照位置での単一引用符名がサポートされる。
qualifiedName
    : (ID | QUOTED_NAME) ('.' (ID | QUOTED_NAME))*
    ;

// --- フェーズ2: flow (8.2.2.13) ---------------------------------------------
// 参照: KerML.xtext の `fragment FlowDeclaration`。
// `'of' PayloadFeatureMember` と `'from' FlowEndMember 'to' FlowEndMember` は
// どちらも独立してoptionalだが、ここでは`flow of T from a to b;` 形を
// 最小サポートする。
// `abstract flow flows: Flow[0..*] nonunique :> messages, flowTransfers
// { doc ... }`（Flows.sysml、2件）のように、`of`/`from...to`を伴わない
// 裸のflow usage形（connection/allocation/message等と同型）も第2代替
// として持つ（connectionUsageのbare形と同じ設計）。
// `flow '外界の映像を撮る'.'映像' to '前方障害物との距離を推定する'.
// 'カメラ映像';`（adas-sysmlv2-main、実モデル）のように、`from`キーワード
// を省略した2端点直接形（`actionFlowStmt`のflowShort相当）が、action本体の
// 外（part/package直下）でも使われる。公式Xtext文法（org.omg.
// sysml.xtextの`FlowDeclaration`fragment）の`ownedRelationship +=
// FlowEndMember 'to' ownedRelationship += FlowEndMember`という代替に
// 対応する。
// `flow '前方衝突警報を通知する'::'前方衝突を警告する'.'警告音' to ...;`
// （adas-sysmlv2-main、実モデル、12件）のように、端点が`::`と`.`を
// 混在させる場合もあるため、`qualifiedName`ではなく`namespacePath`を
// 使う。
flowUsage
    : 'flow' ( 'of' ID )?
      ( 'from' fromEnd=namespacePath 'to' toEnd=namespacePath
      | fromEnd=namespacePath 'to' toEnd=namespacePath
      )?
      ';'
    | isAbstract='abstract'? 'flow' simpleName?
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// `abstract flow def MessageAction :> Action, Link { ... }`（Flows.sysml、
// 4件）のように、`flow def`という定義形は他の`*Def`規則（partDef等）と
// 同型（`abstract`修飾子・継承節・body）である。
flowDef
    : isAbstract='abstract'? 'flow' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// --- フェーズ2: action の item パラメータ (8.2.2.17) ------------------------
// 参照: SysML.xtext の `ItemUsage`（`ItemUsageKeyword: 'item'`）と
// `FeatureDirection`（'in' | 'out' | 'inout'）。
actionDef
    : isAbstract='abstract'? 'action' 'def' simpleName inheritanceClause? ( '{' actionBodyElement* '}' | ';' )
    ;

// `abstract calc getNextState: GetNextState;`（StateSpaceRepresentation.
// sysml、action def本体直下のbareなcalc usage）のように、`calculationUsage`
// 等のusage-keyword規則もaction def本体内で使える必要があるため、
// `calcBodyElement`と同型に`partBodyElement`への委譲を末尾（フォール
// バック）として持つ。action def本体専用の要素（decision/fork等の制御
// ノード・代入文・send/accept/perform/message/if文・action flow文）は
// 先に列挙する（`flow from a to b;`が`partBodyElement`の`flowUsage`と
// `actionFlowStmt`の両方で受理可能な曖昧性を持つため、`actionFlowStmt`を
// 先に置いて既存の`flow_stmt`出力を優先させる必要がある）。
actionBodyElement
    : flowControlNode
    | assignmentStmt
    | sendActionStmt
    | acceptActionStmt
    | performActionStmt
    | messageStmt
    | ifActionStmt
    // 波括弧必須のifActionStmtとは別の、ガード付きsuccession短縮形。
    | guardedTargetSuccessionStmt
    | defaultTargetSuccessionStmt
    | actionFlowStmt
    | partBodyElement
    ;

// 公式コーパスには`in attribute domainValues [0..*];`・`in ref
// alternative : Anything { doc ... }`・`in calc :>> eval =
// evaluationFunction;`のように、`item`以外の型キーワード（`attribute`/
// `ref`/`calc`/`action`）・`::`修飾型・多重度・redefine節・値代入・body
// を組み合わせた形が広く使われている（6ファイル・14件超）。他のusage
// 規則と同じ設計（名前省略・pre/post redefine節）を使う。型節は`::`修飾名
// も取れるよう`ID`ではなく`namespacePath`を使う。
// `actionBodyElement`（action def本体）だけでなく、`in ref :>>
// alternatives = studyAlternatives;`のように`objective`/`subject` usage
// 本体（partBodyElementベース）にネストして使われる例（TradeStudies.sysml）
// もあるため、`partBodyElement`の代替にも登録する（calc def本体は
// `calcBodyElement`が`partBodyElement`に委譲するため、この登録だけで
// StateSpaceRepresentation.sysml/SampledFunctions.sysml/VerificationCases.
// sysmlのcalc def内の同型パラメータも合わせて解決する）。
// `in calc calculation { in x; }`（SampledFunctions.sysml）のように、
// calc種別のactionParameter自身のbody内部にさらにactionParameter
// （`in x;`）をネストする形もあるため、actionParameter自体を再帰的に
// body内へ登録する（documentationStmt/bareDocCommentに加えて）。
// `in transitionLinkSource [1]: StateAction :>> ...;`（States.sysml）の
// ように、多重度を型節より先に置く逆順（eventOccurrenceUsageStmtと同型の
// 順序）もある。既存の「型節→多重度」という通常順（他の多数の実例）は
// 維持しつつ、`preMult`/`postMult`という別ラベルで両方の位置に多重度を
// 許すことで両順序を曖昧性なく共存させる。
// `in clock : Clock[1] default enclosingItem.localClock;`
// （SpatialItems.sysml/Time.sysml）・`in target : Occurrence[1] default
// that as Occurrence { doc ... }`（Actions.sysml）のように、
// actionParameterはattributeUsage/itemUsage等と同型の排他選択
// （`default expr`｜`= expr`）を持つ。
// `out xxx : ~xxxx;`のように、portUsageと同じ`~`接頭辞（共役ポート
// 参照）を型節が取りうる（actionのin/outパラメータとしてport型を渡す形）。
actionParameter
    : (direction | dirReturn='return')
      kind=('item' | 'attribute' | 'ref' | 'calc' | 'action')?
      simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      preMult=multiplicitySpec?
      (':' conjugated='~'? namespacePath)?
      postMult=multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      // `in whileTest default {true} { doc ... }`（Actions.sysml、2件）
      // のように、`default`値が波括弧で囲まれた式（`{true}`）を取ることが
      // ある。直後のactionParameter自体のbody（同じく`{...}`）とは別物で、
      // resultExpressionMemberと同型（末尾`;`は省略可能）に扱う。
      ( 'default' ( '{' defaultValue=expression ';'? '}' | defaultValue=expression ) | '=' value=expression )?
      ( '{' (documentationStmt | bareDocComment | actionParameter)* '}' | ';' )
    ;

direction
    : 'in' | 'out' | 'inout'
    ;

// --- decision/fork/join/merge の制御フローノード (8.2.2.17) ------------------
// 参照: KerML.xtext の `DecisionNode`/`ForkNode`/`JoinNode`/`MergeNode`
// （'decision'|'fork'|'join'|'merge' + 宣言名(省略可) + body-or-semi）。
// 公式仕様通りに名前をAST化する。bodyはactionBodyElementの反復を許可する
// （ネストしたcontrol nodeや代入・send actionを書けるようにする）。
flowControlNode
    : kind=('decision' | 'fork' | 'join' | 'merge') simpleName? ( '{' actionBodyElement* '}' | ';' )
    ;

// --- 代入文 (Section 7.17 AssignmentActionUsage) -----------------------------
// 両演算子（`=`/`:=`）を正しく認識し、name/operator/valueを埋める。
// 先頭の`'assign'`キーワードは省略可能（SysML.xtextのAssignmentActionUsageは
// 明示的な`assign`キーワード形と、KerMLの暗黙のFeatureWrite（キーワード無し）
// 形の両方を許す）。
// `private action initialization\n    assign index := 1;`
// （Actions.sysml、LoopActionのfor-loop展開）のように、代入文自体に
// `action`キーワード+名前という名前付きノード形（公式のAssignmentNode
// DeclarationがActionNodeUsageDeclarationとして許す、`action`キーワード+
// 名前の省略可能プレフィックス）と、直前ノードとの暗黙の連鎖を表す先頭の
// 裸`then`（公式のEmptySuccessionMember、対象参照を伴わない`then`単体）も
// 持つ。visibility修飾子（`private`）も同時に必要。連鎖の意味解釈は
// linter.py側の仕事であり本パーサーの範囲外（bareThenStmt/bareFirstStmtと
// 同じ方針）。
assignmentStmt
    : isThen='then'? visibilityIndicator? ('action' actionName=simpleName?)? 'assign'? target=simpleName op=('=' | ':=') value=expression ';'
    ;

// --- send action (Section 7.17 SendActionUsage) ------------------------------
// 名前付き・匿名(to/via)の両方に対応する。
// `send FCW::'FCWの作動を判定する'.'警報' via '警報出力';`
// （adas-sysmlv2-main、実モデル、1件）のように、payload参照が`::`と`.`を
// 混在させる場合もあるため、payloadのみ`qualifiedName`ではなく
// `namespacePath`を使う（receiver/toTarget/viaTargetは実コーパスで
// `::`混在の使用例が無いため`qualifiedName`のまま）。
sendActionStmt
    : 'action' name=simpleName 'send' payload=namespacePath 'to' receiver=qualifiedName ';'          # sendActionNamed
    | 'send' payload=namespacePath ( 'to' toTarget=qualifiedName | 'via' viaTarget=qualifiedName ) ';' # sendActionAnonymous
    ;

// --- accept action (Section 7.17 AcceptActionUsage) --------------------------
// 型指定ありの形（`accept msg : T via port;`）と型指定なしの形
// （`accept msg via port;`）の両方に対応する。
// `action '外界取得' accept scene : Items::'外界' via 'レンズ';`
// （adas-sysmlv2-main、実モデル、15件）のように、ネストしたアクション
// ノードに`action`キーワード+名前という名前付きプレフィックスを伴い、
// 本体自体が波括弧なしの単一`accept ...;`文である形も持つ（assign/while
// と同型のパターン）。公式Xtext文法の`AcceptNodeDeclaration`
// fragment（`ActionNodeUsageDeclaration?`= `ActionUsageKeyword
// UsageDeclaration?`の省略可能プレフィックス）に対応する。
// messageType節（`Items::'外界'`・`Parts::'方向指示器'::'指示状態'`という
// 3階層`::`区切りも実在）は`::`区切り型参照を受理できるよう
// `namespacePath`を使う。
acceptActionStmt
    : isThen='then'? visibilityIndicator? ('action' actionName=simpleName?)?
      'accept' message=qualifiedName ( ':' messageType=namespacePath )? 'via' port=qualifiedName ';'
    ;

// --- perform action (Section 7.17 PerformActionUsage) -------------------------
// `then perform body;`（Actions.sysml、LoopActionのfor-loop展開）の
// ように、直前ノードとの暗黙の連鎖を表す先頭の裸`then`を持つ
// （assignmentStmtと同じ考え方）。
// `perform action '外界の映像を出力する' { ... }`・`perform action
// 'LDWをONにする' redefines 'スイッチをONにする' { ... }`
// （adas-sysmlv2-main、実モデル、19件）のように、`action`キーワード+
// 名前(+任意でredefines節)+波括弧bodyを伴うperformアクションも持つ。
// 公式Xtext文法の`PerformActionUsageDeclaration`fragment
// （`ActionUsageKeyword UsageDeclaration?`、UsageDeclarationはredefines
// 等のFeatureSpecializationを含む）に対応する。actionUsageStmtと同型の
// 名前プレフィックス・redefine節・bodyを持つ。
// `perform FCW::'外界の映像を撮る';`（adas-sysmlv2-main、実モデル、
// 11件）のように、裸参照対象が`::`区切り（他パッケージ参照）を伴う
// 場合もあるため（dependencyStmtと同じ考え方）、`namespacePath`を使う。
performActionStmt
    : isThen='then'? 'perform' namespacePath ';'
    | isThen='then'? 'perform' 'action' actionName=simpleName?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' actionBodyElement* '}' | ';' )
    ;

// --- message (Section 7.17, InvocationExpression/MessageOccurrence) ----------
messageStmt
    : 'message' simpleName? 'from' fromEnd=qualifiedName 'to' toEnd=qualifiedName ';'
    ;

// `abstract message messages: Message[0..*] nonunique :> transfers,
// actions { ... }`（Flows.sysml）のように、`from`/`to`を伴わない裸の
// `message`usage形（itemUsage/partUsage等と同型）も持つ
// （`messageStmt`は`from`/`to`必須の別構文のため衝突しない）。
messageUsage
    : isAbstract='abstract'? 'message' simpleName?
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// --- if/else (Section 7.17 IfActionUsage) -------------------------------------
// 参照: KerML.xtext / SysML.xtext の `IfActionUsage`。
// bodyはactionBodyElementの反復を許可する（decision node等と同じ方針）。
ifActionStmt
    : 'if' condition=expression '{' thenElement+=actionBodyElement* '}'
      ( 'else' '{' elseElement+=actionBodyElement* '}' )?
    ;

// `if '前方衝突を警告する'.'警告灯' then '前方衝突警告灯'::'警告灯を
// ONにする'; else '前方衝突警告灯'::'警告灯をOFFにする';`
// （adas-sysmlv2-main、実モデル）のように、既存ノード（flow文・accept
// アクション等）の直後に続く、波括弧なしの`if <式> then <参照>;`+
// `else <参照>;`というガード付きsuccession短縮形（波括弧必須の
// `ifActionStmt`とは別物）を持つ。公式Xtext文法の`ActionTargetSuccession`
// （`GuardedTargetSuccession`＝`GuardExpressionMember('if'式) 'then'
// TransitionSuccessionMember`、`DefaultTargetSuccession`＝`'else'
// TransitionSuccessionMember`）に対応する。`if`直後の波括弧有無で
// `ifActionStmt`と曖昧性なく区別できる。連鎖の意味解釈はbareThenStmt/
// bareFirstStmtと同じ方針でlinter.py側の仕事とし、本パーサの範囲外と
// する。参照対象は`::`区切りも実在するため`namespacePath`を使う。
guardedTargetSuccessionStmt
    : 'if' guard=expression 'then' target=namespacePath ';'
    ;

defaultTargetSuccessionStmt
    : 'else' target=namespacePath ';'
    ;

// --- action usage（ネストしたaction, Section 7.17） ---------------------------
// bodyにactionBodyElementの反復を許可し、有用なネストを可能にする。
// `while`ガード（`action X while cond { ... }`）は公式のWhileLoopAction
// Usageを簡略化した形（ループの継続条件）。
// `abstract ref action performedActions: Action[0..*] :> actions,
// enactedPerformances { ... }`（Parts.sysml）のように、他のusage
// キーワード規則と同型のredefinition機能一式（visibility・ref・名前
// 省略・型節+多重度・pre/post redefine節）を持つ。
// `private ref action thisConnection = self;`（Flows.sysml）のように、
// 他のusage規則（item/attribute/requirement等）と同じ`=`値代入も持つ。
// `then private action whileLoop while index <= size(seq) { ... }`
// （Actions.sysml、LoopActionのfor-loop展開）のように、直前ノードとの
// 暗黙の連鎖を表す先頭の裸`then`も持つ（assignmentStmt/performActionStmt
// と同じ考え方）。
// `action <'xxx'> Name { ... }`のように、attributeUsageと同じ配置
// （キーワード直後・名前の前）でShortName注釈を取りうる。
actionUsageStmt
    : isThen='then'? visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'action' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('=' value=expression)?
      ( 'while' guard=expression )?
      ( '{' actionBodyElement* '}' | ';' )
    ;

// --- フェーズ2: requirement の doc (8.2.2.21) -------------------------------
// 参照: SysML.xtext の `Documentation`。`doc` の本体は文字列リテラルではなく
// `body = REGULAR_COMMENT`、すなわち `/* ... */` 形式のブロックコメント。
//
// requirementBodyElementはdocumentationStmtのみ（simpleNameは任意）で
// 表す。専用のdocMember規則は持たない。
requirementDef
    : isAbstract='abstract'? 'requirement' 'def' simpleName inheritanceClause? ( '{' requirementBodyElement* '}' | ';' )
    ;

// 公式コーパスの`requirement def RequirementCheck { ... }`
// （Requirements.sysml）は本体内で`subjectUsage`（`subject subj :
// Anything[1] { ... }`）・`partUsage`（`ref part actors : Part[0..*]
// { ... }`）・`constraintUsage`（`constraint assumptions :>> ...;`）・
// `requirementUsage`（`abstract requirement subrequirements[0..*] :>
// requirementChecks, constraints { ... }`）を広く使うため、他の`_def`と
// 同様`partBodyElement`へ全面委譲する。
requirementBodyElement
    : partBodyElement
    ;

// `concern`キーワードは`requirement`と完全に同型の定義・usage双方を持つ
// （`concern def ConcernCheck :> RequirementCheck { ref concern :>> self:
// ConcernCheck; }`、Requirements.sysmlのみ）ため、requirementDefと同型に
// する。
concernDef
    : isAbstract='abstract'? 'concern' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// --- フェーズ2: state の entry (8.2.2.18) -----------------------------------
// 参照: SysML.xtext の `EntryActionMember`（`kind = EntryActionKind` = 'entry'）。
// StateActionUsage の完全な一般形（インライン定義等）は未対応。既存アクションへの
// 参照 (`entry act1;`) のみサポート。
stateDef
    : isAbstract='abstract'? 'state' 'def' simpleName inheritanceClause? ( '{' stateBodyElement* '}' | ';' )
    ;

// nested `state def Sub;`はsymbolとして登録される。`_find_state_in_symbols`
// はtype=="state_def"のものしか見つけられないため、transitionの
// source/targetから参照するにはこれが必要。
// bare形の`state Sub;`（usageであってdefではない）も持つが、
// `_find_state_in_symbols`はusageを認識しないため、transitionの
// source/targetからは参照できない（構文的完全性のための対応で、
// transitionとの連携価値は無い点に注意）。
stateBodyElement
    : entryActionMember
    | doActionMember
    | exitActionMember
    | stateDef
    | stateUsage
    | transitionStmt
    | bindingConnector
    | successionStmt
    // `succession stateSequencing first [0..1] exclusiveStates then
    // [0..1] exclusiveStates { ... }`（States.sysml、state def本体内）。
    | successionUsage
    | attributeUsage
    | initialTransitionMember
    // `doc /* ... */`（States.sysml、state def本体直下）・
    // `assert constraint { ... }`（同ファイル）も、他のpartBodyElement系と
    // 同様stateBodyElementに登録する。
    | documentationStmt
    | bareDocComment
    | assertConstraintUsage
    // `action :>> subactions :> middle { doc ... }`（States.sysml）の
    // ように、名前省略の裸の`action`usage形もstate def本体で使える
    // （entry/do/exit ActionMemberは'entry'/'do'/'exit'から始まるため
    // 語彙的な衝突はない）。
    | actionUsageStmt
    ;

// bodyにstateBodyElementの反復を許可し、`state On { entry action ...;
// do action ...; exit action ...; }`のような実用上必要な形をサポートする。
// `abstract ref state exhibitedStates: StateAction[0..*] :> stateActions,
// performedActions { ... }`（Parts.sysml）・`ref state self: StateAction
// :>> Action::self, StatePerformance::self;`（States.sysml）のように、
// `ref`修飾子・型節・redefine節（itemUsage/partUsage等と同型）も持つ。
stateUsage
    : isAbstract='abstract'? isRef='ref'? 'state' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' stateBodyElement* '}' | ';' )
    ;

// --- 初期遷移の省略形（`entry; then Off;`） ------------------------------------
// 参照: SysML.xtext の `entry_action_member_with_transition:
// entry_action_member entry_transition_member*`
// （`entry_transition_member: (guarded_target_succession | KW_THEN
// target_succession) ";"`）。ここでは`entry;`（既存のentryActionMember、
// 名前参照なしの形）と、独立した「ソース無し遷移」（暗黙の初期状態からの
// 遷移）の2つの文として扱い、既存の`transition`ノード形状を再利用する。
// `_check_transition`（linter.py:1346）は`source`が`None`の場合チェックを
// スキップするため安全。
initialTransitionMember
    : 'then' target=qualifiedName ';'
    ;

// --- binding connector / succession (8.2.2.13) ---------------------------------
// `_check_binding_connector`/`_check_succession_connector`
// （linter.py:1560,1578）は`self.connections`（connection_defのみが登録
// される）を走査して呼ばれるため、現状はトップレベルのbinding_connector/
// successionノードに対して実際には発火しない（連携未整備、linter.py側の
// 設計）。それでも構文的完全性のため、connectorEndを再利用して実装する。
// `binding [1] bind [0..*] base.edges = [0..*] be;`（ShapeItems.sysml、
// 公式コーパス全体で51件）のように、名前付き（常に`binding`固定）+
// 自体の多重度（常に`[1]`固定）+各end側の多重度を伴う形も持つ。名前・
// 各種多重度はいずれも省略可能にし、既存の裸形（`bind a = b;`・`bind a =
// b { doc ... }`）とも共存させる。多重度は`connMult`（コネクタ自体）・
// `leftMult`/`rightMult`（各end）と別ラベルにして曖昧性・list-getter化を
// 避ける。
// `bind LDW::'レーンモデルを生成する'.'カメラ画角' = 'カメラ画角';`
// （adas-sysmlv2-main、実モデル、5件）のように、端点が`::`と`.`を
// 混在させる場合もあるため、connectUsageと同じ考え方で端点は
// `connectorEnd`ではなく`connectorEndPath`（`.`/`::`両対応）を使う
// （共有`connectorEnd`自体は他の参照元への影響を避けるため変更しない）。
bindingConnector
    : simpleName? connMult=multiplicitySpec? 'bind'
      leftMult=multiplicitySpec? leftEnd=connectorEndPath '='
      rightMult=multiplicitySpec? rightEnd=connectorEndPath
      ( '{' partBodyElement* '}' | ';' )
    ;

successionStmt
    : 'first' firstEnd=connectorEnd 'then' thenEnd=connectorEnd ';'
    ;

// `succession causalOrdering first [nCauses] causes.startShot then
// [nEffects] effects { doc ...; attribute nCauses = size(causes);
// attribute nEffects = size(effects); }`（CausationConnections.sysml）・
// `succession stateSequencing first [0..1] exclusiveStates then [0..1]
// exclusiveStates { doc ... }`（States.sysml）・`succession [seBeforeNum]
// first [0..1] sourceEvent then [0..1] self;`（Flows.sysml）のように、
// `succession`キーワード自体（`successionStmt`は無名の`first ... then
// ...;`のみ）・名前・先頭多重度・connectorEnd側の多重度・bodyを持つ。
// 公式コーパスの.sysmlファイル3件で確認した範囲（名前と先頭多重度は
// 排他的に使われ同時出現例が無い）に絞って実装する。
successionUsage
    : visibilityIndicator? 'succession' simpleName? multiplicitySpec?
      'first' firstMult=multiplicitySpec? firstEnd=connectorEnd
      'then' thenMult=multiplicitySpec? thenEnd=connectorEnd
      ( '{' partBodyElement* '}' | ';' )
    ;

// --- bare first/then（action/part本体内の連鎖チェーン形） --------------------
// 参照: KerML.xtext の`flow_control_stmt`の`KW_FIRST simple_id ";"` /
// `KW_THEN (simple_id | control_node_ref) ";"`分岐。action本体/part本体
// 双方に含まれる。`first A then B;`という1文の組み合わせとは異なり、
// `first A;`と`then B;`はそれぞれ独立した文である点に注意
// （`first start; then fork1; then X;`は「start→fork1」「fork1→X」という
// 連鎖の意図だが、構文上は3つの独立した文で、連鎖の意味解釈はlinter.py側
// の仕事であり本パーサーの範囲外）。
bareFirstStmt
    : 'first' target=qualifiedName ';'
    ;

bareThenStmt
    : 'then' target=qualifiedName ';'
    ;

// --- action flow statement (8.2.2.13 flow_stmt, action本体専用) -------------
// 参照: KerML.xtext の`flow_stmt: flow_of_stmt | flow_from_stmt |
// flow_short_stmt | succession_flow_stmt`。action本体にのみ含まれ
// part本体には含まれない（part本体内のflowは`flowUsage`が別途担当）。
// `flow <path> to <path>;`（flow_short_stmt）と`flow from <path> to
// <path>;`（flow_from_stmt）の両方に対応する（`'Boil Water'.w`のような
// 単一引用符を含むパスもqualifiedNameのQUOTED_NAME対応により動作する）。
actionFlowStmt
    : 'flow' 'from' fromPath=qualifiedName 'to' toPath=qualifiedName ';'  # actionFlowFrom
    | 'flow' fromPath=qualifiedName 'to' toPath=qualifiedName ';'         # actionFlowShort
    ;

// 参照: SysML.xtext の `EntryActionMember`/`DoActionMember`/`ExitActionMember`
// （`kind = EntryActionKind` 等）。`_check_state_actions`（linter.py:3535）が
// 読む `kind` フィールド（"entry"/"do"/"exit"）を持たせる。'action'キーワードと
// 参照先アクション名はどちらも省略可（`entry;` 単体も許可）。
// `entry action entryAction :>> 'entry';`・`do action doAction: Action
// :>> 'do';`・`exit action exitAction: Action :>> 'exit';`（States.sysml）
// のように、型節（`: Action`）・redefine節（`:>>`、対象は`entry`/`do`/
// `exit`自体が予約語のためQUOTED_NAMEで囲む）も持つ。
entryActionMember
    : 'entry' ('action')? qualifiedName? (':' ID)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ';'
    ;

doActionMember
    : 'do' ('action')? qualifiedName? (':' ID)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ';'
    ;

exitActionMember
    : 'exit' ('action')? qualifiedName? (':' ID)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ';'
    ;

// --- transition (8.2.2.18) -------------------------------------------------------
// 参照: SysML.xtext の `transition_stmt` 系。`accept`/`if`/`do`は
// いずれも省略可。`if`節には式文法をそのまま再利用する。
// `_check_transition`（linter.py:1346）は `source`/`target` のみ必須。
// `_check_transition_advanced`/`_check_transition_advanced_structure`
// （linter.py:1694,3577）はtrigger/guard/effectそれぞれに正しい`kind`タグ
// （"trigger"/"guard"/"effect"）を要求するため、それに合わせて組み立てる。
// `entry; then X;`のような初期遷移の省略形（KW_ENTRY直後にKW_THENが続く形）は
// 未対応。
// `transition aTransition first start accept apayload: Anything via
// receiver then done;`（Actions.sysml）のように、`accept`パラメータに
// 型節（`: Anything`）と`via`節（受信ポート/参照）が付く形も持つ。
transitionStmt
    : 'transition' simpleName? 'first' source=qualifiedName
      ( 'accept' trigger=qualifiedName (':' triggerType=namespacePath)? ('via' via=qualifiedName)? )?
      ( 'if' guard=expression )?
      ( 'do' ('action')? effect=qualifiedName )?
      'then' target=qualifiedName ';'
    ;

// --- 式 (KerMLExpressions.xtext) -----------------------------------------------
// 参照: KerMLExpressions.xtext の演算子優先順位階層（低い方から）
// ConditionalExpression > NullCoalescing > Implies > Or > Xor > And >
// EqualityExpression > ClassificationExpression > RelationalExpression >
// RangeExpression > AdditiveExpression > MultiplicativeExpression >
// ExponentiationExpression > UnaryExpression > PrimaryExpression。
// 全15階層のうち、比較・算術という実際に必要になった範囲
// （Equality/Relational/Additive/Multiplicative + 単項マイナス/not）のみ実装する。
// ANTLR4の直接左再帰では「先に書いた選択肢ほど強く結合する」規則を使うため、
// 上記の優先順位を選択肢の順序（単項マイナス/not > 乗除 > 加減 > 比較 > 等価）で
// 表現している（単項マイナスは乗除より強く結合しなければならない点に注意。
// equality/relationalより弱い順序で書くと、`-x > 0` が `-(x > 0)` と
// 解釈されてしまう）。
// `not`は単項マイナスと同じ優先順位（同階層）にする。
// `#(...)`はKerMLのインデックスアクセス式（例: `mRefs#(1)`、
// `mRef.mRefs#(1)`。公式コーパスで6ファイル・99件使用）。通常の算術演算子
// より結合が強い後置演算子として、mulDivExprより前に置く。
expression
    : '-' expression                                            # unaryMinusExpr
    | 'not' expression                                          # notExpr
    | expression '#' '(' expression ')'                         # indexExpr
    // `(that as Action).this`（Actions.sysml）・`(that as Occurrence)`・
    // `(edges#(i).vertices#(2) as Item).matingOccurrences`
    // （ShapeItems.sysml）のように、KerMLの型キャスト式（`expr as Type`）
    // と、それに続く任意の式に対する後置`.member`アクセスを持つ（公式
    // コーパス6.sysmlファイル・20件超で使用）。`qualifiedName`は`.`区切りの
    // 識別子チェーンを常に貪欲に消費するため、裸の名前参照（`a.b.c`）は
    // `nameRefExpr`が担い、`memberAccessExpr`は`(expr as Type)`/関数呼び
    // 出し結果等、
    // qualifiedNameで表現できない式の後にのみ実際に使われる（曖昧性なし、
    // ANTLRの通常のprediction順で解決される）。`#()`と同様、メンバ
    // アクセスに準じる強い結合の後置演算子として扱う。
    | expression '.' member=simpleName                          # memberAccessExpr
    | expression 'as' typeRef=namespacePath                     # asCastExpr
    // `multicausations meta SysML::Usage;`（CauseAndEffect.sysml、4ファイル・
    // 7件）のように、KerMLの`meta`式（メタデータ型参照）を持つ。
    // `asCastExpr`と同型。
    | expression 'meta' typeRef=namespacePath                   # metaExpr
    // KerMLの矢印記法によるコレクション操作（`->`演算子）。公式コーパス
    // .sysmlファイルで実測11種類・7ファイルで使用。2つの形に大別される:
    // (1) 引数を丸括弧で渡す単純呼び出し（例:
    // `derivedRequirements->excludes(originalRequirement)`、
    // `seq->excludingAt(position)`）。(2) 波括弧のラムダ式風本体を渡す反復系
    // 演算（例: `basisDirections->forAll { in basisDirection :
    // VectorQuantityValue; ... }`）。`#()`と同様、メンバアクセスに準じる
    // 強い結合の後置演算子として扱い、indexExprの直後に置く。
    | expression '->' opName=simpleName '(' (expression (',' expression)*)? ')'  # arrowCallExpr
    | expression '->' opName=simpleName '{' arrowLambdaBody '}'                   # arrowLambdaExpr
    // `Triangle::length^2 + Triangle::width^2`のように、`^`べき乗演算子が
    // 公式コーパス17ファイルで使われている（`s^-1`等の単位式が大半）。
    // 算術演算子より強く結合するため`mulDivExpr`より前に置く。
    | expression op='^' expression                              # powerExpr
    | expression op=('*'|'/') expression                       # mulDivExpr
    | expression op=('+'|'-') expression                       # addSubExpr
    // `0 [m]`・`273.15 [K]`・`229835/900 [K]`（ShapeItems.sysml/SI.sysml/
    // USCustomaryUnits.sysml、4件）のように、数値リテラル（または算術式）に
    // 単位を角括弧で付与するquantity literal記法を持つ。単位は算術演算の
    // 結果全体に付与される（`229835/900 [K]`は`(229835/900) [K]`の意味）
    // ため、mulDivExpr/addSubExprより後（弱く結合する位置）に置く。
    // `num#(1) [mRef.mRefs#(1)]`（ISQSpaceTime.sysml）のように、角括弧内が
    // 単純なnamespacePathではなく`#()`インデックスアクセスを伴う式のことも
    // あるため、`unit`節の型は`namespacePath`ではなくより一般的な
    // `expression`にしてある。
    | expression '[' unit=expression ']'                        # quantityLiteralExpr
    | expression op=('<'|'>'|'<='|'>=') expression              # relationalExpr
    | expression op=('=='|'!=') expression                     # equalityExpr
    // `and`/`or`論理演算子（例: `assert constraint boundMatch { (isBound ==
    // mRef.isBound) or (not isBound and mRef.isBound) }`）。比較・等価
    // 演算子より結合が弱いためequalityExprの後に置く（`and`は`or`より
    // 結合が強い、一般的な優先順位）。`&`/`|`は`ShapeItems.sysml`/
    // `Items.sysml`にそれぞれ1件のみ実測（`and`/`or`の代替表記と見られる）。
    // 使用範囲が極めて狭いため新設のノード種別は起こさず、同じ`and`/`or`
    // の代替キーワードとして同一alt内に持つ。
    | expression op=('and' | '&') expression                    # logicalAndExpr
    | expression op=('or' | '|') expression                     # logicalOrExpr
    // `implies`論理演算子（例: `allTrue(assumptions()) implies
    // allTrue(constraints())`）。`and`/`or`より結合が弱い（一般的な優先順位、
    // `or`の後に置く）。
    | expression op='implies' expression                        # impliesExpr
    // KerMLの三項条件式（`cond ? a : b`記法ではなく`if cond ? then else
    // elseExpr`という`if`/`else`キーワードを伴う形。例: `if index == null
    // or index == size(domainValues)? null else if domainValues#(index) <
    // domainValues#(index+1)? Linear(...) else Linear(...);`のように、
    // elseExpr側に別のif式を再帰的に書くことでelse-if連鎖を表現する
    // （`elseExpr`が`expression`を再帰参照するため追加の規則無しで自動的に
    // チェーンできる）。他の二項演算子より結合が弱い最も緩い位置に置く
    // （`if`は既に`ifActionStmt`/`transitionStmt`のguard節で使用済みだが、
    // いずれも異なる文脈のため曖昧性は無い）。
    | 'if' cond=expression '?' thenExpr=expression 'else' elseExpr=expression  # conditionalExpr
    | '(' expression ')'                                        # parenExpr
    // `(1..size(seq))->selectOne{...}`（Interfaces.sysml/
    // SampledFunctions.sysml/ShapeItems.sysml、6件）のように、`(a..b)`と
    // いう範囲式（`multiplicityBracket`の`..`とは別の、任意の式としての
    // 範囲）を持つ。`)`の直前が`..`で終わるか否かでparenExprと曖昧性なく
    // 区別される。
    | '(' lower=expression '..' upper=expression ')'            # rangeExpr
    | '(' expression (',' expression)+ ')'                      # sequenceExpr
    // 空の列挙式`()`（例: `attribute :>> dimensions = ();`、
    // `MeasurementReferences.sysml`）。
    | '(' ')'                                                    # emptySequenceExpr
    // 関数呼び出し式（例: `size(x)`、`notEmpty(x)`、
    // `getDifference(input, stateSpace)`）。引数は`expression`を再帰的に
    // 使うため、入れ子の関数呼び出しも自動的に書ける。`qualifiedName`単体
    // （nameRefExpr）との曖昧性は、ANTLRが`(`の有無を先読みして解決するため
    // 問題ない。ラムダ式を渡す反復系演算子（`->forAll { ... }`等）は
    // arrowLambdaExprが対応する。
    // 呼び出し先は`qualifiedName`（`.`区切りのみ）ではなく`namespacePath`
    // （`::`区切りも可）を使う（例: `NumericalFunctions::isZero(x.num)`、
    // QuantityCalculations.sysml）。公式コーパス全体で`.`区切りの呼び出し先
    // （`a.b(...)`形）は0件のため、これによる既存動作への影響はない。
    // `tradeStudyObjective(selectedAlternative = a)`（TradeStudies.sysml）
    // のように、`new`式ではない通常の関数呼び出しも名前付き引数
    // （`name = expression`）を取ることがあるため、引数リストは
    // `expression`ではなく`newArgument`（位置引数・名前付き引数の両方に
    // 対応済み）を共有する。
    | namespacePath '(' (newArgument (',' newArgument)*)? ')'    # functionCallExpr
    // KerMLのインスタンス生成式（例: `new DimensionOneUnit()`、
    // `new RiskLevel(probability = LevelEnum::low)`）。引数は
    // `functionCallExpr`の位置引数とは異なり`name = expression`という
    // 名前付き引数のみ（公式コーパスで確認した3ファイル・5件すべてが
    // この形）。
    | 'new' qualifiedName '(' (newArgument (',' newArgument)*)? ')'  # newExpr
    | qualifiedName                                             # nameRefExpr
    // `::`修飾名による式（例: `MeasurementUnit::unitPowerFactors`、
    // `calcParameter`の値束縛`in x = MeasurementUnit::y;`で使用）。既存の
    // `qualifiedName`は`.`区切りのみのため、`::`区切りの`namespacePath`を
    // 別代替として持つ。単一IDの場合は先に書いた`nameRefExpr`が勝つ。
    | namespacePath                                             # namespacePathRefExpr
    | literal                                                   # literalExpr
    ;

literal
    : INT_LITERAL
    | REAL_LITERAL
    | STRING_LITERAL
    | 'true'
    | 'false'
    ;

// `->forAll`/`->select`/`->collect`等の波括弧ラムダ式風本体。公式コーパス
// の実測パターン（`{ in basisDirection : VectorQuantityValue; expr }`、
// `{ in i; expr }`、`{ p2 : Point; expr }`（`in`省略）、`{ doc /* ... */
// in x; expr }`（docがパラメータ宣言の前に来る、TradeStudies.sysmlの
// minimize/maximize）を1つの規則で受理する。パラメータ名の直後に中括弧が
// 続く入れ子body形（`in ref a { doc ... } expr`、TradeStudies.sysml
// selectOne）は、当該ファイル自体が別の未対応構文で既にパース失敗して
// おりスコープ外。
// `alternatives->minimize { doc /* ... */ in x; eval(x) };`
// （TradeStudies.sysml minimize/maximize）の`doc /* ... */`は
// `bareDocComment`(キーワード無し)ではなく`doc`キーワード付きの
// `documentationStmt`であるため、`documentationStmt`も受理する
// （`bareDocComment*`のみでは`doc`キーワードが`extraneous input`となる）。
arrowLambdaBody
    : (documentationStmt | bareDocComment)* lambdaParam? (documentationStmt | bareDocComment)* expression
    ;

// `->selectOne {in ref a { doc ... } tradeStudyObjective(...)}`
// （TradeStudies.sysml）のように、lambdaParamは他のusage-keyword規則と
// 同様に`;`だけでなく`{ doc ... }`というbody形も取りうる。body形にする
// ことで、`arrowLambdaBody`の既存構造（`lambdaParam? ... expression`）が
// そのままparam直後の結果式も受理できる。
lambdaParam
    : 'in'? isRef='ref'? simpleName (':' namespacePath)?
      ( '{' (documentationStmt | bareDocComment)* '}' | ';' )
    ;

// `new`式の名前付き引数（`probability = LevelEnum::low`）と、
// `new SamplePair(x, calculation(x))`（SampledFunctions.sysml）のような
// 位置引数（bare expression、カンマ区切り）の両方に対応する。
// `expression`規則には単項の`=`演算子が無い（等価演算子は`==`のみ）ため、
// `name = expr`という形は第1代替でのみ曖昧性なく解釈される。
newArgument
    : simpleName '=' expression
    | expression
    ;

// --- port def / port usage (8.2.2.12) ---------------------------------------
// 参照: SysML.xtext の `PortDefinition`（`DefinitionPrefix PortDefKeyword
// Definition`）と `PortUsage`（`OccurrenceUsagePrefix PortUsageKeyword Usage`）。
// どちらも body の形は part def/usage と同じ（`Definition`/`Usage`フラグメント
// 経由で `DefinitionBody`/`UsageBody` に帰着する）。
// ConjugatedPortDefinitionMember（暗黙の共役ポート）は未対応。
portDef
    : isAbstract='abstract'? 'port' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// partUsageと同じredefinition機能一式（visibility・ref・名前省略・型節
// 前後の:>/:>>節）に加え、bodyも持てる（`ref port :>> participant : Port
// [2..*] nonunique ordered { ... }`のように、実際にbodyを伴う形が公式
// 標準ライブラリに存在するため）。
// `port xxx : ~xxxx;`のように、型節が`~`接頭辞（共役ポート参照、KerMLの
// PortConjugation）を取りうる。linter.py側（_check_conjugated_port_typing）は
// 既にtype_nameが`~`始まりであることを前提に共役ポートの意味チェックを実装
// 済みだったため、文法側の対応が漏れていた。
// `port xxx[xx] : xxxx;`のように、多重度が型節より先（名前の直後）に来る
// 逆順もある（actionParameterのpreMult/postMultと同型の順序）ため、preMult/
// postMultという別ラベルで両方の位置を曖昧性なく共存させる。
portUsage
    : visibilityIndicator? isAbstract='abstract'? isConstant='constant'? isRef='ref'?
      'port' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      preMult=multiplicitySpec?
      (':' conjugated='~'? ID)?
      postMult=multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// --- import (8.2.2.3) --------------------------------------------------------
// 参照: KerML.xtext の `Import`（`(MembershipImport | NamespaceImport)
// RelationshipBody`）。`ImportedNamespace` は `QualifiedName '::' '*'`、
// `ImportedMembership` は `QualifiedName` のみ。どちらも KerML の
// qualified name は `::` 区切り（`.` 区切りの feature chain とは別概念）
// なので、connect/flow で使っている qualifiedName（`.`区切り）とは
// 別の namespacePath（`::`区切り）を用意する。
// visibility indicator（'private import ...;' 等）に対応する。'all'、再帰
// '::**'、'{ }' 形の RelationshipBody は未対応。
importStmt
    : visibilityIndicator? 'import' namespacePath ('::' '*')? ';'
    ;

visibilityIndicator
    : 'public' | 'private' | 'protected'
    ;

// `DataFunctions::'*'`のように、`::`修飾名の各セグメントはIDだけでなく
// QUOTED_NAME（演算子名の引用形、例: `'*'`/`'/'`/`'**'`/`'^'`）も取りうる
// （公式コーパスで25件、うち24件がinheritanceClauseの基底型）。
// qualifiedName（`.`区切り）が既にID|QUOTED_NAMEの混在を許しているのと
// 同じ形にする。
// `'participant'`は`participantMember`（interactionDef本体専用のsequence
// diagram記法）のリテラルキーワードとして予約されているため、レキサーが
// 常にこのキーワードトークンとして解釈し、`namespacePath`（ID|QUOTED_NAME）
// の一部としては使えない。KerMLの基礎feature`participant`（あらゆる
// connectionが持つ暗黙のend）を通常の識別子として参照する実例が公式
// コーパスに存在するため（`ref requirement originalRequirement[1] :>>
// originalRequirements :> participant { ... }`、
// DerivationConnections.sysml）、`namespacePath`のセグメントとして
// `'participant'`も受理する。
// `ref :>> outgoingTransfersFromSelf :> interfacingPorts.
// incomingTransfersToSelf { ... }`（Ports.sysml）のように、redefine対象等
// のnamespacePathが`.`区切りを取ることもある（公式コーパス全体で本1件の
// み）。namespacePathは30箇所から参照されているため、影響範囲を絞るべく、
// 既存の`::`区切りはそのままに区切り文字として`.`も追加で受理する
// （実コーパスで他の29箇所が`.`を含む例は無いため、既存の解釈は
// 変わらない）。
// `redefines type subsets Metadata::metadataItems;`（SysML.sysml、2件）
// のように、予約キーワード`type`がredefine対象（型参照位置）として
// 使われることがある。宣言名（simpleName）としての`type`とは別に、
// 型参照位置（namespacePath）でも`participant`と同じ考え方でセグメント
// 代替に含める。
namespacePath
    : (ID | QUOTED_NAME | 'participant' | 'type' | 'interaction') (('::' | '.') (ID | QUOTED_NAME | 'participant' | 'type' | 'interaction'))*
    ;

// part/port usageのredefine/subsets対象は`SpatialItem::localClock`のように
// `::`修飾名で書かれることが多いため、attributeUsageで使った
// qualifiedNameList（`.`区切りのみ）ではなくnamespacePathのカンマ区切り
// リストを使う。
namespacePathList
    : namespacePath (',' namespacePath)*
    ;

// --- expose (8.2.2.3) --------------------------------------------------------
// 参照: KerML.xtext の `expose_stmt: KW_EXPOSE qualified_id ";"`。
// importと同様、namespacePath（`::`区切り）とワイルドカードに対応する。
// exposeノードは{"type":"special_stmt","children":[{"type":
// "expose",...}]}という入れ子で返す。
exposeStmt
    : 'expose' namespacePath ('::' '*')? ';'
    ;

// --- interface def (8.2.2.14) -------------------------------------------------
// 参照: SysML.xtext の `InterfaceDefinition`。公式文法では body は
// `InterfaceBody`（`end` メンバーが第一級市民の専用構造）で、part def等の
// 汎用 DefinitionBody とは異なる。ここでは `end` メンバーは未対応で、
// part def と同じ body（partBodyElement）を暫定的に流用する簡略形のみ実装。
interfaceDef
    : isAbstract='abstract'? 'interface' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// --- 単一引用符名 (Name: ID | UNRESTRICTED_NAME) --------------------------------
// 参照: KerMLExpressions.xtext の `terminal UNRESTRICTED_NAME` と `Name: ID |
// UNRESTRICTED_NAME`。スペースを含む名前（`'Coffee Brewing Sequence'`等）を
// 宣言名として使えるようにする。現時点では「宣言される名前」の位置にのみ適用し、
// 型参照（`: TypeName` の右辺）や qualifiedName/namespacePath には未適用
// （実サンプルでの必要性が確認できていないため）。
// `attribute type : String[0..1] { ... }`（ImageMetadata.sysml）のように、
// 予約キーワード`type`（`typeDef`専用）を宣言名として使う実例もある
// （公式コーパス全体で本1件のみ）。`typeDef`は常に`'type' 'def'`という
// 並びのみを取るため、宣言名の位置に`'type'`を許しても曖昧性は生じない
// （`namespacePath`の`'participant'`と同じ考え方）。
simpleName
    : ID
    | QUOTED_NAME
    | 'type'
    ;

// --- レキサー ----------------------------------------------------------------

ID
    : [a-zA-Z_][a-zA-Z_0-9]*
    ;

QUOTED_NAME
    : '\'' (~['\\\r\n] | '\\' .)* '\''
    ;

// 参照: KerMLExpressions.xtext の terminal DECIMAL_VALUE / RealValue / STRING_VALUE。
// `1E-24`・`4.046873E+03`・`1.66053906660e-27`（SI.sysml/SIPrefixes.sysml/
// USCustomaryUnits.sysml/MeasurementReferences.sysml、4ファイル・118件）の
// ような指数表記（仮数部+E/e+符号任意+指数部）にも対応するため、指数部を
// 任意の末尾として両トークンに持たせる（最長一致によりANTLRが自動的に
// 指数部込みで消費するため曖昧性は生じない）。
REAL_LITERAL
    : [0-9]+ '.' [0-9]+ ([eE] [+-]? [0-9]+)?
    ;

INT_LITERAL
    : [0-9]+ ([eE] [+-]? [0-9]+)?
    ;

STRING_LITERAL
    : '"' (~["\\\r\n] | '\\' .)* '"'
    ;

// doc の本体専用トークン。一般的なブロックコメントのスキップとしては未対応。
DOC_COMMENT
    : '/*' .*? '*/'
    ;

WS
    : [ \t\r\n]+ -> skip
    ;

LINE_COMMENT
    : '//' ~[\r\n]* -> skip
    ;
