"""
SysML v2 Advanced Checker Constants

定数定義
"""

# 組み込み型
# SysML v2 標準ライブラリの ScalarValues パッケージで定義される基本型。
# Real / Rational / Complex / Natural / Positive が抜けていると、ごく普通のモデル
# （例: `attribute x : Real;`）でも「存在しない型」の誤検出につながる。
BUILTIN_TYPES = {
    "Boolean",
    "String",
    "Number",
    "Integer",
    "Natural",
    "Positive",
    "Rational",
    "Real",
    "Complex",
}

# SysML v2 / KerML の標準ライブラリ（Kernel Libraries / Systems Library / Domain
# Libraries）のトップレベルパッケージ名。`import ScalarValues::*;` や
# `attribute x : ScalarValues::Real;` はローカルに定義されていなくても常に有効な
# 参照であり、「存在しないパッケージ/型」として誤検出してはならない。
#
# 公式リポジトリの`sysml.library`配下（`.sysml`と`.kerml`の両方）に実在する
# `(standard) library package X`宣言を実測して列挙している。
#
# 2026-09-14に jar 0.61.0 同梱のライブラリと突き合わせ直した結果、この集合と
# ライブラリの実体が1件ずつ食い違っていた:
#   - `USCustomaryUnits` が漏れていた（→追加済み。7ファイルの偽陽性の原因）
#   - 逆に `Transitions` はライブラリに存在しない（実在するのは
#     `Kernel Semantic Library/TransitionPerformances.kerml`）。ただしコーパス
#     730件に `import Transitions` は1件も無く、除去しても測定できる差が出ない。
#     余分な名前が持つ risk は検出漏れ側（偽陽性ではない）なので、未測定の変更を
#     混ぜないため今回は残してある。
#
# なお、この集合に載せた名前は「配下のメンバーの存在検証を省略する」効果を持つ
# （例: `import ISQ::NonExistent;`は検出できなくなる）。これは既存の
# ScalarValues等と同じ、意図的なトレードオフ（メンバー解決には標準ライブラリ本体の
# パースが必要で、単一ファイルlintの範囲を超えるため）。
# ネストしたパッケージ（`KerML::Root`の`Root`等）はここには含めない——
# それらは同一ファイル内で解決できるため、linter.pyの`self.packages`が扱う。
STANDARD_LIBRARY_PACKAGES = {
    # --- Kernel Libraries / Kernel Data Type Library (.kerml) ---
    "Collections",
    "ScalarValues",
    "VectorValues",
    # --- Kernel Libraries / Kernel Function Library (.kerml) ---
    "BaseFunctions",
    "BooleanFunctions",
    "CollectionFunctions",
    "ComplexFunctions",
    "ControlFunctions",
    "DataFunctions",
    "IntegerFunctions",
    "NaturalFunctions",
    "NumericalFunctions",
    "OccurrenceFunctions",
    "RationalFunctions",
    "RealFunctions",
    "ScalarFunctions",
    "SequenceFunctions",
    "StringFunctions",
    "TrigFunctions",
    "VectorFunctions",
    # --- Kernel Libraries / Kernel Semantic Library (.kerml) ---
    "Base",
    "Clocks",
    "ControlPerformances",
    "FeatureReferencingPerformances",
    "KerML",
    "Links",
    "Metaobjects",
    "Objects",
    "Observation",
    "Occurrences",
    "Performances",
    "SpatialFrames",
    "StatePerformances",
    "Transfers",
    "TransitionPerformances",
    "Triggers",
    # --- Systems Library (.sysml) ---
    "Actions",
    "Allocations",
    "AnalysisCases",
    "Attributes",
    "Calculations",
    "Cases",
    "Connections",
    "Constraints",
    "Flows",
    "Interfaces",
    "Items",
    "Metadata",
    "Parts",
    "Ports",
    "Requirements",
    "StandardViewDefinitions",
    "States",
    "SysML",
    "UseCases",
    "VerificationCases",
    "Views",
    # `sysml.library`にトップレベルパッケージとしては存在しないが（遷移関連は
    # `TransitionPerformances`/`States`が担当）、後方互換のため残す。
    "Transitions",
    # --- Domain Libraries (.sysml) ---
    "AnalysisTooling",
    "CausationConnections",
    "CauseAndEffect",
    "DerivationConnections",
    "ISQ",
    "ISQAcoustics",
    "ISQAtomicNuclear",
    "ISQBase",
    "ISQCharacteristicNumbers",
    "ISQChemistryMolecular",
    "ISQCondensedMatter",
    "ISQElectromagnetism",
    "ISQInformation",
    "ISQLight",
    "ISQMechanics",
    "ISQSpaceTime",
    "ISQThermodynamics",
    "ImageMetadata",
    "MeasurementRefCalculations",
    "MeasurementReferences",
    "ModelingMetadata",
    "ParametersOfInterestMetadata",
    "Quantities",
    "QuantityCalculations",
    "RequirementDerivation",
    "RiskMetadata",
    "SI",
    "SIPrefixes",
    "SampledFunctions",
    "ShapeItems",
    "SpatialItems",
    "StateSpaceRepresentation",
    "TensorCalculations",
    "Time",
    "TradeStudies",
    # `Domain Libraries/Quantities and Units/USCustomaryUnits.sysml` の
    # `standard library package <USCU> USCustomaryUnits`。2026-09-14に追加。
    # 兄弟（SI・ISQ・Quantities・MeasurementReferences）は最初から入っていたのに
    # これだけ漏れており、`import USCustomaryUnits::*;` を「存在しないパッケージ」と
    # 誤検出していた（730件コーパスで7ファイル。参照実装はクリーンと実測）。
    "USCustomaryUnits",
    "VectorCalculations",
}

# 標準ライブラリのパッケージ**内に定義された enum def** の名前。
# `import RiskMetadata::*;` のあとに `import RiskLevelEnum::*;` と書く形
# （RiskMetadataExample.sysml等）では、先行するワイルドカードimportによって
# enum名がスコープに入り、そこからさらに列挙リテラルをimportできる。
# 単一ファイルlintでは標準ライブラリ本体を読まないため、この名前の実在を
# 確認できず「存在しないパッケージ」と誤検出していた。
#
# jar 0.61.0 同梱の `sysml.library` 配下から `enum def X` 宣言を実測して
# 全10個を列挙している（2026-09-14）。
#
# **パッケージ名の集合（STANDARD_LIBRARY_PACKAGES）と分けてある理由**:
# 当初は「標準ライブラリからのワイルドカードimportがあれば、続く未解決の
# ワイルドカードimportを一律で検証不能とする」という緩和を試したが、730件で
# `both_error -> reference_only_error` が46件（本物の検出を43件喪失）、
# `_check_import` の発火が146→77ファイルへ半減し、撤回した。コーパスの多くが
# 標準ライブラリのワイルドカードimportを持つため、条件が粗すぎた。
# **どの名前が正当かを名指しする**この方式なら、`import NoSuchPackage::*;` は
# この集合に無いので引き続き検出される。
STANDARD_LIBRARY_ENUM_NAMES = {
    "LevelEnum",
    "PortionKind",
    "RequirementConstraintKind",
    "RiskLevelEnum",
    "StateSubactionKind",
    "StatusKind",
    "TransitionFeatureKind",
    "TriggerKind",
    "VerdictKind",
    "VerificationMethodKind",
}

# リンターの重大度レベル
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# 要素参照専用シンボル集合に登録するusage/instanceノード種別。
# これらは「型」ではなく「参照可能なインスタンス/使用箇所」であり、_find_type_in_symbols
# には決して混入させない（インスタンス名を型名として誤って有効扱いする副作用を防ぐため）。
# _find_element_in_symbols からのみ参照される、型解決用シンボルテーブル(self.symbols)とは
# 独立した別集合(self.element_refs)に登録する。
ELEMENT_REFERENCE_ONLY_USAGE_TYPES = {
    "part_instance",
    "action_usage",
    "attribute_usage",
    "connect_usage",
    "flow_usage",
    "calculation_usage",
    "constraint_usage",
    "satisfy_requirement_usage",
    "port_usage",
    "interface_usage",
    "allocation_usage",
    "assert_constraint_usage",
    "include_use_case_usage",
    "exhibit_state_usage",
    "portion_usage",
    "individual_usage",
    "case_usage",
    "analysis_case_usage",
    "verification_case_usage",
    "use_case_usage",
    "view_usage",
    "viewpoint_usage",
    "rendering_usage",
    "metadata_usage",
    "feature_usage",
    "item_usage",
    "subject_usage",
    "objective_usage",
    "requirement_usage",
    "concern_usage",
}