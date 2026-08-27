"""
設定ファイル
抽象名詞辞書、関係語彙などの設定を定義
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set

# ============================================================================
# LLM 設定
# ============================================================================
# クエリ拡張・ノード要約・経路説明で使う生成モデル。
# GPT-5 系（reasoning モデル）の制約（2026-08 に実 API で確認済み）:
#   - temperature は非対応（デフォルト 1 のみ）
#   - max_tokens は非対応。max_completion_tokens を使う
#   - reasoning_effort は 'none' / 'low' 等。'minimal' は非対応
LLM_MODEL: str = os.getenv("GRAPHRAG_LLM_MODEL", "gpt-5.6-luna")

# ============================================================================
# ノード母集団のドメイン接地（C-lite）
# ============================================================================
# ENTITY 判定は POS ベース（固有名詞なら通る）なので、ノードの 97.5% が
# 「PDF 中で大文字始まりだったか」で決まり、"omg" / "usa" / "willert" のような
# 無関係な語が混入する。SYSML_V2_ALIASES を母集団のゲートに使って接地させる。
#
# 無効にすると従来どおり POS ベースのみになる（比較計測用）。
DOMAIN_TERM_GATE: bool = os.getenv("GRAPHRAG_DOMAIN_TERM_GATE", "1").lower() not in {
    "0",
    "false",
    "no",
}


@lru_cache(maxsize=1)
def domain_term_set() -> frozenset:
    """SYSML_V2_ALIASES から、ノード母集団のゲートに使う用語集合を作る。

    辞書は "action definition" のような空白入り表記を持つが、形態素解析後の
    lemma は "actiondefinition" に寄ることがあるため、両方を登録する。
    照合は小文字・前後空白除去で行う（完全一致）。PDF のメタモデル図由来の
    ``"* +/partdefinition +/definedpart partdefinition"`` のようなゴミトークンを
    拾わないよう、あいまい一致はしない。

    Returns:
        frozenset: 正規化済みの用語集合。
    """
    terms = set()
    for aliases in SYSML_V2_ALIASES.values():
        for alias in aliases:
            normalized = str(alias).lower().strip()
            if not normalized:
                continue
            terms.add(normalized)
            terms.add(normalized.replace(" ", ""))
    return frozenset(terms)

# ============================================================================
# データ配置（パス定義）
# ============================================================================
# パスは「このファイルの位置」を基準に解決する。プロセスの作業ディレクトリ
# （cwd）基準にすると、MCP サーバをリポジトリルートから起動した場合に
# GraphRAG/data/ ではなくルート直下の data/ を見にいってしまい、
# 登録済みグラフが 0 件になる。HybridRAG/rag/config.py と同じ方式に揃えている。
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# データディレクトリ（GraphRAG/data）
DATA_DIR: Path = PROJECT_ROOT / "data"

# グラフ（.pkl）の保存先
GRAPHS_DIR: Path = DATA_DIR / "graphs"

# チャンクストレージ（SQLite）
CHUNKS_DB_PATH: Path = DATA_DIR / "chunks.db"

# MCP サーバのセッション状態
SESSION_FILE_PATH: Path = DATA_DIR / "mcp_session.json"

# クエリキャッシュディレクトリ
CACHE_DIR: Path = DATA_DIR / "cache"

# 抽象名詞辞書（仕様書 5.3）- 日本語
ABSTRACT_NOUNS_JA: Set[str] = {
    "要求", "仕様", "制約", "設計", "契約", "方針",
    "種類", "方式", "概念", "方法", "手段", "目的",
    "機能", "性能", "品質", "特性", "属性", "状態",
    "関係", "構造", "形式", "内容", "範囲", "条件"
}

# 抽象名詞辞書（仕様書 5.3）- 英語
ABSTRACT_NOUNS_EN: Set[str] = {
    "requirement", "specification", "constraint", "design", "contract", "policy",
    "type", "method", "concept", "approach", "means", "purpose",
    "function", "performance", "quality", "property", "attribute", "state",
    "relation", "structure", "form", "content", "scope", "condition",
    "system", "component", "module", "interface", "service", "process"
}

# 後方互換性のため
ABSTRACT_NOUNS = ABSTRACT_NOUNS_JA

# イベント的表現のパターン（仕様書 5.3）- 日本語
EVENT_SUFFIXES_JA: List[str] = [
    "した", "中", "完了", "開始", "終了", "実行", "処理"
]

# イベント的表現のパターン（仕様書 5.3）- 英語
EVENT_SUFFIXES_EN: List[str] = [
    "ed", "ing", "complete", "start", "finish", "execute", "process"
]

# 後方互換性のため
EVENT_SUFFIXES = EVENT_SUFFIXES_JA

# サ変名詞のパターン（動詞化可能）
SURU_VERB_PATTERNS: List[str] = [
    "する", "実行", "実施", "処理", "操作"
]

# 事前定義された関係語彙（仕様書 6.2）
# Phase 2: ドメイン拡張により、動的に拡張可能
# デフォルトは汎用関係のみ
ALLOWED_RELATIONS: Set[str] = {
    "is-a",
    "part-of",
    "depends-on",
    "satisfies",
    "uses",
    "related-to",
    "defines",
    "implements"
}

# Sudachi設定
SUDACHI_MODE = "C"  # 最大単位

# エッジ生成の設定
# 共起関係ベースのエッジ生成パラメータ
COOCCURRENCE_WINDOW = 10  # 候補リスト内での共起ウィンドウサイズ
MIN_COOCCURRENCE = 2  # エッジ生成に必要な最小共起回数

# 関係語彙のマッピング（日本語・英語）
# テキスト内で検出された関係語彙から関係タイプを自動判定
#
# 【語彙を追加するときの注意】
# エッジは常に「関係語彙の直前のエンティティ → 直後のエンティティ」の向きで張られる
# （graph_builder._add_edges_from_sentence_analysis）。したがって
# 「A <語彙> B」と読んだときに `A --関係--> B` が成り立つ語彙だけを登録すること。
#   OK : "is part of"    … "A is part of B" → A part-of B
#   NG : "consists of"   … "A consists of B" は B part-of A なので向きが逆になる
#        "contains" / "includes" / "is composed of" も同じ理由で登録しない。
#
# 英語の語彙は単語境界・大文字小文字を無視して照合される
# （graph_builder.find_relation_vocab）。部分文字列一致ではないので
# "is" が "this" や "analysis" に反応することはない。
RELATION_VOCABULARY: Dict[str, str] = {
    # 日本語
    "は": "is-a",  # "AはB" → is-a
    "である": "is-a",
    "の一部": "part-of",  # "Aの一部" → part-of
    "に含まれる": "part-of",
    "に依存": "depends-on",  # "Aに依存" → depends-on
    "を満たす": "satisfies",  # "Aを満たす" → satisfies
    "を使用": "uses",  # "Aを使用" → uses
    "を使う": "uses",
    # 英語 — is-a
    # 注意: bare な "is" / "are" は登録しない。実コーパス（SysML v2 仕様書）では
    # 名詞述語（"is a" 等）が一致した文が 236 なのに対し、bare "is"/"are" だけが
    # 一致した文は 1,874 あり、その直後は to(136) / by(123) / as(66) /
    # used / bound / declared … と受動態・前置詞句が大半だった。
    # "is used to" や "is bound by" を is-a として記録してしまうため、
    # 登録すると is-a エッジの約 87% が誤りになる。
    "is a": "is-a",
    "is an": "is-a",
    "is a kind of": "is-a",
    "is a type of": "is-a",
    "is defined as": "is-a",
    "specializes": "is-a",
    "subsets": "is-a",
    "redefines": "is-a",
    "conforms to": "is-a",
    # 英語 — part-of（「A <語彙> B」で A が B の一部になる向きだけ）
    "part of": "part-of",
    "is part of": "part-of",
    "are part of": "part-of",
    "belongs to": "part-of",
    "is contained in": "part-of",
    "is a member of": "part-of",
    # 英語 — depends-on
    "depends on": "depends-on",
    "depends upon": "depends-on",
    "requires": "depends-on",
    "is based on": "depends-on",
    # 英語 — satisfies
    "satisfies": "satisfies",
    "satisfy": "satisfies",
    "fulfills": "satisfies",
    # 英語 — uses
    "uses": "uses",
    "use": "uses",
    "utilizes": "uses",
    "refers to": "uses",
    "references": "uses",
    # 英語 — defines
    "defines": "defines",
    "define": "defines",
    "specifies": "defines",
    "declares": "defines",
    "introduces": "defines",
    # 英語 — implements
    "implements": "implements",
    "realizes": "implements",
    # 英語 — related-to
    "is related to": "related-to",
    "is associated with": "related-to",
    "relates to": "related-to",
}

# SysML v2特化エイリアス辞書（専門用語対応）
SYSML_V2_ALIASES: Dict[str, List[str]] = {
    # 日本語 → SysML v2英語用語（Definition系）
    "パート定義": ["partdefinition", "part definition"],
    "アイテム定義": ["itemdefinition", "item definition"],
    "アクション定義": ["actiondefinition", "action definition"],
    "ポート定義": ["portdefinition", "port definition"],
    "インターフェース定義": ["interfacedefinition", "interface definition"],
    "属性定義": ["attributedefinition", "attribute definition"],
    "参照定義": ["referencedefinition", "reference definition"],
    "列挙定義": ["enumerationdefinition", "enumeration definition"],
    "メタデータ定義": ["metadatadefinition", "metadata definition"],
    "ケース定義": ["casedefinition", "case definition"],
    "要求定義": ["requirementdefinition", "requirement definition"],
    "制約定義": ["constraintdefinition", "constraint definition"],
    "計算定義": ["calculationdefinition", "calculation definition"],
    "分析ケース定義": ["analysiscasedefinition", "analysis case definition"],
    "検証ケース定義": ["verificationcasedefinition", "verification case definition"],
    "使用ケース定義": ["usecasedefinition", "use case definition"],
    "ビュー定義": ["viewdefinition", "view definition"],
    "ビューポイント定義": ["viewpointdefinition", "viewpoint definition"],
    "レンダリング定義": ["renderingdefinition", "rendering definition"],
    
    # 日本語 → SysML v2英語用語（Usage系）
    "パート使用": ["partusage", "part usage"],
    "アイテム使用": ["itemusage", "item usage"],
    "アクション使用": ["actionusage", "action usage"],
    "ポート使用": ["portusage", "port usage"],
    "属性使用": ["attributeusage", "attribute usage"],
    "参照使用": ["referenceusage", "reference usage"],
    "列挙使用": ["enumerationusage", "enumeration usage"],
    "メタデータ使用": ["metadatausage", "metadata usage"],
    "ケース使用": ["caseusage", "case usage"],
    "要求使用": ["requirementusage", "requirement usage"],
    "制約使用": ["constraintusage", "constraint usage"],
    "計算使用": ["calculationusage", "calculation usage"],
    "分析ケース使用": ["analysiscaseusage", "analysis case usage"],
    "検証ケース使用": ["verificationcaseusage", "verification case usage"],
    "使用ケース使用": ["usecaseusage", "use case usage"],
    "ビュー使用": ["viewusage", "view usage"],
    "レンダリング使用": ["renderingusage", "rendering usage"],
    "インターフェース使用": ["interfaceusage", "interface usage"],
    "接続使用": ["connectionusage", "connection usage"],
    "フロー接続使用": ["flowconnectionusage", "flow connection usage"],
    "サクセッション使用": ["successionusage", "succession usage"],
    "割り当て使用": ["allocationusage", "allocation usage"],
    
    # 日本語 → SysML v2英語用語（関係・操作）
    "特殊化": ["specializes", "specialization"],
    "サブセット": ["subsets", "subsetting"],
    "再定義": ["redefines", "redefinition"],
    "型付け": ["types", "typing"],
    "フィーチャー": ["feature", "featureusage"],
    "メンバーシップ": ["membership"],
    "所有": ["ownership"],
    "継承": ["inheritance"],
    "合成": ["composition"],
    "集約": ["aggregation"],
    "依存": ["dependency"],
    "実現": ["realization"],
    "抽象化": ["abstraction"],
    
    # 日本語 → SysML v2英語用語（構造要素）
    "名前空間": ["namespace"],
    "パッケージ": ["package"],
    "ライブラリ": ["library"],
    "メタクラス": ["metaclass"],
    "ステレオタイプ": ["stereotype"],
    "プロファイル": ["profile"],
    "モデル": ["model"],
    "要素": ["element"],
    "関係": ["relationship"],
    "注釈": ["annotation"],
    "コメント": ["comment"],
    "ドキュメント": ["documentation"],
    
    # 日本語 → SysML v2英語用語（動作・状態）
    "状態": ["state", "stateusage", "statedefinition"],
    "遷移": ["transition", "transitionusage"],
    "トリガー": ["trigger"],
    "ガード": ["guard"],
    "効果": ["effect"],
    "イベント": ["event", "eventoccurrence"],
    "時間": ["time", "timeinstant"],
    "期間": ["duration"],
    "タイムライン": ["timeline"],
    
    # 英語の表記ゆれ対応
    "part def": ["partdefinition"],
    "item def": ["itemdefinition"],
    "action def": ["actiondefinition"],
    "port def": ["portdefinition"],
    "interface def": ["interfacedefinition"],
    "part usage": ["partusage"],
    "item usage": ["itemusage"],
    "action usage": ["actionusage"],
    "port usage": ["portusage"],
    "attribute usage": ["attributeusage"],
    "reference usage": ["referenceusage"],
    "connection usage": ["connectionusage"],
    "flow connection": ["flowconnection", "flowconnectionusage"],
    "succession": ["succession", "successionusage"],
    "allocation": ["allocation", "allocationusage"],
    
    # 複数形対応
    "parts": ["part", "partusage", "partdefinition"],
    "items": ["item", "itemusage", "itemdefinition"],
    "actions": ["action", "actionusage", "actiondefinition"],
    "ports": ["port", "portusage", "portdefinition"],
    "interfaces": ["interface", "interfaceusage", "interfacedefinition"],
    "attributes": ["attribute", "attributeusage", "attributedefinition"],
    "references": ["reference", "referenceusage", "referencedefinition"],
    "connections": ["connection", "connectionusage"],
    "features": ["feature", "featureusage"],
    "constraints": ["constraint", "constraintusage", "constraintdefinition"],
    "requirements": ["requirement", "requirementusage", "requirementdefinition"],
    "cases": ["case", "caseusage", "casedefinition"],
    "usages": ["usage"],
    "definitions": ["definition"],
}

# 不規則変化辞書（英語の不規則複数形対応）
IRREGULAR_PLURALS: Dict[str, str] = {
    # 一般的な不規則変化
    "analyses": "analysis",
    "criteria": "criterion",
    "phenomena": "phenomenon",
    "data": "data",  # 複数形が一般的
    "media": "media",  # 複数形が一般的
    "children": "child",
    "people": "person",
    "feet": "foot",
    "teeth": "tooth",
    "mice": "mouse",
    "geese": "goose",
    "men": "man",
    "women": "woman",
    
    # SysML/技術用語の不規則変化
    "vertices": "vertex",
    "indices": "index",
    "matrices": "matrix",
    "appendices": "appendix",
    "formulae": "formula",
    "schemata": "schema",
    "metadata": "metadata",  # 単複同形
    "software": "software",  # 単複同形
    "hardware": "hardware",  # 単複同形
}

# 一般的なエイリアス辞書（後方互換性のため保持）
GENERAL_ALIASES: Dict[str, List[str]] = {
    # 日本語 → 英語（一般用語）
    "アクション": ["action"],
    "アクション定義": ["action", "actiondefinition"],
    "インタラクション": ["interaction"],
    "要求": ["requirement"],
    "仕様": ["specification"],
    "設計": ["design"],
    "システム": ["system"],
    "コンポーネント": ["component"],
    "モジュール": ["module"],
    "インターフェース": ["interface"],
    "サービス": ["service"],
    "プロセス": ["process"],
    # 英語の同義語
    "actions": ["action"],
    "action definition": ["actiondefinition"],
    "interactions": ["interaction"],
    "requirements": ["requirement"],
    "specifications": ["specification"],
    "designs": ["design"],
    "systems": ["system"],
    "components": ["component"],
    "modules": ["module"],
    "interfaces": ["interface"],
    "services": ["service"],
    "processes": ["process"],
}

# 統合エイリアス辞書（SysML v2特化 + 一般用語）
NODE_ALIASES: Dict[str, List[str]] = {**SYSML_V2_ALIASES, **GENERAL_ALIASES}

# チャンクサイズ（元のテキストを分割する際のサイズ）
CHUNK_SIZE = 500  # 文字数
CHUNK_OVERLAP = 50  # オーバーラップ文字数

# ストップワードリスト（ノイズノード除去用）
# 日本語ストップワード
STOPWORDS_JA: Set[str] = {
    "の", "に", "は", "を", "が", "と", "で", "も", "から", "まで",
    "それ", "これ", "あれ", "どれ", "それら", "これら", "あれら",
    "それ", "これ", "あれ", "その", "この", "あの", "どの",
    "する", "した", "して", "される", "された", "される",
    "ある", "いる", "なる", "なった", "なって",
    "こと", "もの", "ため", "とき", "ところ",
    "など", "など", "よう", "そう", "こう", "ああ",
    "it", "this", "that", "these", "those", "they", "them",
    "effect", "result", "thing", "stuff"
}

# 英語ストップワード（拡張版）
STOPWORDS_EN: Set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "should", "could", "may", "might", "must", "can",
    "it", "this", "that", "these", "those", "they", "them", "we", "us",
    "you", "he", "she", "him", "her", "his", "hers", "its", "our", "your",
    "their", "i", "me", "my", "mine",
    "effect", "result", "thing", "stuff", "one", "ones",
    "further", "act", "addition", "see", "always", "ref", "if",
    # RAG評価レポートで指摘されたストップワード的ノードを追加
    "not", "all", "han", "sub", "whether", "different",
    # 追加のノイズワード（品質管理強化）
    "note", "etc", "via", "per", "vs", "eg", "ie", "cf", "nb",
    "fig", "sec", "ch", "vol", "ed", "pp", "no", "nos",
    "part", "parts", "item", "items", "type", "types",  # 単体では意味が薄い
    "use", "uses", "used", "using", "user", "users",
    "get", "gets", "got", "set", "sets", "put", "puts",
    "make", "makes", "made", "take", "takes", "took",
    "give", "gives", "gave", "come", "comes", "came",
    "go", "goes", "went", "know", "knows", "knew",
    "think", "thinks", "thought", "say", "says", "said",
    "tell", "tells", "told", "ask", "asks", "asked",
    "work", "works", "worked", "play", "plays", "played",
    "run", "runs", "ran", "walk", "walks", "walked",
    "look", "looks", "looked", "seem", "seems", "seemed",
    "feel", "feels", "felt", "try", "tries", "tried",
    "keep", "keeps", "kept", "let", "lets", "leave", "leaves", "left",
    "move", "moves", "moved", "turn", "turns", "turned",
    "start", "starts", "started", "stop", "stops", "stopped",
    "open", "opens", "opened", "close", "closes", "closed",
    "read", "reads", "write", "writes", "wrote", "written",
    "find", "finds", "found", "lose", "loses", "lost",
    "win", "wins", "won", "buy", "buys", "bought",
    "pay", "pays", "paid", "sell", "sells", "sold",
    "spend", "spends", "spent", "cost", "costs",
    "break", "breaks", "broke", "broken", "fix", "fixes", "fixed",
    "build", "builds", "built", "create", "creates", "created",
    "change", "changes", "changed", "help", "helps", "helped",
    "show", "shows", "showed", "shown", "hide", "hides", "hid", "hidden"
}

# 統合ストップワードリスト（日本語と英語を統合）
STOPWORDS: Set[str] = STOPWORDS_JA | STOPWORDS_EN

# 短語フィルタ（3文字未満の単語を除外）
MIN_WORD_LENGTH = 3  # 最小文字数

# ノード種別フィルタ（探索から除外するノード種別）
# 空の場合はすべてのノード種別を許可
EXCLUDED_NODE_TYPES: Set[str] = set()  # 必要に応じて設定可能


def is_table_of_contents(text: str) -> bool:
    """
    目次チャンクかどうかを判定（強化版）
    
    Args:
        text: チェックするテキスト
        
    Returns:
        bool: 目次チャンクの場合True
    """
    import re
    
    if not text or not text.strip():
        return False
    
    text_lower = text.lower()
    
    # 目次特有のキーワードをチェック（厳格な判定）
    toc_keywords = [
        'table of contents',
        'contents',
        '目次',
        'もくじ',
        'chapter index',
        'section index',
        'index of',
    ]
    
    # キーワードが含まれている場合、より厳格にチェック
    has_toc_keyword = any(keyword in text_lower for keyword in toc_keywords)
    
    # 目次の特徴を検出するパターン（強化版）
    patterns = [
        # 基本パターン
        r'^\d+\.\d+\s+.*\s+\d+$',  # "1.1 章タイトル 10" 形式
        r'^\d+\.\d+\.\d+\s+.*\s+\d+$',  # "1.1.1 節タイトル 15" 形式
        r'^第\d+章\s+.*\s+\d+$',   # "第1章 タイトル 10" 形式
        r'^第\d+節\s+.*\s+\d+$',   # "第1節 タイトル 10" 形式
        r'^\d+\s+[A-Z][a-z]+.*\s+\d+$',  # "1 Introduction 5" 形式
        r'^\d+\.\s+.*\s+\d+$',      # "1. タイトル 10" 形式
        r'^Chapter\s+\d+.*\d+$',    # "Chapter 1 ... 10" 形式
        r'^Section\s+\d+.*\d+$',    # "Section 1 ... 10" 形式
        
        # ページ番号パターン（強化）
        r'^\s*\.{3,}\s*\d+$',       # ドット線とページ番号
        r'^\s*[-_]{3,}\s*\d+$',     # ハイフン/アンダースコア線とページ番号
        r'^.*\s+\.{2,}\s+\d+$',     # "タイトル ... 10" 形式
        r'^.*\s+[-_]{2,}\s+\d+$',   # "タイトル --- 10" 形式
        
        # 数字で始まり数字で終わる行（目次によくある）
        r'^\d+[\.\s]+.*\d+$',       # "1. タイトル 10" または "1 タイトル 10"
        r'^[A-Z]\.\d+\s+.*\d+$',    # "A.1 タイトル 10" 形式（付録など）
        
        # 日本語パターン
        r'^[一二三四五六七八九十]+[\.、]\s+.*\d+$',  # "一、タイトル 10" 形式
    ]
    
    lines = text.strip().split('\n')
    if len(lines) == 0:
        return False
    
    toc_line_count = 0
    total_non_empty_lines = 0
    page_number_count = 0  # ページ番号を含む行の数
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        total_non_empty_lines += 1
        
        # パターンマッチング
        matched = False
        for pattern in patterns:
            if re.match(pattern, line_stripped):
                toc_line_count += 1
                matched = True
                break
        
        # ページ番号の検出（末尾の数字）
        if re.search(r'\d+$', line_stripped):
            page_number_count += 1
        
        # 短い行で数字が含まれている場合も目次の可能性
        if not matched and len(line_stripped) < 80:
            # 数字とタイトルらしい単語の組み合わせ
            if re.search(r'\d+[\.\s]+[A-Za-z\u3040-\u309F\u30A0-\u30FF]+', line_stripped):
                toc_line_count += 1
    
    if total_non_empty_lines == 0:
        return False
    
    # 判定基準（より厳格に）
    toc_ratio = toc_line_count / total_non_empty_lines
    page_number_ratio = page_number_count / total_non_empty_lines if total_non_empty_lines > 0 else 0
    
    # 目次と判定する条件（複数の条件を組み合わせ）
    # 1. 目次キーワードがあり、かつ30%以上が目次パターン
    if has_toc_keyword and toc_ratio >= 0.3:
        return True
    
    # 2. 40%以上が目次パターンで、かつ60%以上がページ番号を含む
    if toc_ratio >= 0.4 and page_number_ratio >= 0.6:
        return True
    
    # 3. 50%以上が目次パターン（元の基準、より厳格に）
    if toc_ratio >= 0.5:
        return True
    
    # 4. 目次キーワードがあり、かつページ番号が多く含まれる
    if has_toc_keyword and page_number_ratio >= 0.5:
        return True
    
    return False


def filter_table_of_contents_chunks(chunks: Dict[str, str]) -> Dict[str, str]:
    """
    目次チャンクをフィルタリング
    
    Args:
        chunks: chunk_id -> chunk_text のマッピング
        
    Returns:
        Dict[str, str]: フィルタリング後のチャンク
    """
    filtered = {}
    removed_count = 0
    
    for chunk_id, chunk_text in chunks.items():
        if not is_table_of_contents(chunk_text):
            filtered[chunk_id] = chunk_text
        else:
            removed_count += 1
    
    if removed_count > 0:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"目次チャンクを除去: {removed_count}チャンク除去, 残り: {len(filtered)}チャンク")
    
    return filtered


def normalize_node_name(node_name: str) -> str:
    """
    ノード名を正規化（小文字に統一、特殊文字除去）
    
    Args:
        node_name: ノード名
        
    Returns:
        str: 正規化されたノード名
    """
    import re
    
    # 小文字に統一
    normalized = str(node_name).lower().strip()
    
    # 特殊文字を除去（英数字、アンダースコア、スペースのみ許可）
    # より厳しく特殊文字を除去
    normalized = re.sub(r'[^a-z0-9_\s]', '', normalized)
    
    # 連続するスペースを単一スペースに変換
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized


def is_valid_node_name(node_name: str) -> bool:
    """
    ノード名が有効かどうかを判定（品質管理強化版）
    
    Args:
        node_name: ノード名
        
    Returns:
        bool: 有効な場合True
    """
    import re
    
    # 元のノード名で特殊文字をチェック（正規化前）
    original = str(node_name).strip()
    
    # 特殊文字で始まるノード名を除外
    if re.match(r'^[\'\":;,\[\]{}()+\-*/=<>!@#$%^&|\\]', original):
        return False
    
    # 正規化
    normalized = normalize_node_name(node_name)
    
    # 空文字列チェック
    if not normalized:
        return False
    
    # 最小文字数チェック
    if len(normalized) < MIN_WORD_LENGTH:
        return False
    
    # ストップワードチェック
    if normalized in STOPWORDS:
        return False
    
    # 単語ごとのストップワードチェック
    words = normalized.split()
    if all(word in STOPWORDS for word in words):
        return False
    
    # SysML v2有効ノード名の例外（部分一致パターンに該当するが有効なもの）
    sysml_valid_exceptions = {
        'partusage', 'itemusage', 'partdefinition', 'itemdefinition',
        'actionusage', 'actiondefinition', 'portusage', 'portdefinition',
        'interfaceusage', 'interfacedefinition', 'attributeusage', 'attributedefinition',
        'referenceusage', 'referencedefinition', 'connectionusage', 'flowconnectionusage',
        'constraintusage', 'constraintdefinition', 'requirementusage', 'requirementdefinition',
        'caseusage', 'casedefinition', 'calculationusage', 'calculationdefinition',
        'analysiscaseusage', 'analysiscasedefinition', 'verificationcaseusage', 'verificationcasedefinition',
        'usecaseusage', 'usecasedefinition', 'viewusage', 'viewdefinition',
        'viewpointdefinition', 'renderingusage', 'renderingdefinition',
        'metadatausage', 'metadatadefinition', 'enumerationusage', 'enumerationdefinition',
        'successionusage', 'allocationusage', 'featureusage',
        'standard', 'anderson', 'specification', 'definition', 'usage',  # 正当な単語
        'partusages', 'itemusages', 'actionusages', 'portusages',  # 複数形も有効
        'specializes', 'subsets', 'redefines', 'types', 'membership', 'ownership'
    }
    
    if normalized in sysml_valid_exceptions:
        return True
    
    # 部分一致ノードの除外（不正なノード名パターン）
    invalid_patterns = [
        r'^.*parts$',  # "aparts", "theparts" など（ただし "parts" 単体は除外）
        r'^.*part[a-z]+$',  # "partsthat", "partstree" など（ただし有効例外は除外済み）
        r'^.*item[a-z]+$',  # "itemsthat" など（ただし有効例外は除外済み）
        r'^.*usages$',  # "portusages", "caseusages", "flowusages", "sysmlusages" など（ただし有効例外は除外済み）
        r'^note\.',  # "note.the" など
        r'^note ',  # "note a", "note the concept" など
        r'note\.[a-z]',  # "note.a", "note.the" など（より包括的）
        r'^note$',  # "note" 単体も除外
        r'^notethe$',  # "note.the" -> "notethe" も除外
        r'^noteall$',  # "noteall" など
        r'.*and.*',  # "typeand", "t1andt2", "and7.9.4" など（andを含む複合語）
        r'^[a-z]+and$',  # "typeand" など
        r'^and[a-z0-9]+$',  # "and7.9.4" など
        r'^[a-z0-9]+and[a-z0-9]+$',  # "t1andt2" など
        r'^[a-z]+ [a-z]+ [a-z0-9]+s$',  # "usage part part1s" など
        r'^[a-z]+ [a-z][0-9]+$',  # "part p1", "part p2", "part f1" など
        r'^[a-z]{1,2}$',  # 1-2文字の短語（"a", "an", "is", "of" など）
        r'^[0-9]+$',  # 数字のみ
        r'^[a-z]*[0-9]+[a-z]*$',  # 数字を含む意味不明な文字列（"p1", "f2", "t1" など）
        r'^(the|a|an|is|are|was|were|be|been|being|have|has|had|do|does|did|will|would|should|could|may|might|must|can)$',  # 基本的な英語の機能語
    ]
    
    # 追加の品質チェック：意味のない組み合わせを除外
    meaningless_patterns = [
        r'^[a-z]{1,2}[0-9]+$',  # "a1", "b2", "p1" など
        r'^[0-9]+[a-z]{1,2}$',  # "1a", "2b" など
        r'^(part|item|action|port|interface|attribute|reference|connection|constraint|requirement|case|calculation|analysis|verification|use|view|viewpoint|rendering|metadata|enumeration|succession|allocation|feature)s?[0-9]+$',  # "part1", "items2" など
        r'^[a-z]+s?that$',  # "partsthat", "itemsthat" など
        r'^[a-z]+s?tree$',  # "partstree" など
        r'^[a-z]+s?all$',  # "partsall" など
        r'^[a-z]+s?the$',  # "partsthe" など
        r'^[a-z]+s?and$',  # "partsand" など
        r'^[a-z]+s?or$',  # "partsor" など
        r'^[a-z]+s?but$',  # "partsbut" など
        r'^[a-z]+s?with$',  # "partswith" など
        r'^[a-z]+s?from$',  # "partsfrom" など
        r'^[a-z]+s?into$',  # "partsinto" など
        r'^[a-z]+s?onto$',  # "partsonto" など
    ]
    
    # 無効パターンのチェック
    for pattern in invalid_patterns + meaningless_patterns:
        if re.match(pattern, normalized):
            return False
    
    # SysML v2用語の優先度チェック（有効性を高める）
    sysml_keywords = {
        "definition", "usage", "part", "item", "action", "port", 
        "interface", "attribute", "reference", "connection", "constraint", 
        "requirement", "feature", "case", "calculation", "analysis", 
        "verification", "use", "view", "viewpoint", "rendering", 
        "metadata", "enumeration", "succession", "allocation",
        "specializes", "subsets", "redefines", "types", "membership", "ownership"
    }
    
    # SysML用語を含む場合は有効性を高く評価
    if any(keyword in normalized for keyword in sysml_keywords):
        # ただし、明らかに無効なパターンは除外
        if not any(re.match(pattern, normalized) for pattern in meaningless_patterns):
            return True
    
    # 一般的な英語の有効単語チェック
    common_valid_words = {
        "system", "component", "module", "service", "process", "method", "function",
        "property", "value", "type", "class", "object", "instance", "element",
        "structure", "behavior", "state", "event", "time", "space", "model",
        "specification", "requirement", "design", "implementation", "test",
        "analysis", "synthesis", "verification", "validation", "documentation"
    }
    
    if normalized in common_valid_words:
        return True
    
    return True
    words = normalized.split()
    if all(word in STOPWORDS for word in words):
        return False
    
    # 部分一致ノードの除外（不正なノード名パターン）
    # 例: "aparts", "partsthat", "partstree", "itemsthat" など
    invalid_patterns = [
        r'^.*parts$',  # "aparts", "theparts" など
        r'^.*part[a-z]+$',  # "partsthat", "partstree" など（ただし "partusage" は除外）
        r'^.*item[a-z]+$',  # "itemsthat" など（ただし "itemusage" は除外）
        r'^.*usages$',  # "portusages", "caseusages", "flowusages", "sysmlusages" など
        r'^note\.',  # "note.the" など
        r'^note ',  # "note a", "note the concept" など
        r'note\.[a-z]',  # "note.a", "note.the" など（より包括的）
        r'^note$',  # "note" 単体も除外
        r'^notethe$',  # "note.the" -> "notethe" も除外
        r'^noteall$',  # "noteall" など
        r'.*and.*',  # "typeand", "t1andt2", "and7.9.4" など（andを含む複合語）
        r'^[a-z]+and$',  # "typeand" など
        r'^and[a-z0-9]+$',  # "and7.9.4" など
        r'^[a-z0-9]+and[a-z0-9]+$',  # "t1andt2" など
        r'^[a-z]+ [a-z]+ [a-z0-9]+s$',  # "usage part part1s" など
        r'^[a-z]+ [a-z][0-9]+$',  # "part p1", "part p2", "part f1" など
    ]
    
    # 有効なノード名の例外（部分一致パターンに該当するが有効なもの）
    valid_exceptions = {
        'partusage', 'itemusage', 'partdefinition', 'itemdefinition',
        'standard', 'anderson',  # 正当な単語
        'partusages', 'itemusages'  # 複数形も有効
    }
    
    if normalized not in valid_exceptions:
        for pattern in invalid_patterns:
            if re.match(pattern, normalized):
                return False
    
    return True



def handle_irregular_plurals(word: str) -> List[str]:
    """
    不規則変化を処理（語形変化対応の改善）
    
    Args:
        word: 処理する単語
        
    Returns:
        List[str]: 語形変化のバリエーション
    """
    variations = [word]
    word_lower = word.lower()
    
    # 不規則変化辞書から検索（複数形→単数形）
    if word_lower in IRREGULAR_PLURALS:
        singular = IRREGULAR_PLURALS[word_lower]
        if singular not in variations:
            variations.append(singular)
    
    # 逆引き（単数形→複数形）
    for plural, singular in IRREGULAR_PLURALS.items():
        if word_lower == singular:
            if plural not in variations:
                variations.append(plural)
    
    # 規則変化も処理
    if len(word_lower) >= 3:
        # 複数形 → 単数形
        if word_lower.endswith('s') and len(word_lower) > 3:
            # 'ies' → 'y'
            if word_lower.endswith('ies') and len(word_lower) > 4:
                singular = word_lower[:-3] + 'y'
                if singular not in variations:
                    variations.append(singular)
            # 'es' → '' (boxes → box)
            elif word_lower.endswith('es') and len(word_lower) > 3:
                singular = word_lower[:-2]
                if singular not in variations:
                    variations.append(singular)
            # 's' → ''
            else:
                singular = word_lower[:-1]
                if singular not in variations:
                    variations.append(singular)
        
        # 単数形 → 複数形
        else:
            # 'y' → 'ies'
            if word_lower.endswith('y') and len(word_lower) > 3:
                # 子音 + y → ies
                if word_lower[-2] not in 'aeiou':
                    plural = word_lower[:-1] + 'ies'
                    if plural not in variations:
                        variations.append(plural)
                # 母音 + y → ys
                else:
                    plural = word_lower + 's'
                    if plural not in variations:
                        variations.append(plural)
            # 's', 'sh', 'ch', 'x', 'z' → 'es'
            elif word_lower.endswith(('s', 'sh', 'ch', 'x', 'z')):
                plural = word_lower + 'es'
                if plural not in variations:
                    variations.append(plural)
            # 一般的な場合 → 's'
            else:
                plural = word_lower + 's'
                if plural not in variations:
                    variations.append(plural)
    
    return variations


def expand_with_sysml_aliases(query: str) -> List[str]:
    """
    SysML v2特化エイリアス辞書でクエリを拡張
    
    Args:
        query: 元のクエリ
        
    Returns:
        List[str]: 拡張されたクエリのリスト
    """
    import re
    
    expanded = []
    query_lower = query.lower()
    
    # SysML v2エイリアス辞書から拡張（単語境界を考慮）
    for alias, node_names in SYSML_V2_ALIASES.items():
        alias_lower = alias.lower()
        # 単語境界を考慮したマッチング（誤検出を減らす）
        pattern = r'\b' + re.escape(alias_lower) + r'\b'
        if re.search(pattern, query_lower):
            expanded.extend(node_names)
    
    return expanded


def expand_with_general_aliases(query: str) -> List[str]:
    """
    一般エイリアス辞書でクエリを拡張
    
    Args:
        query: 元のクエリ
        
    Returns:
        List[str]: 拡張されたクエリのリスト
    """
    import re
    
    expanded = []
    query_lower = query.lower()
    
    # 一般エイリアス辞書から拡張（単語境界を考慮）
    for alias, node_names in GENERAL_ALIASES.items():
        alias_lower = alias.lower()
        # 単語境界を考慮したマッチング（誤検出を減らす）
        pattern = r'\b' + re.escape(alias_lower) + r'\b'
        if re.search(pattern, query_lower):
            expanded.extend(node_names)
    
    return expanded


def get_sysml_priority_score(node_name: str) -> float:
    """
    SysML v2用語の優先度スコアを計算
    
    Args:
        node_name: ノード名
        
    Returns:
        float: 優先度スコア（0.0-1.0）
    """
    node_lower = node_name.lower()
    
    # SysML v2コア用語（最高優先度）
    core_terms = {
        "partdefinition", "partusage", "itemdefinition", "itemusage",
        "actiondefinition", "actionusage", "portdefinition", "portusage",
        "interfacedefinition", "interfaceusage", "constraintdefinition", "constraintusage",
        "requirementdefinition", "requirementusage", "casedefinition", "caseusage"
    }
    
    if node_lower in core_terms:
        return 1.0
    
    # SysML v2関連用語（高優先度）
    related_terms = {
        "attributedefinition", "attributeusage", "referencedefinition", "referenceusage",
        "connectionusage", "flowconnectionusage", "successionusage", "allocationusage",
        "calculationdefinition", "calculationusage", "analysiscasedefinition", "analysiscaseusage",
        "verificationcasedefinition", "verificationcaseusage", "usecasedefinition", "usecaseusage",
        "viewdefinition", "viewusage", "viewpointdefinition", "renderingdefinition", "renderingusage",
        "metadatadefinition", "metadatausage", "enumerationdefinition", "enumerationusage"
    }
    
    if node_lower in related_terms:
        return 0.8
    
    # SysML v2関係用語（中優先度）
    relation_terms = {
        "specializes", "subsets", "redefines", "types", "membership", "ownership",
        "feature", "featureusage", "namespace", "package", "library"
    }
    
    if node_lower in relation_terms:
        return 0.6
    
    # 一般的なSysML用語（低優先度）
    general_terms = {
        "definition", "usage", "part", "item", "action", "port", "interface",
        "attribute", "reference", "connection", "constraint", "requirement", "case"
    }
    
    if any(term in node_lower for term in general_terms):
        return 0.4
    
    return 0.0