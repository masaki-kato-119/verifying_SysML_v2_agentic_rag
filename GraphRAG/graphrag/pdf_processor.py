"""
PDF処理モジュール
PDFファイルからテキストを抽出
"""
from pathlib import Path
from typing import Optional

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


class PDFProcessor:
    """
    PDF処理器
    
    PDFファイルからテキストを抽出
    """
    
    def __init__(self, use_pdfplumber: bool = True):
        """
        PDF処理器を初期化
        
        Args:
            use_pdfplumber: pdfplumberを使用するか（True）、pypdfを使用するか（False）
        """
        self.use_pdfplumber = use_pdfplumber and PDFPLUMBER_AVAILABLE
        
        if not PYPDF_AVAILABLE and not PDFPLUMBER_AVAILABLE:
            raise ImportError(
                "PDF processing requires either pypdf or pdfplumber. "
                "Install with: pip install pypdf or pip install pdfplumber"
            )
    
    def extract_text(self, filepath: str, pages: Optional[list] = None) -> str:
        """
        PDFファイルからテキストを抽出
        
        Args:
            filepath: PDFファイルのパス
            pages: 抽出するページ番号のリスト（Noneの場合は全ページ）
        
        Returns:
            str: 抽出されたテキスト
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"PDFファイルが見つかりません: {filepath}")
        
        if self.use_pdfplumber:
            return self._extract_with_pdfplumber(filepath, pages)
        else:
            return self._extract_with_pypdf(filepath, pages)
    
    def _extract_with_pdfplumber(self, filepath: str, pages: Optional[list] = None) -> str:
        """pdfplumberを使用してテキストを抽出"""
        text_parts = []
        
        with pdfplumber.open(filepath) as pdf:
            total_pages = len(pdf.pages)
            
            if pages is None:
                pages_to_extract = range(total_pages)
            else:
                pages_to_extract = [p - 1 for p in pages if 1 <= p <= total_pages]  # 1-indexed to 0-indexed
            
            for page_num in pages_to_extract:
                page = pdf.pages[page_num]
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        
        return "\n\n".join(text_parts)
    
    def _extract_with_pypdf(self, filepath: str, pages: Optional[list] = None) -> str:
        """pypdfを使用してテキストを抽出"""
        text_parts = []
        
        with open(filepath, 'rb') as file:
            pdf_reader = pypdf.PdfReader(file)
            total_pages = len(pdf_reader.pages)
            
            if pages is None:
                pages_to_extract = range(total_pages)
            else:
                pages_to_extract = [p - 1 for p in pages if 1 <= p <= total_pages]  # 1-indexed to 0-indexed
            
            for page_num in pages_to_extract:
                page = pdf_reader.pages[page_num]
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        
        return "\n\n".join(text_parts)
    
    def get_metadata(self, filepath: str) -> dict:
        """
        PDFファイルのメタデータを取得
        
        Args:
            filepath: PDFファイルのパス
        
        Returns:
            dict: メタデータ（タイトル、著者、ページ数など）
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"PDFファイルが見つかりません: {filepath}")
        
        metadata = {
            "filepath": str(path),
            "filename": path.name,
            "file_size": path.stat().st_size
        }
        
        try:
            if self.use_pdfplumber:
                with pdfplumber.open(filepath) as pdf:
                    metadata["page_count"] = len(pdf.pages)
                    if pdf.metadata:
                        metadata.update({
                            "title": pdf.metadata.get("Title", ""),
                            "author": pdf.metadata.get("Author", ""),
                            "subject": pdf.metadata.get("Subject", ""),
                            "creator": pdf.metadata.get("Creator", ""),
                        })
            else:
                with open(filepath, 'rb') as file:
                    pdf_reader = pypdf.PdfReader(file)
                    metadata["page_count"] = len(pdf_reader.pages)
                    if pdf_reader.metadata:
                        metadata.update({
                            "title": pdf_reader.metadata.get("/Title", ""),
                            "author": pdf_reader.metadata.get("/Author", ""),
                            "subject": pdf_reader.metadata.get("/Subject", ""),
                            "creator": pdf_reader.metadata.get("/Creator", ""),
                        })
        # pdfplumber/pypdfは壊れたPDFに対して多様な例外を送出しうるため、
        # メタデータ取得の失敗は個別に列挙せずerrorフィールドに記録して処理を継続する
        except Exception as e:  # noqa: BLE001
            metadata["error"] = str(e)

        return metadata

