"""graphrag.pdf_processor のテキスト抽出・メタデータ取得のテスト。優先度: GraphRAG。

実PDFはpypdfの空白ページ（tests/test_rag_chunking_io.pyと同じ手法）で
ファイル存在チェックやページ数取得などのスモークテストを行う。空白ページは
抽出テキストが空文字になるため、ページ選択（1-indexed→0-indexed変換や
範囲外フィルタ）や空文字スキップ・結合ロジックの検証には、pdfplumber.open /
pypdf.PdfReader をフェイクの reader に差し替えて厳密に確認する
（本モジュールは注入可能な設計ではないため、モジュール属性の置き換えで代替する）。
"""

from pathlib import Path

import pytest
from graphrag.pdf_processor import PDFProcessor
from pypdf import PdfWriter

from graphrag import pdf_processor as pdf_processor_module

# ---- フェイクの pypdf / pdfplumber reader ----


class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakePdfReader:
    """pypdf.PdfReader の代替。open()されたファイルオブジェクトは無視する。"""

    def __init__(self, pages, metadata=None):
        self.pages = pages
        self.metadata = metadata

    def __call__(self, file_obj):
        return self


class _FakePdfPlumberDocument:
    def __init__(self, pages, metadata=None):
        self.pages = pages
        self.metadata = metadata

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _make_dummy_pdf_file(tmp_path: Path) -> Path:
    """存在チェックを通すためだけのダミーファイル（内容は解析しない）。"""
    path = tmp_path / "dummy.pdf"
    path.write_bytes(b"%PDF-fake")
    return path


# ---- 実PDF（空白ページ）でのスモークテスト ----


def test_extract_text_on_real_blank_pdf_with_pdfplumber(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_blank_page(width=72, height=72)
    with open(pdf_path, "wb") as f:
        w.write(f)

    processor = PDFProcessor(use_pdfplumber=True)
    text = processor.extract_text(str(pdf_path))

    assert isinstance(text, str)


def test_extract_text_on_real_blank_pdf_with_pypdf(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    with open(pdf_path, "wb") as f:
        w.write(f)

    processor = PDFProcessor(use_pdfplumber=False)
    text = processor.extract_text(str(pdf_path))

    assert isinstance(text, str)


def test_get_metadata_on_real_pdf_reports_correct_page_count_and_file_info(tmp_path):
    pdf_path = tmp_path / "meta.pdf"
    w = PdfWriter()
    for _ in range(3):
        w.add_blank_page(width=72, height=72)
    with open(pdf_path, "wb") as f:
        w.write(f)

    processor = PDFProcessor(use_pdfplumber=True)
    metadata = processor.get_metadata(str(pdf_path))

    assert metadata["page_count"] == 3
    assert metadata["filename"] == "meta.pdf"
    assert metadata["file_size"] > 0
    assert "error" not in metadata


# ---- extract_text: ファイル未存在 ----


@pytest.mark.parametrize("use_pdfplumber", [True, False])
def test_extract_text_raises_file_not_found(tmp_path, use_pdfplumber):
    processor = PDFProcessor(use_pdfplumber=use_pdfplumber)
    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(FileNotFoundError):
        processor.extract_text(str(missing))


def test_get_metadata_raises_file_not_found(tmp_path):
    processor = PDFProcessor(use_pdfplumber=True)
    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(FileNotFoundError):
        processor.get_metadata(str(missing))


# ---- ページ選択・空文字スキップ・結合ロジック（フェイクreaderで厳密検証） ----


def test_extract_text_with_pdfplumber_joins_pages_and_skips_empty_text(tmp_path, monkeypatch):
    dummy = _make_dummy_pdf_file(tmp_path)
    pages = [_FakePage("page1"), _FakePage(""), _FakePage("page3")]
    monkeypatch.setattr(
        pdf_processor_module.pdfplumber, "open", lambda fp: _FakePdfPlumberDocument(pages)
    )

    processor = PDFProcessor(use_pdfplumber=True)
    text = processor.extract_text(str(dummy))

    # 空文字（ページ2）はスキップされ、残りは "\n\n" で結合される
    assert text == "page1\n\npage3"


def test_extract_text_with_pdfplumber_filters_pages_by_1_indexed_list(tmp_path, monkeypatch):
    dummy = _make_dummy_pdf_file(tmp_path)
    pages = [_FakePage("page1"), _FakePage("page2"), _FakePage("page3")]
    monkeypatch.setattr(
        pdf_processor_module.pdfplumber, "open", lambda fp: _FakePdfPlumberDocument(pages)
    )

    processor = PDFProcessor(use_pdfplumber=True)
    # 1-indexed: ページ1と3のみ要求。範囲外(0, 99)は無視される
    text = processor.extract_text(str(dummy), pages=[1, 3, 0, 99])

    assert text == "page1\n\npage3"


def test_extract_text_with_pypdf_joins_pages_and_skips_empty_text(tmp_path, monkeypatch):
    dummy = _make_dummy_pdf_file(tmp_path)
    pages = [_FakePage("alpha"), _FakePage(None), _FakePage("gamma")]
    fake_reader_factory = _FakePdfReader(pages)
    monkeypatch.setattr(pdf_processor_module.pypdf, "PdfReader", fake_reader_factory)

    processor = PDFProcessor(use_pdfplumber=False)
    text = processor.extract_text(str(dummy))

    assert text == "alpha\n\ngamma"


def test_extract_text_with_pypdf_filters_pages_by_1_indexed_list(tmp_path, monkeypatch):
    dummy = _make_dummy_pdf_file(tmp_path)
    pages = [_FakePage("p1"), _FakePage("p2"), _FakePage("p3")]
    monkeypatch.setattr(pdf_processor_module.pypdf, "PdfReader", _FakePdfReader(pages))

    processor = PDFProcessor(use_pdfplumber=False)
    text = processor.extract_text(str(dummy), pages=[2])

    assert text == "p2"


# ---- get_metadata: フィールドマッピングとエラー処理 ----


def test_get_metadata_with_pdfplumber_maps_metadata_fields(tmp_path, monkeypatch):
    dummy = _make_dummy_pdf_file(tmp_path)
    doc_metadata = {"Title": "My Title", "Author": "Alice", "Subject": "Sub", "Creator": "Tool"}
    monkeypatch.setattr(
        pdf_processor_module.pdfplumber,
        "open",
        lambda fp: _FakePdfPlumberDocument([_FakePage("x")], metadata=doc_metadata),
    )

    processor = PDFProcessor(use_pdfplumber=True)
    metadata = processor.get_metadata(str(dummy))

    assert metadata["page_count"] == 1
    assert metadata["title"] == "My Title"
    assert metadata["author"] == "Alice"


def test_get_metadata_with_pypdf_maps_slash_prefixed_metadata_fields(tmp_path, monkeypatch):
    dummy = _make_dummy_pdf_file(tmp_path)
    doc_metadata = {"/Title": "PyPdf Title", "/Author": "Bob", "/Subject": "S", "/Creator": "C"}
    monkeypatch.setattr(
        pdf_processor_module.pypdf,
        "PdfReader",
        _FakePdfReader([_FakePage("x")], metadata=doc_metadata),
    )

    processor = PDFProcessor(use_pdfplumber=False)
    metadata = processor.get_metadata(str(dummy))

    assert metadata["page_count"] == 1
    assert metadata["title"] == "PyPdf Title"
    assert metadata["author"] == "Bob"


def test_get_metadata_captures_error_when_backend_raises(tmp_path, monkeypatch):
    dummy = _make_dummy_pdf_file(tmp_path)

    def raise_open(fp):
        raise RuntimeError("corrupt pdf")

    monkeypatch.setattr(pdf_processor_module.pdfplumber, "open", raise_open)

    processor = PDFProcessor(use_pdfplumber=True)
    metadata = processor.get_metadata(str(dummy))

    # 例外を伝播させず、metadataに'error'として記録すること（基本フィールドは維持）
    assert metadata["error"] == "corrupt pdf"
    assert metadata["filename"] == "dummy.pdf"
    assert "page_count" not in metadata


# ---- 初期化ロジック ----


def test_init_prefers_pdfplumber_by_default_when_available():
    processor = PDFProcessor()
    assert processor.use_pdfplumber is True


def test_init_use_pdfplumber_false_selects_pypdf_backend():
    processor = PDFProcessor(use_pdfplumber=False)
    assert processor.use_pdfplumber is False


def test_init_raises_import_error_when_no_backend_available(monkeypatch):
    monkeypatch.setattr(pdf_processor_module, "PYPDF_AVAILABLE", False)
    monkeypatch.setattr(pdf_processor_module, "PDFPLUMBER_AVAILABLE", False)

    with pytest.raises(ImportError):
        PDFProcessor()
