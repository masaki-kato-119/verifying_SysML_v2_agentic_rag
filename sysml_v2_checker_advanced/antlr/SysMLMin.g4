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
// `package 'Application Layer';`（DependencyTest.sysml）のように、本体
// `{}`を持たない、フォワード宣言/空パッケージ宣言もある（2026-08-28、
// 730件パース失敗の要因分析で発見）。
packageDef
    : ('standard')? ('library')? 'package' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName ( '{' topLevelElement* '}' | ';' )
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
    | verifyRequirementUsage
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
    // `ref annotatedRef { metadata Important { ... } }`（comprehensive_data_loss.sysml、
    // MetadataTest.sysml）のように、型キーワード（part/item等）を伴わない
    // 裸のfeatureUsage（`ref NAME { ... }`）もpackage直下に書ける
    // （2026-08-28、730件回帰チェックで発見。これまでpartBodyElement内にしか
    // 登録されておらず、package直下では構文エラーになっていた）。
    | featureUsage
    ;

// --- dependency (8.2.2.3) ------------------------------------------------------
// `dependency A to B;`・`dependency D from A to B;`のいずれも受理する。
// visitor側でidentification（`D`部分）は無視する。
// client/supplier参照は`::`区切り（他パッケージ参照）を伴うことがある
// （例: `dependency '意図しない車線逸脱の予防' to '事故の予防'::'車線逸脱
// による事故の予防';`、adas-sysmlv2-main）ため、`.`/`::`両方を受理できる
// `namespacePathList`を使う（単一セグメント名の出力は不変）。
// `#Type`プレフィックスメタデータ注釈（PrefixMetadataMember、8.2.2.9）。
// 公式コーパスでは`#refinement dependency X to Y;`のように`dependency`文の
// 前に付く形が圧倒的多数（apollo-11-sysml-v2だけで300件超）。他の宣言
// （enum/attribute/part/connect等）にも同様に付きうるが、まずは実際の
// 出現頻度が最も高いdependencyStmtに限定して対応する（2026-08-28、
// 参照実装比較レポートP0-4で発見。他の宣言への拡張は別タスクで追う）。
prefixMetadataAnnotation
    : '#' namespacePath
    ;

// `dependency from 'System Assembly'::'Computer Subsystem' to
// 'Software Design';`（Dependency Example.sysml）のように、名前を省略した
// 無名dependency文にも`from`節が付く（名前と`from`が常にペアという
// 従来の前提を外し、両者を独立に任意とする。2026-08-28、730件パース失敗の
// 要因分析で発見）。
dependencyStmt
    : prefixMetadataAnnotation* 'dependency' simpleName? 'from'? clients=namespacePathList 'to' suppliers=namespacePathList ';'
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
// `then event occurrence sensedSpeedReceived;`（Event Occurrence
// Example.sysml）のように、succession先としてevent occurrenceを
// インライン宣言する形も広く使われるため、flowControlNodeと同じ`isThen`
// 先頭修飾子を追加する（2026-08-28、730件パース失敗の要因分析で発見）。
// `event publish_source_event = publish_message.start;`
// （ServerSequenceModelOutside.sysml）のように、`occurrence`キーワードを
// 省略した裸形もある。同ファイルには`event occurrence :>>
// subscribe_target_event = subscribe_message.done;`という、名前を持たず
// `:>>`redefine節（値束縛リデファイン文と同型）と`=`値代入を同時に
// 持つ形もあるため、redefine節・`=`値代入も併せて追加する
// （2026-08-29、235件パース失敗の要因分析で発見）。
eventOccurrenceUsageStmt
    : isThen='then'? direction? 'event' 'occurrence'? simpleName?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      multiplicitySpec?
      (':' namespacePath)?
      ( 'default' defaultValue=expression | '=' value=expression )?
      ( '{' partBodyElement* '}' | ';' )
    ;

// --- exhibit state usage (8.2.2.18) ---------------------------------------------
// 構文的完全性のためのみ実装。linter.py側に対応するチェック関数は無い。
// `exhibit state 'vehicle states': 'Vehicle States';`（5-State-based
// Behavior-1a.sysml）のように型節（`: Type`）を伴うことがある
// （2026-08-28、参照実装比較レポートP1-2で発見）。
// `exhibit state vehicleStates parallel { state s1; ... }`
// （VehicleModel_2_Simplified.sysml等、実コーパスで6件超）のように、
// 本体（stateBodyElement*）・`parallel`修飾子のいずれも持ちうる
// （2026-08-28、state parallel修飾子の調査で発見。以前は`;'`終端のみで
// 本体を一切持てなかった）。
// `exhibit vehicleStates { ... }`（State Exhibition Example.sysml）・
// `exhibit MiningFrigate::miningFrigatesStates { ... }`（Domain.sysml）・
// `exhibit 'vehicle states' :>> VehicleA::'vehicle states' { ... }`
// （5-State-based Behavior-1.sysml）のように、`state`キーワードを省略した
// 裸形（参照は`.`/`::`混在のnamespacePath、redefine節も持ちうる）もある
// （2026-08-29、235件パース失敗の要因分析で発見）。
exhibitStateUsageStmt
    : 'exhibit' 'state' simpleName (':' typeRef=namespacePath)? isParallel='parallel'? ( '{' stateBodyElement* '}' | ';' )
    | 'exhibit' ref=namespacePath
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      isParallel='parallel'?
      ( '{' stateBodyElement* '}' | ';' )
    ;

// --- portion usage: snapshot/timeslice (8.2.2.9) --------------------------------
// 構文的完全性のためのみ実装。linter.py側に対応するチェック関数は無い。
// 当初は`kind simpleName ';'`のみの簡略形だったが、`Time Slice and
// Snapshot Example.sysml`（公式コーパス）に見られる以下の形を受理できな
// かったため拡張した（2026-08-28、参照実装比較レポートP0-2で発見）:
//   snapshot delivery { attribute deliveryDate : Date; }   -- 本体
//   then timeslice ownership[0..*] ordered { ... }         -- then連鎖+多重度+ordered+本体
//   snapshot sale = start;                                 -- 値代入
// `then`はoccurrenceUsage自体の連鎖宣言（`then timeslice X { ... }`が
// 「直前の要素からの遷移であると同時にXを新規宣言する」という複合文）を
// 表すプレフィックスで、bareThenStmt（既存要素への参照のみ）とは別に
// portionUsageStmt自身が持つ。`ordered`/`nonunique`はmultiplicitySpec
// （8.2.2.6.6）が既に対応済みのため追加の規則は不要。
portionUsageStmt
    // `timeslice item UnitedStatesWhenJohnIsPresident[*] : UnitedStates
    // { ... }`（JohnIndividualExample.sysml）のように、`snapshot`/
    // `timeslice`キーワードの直後に`item`等のusage種別キーワードが続く
    // ことがある（2026-08-28、730件パース失敗の要因分析で発見）。
    : isThen='then'? kind=('snapshot' | 'timeslice') subKind=('item' | 'part' | 'action' | 'attribute' | 'state')? simpleName?
      preMult=multiplicitySpec?
      // `snapshot missionSystemAtIngress :> apollo11MissionSystem { ... }`
      // （Apollo11MissionExecutionPackage.sysml）のように、occurrenceUsage
      // と同様のredefine節（`:>`/`:>>`/subsets/redefines）を持ちうる。
      // P0-2対応時に本体・多重度・値代入・then連鎖は追加したがこの節を
      // 見落としていた（2026-08-28、730件回帰チェックで発見）。
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      // `snapshot groundSystemAtIngress :> context : Apollo11MissionContext
      // { ... }`のように、redefine節の後に型節も持ちうる。
      (':' typeRef=namespacePath)?
      // `timeslice asPresident : Person [0..*] { ... }`
      // （JohnIndividualExample.sysml）のように、型節の後にも多重度が
      // 付きうる（partUsage/actionUsageStmtと同型のpreMult/postMult順序、
      // 2026-08-28、730件パース失敗の要因分析で発見）。
      postMult=multiplicitySpec?
      ('=' value=expression)?
      ( '{' partBodyElement* '}' | ';' )
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
// `individual occurrence def IO2 { ... }`（IndividualTest.sysml）のように、
// `individual`は独立構文（individualDef）だけでなく、occurrence/item/part/
// actionの各defの直前に付くプレフィックス修飾子としても使われる
// （2026-08-28、参照実装比較レポートP0-3で発見）。
occurrenceDef
    : isIndividual='individual'? isAbstract='abstract'? 'occurrence' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
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
// `ref occurrence occ1 : Occ;`/`occurrence situations : Situation[*]
// nonunique;`（OccurrenceTest.sysml/Model Library Example.sysml）のように、
// occurrenceUsageは型節`: Type`を全く持っていなかった（2026-08-28、730件
// パース失敗の要因分析で発見）。itemUsageと同じ`typeRef=namespacePath`
// パターンを追加する。
// `occurrence twoTypes: PartDef, Real;`（OccurrenceUsage_invalid.sysml）の
// ように、型節がカンマ区切りの複数型を取ることがある（calculationUsageと
// 同じ理由。2026-08-28、730件パース失敗の要因分析で発見）。
occurrenceUsage
    : direction? isAbstract='abstract'? isConstant='constant'? isRef='ref'? 'occurrence' simpleName?
      (':' typeRef=namespacePath (',' extraTypeRefs+=namespacePath)*)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('=' value=expression)?
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// IndividualDefinitionはEmptyMultiplicityMember（`[]`、上下限を持たない
// 明示的な空の多重度）を持つことが多い。`_check_individual_definition`
// （case_and_view_rules.py）はmultiplicityの存在とsize=Noneの両方を
// 要求し、無ければLintIssueとして報告する仕様のため、文法側では必須に
// せず省略可能にする（`individual def IO1;`のように`[]`を省略した公式
// コーパス実例が存在するため。2026-08-28、参照実装比較レポートP0-3で
// 発見。以前は必須にしていたため、このIndividualTest.sysml自体の1行目
// でパース自体が失敗していた）。既存のmultiplicityBracketは上下限の
// 記述を必須とするため再利用せず、空の`[]`をこの規則専用に直接書く。
individualDef
    : isAbstract='abstract'? 'individual' 'def' simpleName inheritanceClause? (emptyMult='[' ']')? ( '{' partBodyElement* '}' | ';' )
    ;

// `individual two_types : A_1, B_1;`（IndividualUsage_Invalid.sysml）の
// ように、型節がカンマ区切りの複数型を取ることがある（calculationUsageと
// 同じ理由。2026-08-28、730件パース失敗の要因分析で発見）。
// `individual reference : 'Temporal-Spatial Reference_ID1' { ... }`
// （6-Individual and Snapshots.sysml）のように、型節がQUOTED_NAMEを取る
// ことと、`;`終端だけでなく本体`{}`も持ちうることの両方が未対応だった
// （2026-08-28、730件パース失敗の要因分析で発見）。
individualUsage
    : isAbstract='abstract'? 'individual' simpleName ( ':' typeRef=(ID | QUOTED_NAME) (',' extraTypeRefs+=(ID | QUOTED_NAME))* )? ( '{' partBodyElement* '}' | ';' )
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
// `comment cmt_cmt about cmt /* ... */`・`comment about C /* ... */`
// （Comments.sysml/CommentTest.sysml）のように、コメント対象を明示する
// `about`節を持つことがある。`locale`節（下記）も同時に持てる
// （`comment about CommentTest locale "en_US" /* ... */`）
// （2026-08-28、参照実装比較レポートP1-5で発見）。
commentStmt
    : 'comment' simpleName? ('about' about=namespacePath)? ('locale' locale=STRING_LITERAL)? DOC_COMMENT
    ;

// `doc locale "en_US" /* ... */`（CommentTest.sysml）のように、ロケール
// 注釈`locale`節を持つことがある（2026-08-28、参照実装比較レポートP1-5で
// 発見）。
documentationStmt
    : 'doc' simpleName? ('locale' locale=STRING_LITERAL)? DOC_COMMENT
    ;

textualRepresentationStmt
    // `language`に専用ラベルを使う（無ラベルの`STRING_LITERAL`のままだと、
    // 新設した`locale=STRING_LITERAL`と合わせて`ctx.STRING_LITERAL()`が
    // リストを返すようになり、既存の`ctx.STRING_LITERAL().getText()`呼び
    // 出しと衝突するため。requirementUsageのshortName追加時と同じ問題）。
    : ('rep' simpleName)? 'language' language=STRING_LITERAL ('locale' locale=STRING_LITERAL)? DOC_COMMENT
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
// `locale "en_US" /* ... */`（`doc`/`comment`キーワード無し、CommentTest.sysml
// 冒頭）のように、裸の`/* ... */`もlocale節を持てる（2026-08-28、参照実装
// 比較レポートP1-5で発見）。
bareDocComment
    : ('locale' locale=STRING_LITERAL)? DOC_COMMENT
    ;

// KerMLの`alias`文（別名宣言）。公式コーパスでは`alias Box for
// RectangularCuboid;`のように単純だが、名前・対象どちらも記号を含む名前
// （`'3dVectorQuantityValue'`、`'m/s²'`、`'*'`等）をQUOTED_NAME形式で書く
// ケースが多い（`simpleName`はID/QUOTED_NAME両方を包含済みのためそのまま
// 再利用できる）。対象は`alias Torque for ISQ::TorqueValue;`
// （Documentation Example.sysml）のように`::`修飾されることがあるため
// namespacePathを使う（2026-08-28、参照実装比較レポートP0-1で発見）。
// `alias`は`;`終端だけでなく、`alias AttributeValue for DataValue
// { doc /* ... */ }`のようにbodyを持てる形も公式コーパスに存在する
// （`Attributes.sysml`）。
aliasStmt
    : 'alias' simpleName 'for' target=namespacePath ( '{' partBodyElement* '}' | ';' )
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
// `variation case ...`（VariabilityTest.sysml xpect版）のように、
// Variability機能の先頭修飾子がここにも付く（2026-08-28、730件パース
// 失敗の要因分析で発見）。
// `case c1: C1, C2;`（CaseUsage_Invalid.sysml）のように、型節がカンマ区切り
// の複数型を取ることがある（calculationUsageと同じ理由。2026-08-28、
// 730件パース失敗の要因分析で発見）。
caseUsage
    : variability=('variation' | 'variant')? visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'case' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID (',' extraTypeRefs+=ID)*)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

analysisCaseDef
    : isAbstract='abstract'? 'analysis' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `variation analysis a1;`（VariabilityTest.sysml）のように、Variability
// 機能の先頭修飾子がここにも付く（2026-08-28、730件パース失敗の要因分析
// で発見）。
analysisCaseUsage
    : variability=('variation' | 'variant')? visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'analysis' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

verificationCaseDef
    : isAbstract='abstract'? 'verification' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `variation verification v1;`（VariabilityTest.sysml）のように、
// Variability機能の先頭修飾子がここにも付く（2026-08-28、730件パース
// 失敗の要因分析で発見）。
verificationCaseUsage
    : variability=('variation' | 'variant')? visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'verification' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID)?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

useCaseDef
    : isAbstract='abstract'? 'use' 'case' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// `variation use case uc1 { variant use case uc11; variant use case
// uc12; }`（VariabilityTest.sysml）のように、Variability機能の先頭修飾子
// がここにも付く（2026-08-28、730件パース失敗の要因分析で発見）。
// `use case 'provide transportation' : 'Provide Transportation' { ... }`
// （Use Case Usage Example.sysml）のように、型節がQUOTED_NAME（スペースを
// 含む名前の引用形）を取ることがある（従来はIDのみだった。`typeRef`と
// いう専用ラベルを使うことで、`_usage_keyword_node`の既存のToken対応
// パスがそのまま使える。2026-08-28、730件パース失敗の要因分析で発見）。
// `then use case 'drive vehicle' { ... }`（Use Case Usage Example.sysml）
// のように、`then`前置を持ちうる（includeUseCaseUsage等の多くの規則
// では既に`isThen`対応済みで非対称だった。2026-08-29、235件パース失敗
// の要因分析で発見）。
useCaseUsage
    : variability=('variation' | 'variant')? isThen='then'? visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'use' 'case' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=(ID | QUOTED_NAME))?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// `then include use case detectThreat : DetectThreat { ... }`
// （UseCasesHull.sysml）のように、他の多くの規則（performActionStmt等）
// と同様に`then`前置を持ちうる。`include use case uc1 : UC1;`（型節）・
// `include use case uc2 { ... }`（body）・`include use case enterHome_a
// :> enterHome [1..5];`（redefine節+多重度、useCaseUsageと同型の順序）
// もあるため、useCaseUsageと同じredefinition機能一式を持たせる
// （2026-08-29、235件パース失敗の要因分析で発見）。
includeUseCaseUsage
    : isThen='then'? 'include' 'use' 'case' simpleName?
      (preKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=(ID | QUOTED_NAME))?
      multiplicitySpec?
      (postKind+=('specializes' | ':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// `include uc2;`・`include system.uc1;`（UseCaseTest.sysml）・
// `include 'add fuel'[0..*] { ... }`（Use Case Usage Example.sysml）の
// ように、`use case`キーワードを完全に省略した裸の`include`短縮形も
// ある（includeUseCaseUsageとは別の、より簡略な代替形。2026-08-29、
// 235件パース失敗の要因分析で発見）。
// `then include 'enter vehicle' { ... }`（18-Use Case.sysml）のように、
// includeUseCaseUsageと同様`then`前置も持ちうる（2026-08-29、235件パース
// 失敗の要因分析で発見）。
bareIncludeStmt
    : isThen='then'? 'include' ref=namespacePath multiplicitySpec? ( '{' partBodyElement* '}' | ';' )
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

// `@Classified { classificationLevel = ...; }`/`@Security;`
// （MetadataTest.sysml）のように、`metadata`キーワードを省略した
// `@Type`ショートハンド形も使われる（2026-08-28、参照実装比較レポート
// P0-4で発見）。`@`はこれまでlexerのどの規則にも登場しないトークンで、
// 遭遇すると`token recognition error`（構文エラーより重症、エラー回復
// すら効かない）になっていた。
// `#Security #Classified metadata Classified { ... }`（MetadataTest.sysml）
// のような`#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見。
// `@`ショートハンド形での実例は未確認のため据え置き）。
metadataUsage
    : prefixMetadataAnnotation* isAbstract='abstract'? 'metadata' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )  # metadataUsageKeyword
    | '@' typeRef=namespacePath ( '{' partBodyElement* '}' | ';' )                                        # metadataUsageShorthand
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
// `in part : Engine;`・`return part : Engine;`（TradeStudyTest.sysml）
// のように、actionParameterと同型の`kind`（item/attribute/ref/part/
// calc/action）節を持つことがある（従来calcParameterにはkind節が
// 一切なく、`part`に限らず全種別が未対応だった。2026-08-29、235件
// パース失敗の要因分析で発見）。
calcParameter
    : (direction | dirReturn='return')
      kind=('item' | 'attribute' | 'ref' | 'part' | 'calc' | 'action')?
      simpleName?
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
// `assume constraint fuelConstraint { ... }`（8-Requirements.sysml）のように、
// `assert`/`require`と同じ位置・形状で`assume`キーワードも使われる
// （KerMLの要求済み制約：`assume`は「前提」の意味）。`require constraint
// c1 :>> c;`（RequirementTest.sysml）のようにredefine節（複数可）も
// 取りうる。`#goal requirement { assume #goal constraint ...; }`
// （RequirementMetadataExample.sysml）のような`#Type`プレフィックス注釈
// も持つ（2026-08-28、730件回帰チェックで発見。以前は`assume`キーワード
// 自体・redefine節・prefixMetadataAnnotationのいずれも未対応だった）。
// `assert constraint two_types : AConstraint, ABlock;`
// （ConstraintUsage_Invalid.sysml）のように、型節がカンマ区切りの複数型を
// 取ることがある（constraintUsageと同じ理由。2026-08-28、730件パース
// 失敗の要因分析で発見）。
assertConstraintUsage
    : visibilityIndicator? assertKind=('assert' | 'require' | 'assume') prefixMetadataAnnotation* ('not')? 'constraint' simpleName?
      ( ':' typeRef=namespacePath (',' extraTypeRefs+=namespacePath)* )?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
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
// `calc <ln> naturalLogarithm { ... }`（CoSMAQuantitiesAndUnitsPackage.sysml）
// のようなShortName注釈（P1-1でpartUsage/requirementUsage等には追加済み
// だったが、calculationUsageへの追加を見落としていた。2026-08-28、
// 730件回帰チェックで発見）。`typeRef`という専用ラベルを使う（無ラベルの
// `ID`のままだとshortNameのID代替と合わせて`ctx.ID()`がリストを返す
// ようになり、`_usage_keyword_node`の単純な`ctx.ID()`呼び出しと衝突する
// ため。requirementUsage対応時と同じ理由）。
// `calc f1 : F1, F2;`（CalculationUsage_Invalid1.sysml、参照実装は構文上は
// 受理しつつ「1つの型のみ許可」という別の意味検証エラーを出す）のように、
// 型節がカンマ区切りの複数型を取ることがある（他の多くのusage系規則にも
// 共通する一般的なKerMLのFeatureTyping機構。2026-08-28、730件パース失敗の
// 要因分析で発見）。
calculationUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'calc' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=ID (',' extraTypeRefs+=ID)*)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' calcBodyElement* '}' | ';' )
    ;

// `constraint { stateSpace.order == order }`（StateSpaceRepresentation.
// sysml）のように、名前もキーワード修飾子も伴わない裸のconstraint usage
// が、括弧内に単一の真偽式のみを持つ形（セミコロン無し）を取ることが
// ある。`assertConstraintUsage`が持つ`resultExpr=expression`代替と同型の
// 代替を持つ。
// `assert constraint two_types : AConstraint, ABlock;`
// （ConstraintUsage_Invalid.sysml）のように、型節がカンマ区切りの複数型を
// 取ることがある（calculationUsageと同じ理由。2026-08-28、730件パース
// 失敗の要因分析で発見）。
constraintUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'constraint' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' ID (',' extraTypeRefs+=ID)*)?
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
// `satisfy 'flr-R001' by performLunarMission.outbound.prep.load;`
// （FunctionSpecificationPackage.sysml）のように、既存のrequirement usageを
// 名前だけで参照する場合、`requirement`キーワードを省略できる
// （2026-08-28、730件パース失敗の要因分析で発見）。
// `satisfy Drone_StakeholderRequirements::longDistance by drone;`
// （Drone_BaseArchitecture.sysml）のように、`satisfy`対象の参照名も`::`
// 修飾を取りうる（simpleNameではなくnamespacePathを使う。2026-08-28、
// 730件パース失敗の要因分析で発見）。
satisfyRequirementUsage
    : 'assert' ('not')? 'satisfiedBy' ( 'requirement' simpleName ':' ID | simpleName ) ';'
    | 'satisfy' 'requirement'? nameRef=namespacePath 'by' by=namespacePath ( '{' partBodyElement* '}' | ';' )
    ;

// `verify requirement : R;`・`verify requirement massRequirement :
// MassRequirement;`（VerificationTest.sysml、9-Verification-simplified.sysml）
// のように、`verify`は`requirement`キーワード付きで無名/有名の
// インラインrequirement usage宣言（型節付き）を導入できる。一方
// `verify r;`・`verify vehicleSpec by VehicleTest;`・`verify
// vehicleMassRequirement :>> massRequirement;`（diagnostics.test.ts、
// 9-Verification-simplified.sysml）のように、既存requirement usageへの
// 裸参照（`by`節・redefine節・body節はいずれも任意）という形も別途ある。
// `requirement`キーワードの有無で2つの代替を判別する（2026-08-28、730件
// パース失敗の要因分析で発見）。
verifyRequirementUsage
    : 'verify' 'requirement' simpleName? (':' typeRef=namespacePath)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    | 'verify' nameRef=namespacePath ('by' by=namespacePath)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' partBodyElement* '}' | ';' )
    ;

// `require viewpointSatisfactions { ref :>> ownedPerformances::this,
// subperformances::this default that.that; }`（Views.sysml、
// `satisfyRequirementUsage`のbody内にネスト）のように、`require`単体
// （`constraint`キーワード無し）で名前+bodyを導入する形が別途存在する
// （`require constraint { expr }`とは`constraint`キーワードの有無で異なる
// 別形）。`assume c1 [0..*];`（RequirementTest.sysml）のように`assume`
// キーワードも同じ位置で使われ、多重度（`[...]`）も取りうる（2026-08-28、
// 730件回帰チェックで発見）。
requireUsage
    : kind=('require' | 'assume') prefixMetadataAnnotation* simpleName multiplicitySpec? ( '{' partBodyElement* '}' | ';' )
    ;

// --- interface usage (8.2.2.14) -----------------------------------------------
// `_check_interface_usage`（linter.py:662）が読む `type_name`/
// `interface_part.{type,from_end,to_end}.reference_subsetting.
// referenced_feature` に合わせて実装する。
// `interface engineToTransmissionInterface: EngineToTransmissionInterface
// connect engine::drivePwrPort to transmission::clutchPort { ... }`
// （VehicleModel.sysml）のように、endが`::`修飾参照を取ることがあり
// （共有`connectorEnd`はqualifiedNameのみのため受理できない。
// investigate_connectorend_coloncolonで実際に必要と確認）、かつbody
// （`{ ... }`）を持つこともある（以前は`;`終端のみだった）。他の共有
// 参照元（allocationUsage/successionStmt/successionUsage/
// connectionUsage）は`::`が必要な公式サンプルが見つからなかったため、
// 共有connectorEnd自体は変更せず、connectUsage/bindingConnectorと同じ
// パターンでこの規則専用にconnectorEndPathへ切り替える
// （2026-08-28、investigate_connectorend_coloncolonで発見）。
// `interface APIS_transfer_interface : Interfaces::APIS_transfer_interface_def
// connect ...;`（AHFSequences.sysml）のように、名前付き代替（第1代替）の
// 型節が`::`修飾名を取ることがある（従来は単一segmentのIDのみだった。
// 2026-08-29、235件パース失敗の要因分析で発見）。`typeRef`という専用
// ラベルを使うことで、第2代替（無ラベル`ID`のみ）との判別が
// `ctx.typeRef`の有無で明確にできる。
interfaceUsage
    : isAbstract='abstract'? 'interface' simpleName ':' typeRef=namespacePath ( 'connect' connectorEndPath 'to' connectorEndPath )? ( '{' partBodyElement* '}' | ';' )
    // `abstract interface interfaces: Interface[0..*] nonunique :>
    // connections { doc ... }`（Interfaces.sysml）のように、`connect`を
    // 伴わない裸のinterface usage形（connection/allocation/message/flow等と
    // 同型）も第2代替として持つ（connectionUsage/flowUsageのbare形と
    // 同じ設計）。`interface : StagingInterface connect a.p to b.q;`
    // （TechnicalComponentsPackage.sysml）のように、名前を省略した
    // 型付きinterface usageへの`connect`節も第1代替では受理できない
    // （simpleNameが必須のため）ので、この第2代替にも`connect`節を追加する
    // （2026-08-28、730件パース失敗の要因分析で発見）。
    // `interface producer_2.publicationPort to server_2.publicationPort;`
    // （ServerSequenceOutsideRealization-2.sysml）のように、名前・型節・
    // `connect`キーワードすべてを省略した最小形（ドット区切りパス同士を
    // 直接`to`で接続）もある。`connect`キーワード自体を任意化することで
    // 対応する（2026-08-29、235件パース失敗の要因分析で発見）。
    | isAbstract='abstract'? 'interface' simpleName?
      (':' ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( 'connect'? connectorEndPath 'to' connectorEndPath )?
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
// `allocate DSLA::DroneSystem::navigationModule to Drone::controlUnit;`
// （The-SysMLv2-Book-DroneSystemModel-Example.sysml）のように、endが
// `::`修飾参照を取ることがある（共有`connectorEnd`はqualifiedNameのみの
// ため受理できない。investigate_connectorend_coloncolonで実際に必要と
// 確認）。connectUsage/interfaceUsageと同じパターンでこの規則専用に
// connectorEndPathへ切り替える（2026-08-28、発見）。
allocationUsage
    : isAbstract='abstract'? 'allocation' simpleName
      ( ':' ID )?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( 'allocate' connectorEndPath 'to' connectorEndPath )?
      ( '{' partBodyElement* '}' | ';' )
    | 'allocate' connectorEndPath 'to' connectorEndPath ';'
    ;

// 本体は他の全ての_def（part_def, item_def, port_def, interface_def等）と
// 同じフラットなchildrenリストで表す（特殊な入れ子構造は使わない）。
// `_check_connection_def`（linter.py:528）は`from`/`to`フィールドを読むが、
// body形式ではどちらも設定されない。
// `#multicausation connection def MultiCauseEffect { ... }`
// （CauseAndEffectExample.sysml）のような`#Type`プレフィックス注釈
// （2026-08-28、730件回帰チェックで発見）。
connectionDef
    : prefixMetadataAnnotation* isAbstract='abstract'? 'connection' 'def' simpleName inheritanceClause? ( '{' connectionBodyElement* '}' | ';' )
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
// `end p2: ~P;`（ConjugationTest.sysml）・`end communicationPartnerB :
// ~VerbalExchange;`（family.sysml）のように、型節が`~`接頭辞（共役ポート
// 参照）を取りうる。portUsage（1990行目付近）は既に対応済みで非対称
// だった（2026-08-28、参照実装比較レポートP1-4で発見）。
// `end #cause cause1 : Causer1;`（CauseAndEffectExample.sysml）のような
// `#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見）。
// `end #cause ::> a;`（CauseAndEffectExample.sysml）のように、名前・型節を
// 一切伴わず、`#Type`プレフィックス直後に`::>`（`references`の記号形
// 同義語）+参照先のみで構成される代替形もある（2026-08-28、発見）。
// `end :>> source ::> producer.publicationPort;`
// （ServerSequenceOutsideRealization-2.sysml）のように、名前を伴わない
// `:>>`redefine節（postKind）と直後の`::>`直接参照（directKind）を
// 同時に持つことがある（従来この2つは互いに排他的な代替として扱って
// いたため未対応だった。directKindをpostKind節の後に続く任意節として
// 統合する。2026-08-29、235件パース失敗の要因分析で発見）。
connectionEndMember
    : 'end' prefixMetadataAnnotation*
      (endName=simpleName endMult=multiplicitySpec?)?
      kind=('occurrence' | 'port' | 'item')?
      isRef='ref'?
      innerName=simpleName?
      (':' conjugated='~'? ID)?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      (directKind=('::>' | 'references') directTarget=namespacePath)?
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
// `individual part def IP1 { ... }`（IndividualTest.sysml）のように、
// `individual`はpart defのプレフィックス修飾子としても使われる
// （2026-08-28、参照実装比較レポートP0-3で発見。occurrenceDef参照）。
// `#system part bm1 : Batmobile { ... }`（DontPanic-SysMLv2-Batmobile.sysml）
// のように、`#Type`プレフィックス注釈（P0-4でdependencyStmtのみ対応）は
// part def/usage等にも付きうる（2026-08-28、730件回帰チェックで発見）。
// `variation part def V :> P { variant part x : Q { ... } }`
// （VariabilityTest.sysml）のように、Variability（可変性）ライブラリ機能の
// `variation`（このdef/usage自体が可変ポイントであることを表す）/
// `variant`（variation本体内で選択肢として使われることを表す）という
// 先頭修飾子が、複数のdef/usage系規則に広く付きうる（2026-08-28、730件
// パース失敗の要因分析で発見）。isIndividualと同じ設計で先頭に追加する。
// `public abstract part def Vehicle { ... }`（comprehensive_data_loss.sysml）・
// `private part def Automobile;`（Package Example.sysml）のように、
// visibilityIndicator（public/private/protected）が付くことがある
// （calculationDef/constraintDefは既に対応済みで非対称だった。
// 2026-08-29、235件パース失敗の要因分析で発見）。
partDef
    : visibilityIndicator? variability=('variation' | 'variant')? prefixMetadataAnnotation* isIndividual='individual'? isAbstract='abstract'? 'part' 'def' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

// 参照: SysML.xtext の `ItemDefinition`（`OccurrenceDefinitionPrefix
// ItemDefKeyword Definition`）。PartDefinitionと完全に同型（bodyも同じ
// DefinitionBodyフラグメント経由）なので、partDefと同じpartBodyElementを流用する。
// `item def <xxx> Name { ... }`のように、他のdef系規則
// （package/view def/metadata def/attribute usage）と同じShortName注釈
// （KerMLの一般的な短縮名機能）を取りうる。
// `individual item def II1 { ... }`（IndividualTest.sysml）のように、
// `individual`はitem defのプレフィックス修飾子としても使われる
// （2026-08-28、参照実装比較レポートP0-3で発見。occurrenceDef参照）。
// `public item def A { ... }`（ItemTest.sysml）のように、
// visibilityIndicatorが付くことがある（partDefと同型のギャップ。
// 2026-08-29、235件パース失敗の要因分析で発見）。
itemDef
    : visibilityIndicator? isIndividual='individual'? isAbstract='abstract'? 'item' 'def' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
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
// `individual item ii : II1;`/`individual item :>> i : II2;`
// （IndividualTest.sysml）のように、`individual`はusage側にも付く
// プレフィックス修飾子（2026-08-28、参照実装比較レポートP0-3で発見）。
// `ref individual item :>> operator : Alice;`（Boeing.sysml）のように、
// `ref`が`individual`より前に来る語順も実在する（既存の`individual ...
// ref`という語順とは逆）。`isRefPre`という別スロットをisIndividualの前に
// 追加して両語順を受理する（2026-08-28、730件回帰チェックで発見）。
// `item concerns[*]: Concern;`（CoSMAPackage.sysml）のように、名前の直後に
// 多重度、その後に型節という順序もある（partUsage/requirementUsageと
// 同じpreMult/postMult設計。2026-08-28、730件パース失敗の要因分析で発見）。
itemUsage
    : visibilityIndicator? isRefPre='ref'? isIndividual='individual'? isDerived='derived'? isAbstract='abstract'? isRef='ref'? 'item' simpleName?
      preMult=multiplicitySpec?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      // `item boundingBox : ShapeItems::Box [1] :> boundingShapes { ... }`
      // （DontPanic-SysMLv2-Batmobile.sysml）のように、型節が`::`修飾型名を
      // 取ることがある（単一`ID`のままでは受理できない。2026-08-28、730件
      // パース失敗の要因分析で発見）。`typeRef`という専用ラベルを使う
      // （_usage_keyword_nodeが自動で読む）。
      (':' typeRef=namespacePath)?
      postMult=multiplicitySpec?
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
// `requirement <C1> rangeRequirementSmall :> smallEVRequirement : RangeRequirement
// { ... }`（EVSample.sysml）のように、ShortName注釈（山括弧の短縮名）を
// 持つことがある（2026-08-28、参照実装比較レポートP1-1で発見。公式コーパス
// で87件）。
// `#goal requirement deliverPayload { ... }`（RequirementMetadataExample.sysml）
// のような`#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見）。
// `variation requirement r { variant requirement r1; }`
// （VariabilityTest.sysml）のように、Variability機能の先頭修飾子がここにも
// 付く（partDefと同じ理由、2026-08-28）。
// `requirement goals[1..*] : Goal;`（CoSMAPackage.sysml）のように、名前の
// 直後に多重度、その後に型節という順序もある（partUsage/portUsageと同じ
// preMult/postMult設計。2026-08-28、730件パース失敗の要因分析で発見）。
requirementUsage
    : variability=('variation' | 'variant')? prefixMetadataAnnotation* visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'requirement' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName?
      preMult=multiplicitySpec?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      // `typeRef`という専用ラベルを使う（無ラベルの`ID`のままだと、上のshortName
      // （ID|QUOTED_NAMEの代替）と合わせて`ctx.ID()`が2件のリストを返すように
      // なり、`_usage_keyword_node`側の単純な`ctx.ID()`呼び出しと衝突するため）。
      // `requirement <'1.0'> r10 : R1def, R11def;`（RequirementUsage_Invalid.
      // sysml）のように、型節がカンマ区切りの複数型を取ることがある
      // （calculationUsageと同じ理由。2026-08-28、730件パース失敗の要因
      // 分析で発見）。
      (':' typeRef=ID (',' extraTypeRefs+=ID)*)?
      postMult=multiplicitySpec?
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
      // `subject miningcorporation : Domain::MiningCorporation;`
      // （MiningCorporationRequirementsDecl.sysml等）のように、型節が`::`
      // 修飾型名を取ることがある（itemUsageと同じ理由で追加。2026-08-28、
      // 730件パース失敗の要因分析で発見）。
      (':' typeRef=namespacePath)?
      multiplicitySpec?
      ('=' value=expression)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// `stakeholder s : S;`・`stakeholder s1;`（ViewTest.sysml/
// Annex_A_VehicleViews.sysml等）のように、`concern def`本体内で使われる
// stakeholder宣言（subjectUsageと同型の設計。2026-08-28、730件パース
// 失敗の要因分析で発見）。
stakeholderUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'stakeholder' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=namespacePath)?
      multiplicitySpec?
      ('=' value=expression)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('default' defaultValue=expression)?
      ( '{' partBodyElement* '}' | ';' )
    ;

// `actor driver : RoadUser;`・`actor passengers : Person[0..4];`
// （TrafficLightIntersectionRequirements.sysml/Use Case Definition
// Example.sysml等）のように、`use case def`本体内で使われるactor宣言
// （subjectUsageと同型の設計、2026-08-28、730件パース失敗の要因分析で
// 発見）。
// `actor hostileShip : Domain::HostileShip;`（UseCasesHull.sysml）のように、
// 型節が`::`修飾名を取ることがある（従来は単一segmentのIDのみで、
// stakeholderUsage（同型の姉妹規則）とも非対称だった。2026-08-29、
// 235件パース失敗の要因分析で発見）。
actorUsage
    : visibilityIndicator? isAbstract='abstract'? isRef='ref'? 'actor' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=namespacePath)?
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
// `#Security enum def ClassificationLevel { ... }`（MetadataTest.sysml）
// のような`#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見）。
enumDef
    : prefixMetadataAnnotation* 'enum' 'def' simpleName inheritanceClause? ( '{' enumBodyElement* '}' | ';' )
    ;

enumBodyElement
    : documentationStmt
    | bareDocComment
    | enumLiteral
    // `enum red { :>> val = 0; }`（EnumerationTest.sysml）のように、
    // enumLiteralの本体内で継承した属性を再定義する裸の`:>> name = expr;`
    // 値束縛リデファイン文が使われる（partBodyElement等では既にvalueBindingStmt
    // を含むが、enumBodyElementには未登録だった。2026-08-28、730件パース
    // 失敗の要因分析で発見）。
    | valueBindingStmt
    ;

// (a) `enum 'literal';`という明示的キーワード形、(b)/(c) 裸の名前に
// 値代入または本体が続く形、のいずれも受理する。
// `uncl : ClassificationLevel = 0;`（MetadataTest.sysml、pilot-implementation
// 生データ）のように、列挙子自体が型節（`: Type`）を伴うことがある
// （2026-08-28、730件回帰チェックで発見）。
// `#Security enum secret : ClassificationLevel = 2;`（MetadataTest.sysml）
// のような`#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見。
// extend_hash_prefix_annotation_and_bare_ref_featureで他規則へは拡張済み
// だったがenumLiteral自体を見落としていた）。
enumLiteral
    : prefixMetadataAnnotation* 'enum'? simpleName (':' typeRef=namespacePath)? '=' value=expression ';'               # enumLiteralValue
    | prefixMetadataAnnotation* 'enum'? simpleName (':' typeRef=namespacePath)? ( '{' enumBodyElement* '}' | ';' )      # enumLiteralBody
    ;

// --- attribute definition (8.2.2.6) ---------------------------------------------
// 参照: SysML.xtext の`AttributeDefinition`。PartDefinition/ItemDefinitionと同型
// （bodyも同じDefinitionBodyフラグメント経由）なので、partBodyElementを流用する。
// `variation attribute def DiameterChoices :> Diameter { ... }`
// （Variation Definitions.sysml）のように、Variability機能の`variation`/
// `variant`先頭修飾子がここにも付く（partDefと同じ理由、2026-08-28）。
attributeDef
    : variability=('variation' | 'variant')? prefixMetadataAnnotation* isAbstract='abstract'? 'attribute' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
    ;

partBodyElement
    : attributeUsage
    | attributeDef
    // `part def Camera { private import PictureTaking::*; ... }`
    // （camera.sysml）のように、`import`文は型定義スコープに閉じた形でも
    // 使われる（従来はpackage直下限定だった。2026-08-28、730件パース
    // 失敗の要因分析で発見）。
    | importStmt
    // `view structure : GeneralView { expose
    // TrafficLightIntersection::intersectionInstance; ... }`
    // （Views.sysml）のように、`exposeStmt`はview/viewpoint本体
    // （partBodyElement経由）でも使われる（従来はpackage直下限定だった。
    // 2026-08-28、730件パース失敗の要因分析で発見）。
    | exposeStmt
    | filterStmt
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
    // `verify requirement : R;`（objective本体内、VerificationTest.sysml）・
    // `verify r;`（同）のように、`verifyRequirementUsage`もpartBodyElement
    // 内に書ける（2026-08-28、730件パース失敗の要因分析で発見）。
    | verifyRequirementUsage
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
    // `subject`/`objective`/`actor`/`stakeholder`は常に別のcase/analysis/
    // requirement/objective/concern定義の本体内にネストして使われる
    // （公式コーパスに例外なし）ため、partBodyElementのみに登録する。
    | subjectUsage
    | objectiveUsage
    | actorUsage
    | stakeholderUsage
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
    // `part def SomeDevice { state def DeviceLifecycle { ... } }`
    // （smart-home-complex.sysml）のように、ネストした状態機械定義
    // （`state def`）はstateUsage（914行目）と同じくpartBodyElement内にも
    // 書ける。公式SysML v2比較評価（2026-08-28、
    // eval/SYSML_LINTER_REFERENCE_COMPARISON_REPORT.md §P1-3）で発見。
    | stateDef
    // `part def Vehicle { timeslice assembly; snapshot delivery { ... } }`
    // （Time Slice and Snapshot Example.sysml）のように、portion usage
    // （snapshot/timeslice）はpackageBodyElementだけでなくpartBodyElement
    // 内にも書ける（2026-08-28、参照実装比較レポートP0-2で発見）。
    | portionUsageStmt
    // `individual occurrence def IO2 { individual io : IO1; }`
    // （IndividualTest.sysml）のように、individualUsageは
    // packageBodyElementだけでなくpartBodyElement内にも書ける
    // （2026-08-28、参照実装比較レポートP0-3で発見）。
    | individualUsage
    // `ref y { @Classified { ... } @Security; }`（MetadataTest.sysml）
    // のように、metadataUsage（`metadata X { ... }`および`@X { ... }`
    // ショートハンド）もpackageBodyElementだけでなくpartBodyElement内に
    // 書ける（2026-08-28、参照実装比較レポートP0-4で発見）。
    | metadataUsage
    // `part def VehicleA { exhibit state 'vehicle states': 'Vehicle States'; }`
    // （5-State-based Behavior-1a.sysml）のように、exhibitStateUsageStmtは
    // packageBodyElementだけでなくpartBodyElement内にも書ける
    // （2026-08-28、参照実装比較レポートP1-2で発見）。
    | exhibitStateUsageStmt
    // `part def C { comment /* ... */ comment about CommentTest locale
    // "en_US" /* ... */ }`（CommentTest.sysml）のように、commentStmtも
    // packageBodyElementだけでなくpartBodyElement内にも書ける
    // （2026-08-28、参照実装比較レポートP1-5で発見）。
    | commentStmt
    // `part def Building { part def Floor { ... } }`
    // （smart-home-complex.sysml）のように、partDef自体もstateDef同様
    // partBodyElement内にネストして書ける（2026-08-28、730件回帰
    // チェックで発見）。
    | partDef
    // `part AHFN_LocalCloudDD_Seqs = ... { occurrence def
    // APIS_transfer_lifetime { ... } }`（AHFSequences.sysml）のように、
    // occurrenceDef自体もpartDef/stateDef/actionDefと同型にpartBodyElement
    // 内へネストして書ける（2026-08-29、235件パース失敗の要因分析で発見）。
    | occurrenceDef
    // `requirement def R { ... requirement def <'1'> A { ... } }`
    // （RequirementTest.sysml）のように、requirementDef自体も
    // requirementBodyElement（=partBodyElementに委譲）内へネストして
    // 書ける（2026-08-29、235件パース失敗の要因分析で発見。occurrenceDef
    // と同型のギャップ）。
    | requirementDef
    // `use case def X { then include use case detectThreat : DetectThreat
    // { ... } }`（UseCasesHull.sysml）のように、includeUseCaseUsage自体も
    // use case def/usage本体（partBodyElement経由）内に書ける（従来は
    // packageBodyElementにしか登録されておらず未対応だった。2026-08-29、
    // 235件パース失敗の要因分析で発見）。
    | includeUseCaseUsage
    // `include uc2;`（UseCaseTest.sysml）のように、`use case`キーワード
    // を省略した裸のinclude短縮形もuse case def/usage本体（partBodyElement
    // 経由）内に書ける（2026-08-29、235件パース失敗の要因分析で発見）。
    | bareIncludeStmt
    // `frame concern ProfitabilityConcern;`（BusinessCaseOpsCon.sysml）・
    // `frame 'Reduce the number of special parts';`
    // （DontPanic-SysMLv2-Batmobile.sysml）のように、requirement/concern/
    // viewpoint定義本体内でframed concern参照を宣言する`frame`文が完全に
    // 未実装だった（2026-08-29、235件パース失敗の要因分析で発見）。
    | frameStatement
    // `part def Module { interface def SensorLink { end source :
    // DataPort; end target : DataPort; } }`（synthetic-100.sysml）の
    // ように、interfaceDef自体もpartDef等と同型にpartBodyElement内へ
    // ネストして書ける（従来packageBodyElementにしか登録されておらず
    // 未対応だった。同ファイルの`end`メンバー宣言自体は既存の
    // connectionEndMember経由で既に対応済み。2026-08-29、235件パース
    // 失敗の要因分析で発見）。
    | interfaceDef
    ;

// `frame`文（FramedConcernMembership）。requirement/concern/viewpoint
// def・viewpoint usageの本体（いずれもpartBodyElement経由）で使われる。
// `frame concern X;`という`concern`キーワード付き形と、`frame 'Name';`・
// `frame c;`という省略形の両方がある。`frame c3[0..*];`のように多重度、
// `frame concern hs : HomeSafety;`のように型節も付きうる。
frameStatement
    : 'frame' isConcern='concern'? name=simpleName multiplicitySpec? (':' typeRef=namespacePath)? ';'
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
// `private ref #Classified #Security z1;`・`abstract #Classified z2;`
// （MetadataTest.sysml）のように、`#Type`プレフィックス注釈は他の
// 修飾子（visibility/abstract/constant/ref）の後、名前の前に置かれる
// （2026-08-28、730件回帰チェックで発見）。
// `#cause causeA ::> a;`（CauseAndEffectExample.sysml）のように、型
// キーワードを一切伴わず`#Type`プレフィックス+名前+`::>`（`references`の
// 記号形同義語）のみで構成される裸のfeature宣言がpackage直下にある
// （2026-08-28、発見）。`::>`はpreKind/postKindにも追加する
// （`_redefine_dict`側でsubsets/redefinesとは別の"references"種別へ
// 正規化する）。
// `variant q;`/`variant manualTransmission;`/`variant '4cylEngine';`
// （VariabilityTest.sysml/Variation Usages.sysml/Variation
// Definitions.sysml）のように、型キーワードを伴わない裸のvariant参照
// （既存のfeatureUsageの裸形をそのまま使う）にもVariability機能の先頭
// 修飾子が付く（2026-08-28）。
featureUsage
    : variability=('variation' | 'variant')? visibilityIndicator? isAbstract='abstract'? isConstant='constant'? isRef='ref'?
      prefixMetadataAnnotation*
      simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines' | '::>') preTarget+=namespacePathList)*
      // `ref presidentOfCountry[0..1] : Person :> presidentOfCountry.asPresident;`
      // （JohnIndividualExample.sysml）のように、型節の前にも多重度が付く
      // ことがある（partUsage/actionUsageStmtと同型のpreMult/postMult順序、
      // 2026-08-28、730件パース失敗の要因分析で発見）。
      preMult=multiplicitySpec?
      (':' typeList=namespacePathList)?
      postMult=multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines' | '::>') postTarget+=namespacePathList)*
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
// `individual part p : IP1;`/`individual part :>> p : IP2;`
// （IndividualTest.sysml）のように、`individual`はusage側にも付く
// プレフィックス修飾子（2026-08-28、参照実装比較レポートP0-3で発見）。
// `part <'1'> b: B;`（PartTest.sysml）のように、ShortName注釈（山括弧の
// 短縮名）を持つことがある（2026-08-28、参照実装比較レポートP1-1で発見）。
// `part missions[1..*] : Mission;`（CoSMAPackage.sysml）のように、名前の
// 直後に多重度、その後に型節という順序もある（portUsageのpreMult/postMult
// と同じ設計）。`part subcomponents : MassedComponent [*] default null;`
// （同ファイル）のように、値代入節の後に`default`節（既定値。
// attributeUsageと同じ意味）も取りうる（2026-08-28、730件回帰チェックで
// 発見）。
// `variation part v : P { variant q { ... } }`（VariabilityTest.sysml）・
// `variation part transmission : Transmission[1] { variant
// manualTransmission; variant automaticTransmission; }`（Variation
// Usages.sysml）のように、Variability機能の先頭修飾子がここにも付く
// （partDefと同じ理由、2026-08-28）。
partUsage
    : variability=('variation' | 'variant')? prefixMetadataAnnotation* visibilityIndicator? isIndividual='individual'? isAbstract='abstract'? isConstant='constant'? isRef='ref'?
      'part' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      preMult=multiplicitySpec?
      // `part crew[1..*] : Astronaut, LogicalComponentsPackage::Crew :>>
      // crew;`（MissionPackage.sysml）のように、型節がカンマ区切りの複数型を
      // 取ることがある（calculationUsageと同じ理由。2026-08-28、730件
      // パース失敗の要因分析で発見）。
      (':' typeRef=namespacePath (',' extraTypeRefs+=namespacePath)*)?
      postMult=multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ('=' value=expression)?
      ('default' defaultValue=expression)?
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
// `derived constant ref attribute y :> x;`（PartTest.sysml）のように、
// attributeUsageにも他のusage系規則と同じ`ref`修飾子が付きうる
// （2026-08-28、730件回帰チェックで発見。それまでisRefが未実装だった）。
// `#mop attribute totalPower redefines totalPower = ...;`
// （smart-home-complex2.sysml）のような`#Type`プレフィックス注釈も同時に
// 発見（P0-4の継続）。
// `variant attribute diameterSmall = 70[mm];`（Variation Definitions.sysml）
// のように、Variability機能の先頭修飾子がここにも付く（partDefと同じ理由、
// 2026-08-28）。
// `attribute occurs[0..1]: Real;`（14c-Language Extensions.sysml）のように、
// 名前の直後に多重度、その後に型節という順序もある（partUsage/itemUsageと
// 同じpreMult/postMult設計。2026-08-28、730件パース失敗の要因分析で発見）。
attributeUsage
    : variability=('variation' | 'variant')? prefixMetadataAnnotation* visibilityIndicator? isDerived='derived'? isAbstract='abstract'? isConstant='constant'? isRef='ref'?
      'attribute' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName?
      preMult=multiplicitySpec?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' (typeList=namespacePathList | typeQuoted=QUOTED_NAME))?
      postMult=multiplicitySpec?
      // `attribute i : ScalarValues::Integer := 0;`（StructuredControlTest.sysml、
      // AssignmentTest.sysml）のように、`=`（再定義できない束縛値）とは別に
      // `:=`（初期値、下流で変更可能）という代入演算子も使われる
      // （2026-08-28、730件パース失敗の要因分析で発見）。
      (('=' | ':=') value=expression)?
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
// `attribute ratio : RatioValue nonunique :> Quantities::scalarQuantities;`
// （CoSMAQuantitiesAndUnitsPackage.sysml）のように、`ordered`/`nonunique`
// 修飾子は明示的な多重度ブラケット`[...]`を伴わない裸の形でも使える
// （2026-08-28、730件回帰チェックで発見）。
multiplicitySpec
    : multiplicityBracket multiplicityModifiers?
    | multiplicityModifiers
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
// `#multicausation connect ( ... );`（CauseAndEffectExample.sysml）のような
// `#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見）。
// `#multicausation connect ( cause1 ::> causer1, cause2 ::> causer2,
// effect1 ::> effected1, effect2 ::> effected2 );`
// （CauseAndEffectExample.sysml）のように、2項の`A to B`形とは別に、
// 括弧で囲んだ3項以上のend列（n元connect、KerMLのNaryConnectorPart）も
// 存在する（2026-08-28、730件回帰チェックで発見）。
// `#causation connect b to d { @CausationMetadata { isNecessary = true;
// probability = 0.1; } }`（CauseAndEffectExample.sysml）のように、`;`
// 終端だけでなくbody（`{ ... }`）も持ちうる（2026-08-28、発見。以前は
// `;`終端のみだった）。
connectUsage
    : prefixMetadataAnnotation* 'connect'
      ( fromEnd=connectorEndPath 'to' toEnd=connectorEndPath
      | '(' naryEnds+=connectorEndPath (',' naryEnds+=connectorEndPath)+ ')'
      )
      ( '{' partBodyElement* '}' | ';' )
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
// `#derivation connection { ... }`（Drone_BaseArchitecture.sysml）のような
// `#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見）。
// `#multicausation connection : MultiCauseEffect connect ( cause1 ::>
// causer1, cause2 ::> causer2, ... );`（CauseAndEffectExample.sysml）の
// ように、型付き`connect`節にも括弧で囲んだn元end列（connectUsageと
// 同じ設計）が付きうる（2026-08-28、730件回帰チェックで発見）。
connectionUsage
    : prefixMetadataAnnotation* 'connection' ':' typeRef=namespacePath 'connect'
      ( firstMult=multiplicitySpec? firstEnd=connectorEnd
        'to' thenMult=multiplicitySpec? thenEnd=connectorEnd
      | '(' naryEnds+=connectorEndPath (',' naryEnds+=connectorEndPath)+ ')'
      )
      ( '{' partBodyElement* '}' | ';' )
    // `abstract connection capabilityToGoals[*] : CapabilityToGoalDerivation;`
    // （CoSMAPackage.sysml）のように、名前の直後に多重度、その後に型節と
    // いう順序もある（partUsage/requirementUsageと同じpreMult/postMult
    // 設計。2026-08-28、730件パース失敗の要因分析で発見）。
    | prefixMetadataAnnotation* isAbstract='abstract'? 'connection' simpleName?
      preMult=multiplicitySpec?
      (':' ID)?
      postMult=multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      // `connection link : DataLink connect tx.txPort to rx.rxPort;`
      // （dfa-coverage-advanced.sysml）のように、名前と型節の両方を持つ
      // connectionUsageにもインライン（本体`{}`なし）の`connect...to...`が
      // 続きうる（interfaceUsageの第2代替と同型の拡張。2026-08-29、235件
      // パース失敗の要因分析で発見）。
      ( 'connect'
        ( firstMult=multiplicitySpec? firstEnd=connectorEnd
          'to' thenMult=multiplicitySpec? thenEnd=connectorEnd
        | '(' naryEnds+=connectorEndPath (',' naryEnds+=connectorEndPath)+ ')'
        )
      )?
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
// `cause1 ::> causer1`（CauseAndEffectExample.sysml）のように、`::>`は
// `references`キーワードの記号形の同義語（KerMLのReferences定義）。
// 2026-08-28、n元connect文の調査で発見。
connectorEndPath
    : (ID ('references' | '::>'))? namespacePath
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
// `flow publish_request from producerBehavior.publish.request to
// publicationPort.publish { attribute :>> isInstant = true; }`
// （ServerSequenceOutsideRealization-3.sysml）のように、裸短縮形
// （`from...to`）に名前を伴い、かつ`;`終端の代わりに本体を持つことも
// ある（従来この代替に名前スロット自体が無かった。2026-08-29、235件
// パース失敗の要因分析で発見）。
// `ofType`/`typeRef`という専用ラベルを使うことで、両代替の無ラベル`ID`が
// 合算されるANTLRの既知の挙動を避け、`ctx.typeRef`の有無で代替を判別
// できるようにする（interfaceUsageのtypeRefと同じ設計。2026-08-29、
// 名前スロット追加に伴いsimpleNameの有無だけでは判別できなくなった
// ため対応）。
flowUsage
    : 'flow' simpleName? ( 'of' ofType=ID )?
      ( 'from' fromEnd=namespacePath 'to' toEnd=namespacePath
      | fromEnd=namespacePath 'to' toEnd=namespacePath
      )?
      ( '{' partBodyElement* '}' | ';' )
    | isAbstract='abstract'? 'flow' simpleName?
      (':' typeRef=ID)?
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
// `individual action def AP1 { ... }`（IndividualTest.sysml）のように、
// `individual`はaction defのプレフィックス修飾子としても使われる
// （2026-08-28、参照実装比較レポートP0-3で発見。occurrenceDef参照）。
// `variation action def A { variant action a1; variant action a2; }`
// （VariabilityTest.sysml）のように、Variability機能の先頭修飾子がここにも
// 付く（partDefと同じ理由、2026-08-28）。
actionDef
    : variability=('variation' | 'variant')? isIndividual='individual'? isAbstract='abstract'? 'action' 'def' simpleName inheritanceClause? ( '{' actionBodyElement* '}' | ';' )
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
// `in part testVehicle : Vehicle = VehicleMassTest::testVehicle;`
// （Verification Case Definition Example.sysml）のように、kind節に
// `part`も現れる（従来item/attribute/ref/calc/actionのみで`part`が
// 抜けていた。2026-08-29、235件パース失敗の要因分析で発見）。
actionParameter
    : (direction | dirReturn='return')
      kind=('item' | 'attribute' | 'ref' | 'part' | 'calc' | 'action')?
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
      // `out attribute positions :> ISQ::length[*] := ( );`
      // （Assignment Example.sysml）のように、`=`とは別に`:=`という
      // 代入演算子も使われる（2026-08-28、730件パース失敗の要因分析で
      // 発見）。
      ( 'default' ( '{' defaultValue=expression ';'? '}' | defaultValue=expression ) | ('=' | ':=') value=expression )?
      // `in dt : TimeValue { @ToolVariable { name = "deltaT"; } }`
      // （AnalysisAnnotation.sysml）のように、型節直後のbodyに
      // `@Type { ... }`ショートハンド形のインラインメタデータ注釈が
      // 続くことがある（2026-08-28、730件パース失敗の要因分析で発見）。
      ( '{' (documentationStmt | bareDocComment | actionParameter | metadataUsage)* '}' | ';' )
    ;

direction
    : 'in' | 'out' | 'inout'
    ;

// --- decide/fork/join/merge の制御フローノード (8.2.2.17) ------------------
// 参照: KerML.xtext の `DecisionNode`/`ForkNode`/`JoinNode`/`MergeNode`
// （'decide'|'fork'|'join'|'merge' + 宣言名(省略可) + body-or-semi）。
// 公式仕様通りに名前をAST化する。bodyはactionBodyElementの反復を許可する
// （ネストしたcontrol nodeや代入・send actionを書けるようにする）。
// キーワードは公式文法（sysml2-cli/grammar/sysml.peg の`KW_DECIDE`、
// SysML-textual-bnf.kebnf の`'decide'`）に合わせて`decision`ではなく
// `decide`が正しい（2026-08-28、`then decide`未対応の調査中に発見した
// 既存の誤り。実コーパスでも`decide;`/`then decide D;`という形でのみ
// 使われ、`decision`が実際のキーワードとして使われている例は無い）。
// `action A1; then fork F { ... }`（ControlNodeTest.sysml）・
// `then merge m;`（ActionTest.sysml）・`then decide D;`（DecisionTest.sysml.xt）
// のように、succession先としてcontrol nodeをインライン宣言する形が
// 広く使われるため、assignmentStmtと同じ`isThen`先頭修飾子を追加する
// （2026-08-28、730件パース失敗の要因分析で発見。コーパス全体で11件の
// パース失敗の直接原因）。
flowControlNode
    : isThen='then'? kind=('decide' | 'fork' | 'join' | 'merge') simpleName? ( '{' actionBodyElement* '}' | ';' )
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
// 同じ方針）。代入先は`do assign counter.count := counter.count + 1;`
// （AssignmentTest.sysml）のようにドット区切りのfeature chainを取りうる
// ため、simpleNameではなくnamespacePathを使う（2026-08-28、参照実装比較
// レポートP0-1/P0-5で発見）。
assignmentStmt
    : isThen='then'? visibilityIndicator? ('action' actionName=simpleName?)? 'assign'? target=namespacePath op=('=' | ':=') value=expression ';'
    ;

// --- send action (Section 7.17 SendActionUsage) ------------------------------
// 名前付き・匿名(to/via)の両方に対応する。
// `send FCW::'FCWの作動を判定する'.'警報' via '警報出力';`
// （adas-sysmlv2-main、実モデル、1件）のように、payload参照が`::`と`.`を
// 混在させる場合もあるため、payloadのみ`qualifiedName`ではなく
// `namespacePath`を使う（receiver/toTarget/viaTargetは実コーパスで
// `::`混在の使用例が無いため`qualifiedName`のまま）。
// `action publish send new Publish(someTopic, somePublication) via
// publicationPort;`（ServerSequenceOutsideRealization-2.sysml）のように、
// payloadが`new Type(args)`というオブジェクト生成式のこともある
// （2026-08-28、730件パース失敗の要因分析で発見）。`payload=namespacePath`
// を`expression`へ全面置換すると既存の文字列ベースの`payload`フィールド
// （多数のテスト・呼び出し元が依存）が壊れるため、`new`式専用の代替節
// `newPayload`を別ラベルで追加する形に留める（named形には`via`節も無かった
// ため、anonymous形と同じ`to`/`via`両対応にする）。
// `then action sendFuelCommand send new FuelCommand() to engine_a;`
// （Interaction Realization-1.sysml）のように、named形は先頭の裸`then`
// （直前ノードとの暗黙の連鎖、assignmentStmt/flowControlNodeと同じ設計）
// も持ちうる（2026-08-28、730件パース失敗の要因分析で発見）。
sendActionStmt
    : isThen='then'? 'action' name=simpleName 'send'
      ( payload=namespacePath | 'new' newPayloadType=qualifiedName '(' (newPayloadArgs+=newArgument (',' newPayloadArgs+=newArgument)*)? ')' )
      ( 'to' receiver=qualifiedName | 'via' receiverVia=qualifiedName ) ';'          # sendActionNamed
    | 'send'
      ( payload=namespacePath | 'new' newPayloadType=qualifiedName '(' (newPayloadArgs+=newArgument (',' newPayloadArgs+=newArgument)*)? ')' )
      ( 'to' toTarget=qualifiedName | 'via' viaTarget=qualifiedName ) ';' # sendActionAnonymous
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
// `then accept sig after 10[SI::s];`（ActionTest.sysml）のように、
// `via`節が無く代わりに`after`継続時間（タイムアウト）節を持つ形もある
// （従来`via`節は必須だったが、`then accept S;`という`via`/`after`いずれも
// 無い裸形も同じくActionTest.sysmlで使われているため、この節全体を
// 任意化する。2026-08-29、235件パース失敗の要因分析で発見）。
acceptActionStmt
    : isThen='then'? visibilityIndicator? ('action' actionName=simpleName?)?
      'accept' message=qualifiedName ( ':' messageType=namespacePath )?
      ( 'via' port=qualifiedName | 'after' afterDuration=expression )?
      ';'
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
    // `perform GroundSupportSystem::performCrewIngress :>> performCrewIngress;`
    // （Apollo11MissionExecutionPackage.sysml）のように、`action`キーワード
    // を伴わない裸形にもredefine節を持ちうる（2026-08-28、730件回帰
    // チェックで発見。fix_portionusage_redefine_clause対応中に同ファイルで
    // 連鎖的に見つかった別のギャップ）。
    // `variation perform action doXorY { variant perform doX; variant
    // perform doY; }`（7a1-Variant Configuration...-a.sysml）のように、
    // Variability機能の先頭修飾子がここにも付く（2026-08-28、730件パース
    // 失敗の要因分析で発見）。
    // `perform illuminateRegion.sendOnOffCmd { out onOffCmd =
    // onOffCmdPort.onOffCmd; }`（Flashlight Example.sysml）のように、
    // 裸参照形にも`action`キーワード付き形と同型のbodyが続くことがある
    // （2026-08-28、730件パース失敗の要因分析で発見）。
    : variability=('variation' | 'variant')? isThen='then'? 'perform' namespacePath
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' actionBodyElement* '}' | ';' )
    // `perform action performLunarMission : PerformLunarMission;`
    // （MissionPackage.sysml）のように、`action`キーワード付き形にも型節が
    // 付くことがある（2026-08-28、730件パース失敗の要因分析で発見）。
    // `hasActionKeyword`という専用ラベルを`action`トークンに付ける
    // （typeRefの追加により、無ラベルの`ctx.namespacePath()`が両代替の
    // occurrenceを合算したリストを返すようになり、第1代替（裸参照）との
    // 判別に使えなくなったため。トランスフォーマー側はこのラベルの有無で
    // 代替を判別する）。
    // `perform action takePicture[*] :> PictureTaking::takePicture;`
    // （camera.sysml）のように、`action`キーワード付き形にも名前直後の
    // 多重度`[...]`が付くことがある（2026-08-29、235件パース失敗の要因
    // 分析で発見）。
    | variability=('variation' | 'variant')? isThen='then'? 'perform' hasActionKeyword='action' actionName=simpleName?
      mult=multiplicitySpec?
      (':' typeRef=namespacePath)?
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
// `message publish_message of Publish[1];`（17b-Sequence-Modeling.sysml）
// のように、ペイロード型節が`of Type`形を取ることがある（`: ID`単一
// セグメントとは異なり`::`区切りの型参照も受理できるようnamespacePathを
// 使う）（2026-08-28、参照実装比較レポートP2-1で発見）。
// `message submitCheckout of CheckoutRequest from storefront.submitSent to
// apiGateway.submitReceived;`（WebShopArchitecture.sysml）のように、`of Type`
// ペイロード型節と`from...to`端点節を同時に持つことがある（従来
// `messageStmt`側にのみ`from...to`があり、`messageUsage`側は非対応だった。
// 2026-08-29、235件パース失敗の要因分析で発見）。
messageUsage
    : isAbstract='abstract'? 'message' simpleName?
      ( ':' ID | 'of' payloadType=namespacePath )?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( 'from' fromEnd=namespacePath 'to' toEnd=namespacePath )?
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
// `individual action a : AP1;`/`individual action :>> a : IA2;`
// （IndividualTest.sysml）のように、`individual`はusage側にも付く
// プレフィックス修飾子（2026-08-28、参照実装比較レポートP0-3で発見）。
// `action subfunctions[*] : Function :>> subactions;`（CoSMAPackage.sysml）
// のように、名前の直後に多重度、その後に型節という順序もある
// （partUsage/portUsageと同じpreMult/postMult設計、2026-08-28、
// 730件回帰チェックで発見）。
// `variant action a1; variant action a2;`（VariabilityTest.sysml）のように、
// Variability機能の先頭修飾子がここにも付く（partDefと同じ理由、
// 2026-08-28）。
actionUsageStmt
    : variability=('variation' | 'variant')? isThen='then'? visibilityIndicator? isIndividual='individual'? isAbstract='abstract'? isRef='ref'? 'action' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      preMult=multiplicitySpec?
      // `action 'provide power': 'Provide Power'{ ... }`（3a-Function-based
      // Behavior-1.sysml）のように、型節がQUOTED_NAMEを取ることがある
      // （2026-08-28、730件パース失敗の要因分析で発見）。
      (':' typeRef=(ID | QUOTED_NAME))?
      postMult=multiplicitySpec?
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
// `requirement def <'FLR-R001'> PropellantLoadingRequirement { ... }`
// （FunctionalRequirementsPackage.sysml）のように、ShortName注釈（山括弧の
// 短縮名）を持つことがある（2026-08-28、730件回帰チェックで発見。
// requirementUsageへは既にP1-1で追加済みだったが、requirementDefへの
// 追加を見落としていた）。
requirementDef
    : prefixMetadataAnnotation* isAbstract='abstract'? 'requirement' 'def' ('<' shortName=(ID | QUOTED_NAME) '>')? simpleName inheritanceClause? ( '{' requirementBodyElement* '}' | ';' )
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
// `state def S1 parallel { ... }`（TransitionUsage_invalid.sysml.xt）のように、
// 直交(orthogonal)状態を表す`parallel`修飾子が本体の直前に付きうる
// （2026-08-28、StateTest.sysmlの調査で発見。実コーパスで10件超）。
stateDef
    : isAbstract='abstract'? 'state' 'def' simpleName inheritanceClause? isParallel='parallel'? ( '{' stateBodyElement* '}' | ';' )
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
    // `state s { ... action def VehicleStartSignal; ... }`
    // （StopWatchStates.sysml）のように、state本体内に別の`action def`を
    // ネストさせる構文も使われる（stateDefと同じくpartBodyElementの
    // fix_nested_partdef_in_partbodyと同型のギャップ。2026-08-28、
    // 730件パース失敗の要因分析で発見）。
    | actionDef
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
    // `ref vehicle : Vehicle;`（VehicleModel.sysml、5-State-based
    // Behavior-1.sysml）のように、型キーワードを伴わない裸のfeatureUsage
    // もstate def本体内に書ける（2026-08-28、730件回帰チェックで発見）。
    | featureUsage
    // `accept s : Sig do action D then S2;`のような、`transition ...
    // first`を伴わない暗黙遷移形（2026-08-28、730件回帰チェックで発見）。
    | implicitTransitionStmt
    // `state def Counting { part counter : Counter; ... }`
    // （AssignmentTest.sysml）のように、partUsageもstateBodyElement内に
    // 書ける（attributeUsage/featureUsage/actionUsageStmtは登録済みで
    // 非対称だった。2026-08-29、235件パース失敗の要因分析で発見）。
    | partUsage
    // `state def VehicleStates { in operatingVehicle : Vehicle; }`
    // （State Actions.sysml）のように、`in`/`out`方向付きパラメータ宣言
    // （actionParameter）もstateBodyElement内に書ける（part/objective本体
    // はpartBodyElement経由で既に対応済みで非対称だった。partUsageと
    // 同根の不足。2026-08-29、235件パース失敗の要因分析で発見）。
    | actionParameter
    ;

// bodyにstateBodyElementの反復を許可し、`state On { entry action ...;
// do action ...; exit action ...; }`のような実用上必要な形をサポートする。
// `abstract ref state exhibitedStates: StateAction[0..*] :> stateActions,
// performedActions { ... }`（Parts.sysml）・`ref state self: StateAction
// :>> Action::self, StatePerformance::self;`（States.sysml）のように、
// `ref`修飾子・型節・redefine節（itemUsage/partUsage等と同型）も持つ。
// `state s parallel { ... }`（StateTest.sysml）・`exhibit state
// vehicleStates parallel { ... }`（VehicleModel_2_Simplified.sysml）の
// ように、直交(orthogonal)状態を表す`parallel`修飾子が本体の直前に付きうる
// （2026-08-28、StateTest.sysmlの調査で発見。実コーパスで10件超）。
// `state 'vehicle states': 'Vehicle States' parallel { ... }`
// （5-State-based Behavior-1.sysml）のように、型節がQUOTED_NAMEを取る
// ことがある（2026-08-28、730件パース失敗の要因分析で発見）。
// `then state wait;`（AssignmentTest.sysml）のように、`then`前置を持ち
// うる（他の多くの規則（performActionStmt等）では既に`isThen`対応済み
// で非対称だった。2026-08-29、235件パース失敗の要因分析で発見）。
stateUsage
    : isThen='then'? isAbstract='abstract'? isRef='ref'? 'state' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      (':' typeRef=(ID | QUOTED_NAME))?
      multiplicitySpec?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      isParallel='parallel'?
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
// `ref bind chargePort = battery.chargeInPort;`
// （The-SysMLv2-Book-DroneSystemModel-Example.sysml）のように、他のusage
// 系規則と同じ`ref`修飾子が付きうる（2026-08-28、コーパス全体1件のみだが
// 公式の書籍例で確認）。
bindingConnector
    : isRef='ref'? simpleName? connMult=multiplicitySpec? 'bind'
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
// `succession flow onOffCmdFlow from sendOnOffCmd.onOffCmd to
// produceDirectedLight.onOffCmd;`（FlashlightExample.sysml）のように、
// successionとflowを組み合わせた複合キーワード形（SuccessionFlowUsage）が
// ある。`first`/`then`形とは終端の書き方が異なる（`from`/`to` +
// namespacePath、connectorEndではない）ため、別代替として持つ
// （2026-08-28、参照実装比較レポートP2-2で発見）。
successionUsage
    : visibilityIndicator? 'succession' simpleName? multiplicitySpec?
      'first' firstMult=multiplicitySpec? firstEnd=connectorEnd
      'then' thenMult=multiplicitySpec? thenEnd=connectorEnd
      ( '{' partBodyElement* '}' | ';' )                                # successionUsageFirstThen
    | visibilityIndicator? 'succession' 'flow' simpleName?
      'from' fromEnd=namespacePath 'to' toEnd=namespacePath ';'         # successionUsageFlow
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
// `entry assign counter.count := 0;`（AssignmentTest.sysml）のように、
// doActionMemberの`do send ...`と同型のインライン代入アクションも
// 単独のentry-actionメンバーとして書ける（2026-08-29、235件パース失敗の
// 要因分析で発見）。
// `entry performSelfTest{ in vehicle = operatingVehicle; }`
// （State Actions.sysml）のように、参照直後に`;`終端の代わりに
// `{ actionBodyElement* }`本体を持つこともある（2026-08-29、235件
// パース失敗の要因分析で発見）。
entryActionMember
    : 'entry' ('action')? qualifiedName? (':' ID)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' actionBodyElement* '}' | ';' )
    | 'entry' assign=assignmentStmt
    ;

// `do send new Sig(T.s.x) to p;`（StateTest.sysml、公式xpectテスト）のように、
// transitionStmt/implicitTransitionStmtの`do`節と同じインラインsend
// アクションを、単独のdo-actionメンバーとしても書ける（2026-08-28、
// 730件回帰チェックで発見。実コーパスでも10件超）。
// `do assign counter.count := counter.count + 1;`（AssignmentTest.sysml）
// のように、entryActionMemberと同型のインライン代入アクションも
// doActionMemberで書ける（2026-08-29、235件パース失敗の要因分析で発見）。
// `do action providePower { ... }`（State Actions.sysml）のように、
// 参照直後に`;`終端の代わりに`{ actionBodyElement* }`本体を持つことも
// ある（2026-08-29、235件パース失敗の要因分析で発見）。
doActionMember
    : 'do' ('action')? qualifiedName? (':' ID)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' actionBodyElement* '}' | ';' )
    | 'do' 'send' payload=expression ( 'to' sendTarget=namespacePath | 'via' sendVia=namespacePath )? ';'
    | 'do' assign=assignmentStmt
    ;

// `exit action applyParkingBrake { ... }`（State Actions.sysml）のように、
// 参照直後に`;`終端の代わりに`{ actionBodyElement* }`本体を持つことも
// ある（2026-08-29、235件パース失敗の要因分析で発見）。
exitActionMember
    : 'exit' ('action')? qualifiedName? (':' ID)?
      (postKind+=(':>' | ':>>' | 'subsets' | 'redefines') postTarget+=namespacePathList)*
      ( '{' actionBodyElement* '}' | ';' )
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
// source/trigger/via/effect/targetはいずれも`::`修飾された参照
// （例: `transition first Sub::off then Sub::on;`）を取りうるため、
// qualifiedNameではなくnamespacePathを使う（2026-08-28、参照実装比較
// レポートP0-1で発見）。
// `accept when 'sense temperature'.temp > vehicle1_c1.Tmax`（変化トリガー、
// ChangeTriggerKind）・`accept at vehicle1_c1.maintenanceTime`（時刻トリガー、
// TimeTriggerKind）は、既存の`trigger=namespacePath`（単純な信号参照）とは
// 別の代替として持つ（2026-08-28、参照実装比較レポートP0-5で発見。
// `5-State-based Behavior-1a.sysml`で確認）。
// `accept after 48[h]`（Change and Time Triggers.sysml、Local Clock
// Example.sysml）のように、`after`継続時間（タイムアウト）トリガーも
// `when`/`at`と同型の代替として持つ（2026-08-29、235件パース失敗の
// 要因分析で発見）。
transitionTrigger
    : triggerKind=('when' | 'at' | 'after') triggerExpr=expression
    | trigger=namespacePath (':' triggerType=namespacePath)? ('via' via=namespacePath)?
    ;

// `do send new 'Start Signal'() to vehicle1_c1.vehicleController`のように、
// `do`節は既存アクション参照（`effect=namespacePath`）だけでなく、その場で
// 組み立てるsendアクションも効果として持てる（2026-08-28、参照実装比較
// レポートP0-5で発見）。ペイロードは`new X()`（newExpr）等の式一般を
// 受理する必要があるため、`sendActionStmt`の`payload=namespacePath`
// （単純参照のみ）は再利用せず、この文脈専用に`expression`を使う。
// また`sendActionStmt`は独自の`;`終端を持つため、`then`まで続く
// transitionStmt本体には埋め込めない（終端記号が重複してしまう）。
transitionEffect
    : 'send' payload=expression ( 'to' sendTarget=namespacePath | 'via' sendVia=namespacePath )?
    | ('action')? effect=namespacePath
    ;

// `then launch { doc /* ... */ }`（MissionPackage.sysml）のように、
// 遷移先（target）に`;`終端だけでなく`{ doc ... }`という本体も付く
// ことがある（lambdaParamと同型のdocのみ本体。2026-08-29、235件パース
// 失敗の要因分析で発見）。
transitionStmt
    : 'transition' simpleName? 'first' source=namespacePath
      ( 'accept' transitionTrigger )?
      ( 'if' guard=expression )?
      ( 'do' transitionEffect )?
      'then' target=namespacePath
      ( '{' (documentationStmt | bareDocComment)* '}' | ';' )
    ;

// `accept s : Sig do action D then S2;`・`accept Exit then done;`
// （StateTest.sysml、公式xpectテスト、noErrors指定）のように、`transition
// ... first`を伴わない暗黙遷移形がある。囲むstate自体が暗黙のsourceとなる
// （transformer側でsource=Noneにし、_check_transitionがNoneならスキップする
// 既存の仕様、initialTransitionMemberと同じ扱いにする）。accept/if/doの
// いずれか最低1つが無いと、`then target;`のみの`initialTransitionMember`
// と完全に同形になり曖昧になるため、3つの代替（accept起点/if起点/do起点）
// でそれぞれ最低1つの存在を強制する（2026-08-28、730件回帰チェックで発見）。
implicitTransitionStmt
    : 'accept' transitionTrigger ( 'if' guard=expression )? ( 'do' transitionEffect )? 'then' target=namespacePath ';'
    | 'if' guard=expression ( 'do' transitionEffect )? 'then' target=namespacePath ';'
    | 'do' transitionEffect 'then' target=namespacePath ';'
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
    // KerMLの分類判定式（ClassificationExpression、`istype`/`hastype`）。
    // 例: `sys istype PowerProvider`（CalculationsPackage.sysml）、
    // `engine istype '6CylEngine'`（QUOTED_NAME型名）。優先順位階層の
    // 「EqualityExpression > ClassificationExpression >
    // RelationalExpression」（このファイル冒頭のコメント参照）に従い、
    // relationalExprとequalityExprの間（asCastExpr/metaExprと同型）に置く
    // （2026-08-28、730件回帰チェックで発見）。
    | expression op=('istype'|'hastype') typeRef=namespacePath  # classificationExpr
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
    // `filter @SysML::PartUsage or @SysML::PartDefinition;`（Views.sysml）の
    // `filterStmt`本体で使われる、メタデータ型への`@`参照式（分類判定の
    // 短縮記法。metadataUsageShorthand宣言文の`@Type { ... }`とは別に、
    // 式コンテキストでも同じ`@Type`表記が使われる。2026-08-28、730件
    // パース失敗の要因分析で発見）。
    | '@' typeRef=namespacePath                                 # metadataRefExpr
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
// `#service port def ServiceDiscovery { ... }`（AHFCoreLib.sysml）のような
// `#Type`プレフィックス注釈（2026-08-28、730件回帰チェックで発見）。
// `private port def C { ... }`（PartTest.sysml）のように、
// visibilityIndicatorが付くことがある（partDefと同型のギャップ。
// 2026-08-29、235件パース失敗の要因分析で発見）。
portDef
    : visibilityIndicator? prefixMetadataAnnotation* isAbstract='abstract'? 'port' 'def' simpleName inheritanceClause? ( '{' partBodyElement* '}' | ';' )
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
// `variation port ...`/`variant port ...`（VehicleVariabilityModel.sysml/
// Variability.sysml）のように、Variability機能の先頭修飾子がここにも付く
// （2026-08-28、730件パース失敗の要因分析で発見）。
// `port two_port_def_types: pd1, pd2 { ... }`（PortUsage_Invalid.sysml）の
// ように、型節がカンマ区切りの複数型を取ることがある（calculationUsageと
// 同じ理由。2026-08-28、730件パース失敗の要因分析で発見）。
// `port controlPort : ~Domain::PodPort;`（MiningFrigate.sysml）のように、
// 共役（`~`）修飾型節が`::`修飾名を取ることがある（従来は単一segment
// のIDのみで、namespacePathへの全面置換漏れだった。2026-08-29、235件
// パース失敗の要因分析で発見）。
portUsage
    : variability=('variation' | 'variant')? prefixMetadataAnnotation* visibilityIndicator? isAbstract='abstract'? isConstant='constant'? isRef='ref'?
      'port' simpleName?
      (preKind+=(':>' | ':>>' | 'subsets' | 'redefines') preTarget+=namespacePathList)*
      preMult=multiplicitySpec?
      (':' conjugated='~'? typeRefs+=namespacePath (',' typeRefs+=namespacePath)*)?
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
// visibility indicator（'private import ...;' 等）に対応する。'all'、
// '{ }' 形の RelationshipBody は未対応。
// 再帰ワイルドカード`::**`（パッケージ自身に加えその配下の入れ子パッケージの
// メンバまでインポートする形）に対応する（2026-08-28、730件パース失敗の
// 要因分析で発見。`**`はレキサー上`*`トークン2つの並びとして扱われる）。
importStmt
    : visibilityIndicator? 'import' namespacePath ('::' '*' '*'?)? ';'
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
// importと同様、namespacePath（`::`区切り）と再帰ワイルドカード`::**`を含む
// ワイルドカードに対応する（2026-08-28、importStmtと同じ理由で追加）。
// exposeノードは{"type":"special_stmt","children":[{"type":
// "expose",...}]}という入れ子で返す。
exposeStmt
    : 'expose' namespacePath ('::' '*' '*'?)? ';'
    ;

// `filter @SysML::PartUsage or @SysML::PartDefinition or
// @SysML::PortUsage or @SysML::PortDefinition;`（Views.sysml）のように、
// view/viewpoint本体で表示対象を絞り込むfilter文が、`exposeStmt`と同じ
// view本体（partBodyElement経由）で使われる。対象は`@Type`メタデータ
// 参照式の論理式（`metadataRefExpr`、2026-08-28、730件パース失敗の
// 要因分析で発見）。
filterStmt
    : 'filter' expression ';'
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

// `//* XPECT errors --- "..." at "..." --- */`（公式xpectテスト
// フィクスチャで使われる複数行アノテーション規約、Connector_Invalid.sysml
// 等）のように、`//`直後に`*`が続く場合がある。これを素朴に`LINE_COMMENT`
// （その行末`~[\r\n]*`までしか消費できない）として扱うと、続く行の
// アノテーション本文（引用文字列等）がそのままトークンとして漏れ出し、
// 本来のコード（`--- */`直後の実文）へのパースエラーを引き起こす
// （2026-08-28、730件パース失敗の要因分析で発見。以前から既知の問題を
// 今回解消）。対応する`*/`までを1つの複数行ブロックコメントとして
// 読み飛ばす専用規則を`LINE_COMMENT`より先に置く（ANTLRは最長一致を
// 優先するため、`*/`が実在すれば自然にこちらが選ばれる）。
XPECT_BLOCK_COMMENT
    : '//*' .*? '*/' -> skip
    ;

LINE_COMMENT
    : '//' ~[\r\n]* -> skip
    ;
