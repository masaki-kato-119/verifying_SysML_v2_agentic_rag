"""rag.indexer のファイル種別判定・SysML関係抽出・登録オーケストレーション。
優先度: HybridRAG/rag(t5_add_tests_hybridrag_gaps)。

indexer.py(1,104行)はこれまでテストが無かった。detect_file_type/
_extract_sysml_relationshipsは純粋関数として重点的に、index_documentは
vector_store/metadata_store/graph_storeを注入できる設計を活かし、
フェイクオブジェクトでネットワーク・実DB無しにオーケストレーション
（正常系・メタ登録失敗時のベクトル側ロールバック）を検証する。
"""

from pathlib import Path

import pytest
from rag import indexer
from rag.indexer import SysMLRelationship, _extract_sysml_relationships, detect_file_type

# ---- detect_file_type ----


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("doc.md", "md"),
        ("doc.markdown", "md"),
        ("doc.pdf", "pdf"),
        ("doc.docx", "docx"),
        ("doc.xlsx", "xlsx"),
        ("doc.xls", "xlsx"),
        ("doc.pptx", "pptx"),
        ("doc.sysml", "sysml"),
        ("doc.txt", "txt"),
        ("doc.unknown_ext", "txt"),
        ("doc", "txt"),
    ],
)
def test_detect_file_type(filename, expected):
    assert detect_file_type(Path(filename)) == expected


# ---- _extract_sysml_relationships ----


def test_extract_relationships_returns_empty_for_non_dict_ast():
    assert _extract_sysml_relationships("not a dict") == []
    assert _extract_sysml_relationships(None) == []


def test_extract_relationships_inheritance():
    ast = {
        "type": "part_def",
        "name": "Car",
        "inheritance": {"base": "Vehicle"},
    }

    rels = _extract_sysml_relationships(ast)

    assert rels == [
        SysMLRelationship(
            source_name="Car",
            target_name="Vehicle",
            relation_type="inheritance",
            source_type="part_def",
            target_type="part_def",
        )
    ]


def test_extract_relationships_part_of_from_nested_part_instance():
    ast = {
        "type": "part_def",
        "name": "Car",
        "children": [
            {"type": "part_instance", "name": "eng", "type_name": "Engine", "role": "propulsion"},
        ],
    }

    rels = _extract_sysml_relationships(ast)

    assert len(rels) == 1
    assert rels[0].relation_type == "part-of"
    assert rels[0].source_name == "Car"
    assert rels[0].target_name == "Engine"
    assert rels[0].metadata == {"instance_name": "eng", "role": "propulsion"}


def test_extract_relationships_satisfied_by_with_action():
    ast = {
        "type": "requirement_def",
        "name": "R1",
        "satisfied_by": ["catalog.searchBooks"],
    }

    rels = _extract_sysml_relationships(ast)

    assert len(rels) == 1
    assert rels[0].relation_type == "satisfiedBy"
    assert rels[0].target_name == "catalog.searchBooks"
    assert rels[0].target_type == "action_def"


def test_extract_relationships_satisfied_by_without_action():
    ast = {
        "type": "requirement_def",
        "name": "R1",
        "satisfied_by": ["catalog"],
    }

    rels = _extract_sysml_relationships(ast)

    assert len(rels) == 1
    assert rels[0].target_name == "catalog"
    assert rels[0].target_type == "part_def"


def test_extract_relationships_connected_to():
    ast = {
        "type": "connection_def",
        "name": "C1",
        "from": {"name": "PartA"},
        "to": {"name": "PartB"},
    }

    rels = _extract_sysml_relationships(ast)

    assert len(rels) == 1
    assert rels[0].relation_type == "connected-to"
    assert rels[0].source_name == "PartA"
    assert rels[0].target_name == "PartB"
    assert rels[0].metadata == {"connection_name": "C1"}


def test_extract_relationships_state_transition_flow_id_stmt():
    ast = {
        "type": "action_def",
        "name": "A1",
        "children": [
            {"type": "flow_id_stmt", "source": "s1", "target": "s2"},
        ],
    }

    rels = _extract_sysml_relationships(ast)

    assert len(rels) == 1
    assert rels[0].relation_type == "state-transition"
    assert rels[0].source_name == "A1::s1"
    assert rels[0].target_name == "A1::s2"


def test_extract_relationships_recurses_into_nested_packages():
    ast = {
        "type": "package",
        "name": "Outer",
        "children": [
            {
                "type": "package",
                "name": "Inner",
                "children": [
                    {"type": "part_def", "name": "Widget", "inheritance": {"base": "Base"}}
                ],
            }
        ],
    }

    rels = _extract_sysml_relationships(ast)

    assert len(rels) == 1
    assert rels[0].source_name == "Outer::Inner::Widget"


def test_extract_relationships_unknown_node_type_is_ignored():
    ast = {"type": "totally_unknown_node", "name": "x"}

    assert _extract_sysml_relationships(ast) == []


# ---- load_and_chunk_with_metadata ----


def test_load_and_chunk_sysml_file_is_a_single_chunk(tmp_path):
    path = tmp_path / "model.sysml"
    path.write_text("package P { part def Q; }", encoding="utf-8")

    chunks, page_numbers, metas = indexer.load_and_chunk_with_metadata(path)

    assert chunks == ["package P { part def Q; }"]
    assert page_numbers == [None]
    assert metas[0]["chunk_kind"] == "sysml_code"
    assert metas[0]["code_language"] == "sysml"


def test_load_and_chunk_empty_sysml_file_returns_nothing(tmp_path):
    path = tmp_path / "empty.sysml"
    path.write_text("   \n  ", encoding="utf-8")

    chunks, page_numbers, metas = indexer.load_and_chunk_with_metadata(path)

    assert chunks == []
    assert page_numbers == []
    assert metas == []


def test_load_and_chunk_plain_text_file(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("Hello world. This is a plain text document.", encoding="utf-8")

    chunks, page_numbers = indexer.load_and_chunk(path)

    assert len(chunks) >= 1
    assert all(p is None for p in page_numbers)
    assert "Hello world" in chunks[0]


# ---- index_document (フェイクの vector_store / metadata_store で検証) ----


class _FakeVectorStore:
    def __init__(self):
        self.registered = None
        self.deleted = None

    def register_texts(self, *, document_id, texts, base_metadata, per_chunk_metadata):
        self.registered = (document_id, texts, base_metadata, per_chunk_metadata)
        return [f"{document_id}::chunk-{i}" for i in range(len(texts))]

    def delete(self, ids):
        self.deleted = ids


class _FakeMetadataStore:
    def __init__(self, fail=False):
        self.fail = fail
        self.records = None

    def bulk_insert_chunks(self, records):
        if self.fail:
            raise RuntimeError("db unavailable")
        self.records = records


def test_index_document_happy_path_registers_vector_and_metadata(tmp_path):
    path = tmp_path / "doc.sysml"
    path.write_text("package P { part def Q; }", encoding="utf-8")
    vector_store = _FakeVectorStore()
    metadata_store = _FakeMetadataStore()

    result = indexer.index_document(path, vector_store=vector_store, metadata_store=metadata_store)

    assert result["file_type"] == "sysml"
    assert result["num_chunks"] == 1
    assert vector_store.registered is not None
    assert metadata_store.records is not None
    assert metadata_store.records[0]["chunk_id"] == vector_store.registered[0] + "::chunk-0"


def test_index_document_rolls_back_vector_store_when_metadata_insert_fails(tmp_path):
    path = tmp_path / "doc.sysml"
    path.write_text("package P { part def Q; }", encoding="utf-8")
    vector_store = _FakeVectorStore()
    metadata_store = _FakeMetadataStore(fail=True)

    with pytest.raises(RuntimeError, match="db unavailable"):
        indexer.index_document(path, vector_store=vector_store, metadata_store=metadata_store)

    assert vector_store.deleted == [f"{path.resolve()}::chunk-0"]


def test_index_document_raises_file_not_found(tmp_path):
    missing = tmp_path / "does_not_exist.sysml"

    with pytest.raises(FileNotFoundError):
        indexer.index_document(
            missing, vector_store=_FakeVectorStore(), metadata_store=_FakeMetadataStore()
        )
