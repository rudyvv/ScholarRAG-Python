"""Document parsing service — extracts text from multiple file formats.

Supports PDF, DOCX, XLSX/XLS, PPTX, TXT, MD, and CSV files.
Uses LangChain document loaders where available, with manual fallbacks.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from app.core.exceptions import BadRequestException


class DocumentParser:
    """Parse documents of various formats into plain text with metadata.

    Usage::

        parser = DocumentParser()
        result = parser.parse_document("/path/to/file.pdf", "pdf")
        print(result["text"])
        print(result["metadata"])
    """

    ALLOWED_TYPES: dict[str, list[str]] = {
        "pdf": ["application/pdf"],
        "docx": [
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ],
        "xlsx": [
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ],
        "xls": ["application/vnd.ms-excel"],
        "pptx": [
            "application/vnd.openxmlformats-officedocument"
            ".presentationml.presentation"
        ],
        "txt": ["text/plain"],
        "md": ["text/markdown", "text/x-markdown"],
        "csv": ["text/csv", "application/csv"],
        # Code files
        "py": ["text/x-python", "text/x-script.python", "text/x-python3"],
        "js": ["text/javascript", "application/javascript"],
        "ts": ["text/typescript", "application/typescript"],
        "java": ["text/x-java", "text/x-java-source"],
        "c": ["text/x-c", "text/x-csrc"],
        "cpp": ["text/x-c++", "text/x-c++src"],
        "h": ["text/x-c-header"],
        "hpp": ["text/x-c++-header"],
        "go": ["text/x-go"],
        "rs": ["text/x-rust"],
        "rb": ["text/x-ruby"],
        "php": ["text/x-php"],
        "swift": ["text/x-swift"],
        "kt": ["text/x-kotlin"],
    }

    def __init__(
        self, supported_types: dict[str, list[str]] | None = None
    ) -> None:
        """Initialize with optional custom MIME type whitelist.

        Args:
            supported_types: Mapping of file extension -> list of MIME types.
                Defaults to ``ALLOWED_TYPES``.
        """
        self.supported_types = supported_types or self.ALLOWED_TYPES

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_document(
        self, file_path: str, file_type: str
    ) -> dict[str, Any]:
        """Parse a document and return extracted text + metadata.

        Args:
            file_path: Absolute or relative path to the file.
            file_type: File extension without leading dot
                (e.g. ``"pdf"``, ``"docx"``, ``"txt"``).

        Returns:
            A dict with two keys:

            - ``text``: The full extracted plain text.
            - ``metadata``: Dict with ``page_count``, ``char_count``,
              ``file_type``, and ``language_hint``.

        Raises:
            BadRequestException: If the file type is unsupported, the
                document is empty, or it is encrypted / password-protected.
            FileNotFoundError: If the file does not exist on disk.
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.stat().st_size:
            raise BadRequestException("Document is empty")

        if file_type not in self.supported_types:
            raise BadRequestException(
                f"Unsupported file type: {file_type}"
            )

        parser = self._get_parser(file_type)
        result = parser(path)

        text = result.get("text", "")
        if not text or not text.strip():
            raise BadRequestException("Document is empty")

        language_hint = self._detect_language(text)

        metadata: dict[str, Any] = {
            "page_count": result.get("page_count", 0),
            "char_count": len(text),
            "file_type": file_type,
            "language_hint": language_hint,
        }

        return {"text": text, "metadata": metadata}

    # ------------------------------------------------------------------
    # Internal — language detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_language(text: str) -> str:
        """Simple CJK heuristic — checks first 1000 characters."""
        for char in text[:1000]:
            # "Lo" = Letter, Other (includes CJK ideographs)
            if unicodedata.category(char) == "Lo":
                return "zh"
        return "en"

    # ------------------------------------------------------------------
    # Internal — parser dispatch
    # ------------------------------------------------------------------

    def _get_parser(
        self, file_type: str
    ) -> Any:
        parsers: dict[str, Any] = {
            "pdf": self._parse_pdf,
            "docx": self._parse_docx,
            "xlsx": self._parse_excel,
            "xls": self._parse_excel,
            "pptx": self._parse_pptx,
            "txt": self._parse_text,
            "md": self._parse_text,
            "csv": self._parse_csv,
            # Code files — all parsed as plain text
            "py": self._parse_text,
            "js": self._parse_text,
            "ts": self._parse_text,
            "java": self._parse_text,
            "c": self._parse_text,
            "cpp": self._parse_text,
            "h": self._parse_text,
            "hpp": self._parse_text,
            "go": self._parse_text,
            "rs": self._parse_text,
            "rb": self._parse_text,
            "php": self._parse_text,
            "swift": self._parse_text,
            "kt": self._parse_text,
        }
        parser = parsers.get(file_type)
        if parser is None:
            raise BadRequestException(
                f"Unsupported file type: {file_type}"
            )
        return parser

    # ------------------------------------------------------------------
    # Per-format parsers
    # ------------------------------------------------------------------

    def _parse_pdf(self, path: Path) -> dict[str, Any]:
        """Extract text from PDF — PyPDFLoader with manual fallback."""
        # Attempt 1: LangChain PyPDFLoader
        try:
            from langchain_community.document_loaders import PyPDFLoader

            loader = PyPDFLoader(str(path))
            docs = loader.load()
            text = "\n".join(d.page_content for d in docs)
            return {"text": text, "page_count": len(docs)}
        except Exception as exc:
            err_msg = str(exc).lower()
            if "password" in err_msg or "encrypt" in err_msg:
                raise BadRequestException(
                    "Document is encrypted or password protected"
                ) from exc

        # Attempt 2: manual pypdf fallback
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise BadRequestException(
                    "Document is encrypted or password protected"
                )
            pages = [page.extract_text() for page in reader.pages]
            text = "\n".join(pages)
            return {"text": text, "page_count": len(reader.pages)}
        except BadRequestException:
            raise
        except Exception as exc:
            raise BadRequestException(
                f"Failed to parse PDF: {exc}"
            ) from exc

    def _parse_docx(self, path: Path) -> dict[str, Any]:
        """Extract text from DOCX via Docx2txtLoader with fallback."""
        try:
            from langchain_community.document_loaders import Docx2txtLoader

            loader = Docx2txtLoader(str(path))
            docs = loader.load()
            text = docs[0].page_content if docs else ""
            return {"text": text, "page_count": 0}
        except Exception:
            # Fallback: direct docx2txt
            try:
                import docx2txt

                text = docx2txt.process(str(path))
                return {"text": text, "page_count": 0}
            except Exception as exc:
                err_msg = str(exc).lower()
                if "password" in err_msg or "encrypt" in err_msg:
                    raise BadRequestException(
                        "Document is encrypted or password protected"
                    ) from exc
                raise BadRequestException(
                    f"Failed to parse DOCX: {exc}"
                ) from exc

    def _parse_excel(self, path: Path) -> dict[str, Any]:
        """Extract text from Excel files via pandas read_excel."""
        try:
            import pandas as pd

            dfs = pd.read_excel(str(path), sheet_name=None)
        except Exception as exc:
            raise BadRequestException(
                f"Failed to parse Excel file: {exc}"
            ) from exc

        text_parts: list[str] = []
        for sheet_name, df in dfs.items():
            text_parts.append(f"=== Sheet: {sheet_name} ===")
            text_parts.append(df.to_string(index=False))
        text = "\n".join(text_parts)
        return {"text": text, "page_count": 0}

    def _parse_pptx(self, path: Path) -> dict[str, Any]:
        """Extract text from PPTX via python-pptx."""
        try:
            from pptx import Presentation

            prs = Presentation(str(path))
        except Exception as exc:
            raise BadRequestException(
                f"Failed to parse PPTX: {exc}"
            ) from exc

        text_parts: list[str] = []
        for slide in prs.slides:
            slide_text: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    slide_text.append(shape.text_frame.text or "")
            text_parts.append("\n".join(slide_text))
        text = "\n".join(text_parts)
        return {"text": text, "page_count": len(prs.slides)}

    def _parse_text(self, path: Path) -> dict[str, Any]:
        """Read plain-text / markdown files via UTF-8."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return {"text": text, "page_count": 0}
        except Exception as exc:
            raise BadRequestException(
                f"Failed to read text file: {exc}"
            ) from exc

    def _parse_csv(self, path: Path) -> dict[str, Any]:
        """Extract text from CSV via pandas read_csv."""
        try:
            import pandas as pd

            df = pd.read_csv(str(path))
            text = df.to_string(index=False)
            return {"text": text, "page_count": 0}
        except Exception as exc:
            raise BadRequestException(
                f"Failed to parse CSV: {exc}"
            ) from exc
