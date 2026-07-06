"""Document chunking service — splits document text into overlapping chunks.

Provides type-aware chunking strategies:

- **markdown** (``md``): Split by Markdown headings (``#`` … ``######``).
- **code** (``py``, ``js``, ``ts``, ``java``, ``go``, ``rs``, …): Split by
  top-level function / class / method definitions.
- **pdf**: Split by paragraph breaks (double newlines).
- **generic** (all other types): ``RecursiveCharacterTextSplitter`` with
  sensible defaults.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.exceptions import BadRequestException

# Language-agnostic function/class definition regex patterns.
# Each pattern captures boundaries that should start a new chunk.
_CODE_BOUNDARIES: list[tuple[str, str]] = [
    # Python / Ruby
    (r"^(def |class |@\w+|async def )", "py"),
    # JavaScript / TypeScript
    (r"^(function |class |const |let |var |async function |export )", "js"),
    # Java / C / C++ / C# / Go / Rust / PHP / Swift / Kotlin
    (r"^(public |private |protected |static |func |fn |fun )", "java"),
    (r"^(int |void |String |bool |float |double |char )", "c"),
    (r"^(impl |trait |enum |struct |fn )", "rs"),
    (r"^(func |type |struct )", "go"),
    # Fallback: any line that looks like a declaration
    (r"^\s*(def|function|class|struct|trait|impl|enum|fn|func|fun"
     r"|sub|procedure)\s", "generic"),
]

# Markdown heading pattern
_MD_HEADING = re.compile(r"^#{1,6}\s+\S")

# Paragraph separator (double newline)
_PARA_SEP = re.compile(r"\n\s*\n")


class DocumentChunker:
    """Split document text into chunks using a type-aware strategy.

    Usage::

        chunker = DocumentChunker(chunk_size=512, chunk_overlap=128)
        chunks = chunker.chunk_document(text, file_type="md")
    """

    # ── Document-category constants ──────────────────────────────────────
    CAT_MARKDOWN = "markdown"
    CAT_CODE = "code"
    CAT_PDF = "pdf"
    CAT_GENERIC = "generic"

    # File-type → category mapping
    TYPE_CATEGORY: dict[str, str] = {
        "md": CAT_MARKDOWN,
        "pdf": CAT_PDF,
        # Code
        "py": CAT_CODE,
        "js": CAT_CODE,
        "ts": CAT_CODE,
        "java": CAT_CODE,
        "c": CAT_CODE,
        "cpp": CAT_CODE,
        "h": CAT_CODE,
        "hpp": CAT_CODE,
        "go": CAT_CODE,
        "rs": CAT_CODE,
        "rb": CAT_CODE,
        "php": CAT_CODE,
        "swift": CAT_CODE,
        "kt": CAT_CODE,
    }
    # All others (docx, xlsx, xls, pptx, txt, csv, …) → CAT_GENERIC

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 128) -> None:
        """Initialize chunker with size and overlap parameters.

        Args:
            chunk_size: Maximum number of characters per chunk (default 512).
            chunk_overlap: Number of overlapping characters between
                consecutive chunks (default 128).
        """
        if chunk_size <= 0:
            raise BadRequestException("chunk_size must be positive")  # noqa: TRY003
        if chunk_overlap < 0:
            raise BadRequestException("chunk_overlap must be non-negative")  # noqa: TRY003
        if chunk_overlap >= chunk_size:
            raise BadRequestException(  # noqa: TRY003
                "chunk_overlap must be less than chunk_size"
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_document(
        self,
        text: str,
        file_type: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Split document text into chunks based on *file_type*.

        Args:
            text: The full document plain text to split.
            file_type: File extension without leading dot
                (e.g. ``"md"``, ``"py"``, ``"pdf"``).  Determines the
                chunking strategy.
            metadata: Optional base metadata dict. Each chunk will
                include a copy enriched with ``chunk_index``.

        Returns:
            A list of chunk dicts, each with the keys:

            - ``content`` (str): The chunk text.
            - ``metadata`` (dict): Base metadata + ``chunk_index`` +
              ``chunk_strategy``.
            - ``chunk_index`` (int): The zero-based chunk position.

            Returns an empty list when ``text`` is empty or blank.
        """
        if not text or not text.strip():
            return []

        category = self.TYPE_CATEGORY.get(file_type, self.CAT_GENERIC)

        if category == self.CAT_MARKDOWN:
            raw_chunks = self._chunk_markdown(text)
        elif category == self.CAT_CODE:
            raw_chunks = self._chunk_code(text)
        elif category == self.CAT_PDF:
            raw_chunks = self._chunk_paragraphs(text)
        else:
            raw_chunks = self._chunk_generic(text)

        # ── Post-process: apply size constraints ─────────────────────
        # If any strategy produced chunks larger than chunk_size, split
        # them further with the generic splitter.
        final_chunks: list[str] = []
        for chunk_text in raw_chunks:
            if len(chunk_text) > self.chunk_size:
                sub = self._split_with_overlap(chunk_text)
                final_chunks.extend(sub)
            else:
                final_chunks.append(chunk_text)

        base_metadata = metadata or {}
        result: list[dict[str, Any]] = []
        for i, chunk_text in enumerate(final_chunks):
            chunk_meta = {
                **base_metadata,
                "chunk_index": i,
                "chunk_strategy": category,
            }
            result.append(
                {
                    "content": chunk_text,
                    "metadata": chunk_meta,
                    "chunk_index": i,
                }
            )

        return result

    # ------------------------------------------------------------------
    # Strategy: Markdown — split by headings
    # ------------------------------------------------------------------

    def _chunk_markdown(self, text: str) -> list[str]:
        """Split Markdown text at heading boundaries (``#`` … ``######``).

        Lines that match one or more ``#`` followed by a space start a
        new chunk.  Introductory text before the first heading is kept
        as its own chunk.
        """
        lines = text.split("\n")
        chunks: list[str] = []
        current: list[str] = []

        for line in lines:
            if _MD_HEADING.match(line) and current:
                chunks.append("\n".join(current))
                current = [line]
            else:
                current.append(line)

        if current:
            chunks.append("\n".join(current))

        return chunks if chunks else [text]

    # ------------------------------------------------------------------
    # Strategy: Code — split by function/class definitions
    # ------------------------------------------------------------------

    def _chunk_code(self, text: str) -> list[str]:
        """Split code text at top-level definition boundaries.

        Uses a set of regex patterns to detect lines that begin a new
        function, class, or method definition.  Docstrings and
        decorators are kept with the definition they belong to.
        """
        lines = text.split("\n")
        chunks: list[str] = []
        current: list[str] = []

        for line in lines:
            if self._is_code_boundary(line) and current:
                chunks.append("\n".join(current))
                current = [line]
            else:
                current.append(line)

        if current:
            chunks.append("\n".join(current))

        return chunks if chunks else [text]

    @staticmethod
    def _is_code_boundary(line: str) -> bool:
        """Return ``True`` if *line* starts a new code definition block."""
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*", '"', "'")):
            return False
        return any(
            re.match(pattern, stripped) for pattern, _lang in _CODE_BOUNDARIES
        )

    # ------------------------------------------------------------------
    # Strategy: PDF / paragraph — split by double newlines
    # ------------------------------------------------------------------

    def _chunk_paragraphs(self, text: str) -> list[str]:
        """Split text at paragraph breaks (two or more consecutive newlines).

        Each paragraph becomes a chunk.  Empty paragraphs are discarded.
        """
        raw = _PARA_SEP.split(text)
        return [p.strip() for p in raw if p.strip()]

    # ------------------------------------------------------------------
    # Strategy: Generic — RecursiveCharacterTextSplitter
    # ------------------------------------------------------------------

    def _chunk_generic(self, text: str) -> list[str]:
        """Split text with the generic RecursiveCharacterTextSplitter."""
        splitter = self._build_splitter()
        return splitter.split_text(text)

    def _build_splitter(self) -> Any:
        """Build a ``RecursiveCharacterTextSplitter`` instance."""
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            from langchain.text_splitter import (  # type: ignore[no-redef]
                RecursiveCharacterTextSplitter,
            )

        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            length_function=len,
        )

    # ------------------------------------------------------------------
    # Over-size fallback
    # ------------------------------------------------------------------

    def _split_with_overlap(self, text: str) -> list[str]:
        """Split a single oversized text with RecursiveCharacterTextSplitter."""
        splitter = self._build_splitter()
        return splitter.split_text(text)
