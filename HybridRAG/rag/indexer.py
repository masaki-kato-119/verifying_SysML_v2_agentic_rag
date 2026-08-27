"""ドキュメントインデックス化モジュール。

このモジュールは、ファイルを読み込み、チャンク分割し、
ベクトルDBとメタDBに登録する機能を提供します。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .chunking import (
    chunk_text_semantic,
    read_excel_file,
    read_markdown_file,
    read_pdf_file,
    read_powerpoint_file,
    read_text_file,
    read_word_file,
)
from .metadata_store import MetadataStore
from .vector_store import VectorStoreAPI

# エンティティ自動抽出モジュール（オプション）
try:
    from .entity_extractor import extract_entities_with_llm, extract_entities_with_parser

    ENTITY_EXTRACTOR_AVAILABLE = True
except ImportError:
    ENTITY_EXTRACTOR_AVAILABLE = False
    extract_entities_with_llm = None
    extract_entities_with_parser = None

if TYPE_CHECKING:
    from .graph_store import GraphStore

logger = logging.getLogger(__name__)

# SysML ASTパーサーをオプションでインポート（sysml_v2_checker_advancedが利用可能な場合のみ）
try:
    from sysml_v2_checker_advanced import parse_sysml
    _SYSML_PARSER_AVAILABLE = True
except ImportError:
    _SYSML_PARSER_AVAILABLE = False
    parse_sysml = None


@dataclass
class SysMLRelationship:
    """SysML ASTから抽出した関係情報。
    
    Attributes:
        source_name: 起点要素の名前（例: "LibrarySystem"）
        target_name: 終点要素の名前（例: "CatalogSystem"）
        relation_type: 関係の種類（"part-of", "satisfiedBy", "connected-to", "inheritance", "state-transition"）
        source_type: 起点要素の型（"part_def", "requirement_def", "connection_def"など）
        target_type: 終点要素の型（"part_def", "action_def"など）
        metadata: 追加メタデータ（例: connection_defのconnector情報）
    """
    source_name: str
    target_name: str
    relation_type: str
    source_type: str
    target_type: str
    metadata: Optional[Dict[str, object]] = None


def _extract_sysml_relationships(ast: Dict, namespace: str = "") -> List[SysMLRelationship]:
    """SysML ASTから関係を抽出する。

    SysML ASTを再帰的に走査し、以下の関係を抽出します:
    - part_def: part_instance（part-of関係）とinheritance関係
    - requirement_def: satisfiedBy関係
    - connection_def: connected-to関係
    - action_def: flow_stmt（state-transition関係）

    Args:
        ast: パース済みのSysML AST（辞書形式）。
        namespace: 現在の名前空間（パッケージ名）。
            ネストされたパッケージの場合は "::" で連結されます。

    Returns:
        List[SysMLRelationship]: 抽出された関係のリスト。
            各関係には起点要素、終点要素、関係の種類、要素の型が含まれます。
    """
    relationships: List[SysMLRelationship] = []
    
    if not isinstance(ast, dict):
        return relationships
    
    node_type = ast.get("type")
    
    # パッケージの場合は子ノードを再帰的に処理
    if node_type == "package":
        package_name = ast.get("name", "")
        current_namespace = f"{namespace}::{package_name}" if namespace else package_name
        for child in ast.get("children", []):
            if isinstance(child, dict):
                relationships.extend(_extract_sysml_relationships(child, current_namespace))
    
    # part_def: part_instance（part-of関係）とinheritanceを抽出
    elif node_type == "part_def":
        part_name = ast.get("name", "")
        full_part_name = f"{namespace}::{part_name}" if namespace else part_name
        
        # inheritance関係を抽出
        if "inheritance" in ast and ast["inheritance"]:
            inheritance = ast["inheritance"]
            if isinstance(inheritance, dict):
                base = inheritance.get("base")
            else:
                base = str(inheritance) if inheritance else None
            if base:
                relationships.append(SysMLRelationship(
                    source_name=full_part_name,
                    target_name=base,
                    relation_type="inheritance",
                    source_type="part_def",
                    target_type="part_def",
                ))
        
        # part_instance（part-of関係）を抽出
        # 注意: パーサーの問題でchildrenが空になる場合があるため、
        # 再帰的に子ノードを走査してpart_instanceを探す
        def _find_part_instances(node: Dict, parent_part_name: str) -> None:
            """再帰的にpart_instanceを探す"""
            if not isinstance(node, dict):
                return
            node_type = node.get("type")
            if node_type == "part_instance":
                instance_name = node.get("name", "")
                instance_type = node.get("type_name", "")
                role = node.get("role")
                if instance_type:
                    relationships.append(SysMLRelationship(
                        source_name=parent_part_name,
                        target_name=instance_type,
                        relation_type="part-of",
                        source_type="part_def",
                        target_type="part_def",
                        metadata={"instance_name": instance_name, "role": role},
                    ))
            # 再帰的に子ノードを処理
            for key in ["children"]:
                if key in node:
                    for child in node[key]:
                        if isinstance(child, dict):
                            _find_part_instances(child, parent_part_name)
        
        _find_part_instances(ast, full_part_name)
        
        # 再帰的に子ノードを処理（他の関係も抽出）
        for child in ast.get("children", []):
            if isinstance(child, dict):
                relationships.extend(_extract_sysml_relationships(child, namespace))
    
    # requirement_def: satisfiedBy関係を抽出
    elif node_type == "requirement_def":
        req_name = ast.get("name", "")
        full_req_name = f"{namespace}::{req_name}" if namespace else req_name
        satisfied_by = ast.get("satisfied_by", [])
        
        for ref in satisfied_by:
            if isinstance(ref, str):
                # refは "part.action" 形式（例: "catalog.searchBooks"）
                parts = ref.split(".")
                if len(parts) >= 1:
                    part_name = parts[0]
                    action_name = parts[1] if len(parts) > 1 else None
                    if action_name:
                        # requirement -> action（satisfiedBy関係）
                        relationships.append(SysMLRelationship(
                            source_name=full_req_name,
                            target_name=f"{part_name}.{action_name}",
                            relation_type="satisfiedBy",
                            source_type="requirement_def",
                            target_type="action_def",
                            metadata={"part_name": part_name, "action_name": action_name},
                        ))
                    else:
                        # requirement -> part（satisfiedBy関係）
                        relationships.append(SysMLRelationship(
                            source_name=full_req_name,
                            target_name=part_name,
                            relation_type="satisfiedBy",
                            source_type="requirement_def",
                            target_type="part_def",
                        ))
    
    # connection_def: connected-to関係を抽出
    elif node_type == "connection_def":
        conn_name = ast.get("name", "")
        full_conn_name = f"{namespace}::{conn_name}" if namespace else conn_name
        from_ref = ast.get("from", {})
        to_ref = ast.get("to", {})
        
        from_name = ""
        to_name = ""
        
        if isinstance(from_ref, dict):
            from_name = from_ref.get("name", "")
        elif isinstance(from_ref, str):
            from_name = from_ref
        
        if isinstance(to_ref, dict):
            to_name = to_ref.get("name", "")
        elif isinstance(to_ref, str):
            to_name = to_ref
        
        if from_name and to_name:
            # from -> to（connected-to関係）
            relationships.append(SysMLRelationship(
                source_name=from_name,
                target_name=to_name,
                relation_type="connected-to",
                source_type="part_def",
                target_type="part_def",
                metadata={"connection_name": full_conn_name},
            ))
    
    # action_def: state-transition関係を抽出（action_body内のflow_stmtから）
    elif node_type == "action_def":
        action_name = ast.get("name", "")
        full_action_name = f"{namespace}::{action_name}" if namespace else action_name
        
        # action_body内のflow_stmtを再帰的に走査
        def _find_flows(node: Dict, parent_action_name: str, previous_target: Optional[str] = None) -> Optional[str]:
            """再帰的にflow_stmtを探してstate-transition関係を抽出
            
            Args:
                node: 走査するノード
                parent_action_name: 親actionの名前（名前空間付き）
                previous_target: 前のflowのtarget（arrow_only_stmt用）
            
            Returns:
                最後に見つかったtarget（arrow_only_stmt用）
            """
            if not isinstance(node, dict):
                return previous_target
            
            node_type = node.get("type")
            current_target = previous_target
            
            # flow_id_stmt: "Source -> Target"
            if node_type == "flow_id_stmt":
                source = node.get("source", "")
                target = node.get("target", "")
                
                if source and target:
                    # 名前空間を考慮して完全な名前を構築
                    full_source = f"{parent_action_name}::{source}" if parent_action_name else source
                    full_target = f"{parent_action_name}::{target}" if parent_action_name else target
                    
                    relationships.append(SysMLRelationship(
                        source_name=full_source,
                        target_name=full_target,
                        relation_type="state-transition",
                        source_type="action",
                        target_type="action",
                        metadata={"action_name": parent_action_name, "source": source, "target": target},
                    ))
                    current_target = target
                elif source:
                    # targetが空の場合は、前のtargetを使用（連続するflowの場合）
                    if previous_target:
                        full_source = f"{parent_action_name}::{source}" if parent_action_name else source
                        full_target = f"{parent_action_name}::{previous_target}" if parent_action_name else previous_target
                        
                        relationships.append(SysMLRelationship(
                            source_name=full_source,
                            target_name=full_target,
                            relation_type="state-transition",
                            source_type="action",
                            target_type="action",
                            metadata={"action_name": parent_action_name, "source": source, "target": previous_target},
                        ))
            
            # arrow_only_stmt: "-> Target"
            elif node_type == "arrow_only_stmt":
                target = node.get("target", "")
                
                if target and previous_target:
                    # 前のflowのtargetから現在のtargetへ
                    full_source = f"{parent_action_name}::{previous_target}" if parent_action_name else previous_target
                    full_target = f"{parent_action_name}::{target}" if parent_action_name else target
                    
                    relationships.append(SysMLRelationship(
                        source_name=full_source,
                        target_name=full_target,
                        relation_type="state-transition",
                        source_type="action",
                        target_type="action",
                        metadata={"action_name": parent_action_name, "source": previous_target, "target": target},
                    ))
                    current_target = target
                elif target:
                    # previous_targetがない場合は、action名からtargetへ
                    full_source = parent_action_name
                    full_target = f"{parent_action_name}::{target}" if parent_action_name else target
                    
                    relationships.append(SysMLRelationship(
                        source_name=full_source,
                        target_name=full_target,
                        relation_type="state-transition",
                        source_type="action_def",
                        target_type="action",
                        metadata={"action_name": parent_action_name, "source": parent_action_name, "target": target},
                    ))
                    current_target = target
            
            # 再帰的に子ノードを処理
            for key in ["children"]:
                if key in node:
                    for child in node[key]:
                        if isinstance(child, dict):
                            current_target = _find_flows(child, parent_action_name, current_target) or current_target
            
            return current_target
        
        _find_flows(ast, full_action_name)
        
        # 再帰的に子ノードを処理（他の関係も抽出）
        for child in ast.get("children", []):
            if isinstance(child, dict):
                relationships.extend(_extract_sysml_relationships(child, namespace))
    
    # その他のノードタイプも再帰的に処理
    # package/part_def/action_def は上の分岐で既に子ノードを再帰済み（package は
    # 名前空間を更新して再帰するため、ここで再度処理すると関係が重複生成される）。
    elif node_type not in ("package", "part_def", "action_def"):
        for key in ["children"]:
            if key in ast:
                for child in ast[key]:
                    if isinstance(child, dict):
                        relationships.extend(_extract_sysml_relationships(child, namespace))

    return relationships


def _find_chunk_ids_for_sysml_elements(
    element_names: List[str],
    chunks: List[str],
    chunk_ids: List[str],
) -> Dict[str, List[str]]:
    """SysML要素名を含むチャンクIDを検索する。
    
    Args:
        element_names: 検索するSysML要素名のリスト
        chunks: チャンクテキストのリスト
        chunk_ids: チャンクIDのリスト
        
    Returns:
        要素名 -> チャンクIDのリストのマッピング
    """
    element_to_chunks: Dict[str, List[str]] = {}
    
    for element_name in element_names:
        # 名前空間を除去して短縮名を取得（例: "LibrarySystem::CatalogSystem" -> "CatalogSystem"）
        short_name = element_name.split("::")[-1].split(".")[-1]
        matching_chunk_ids = []
        
        for text_chunk, chunk_id in zip(chunks, chunk_ids):
            # 要素名がチャンクテキストに含まれているかチェック
            # "part def CatalogSystem" や "CatalogSystem" を含むチャンクを探す
            if short_name in text_chunk or element_name in text_chunk:
                matching_chunk_ids.append(chunk_id)
        
        if matching_chunk_ids:
            element_to_chunks[element_name] = matching_chunk_ids
    
    return element_to_chunks


def detect_file_type(path: Path) -> str:
    """拡張子からファイル種別を判定する。

    Args:
        path: ファイルパス。

    Returns:
        str: ファイル種別（"txt", "md", "pdf", "docx", "xlsx", "pptx", "sysml" のいずれか）。
            該当しない場合は "txt" を返します。

    Example:
        >>> path = Path("document.pdf")
        >>> file_type = detect_file_type(path)
        >>> print(file_type)
        pdf
    """
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in {".xlsx", ".xls"}:
        return "xlsx"
    if suffix == ".pptx":
        return "pptx"
    if suffix == ".sysml":
        return "sysml"
    return "txt"


def load_and_chunk(path: Path) -> Tuple[List[str], List[Optional[int]]]:
    """パスからファイルを読み込み、テキスト化してチャンク分割する。

    txt / md: UTF-8テキストとして読み込み
    pdf: pypdfで全文テキスト抽出後にチャンク
    docx: python-docxで段落ごとにテキスト抽出後にチャンク
    xlsx: openpyxlでシートごとにテキスト抽出後にチャンク
    pptx: python-pptxでスライドごとにテキスト抽出後にチャンク

    Args:
        path: 読み込むファイルのパス。

    Returns:
        Tuple[List[str], List[Optional[int]]]:
            - チャンクのリスト
            - 各チャンクに対応する page_number のリスト
              （PDF: ページ番号、Word: 段落番号、Excel: シート番号、PowerPoint: スライド番号、その他: None）

    Raises:
        FileNotFoundError: ファイルが存在しない場合。
        Exception: ファイルの読み込みに失敗した場合。

    Example:
        >>> path = Path("document.txt")
        >>> chunks, pages = load_and_chunk(path)
        >>> print(f"Number of chunks: {len(chunks)}")
        Number of chunks: 5
    """
    chunks, page_numbers, _metas = load_and_chunk_with_metadata(path)
    return chunks, page_numbers


def load_and_chunk_with_metadata(path: Path) -> Tuple[List[str], List[Optional[int]], List[Dict[str, object]]]:
    """パスからファイルを読み込み、意味単位を考慮してチャンク分割する（メタデータ付き）。

    ファイルタイプに応じて適切な読み込み方法を使用し、
    セマンティックチャンキング（chunk_text_semantic）で意味単位を考慮して分割します。

    Args:
        path: 読み込むファイルのパス。

    Returns:
        Tuple[List[str], List[Optional[int]], List[Dict[str, object]]]:
            - chunks: チャンクテキストのリスト
            - page_numbers: 各チャンクに対応するページ番号のリスト
                - PDF: ページ番号
                - Word: 段落番号
                - Excel: シート番号
                - PowerPoint: スライド番号
                - その他: None
            - per_chunk_meta: 各チャンクのメタデータのリスト
                - section_id: セクションID（Markdownの場合）
                - section_title: セクションタイトル（Markdownの場合）
                - chunk_kind: チャンクの種類（"text", "code", "sysml_code"など）
                - code_language: コード言語（コードブロックの場合）

    Raises:
        FileNotFoundError: ファイルが存在しない場合。
        Exception: ファイルの読み込みに失敗した場合。

    Note:
        - SysMLファイルの場合は、ファイル全体を1チャンクとして扱います。
        - PDF、Word、Excel、PowerPointの場合は、ページ/段落/シート/スライドごとに
          セマンティックチャンキングを適用します。
    """
    ftype = detect_file_type(path)
    if ftype == "md":
        text = read_markdown_file(path)
        pairs = chunk_text_semantic(text)
        chunks = [t for t, _ in pairs]
        metas: List[Dict[str, object]] = [m for _, m in pairs]
        return chunks, [None] * len(chunks), metas
    if ftype == "sysml":
        # SysMLは「定義途中で切れて壊れる」と検索精度が大きく落ちるため、
        # ステップ1では安全側に倒して「ファイル全体を1チャンク」として登録する。
        # （後続ステップで、章/節や定義単位など、より高精度な分割へ拡張する）
        text = read_text_file(path)
        if not text.strip():
            return [], [], []
        return [text], [None], [{"section_id": None, "section_title": None, "chunk_kind": "sysml_code", "code_language": "sysml"}]
    if ftype == "pdf":
        _full_text, pages = read_pdf_file(path)
        chunks: List[str] = []
        page_numbers: List[Optional[int]] = []
        metas: List[Dict[str, object]] = []
        for page_number, page_text in pages:
            pairs = chunk_text_semantic(page_text)
            page_chunks = [t for t, _ in pairs]
            page_metas = [m for _, m in pairs]
            chunks.extend(page_chunks)
            metas.extend(page_metas)
            page_numbers.extend([page_number] * len(page_chunks))
        return chunks, page_numbers, metas
    if ftype == "docx":
        _full_text, paragraphs = read_word_file(path)
        chunks: List[str] = []
        paragraph_numbers: List[Optional[int]] = []
        metas: List[Dict[str, object]] = []
        for para_number, para_text in paragraphs:
            pairs = chunk_text_semantic(para_text)
            para_chunks = [t for t, _ in pairs]
            para_metas = [m for _, m in pairs]
            chunks.extend(para_chunks)
            metas.extend(para_metas)
            paragraph_numbers.extend([para_number] * len(para_chunks))
        return chunks, paragraph_numbers, metas
    if ftype == "xlsx":
        _full_text, sheets = read_excel_file(path)
        chunks: List[str] = []
        sheet_numbers: List[Optional[int]] = []
        metas: List[Dict[str, object]] = []
        for sheet_number, sheet_text in sheets:
            pairs = chunk_text_semantic(sheet_text)
            sheet_chunks = [t for t, _ in pairs]
            sheet_metas = [m for _, m in pairs]
            chunks.extend(sheet_chunks)
            metas.extend(sheet_metas)
            sheet_numbers.extend([sheet_number] * len(sheet_chunks))
        return chunks, sheet_numbers, metas
    if ftype == "pptx":
        _full_text, slides = read_powerpoint_file(path)
        chunks: List[str] = []
        slide_numbers: List[Optional[int]] = []
        metas: List[Dict[str, object]] = []
        for slide_number, slide_text in slides:
            pairs = chunk_text_semantic(slide_text)
            slide_chunks = [t for t, _ in pairs]
            slide_metas = [m for _, m in pairs]
            chunks.extend(slide_chunks)
            metas.extend(slide_metas)
            slide_numbers.extend([slide_number] * len(slide_chunks))
        return chunks, slide_numbers, metas

    text = read_text_file(path)
    pairs = chunk_text_semantic(text)
    chunks = [t for t, _ in pairs]
    metas: List[Dict[str, object]] = [m for _, m in pairs]
    return chunks, [None] * len(chunks), metas


def index_document(
    path: Path,
    *,
    vector_store: Optional[VectorStoreAPI] = None,
    metadata_store: Optional[MetadataStore] = None,
    graph_store: Optional["GraphStore"] = None,
    entities_json_path: Optional[Path] = None,
    auto_extract_entities: bool = False,
    entity_extraction_method: str = "llm",  # "llm" or "parser"
    entity_extraction_model: Optional[str] = None,  # None なら DEFAULT_ENTITY_EXTRACTION_MODEL
) -> Dict[str, object]:
    """1つのファイルを読み込み、チャンク化し、ベクトルDBとメタDBの両方に登録する。

    document_id にはファイルの絶対パス文字列を使用します。
    chunk_id は ``document_id::chunk-{i}`` 形式で生成されます。

    さらに、`graph_store` が指定されている場合、軽量GraphRAGとして
    同一ファイル内の隣接チャンク間の関係（next/prev）をグラフ化します。

    Args:
        path: インデックス化するファイルのパス。
        vector_store: ベクトルストアAPIインスタンス。
            Noneの場合は新規作成されます。
        metadata_store: メタデータストアインスタンス。
            Noneの場合は新規作成されます。
        graph_store: グラフストアインスタンス（軽量GraphRAG用、オプション）。
            Noneの場合はGraph構築をスキップします。
            指定されている場合、同一ファイル内の隣接チャンク（chunk_indexの前後）を
            `next/prev` エッジとしてグラフ化します。
        entities_json_path: GraphRAG拡張機能用のエンティティ定義JSONファイルのパス（オプション）。
            指定された場合、JSONファイルからConstraint、SyntaxRule、SpecClause、Termを読み込み、
            GraphStoreに追加します。JSONファイルの形式は `data/entities_example.json` を参照してください。

    Returns:
        Dict[str, object]: インデックス化結果の辞書。以下のキーを含みます:
            - document_id: ドキュメントID（絶対パス）
            - file_name: ファイル名
            - file_type: ファイル種別
            - num_chunks: チャンク数

    Raises:
        FileNotFoundError: ファイルが存在しない場合。

    Example:
        >>> path = Path("document.pdf")
        >>> result = index_document(path)
        >>> print(result["num_chunks"])
        10
        >>> # GraphRAGも有効化する場合
        >>> from rag.graph_store import GraphStore
        >>> graph = GraphStore(persist_path=Path("data/graph.pkl"))
        >>> result = index_document(path, graph_store=graph)
        >>> # GraphRAG拡張機能（エンティティ登録）も有効化する場合
        >>> entities_json = Path("data/entities.json")
        >>> result = index_document(path, graph_store=graph, entities_json_path=entities_json)
    """
    if vector_store is None:
        vector_store = VectorStoreAPI()
    if metadata_store is None:
        metadata_store = MetadataStore()

    started = perf_counter()
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"ファイルが存在しません: {path}")

    logger.info(
        "index_document.start",
        extra={"event": "index_document.start", "document_id": str(path)},
    )

    file_type = detect_file_type(path)
    t0 = perf_counter()
    chunks, page_numbers, chunk_metas = load_and_chunk_with_metadata(path)
    load_ms = int((perf_counter() - t0) * 1000)

    document_id = str(path)
    base_metadata = {
        "file_name": path.name,
        "file_path": document_id,
        "file_type": file_type,
    }

    ids: List[str] = []
    vector_ms = 0
    meta_ms = 0
    graph_ms = 0

    # 1) Vector登録 → 2) Meta登録 → 3) Graph登録 の順に実行し、
    # 途中で失敗した場合は「ベクトル側を削除」して整合性を保つ。
    # （SQLite側は bulk_insert_chunks でロールバックされる）
    try:
        t0 = perf_counter()
        # per-chunk metadata: page_number + semantic metadata
        per_chunk_metadata: List[Dict[str, object]] = []
        for pn, meta in zip(page_numbers, chunk_metas):
            # ChromaDB の metadata は None を受け付けないため除去する
            merged: Dict[str, object] = {k: v for k, v in meta.items() if v is not None}
            if pn is not None:
                merged["page_number"] = pn
            per_chunk_metadata.append(merged)

        ids = vector_store.register_texts(
            document_id=document_id,
            texts=chunks,
            base_metadata=base_metadata,
            per_chunk_metadata=per_chunk_metadata,
        )
        vector_ms = int((perf_counter() - t0) * 1000)

        records = []
        for idx, (cid, chunk_text_value, pn, meta) in enumerate(zip(ids, chunks, page_numbers, chunk_metas)):
            records.append(
                {
                    "chunk_id": cid,
                    "file_name": path.name,
                    "file_path": document_id,
                    "file_type": file_type,
                    "chunk_text": chunk_text_value,
                    "chunk_index": idx,
                    "page_number": pn,
                    "section_id": meta.get("section_id"),
                    "section_title": meta.get("section_title"),
                    "chunk_kind": meta.get("chunk_kind"),
                    "code_language": meta.get("code_language"),
                }
            )

        t0 = perf_counter()
        metadata_store.bulk_insert_chunks(records)
        meta_ms = int((perf_counter() - t0) * 1000)
    except Exception:
        # metadata が失敗した場合、vector側に残ったデータを削除してロールバック
        if ids:
            try:
                vector_store.delete(ids)
            except Exception:
                # ここでの削除失敗は「追加の障害」なのでログに残す
                logger.exception(
                    "index_document.rollback_vector_failed",
                    extra={"event": "index_document.rollback_vector_failed", "document_id": document_id},
                )
        logger.exception(
            "index_document.error",
            extra={
                "event": "index_document.error",
                "document_id": document_id,
                "file_type": file_type,
                "n_chunks": len(chunks),
                "ms_load": load_ms,
                "ms_vector": vector_ms,
                "ms_meta": meta_ms,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise

    # --- GraphRAG（軽量版）: 隣接チャンクの関係をグラフ化（任意） ---
    # まずは最小実装として「同一ファイル内の前後関係（chunk_indexの隣接）」のみ作る。
    # 将来の拡張: LLMによる関係抽出（依存関係、因果関係など）を追加可能。
    if graph_store is not None:
        t0 = perf_counter()
        try:
            # 各チャンクをノードとして追加
            for idx, (cid, chunk_text_value, pn) in enumerate(zip(ids, chunks, page_numbers)):
                graph_store.add_chunk_node(
                    cid,
                    text=chunk_text_value,
                    metadata={
                        "file_name": path.name,
                        "file_path": document_id,
                        "file_type": file_type,
                        "node_type": "chunk",
                        "chunk_index": idx,
                        "page_number": pn,
                        "section_id": chunk_metas[idx].get("section_id") if idx < len(chunk_metas) else None,
                        "section_title": chunk_metas[idx].get("section_title") if idx < len(chunk_metas) else None,
                        "chunk_kind": chunk_metas[idx].get("chunk_kind") if idx < len(chunk_metas) else None,
                        "code_language": chunk_metas[idx].get("code_language") if idx < len(chunk_metas) else None,
                    },
                )

            # --- 章/節ノードを構築（ステップ3） ---
            # section_id がある場合、sectionノードを作り、chunkとの包含関係を張る。
            section_nodes: dict[str, str] = {}  # section_id -> node_id
            section_titles: dict[str, str] = {}
            for idx, cid in enumerate(ids):
                meta = chunk_metas[idx] if idx < len(chunk_metas) else {}
                sid = meta.get("section_id")
                stitle = meta.get("section_title")
                if not isinstance(sid, str) or not sid.strip():
                    continue
                sid = sid.strip()
                section_node_id = f"{document_id}::section-{sid}"
                section_nodes[sid] = section_node_id
                if isinstance(stitle, str) and stitle.strip():
                    section_titles[sid] = stitle.strip()

                if not graph_store.has_node(section_node_id):
                    graph_store.add_chunk_node(
                        section_node_id,
                        text="",
                        metadata={
                            "file_name": path.name,
                            "file_path": document_id,
                            "file_type": file_type,
                            "node_type": "section",
                            "section_id": sid,
                            "section_title": section_titles.get(sid),
                        },
                    )

                # section <-> chunk
                graph_store.add_edge(section_node_id, cid, relation="contains", weight=1.0)
                graph_store.add_edge(cid, section_node_id, relation="in_section", weight=1.0)

            # section の親子（"8.1.2" -> 親 "8.1"）
            for sid, node_id in list(section_nodes.items()):
                if "." not in sid:
                    continue
                parent_sid = sid.rsplit(".", 1)[0]
                parent_node_id = section_nodes.get(parent_sid) or f"{document_id}::section-{parent_sid}"
                if parent_sid not in section_nodes:
                    section_nodes[parent_sid] = parent_node_id
                    if not graph_store.has_node(parent_node_id):
                        graph_store.add_chunk_node(
                            parent_node_id,
                            text="",
                            metadata={
                                "file_name": path.name,
                                "file_path": document_id,
                                "file_type": file_type,
                                "node_type": "section",
                                "section_id": parent_sid,
                                "section_title": section_titles.get(parent_sid),
                            },
                        )
                # 親子を双方向で接続（探索で上下に辿れるようにする）
                graph_store.add_edge(parent_node_id, node_id, relation="subsection", weight=1.0)
                graph_store.add_edge(node_id, parent_node_id, relation="parent_section", weight=1.0)

            # TOC（目次）ノード（最低限: ドキュメント内のトップレベルセクションへリンク）
            if section_nodes:
                toc_id = f"{document_id}::toc"
                if not graph_store.has_node(toc_id):
                    graph_store.add_chunk_node(
                        toc_id,
                        text="",
                        metadata={
                            "file_name": path.name,
                            "file_path": document_id,
                            "file_type": file_type,
                            "node_type": "toc",
                        },
                    )
                top_level = [sid for sid in section_nodes.keys() if "." not in sid]
                for sid in top_level:
                    snode = section_nodes[sid]
                    graph_store.add_edge(toc_id, snode, relation="toc_section", weight=1.0)
                    graph_store.add_edge(snode, toc_id, relation="in_toc", weight=1.0)

            # 隣接関係（next/prev）を双方向エッジとして付与
            # 例: chunk-0 → chunk-1 (next), chunk-1 → chunk-0 (prev)
            for a, b in zip(ids, ids[1:]):
                graph_store.add_bidirectional_edge(a, b, relation_ab="next", relation_ba="prev")

            # --- SysML AST由来の関係を追加（フェーズ5: GraphRAG関係タイプ拡張） ---
            if file_type == "sysml" and _SYSML_PARSER_AVAILABLE and parse_sysml:
                try:
                    # SysMLファイルのテキストを取得
                    sysml_text = read_text_file(path)
                    if sysml_text.strip():
                        # ASTをパース
                        ast = parse_sysml(sysml_text)
                        if ast.get("type") != "error":
                            # 関係を抽出
                            relationships = _extract_sysml_relationships(ast)
                            
                            # 関係の起点・終点要素名を収集
                            element_names = set()
                            for rel in relationships:
                                element_names.add(rel.source_name)
                                element_names.add(rel.target_name)
                            
                            # 要素名を含むチャンクIDを検索
                            element_to_chunks = _find_chunk_ids_for_sysml_elements(
                                list(element_names),
                                chunks,
                                ids,
                            )
                            
                            # 関係をGraphStoreに追加
                            for rel in relationships:
                                source_chunks = element_to_chunks.get(rel.source_name, [])
                                target_chunks = element_to_chunks.get(rel.target_name, [])
                                
                                # 各sourceチャンクから各targetチャンクへエッジを追加
                                for source_chunk_id in source_chunks:
                                    for target_chunk_id in target_chunks:
                                        if source_chunk_id != target_chunk_id:
                                            graph_store.add_edge(
                                                source_chunk_id,
                                                target_chunk_id,
                                                relation=rel.relation_type,
                                                weight=1.0,
                                                metadata=rel.metadata or {},
                                            )
                            
                            logger.info(
                                "index_document.sysml_relationships_added",
                                extra={
                                    "event": "index_document.sysml_relationships_added",
                                    "document_id": document_id,
                                    "num_relationships": len(relationships),
                                },
                            )
                except Exception as e:
                    # SysML関係抽出の失敗はログに記録するが、インデックス自体は成功扱い
                    logger.warning(
                        "index_document.sysml_relationship_extraction_failed",
                        extra={
                            "event": "index_document.sysml_relationship_extraction_failed",
                            "document_id": document_id,
                            "error": str(e),
                        },
                        exc_info=True,
                    )

            # --- GraphRAG拡張: エンティティ（Constraint, SyntaxRule等）の追加（オプション） ---
            # 方法1: 自動抽出
            if auto_extract_entities and ENTITY_EXTRACTOR_AVAILABLE and graph_store:
                try:
                    # チャンク情報を準備
                    chunk_data = [
                        {
                            "chunk_id": cid,
                            "text": chunk_text_value,
                            "metadata": chunk_metas[idx] if idx < len(chunk_metas) else {},
                        }
                        for idx, (cid, chunk_text_value) in enumerate(zip(ids, chunks))
                    ]

                    # エンティティを抽出
                    if entity_extraction_method == "llm" and extract_entities_with_llm:
                        entities_data = extract_entities_with_llm(chunk_data, model=entity_extraction_model)
                    elif entity_extraction_method == "parser" and extract_entities_with_parser:
                        entities_data = extract_entities_with_parser(chunk_data, file_type=file_type)
                    else:
                        logger.warning(
                            "index_document.unsupported_extraction_method",
                            extra={
                                "event": "index_document.unsupported_extraction_method",
                                "method": entity_extraction_method,
                            },
                        )
                        entities_data = {"constraints": [], "syntax_rules": [], "spec_clauses": [], "terms": []}

                    # 抽出されたエンティティをGraphStoreに追加
                    for constraint in entities_data.get("constraints", []):
                        graph_store.add_constraint_node(
                            constraint["id"],
                            name=constraint.get("name", ""),
                            description=constraint.get("description", ""),
                        )
                        for chunk_id in constraint.get("related_chunks", []):
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(chunk_id, constraint["id"], relation="derived_from")

                    for rule in entities_data.get("syntax_rules", []):
                        graph_store.add_syntax_rule_node(
                            rule["id"],
                            name=rule.get("name", ""),
                            description=rule.get("description", ""),
                        )
                        for chunk_id in rule.get("related_chunks", []):
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(chunk_id, rule["id"], relation="refers_to")

                    for clause in entities_data.get("spec_clauses", []):
                        graph_store.add_spec_clause_node(
                            clause["id"],
                            clause_number=clause.get("clause_number", ""),
                            title=clause.get("title", ""),
                        )
                        for chunk_id in clause.get("related_chunks", []):
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(chunk_id, clause["id"], relation="derived_from")

                    for term in entities_data.get("terms", []):
                        graph_store.add_term_node(
                            term["id"],
                            term=term.get("term", ""),
                            definition=term.get("definition", ""),
                        )
                        for chunk_id in term.get("related_chunks", []):
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(chunk_id, term["id"], relation="contains")

                    logger.info(
                        "index_document.entities_auto_extracted",
                        extra={
                            "event": "index_document.entities_auto_extracted",
                            "document_id": document_id,
                            "method": entity_extraction_method,
                            "num_constraints": len(entities_data.get("constraints", [])),
                            "num_syntax_rules": len(entities_data.get("syntax_rules", [])),
                            "num_spec_clauses": len(entities_data.get("spec_clauses", [])),
                            "num_terms": len(entities_data.get("terms", [])),
                        },
                    )
                except Exception as e:
                    # 自動抽出の失敗は警告のみ（インデックス自体は成功扱い）
                    logger.warning(
                        "index_document.auto_extraction_failed",
                        extra={
                            "event": "index_document.auto_extraction_failed",
                            "document_id": document_id,
                            "method": entity_extraction_method,
                            "error": str(e),
                        },
                        exc_info=True,
                    )

            # 方法2: JSONファイルから読み込み
            if entities_json_path is not None and entities_json_path.exists():
                try:
                    import json
                    with open(entities_json_path, "r", encoding="utf-8") as f:
                        entities_data = json.load(f)
                    
                    # Constraintを追加
                    for constraint in entities_data.get("constraints", []):
                        graph_store.add_constraint_node(
                            constraint["id"],
                            name=constraint.get("name", ""),
                            description=constraint.get("description", ""),
                        )
                        # 既存のチャンクとの関係を追加
                        for chunk_id in constraint.get("related_chunks", []):
                            # チャンクIDが存在するか確認（document_id::chunk-{i}形式）
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(
                                    chunk_id,
                                    constraint["id"],
                                    relation="derived_from"
                                )
                    
                    # SyntaxRuleを追加
                    for rule in entities_data.get("syntax_rules", []):
                        graph_store.add_syntax_rule_node(
                            rule["id"],
                            name=rule.get("name", ""),
                            description=rule.get("description", ""),
                        )
                        # 既存のチャンクとの関係を追加
                        for chunk_id in rule.get("related_chunks", []):
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(
                                    chunk_id,
                                    rule["id"],
                                    relation="refers_to"
                                )
                    
                    # SpecClauseを追加
                    for clause in entities_data.get("spec_clauses", []):
                        graph_store.add_spec_clause_node(
                            clause["id"],
                            clause_number=clause.get("clause_number", ""),
                            title=clause.get("title", ""),
                        )
                        # 既存のチャンクとの関係を追加
                        for chunk_id in clause.get("related_chunks", []):
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(
                                    chunk_id,
                                    clause["id"],
                                    relation="derived_from"
                                )
                    
                    # Termを追加
                    for term in entities_data.get("terms", []):
                        graph_store.add_term_node(
                            term["id"],
                            term=term.get("term", ""),
                            definition=term.get("definition", ""),
                        )
                        # 既存のチャンクとの関係を追加
                        for chunk_id in term.get("related_chunks", []):
                            if chunk_id in ids or graph_store.has_node(chunk_id):
                                graph_store.add_edge(
                                    chunk_id,
                                    term["id"],
                                    relation="contains"
                                )
                    
                    logger.info(
                        "index_document.entities_added",
                        extra={
                            "event": "index_document.entities_added",
                            "document_id": document_id,
                            "entities_json_path": str(entities_json_path),
                        },
                    )
                except Exception as e:
                    # エンティティ追加の失敗は警告のみ（インデックス自体は成功扱い）
                    logger.warning(
                        "index_document.entities_add_failed",
                        extra={
                            "event": "index_document.entities_add_failed",
                            "document_id": document_id,
                            "entities_json_path": str(entities_json_path),
                            "error": str(e),
                        },
                        exc_info=True,
                    )

            # 永続化はオプション（persist_pathが設定されていれば保存）
            if getattr(graph_store, "persist_path", None) is not None:
                graph_store.save()
            graph_ms = int((perf_counter() - t0) * 1000)
        except Exception:
            # Graphは補助情報なので、失敗してもインデックス自体は成功扱いにする
            # （ログは上位で拾えるように例外は握りつぶす）
            logger.exception(
                "index_document.graph_failed",
                extra={"event": "index_document.graph_failed", "document_id": document_id},
            )

    logger.info(
        "index_document.done",
        extra={
            "event": "index_document.done",
            "document_id": document_id,
            "file_type": file_type,
            "n_chunks": len(chunks),
            "ms_load": load_ms,
            "ms_vector": vector_ms,
            "ms_meta": meta_ms,
            "ms_graph": graph_ms,
            "duration_ms": int((perf_counter() - started) * 1000),
        },
    )

    duration_ms = int((perf_counter() - started) * 1000)
    return {
        "document_id": document_id,
        "file_name": path.name,
        "file_type": file_type,
        "num_chunks": len(chunks),
        # Observability: index_document 内のステップ別計測
        "load_ms": load_ms,
        "vector_ms": vector_ms,
        "meta_ms": meta_ms,
        "graph_ms": graph_ms,
        "duration_ms": duration_ms,
    }



