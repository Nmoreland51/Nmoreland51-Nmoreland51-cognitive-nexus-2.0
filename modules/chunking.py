"""Split documents into passages for search.

The old splitter cut every 750 words, joined the words with single spaces (destroying code and
tables) and gave two passages the same id when they began with the same 100 characters. Passages
that long are also more than a small embedding model reads (all-minilm reads 256 tokens) and more
than a CPU-bound chat prompt can afford.

This one keeps the document's own structure: it splits at headings, paragraphs and code blocks,
keeps line breaks, packs neighbouring pieces up to a target size, and records the heading each
passage sits under so a passage still says what it is about when read alone.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

DEFAULT_TARGET_WORDS = 160
DEFAULT_OVERLAP_WORDS = 25
CODE_TARGET_LINES = 40

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(```|~~~)")
_CODE_START = re.compile(r"^\s*(?:def |class |async def |function |export |public |private |protected |static |func |fn |impl |interface |struct |enum |@|#include|package |module )")


@dataclass
class Chunk:
    text: str
    heading: str = ""
    position: int = 0
    start_line: int = 0

    def to_dict(self) -> dict[str, Any]:
        words = len(self.text.split())
        return {
            "text": self.text,
            "heading": self.heading,
            "chunk_index": self.position,
            "start_line": self.start_line,
            "word_count": words,
            "chunk_id": chunk_id(self.text, self.position),
        }


def chunk_id(text: str, position: int) -> str:
    """Id from the whole passage and its place in the document, so two passages never collide."""

    return hashlib.sha1(f"{position}\n{text}".encode("utf-8")).hexdigest()[:16]


def _words(text: str) -> int:
    return len(text.split())


def _split_long(block: str, target: int, overlap: int) -> list[str]:
    """Split one oversized paragraph at sentence ends, then by words, with a little overlap."""

    sentences = re.split(r"(?<=[.!?])\s+", block)
    pieces: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        size = _words(sentence)
        if size > target:
            if current:
                pieces.append(" ".join(current))
                current, count = [], 0
            words = sentence.split()
            step = max(1, target - overlap)
            for start in range(0, len(words), step):
                pieces.append(" ".join(words[start : start + target]))
                if start + target >= len(words):
                    break
            continue
        if count + size > target and current:
            pieces.append(" ".join(current))
            tail = " ".join(current).split()[-overlap:] if overlap else []
            current, count = ([" ".join(tail)] if tail else []), len(tail)
        current.append(sentence)
        count += size
    if current:
        pieces.append(" ".join(current))
    return [piece for piece in pieces if piece.strip()]


def _blocks(text: str) -> list[tuple[str, str, int, bool]]:
    """(block text, heading it sits under, first line number, is code) for each paragraph-like block."""

    blocks: list[tuple[str, str, int, bool]] = []
    heading = ""
    current: list[str] = []
    start = 1
    in_fence = False

    def flush(is_code: bool = False) -> None:
        nonlocal current
        body = "\n".join(current).strip("\n")
        if body.strip():
            blocks.append((body, heading, start, is_code))
        current = []

    for number, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line.strip()):
            if in_fence:
                current.append(line)
                flush(is_code=True)
                in_fence = False
            else:
                flush()
                start = number
                current.append(line)
                in_fence = True
            continue
        if in_fence:
            current.append(line)
            continue
        match = _HEADING.match(line)
        if match:
            flush()
            heading = match.group(2).strip()
            start = number
            current.append(line)
            flush()
            continue
        if not line.strip():
            flush()
            continue
        if not current:
            start = number
        current.append(line)
    flush(is_code=in_fence)
    return blocks


def chunk_text(text: str, *, target_words: int = DEFAULT_TARGET_WORDS, overlap_words: int = DEFAULT_OVERLAP_WORDS) -> list[Chunk]:
    """Passages of about `target_words` words that follow the document's headings and paragraphs."""

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []
    chunks: list[Chunk] = []
    parts: list[str] = []
    size = 0
    part_heading = ""
    part_start = 1

    def emit() -> None:
        nonlocal parts, size
        body = "\n\n".join(parts).strip()
        if body:
            chunks.append(Chunk(text=body, heading=part_heading, position=len(chunks), start_line=part_start))
        parts, size = [], 0

    for block, heading, start, is_code in _blocks(text):
        words = _words(block)
        if heading != part_heading and parts:
            emit()
        if not parts:
            part_heading, part_start = heading, start
        if words > target_words * 1.5 and not is_code:
            emit()
            for piece in _split_long(block, target_words, overlap_words):
                chunks.append(Chunk(text=piece, heading=heading, position=len(chunks), start_line=start))
            continue
        if words > target_words * 1.5 and is_code:
            emit()
            for piece, line in _split_code(block, start):
                chunks.append(Chunk(text=piece, heading=heading, position=len(chunks), start_line=line))
            continue
        if size + words > target_words and parts:
            emit()
            part_heading, part_start = heading, start
        parts.append(block)
        size += words
    emit()
    return chunks


def _split_code(code: str, first_line: int = 1, target_lines: int = CODE_TARGET_LINES) -> list[tuple[str, int]]:
    """Split source code at top-level definitions and blank lines, never in the middle of a line."""

    lines = code.split("\n")
    pieces: list[tuple[str, int]] = []
    current: list[str] = []
    start = first_line

    def close(next_start: int) -> None:
        nonlocal current, start
        body = "\n".join(current).rstrip()
        if body.strip():
            pieces.append((body, start))
        current, start = [], next_start

    for offset, line in enumerate(lines):
        number = first_line + offset
        blank = not line.strip()
        new_definition = bool(_CODE_START.match(line)) and not line.startswith((" ", "\t"))
        if current and blank and len(current) >= target_lines:
            close(number + 1)  # a blank line after a full piece: it separates, it belongs to neither
            continue
        if current and (len(current) >= target_lines * 2 or (new_definition and len(current) >= target_lines // 2)):
            close(number)
        if not current and blank:
            start = number + 1  # do not begin a piece with empty lines
            continue
        current.append(line)
    close(0)
    return pieces


def chunk_code(code: str, *, language: str = "") -> list[Chunk]:
    """Passages for a source file: whole definitions where possible, with their line numbers."""

    code = (code or "").replace("\r\n", "\n").replace("\r", "\n")
    label = f"{language} source" if language else "source code"
    return [
        Chunk(text=piece, heading=f"{label}, from line {line}", position=index, start_line=line)
        for index, (piece, line) in enumerate(_split_code(code))
    ]
