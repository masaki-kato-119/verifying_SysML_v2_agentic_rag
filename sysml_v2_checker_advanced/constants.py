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
# `(standard) library package X`宣言を実測して、全93個を漏れなく列挙している。
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
    "VectorCalculations",
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