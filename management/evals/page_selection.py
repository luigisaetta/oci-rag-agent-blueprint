"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: Significant PDF page scoring and selection helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MIN_USEFUL_WORDS = 45
BOILERPLATE_TERMS = (
    "table of contents",
    "contents",
    "index",
    "copyright",
    "all rights reserved",
    "revision history",
    "document history",
)


@dataclass(frozen=True)
class PdfPageText:
    """Extracted text for one PDF page.

    Attributes:
        page_number: One-based PDF page number.
        text: Extracted page text.
    """

    page_number: int
    text: str


@dataclass(frozen=True)
class ScoredPage:
    """A PDF page with a significance score.

    Attributes:
        page: Source page.
        score: Heuristic significance score.
    """

    page: PdfPageText
    score: float


def normalize_page_text(text: str) -> str:
    """Normalize extracted PDF page text.

    Args:
        text: Raw extracted page text.

    Returns:
        str: Whitespace-normalized text.
    """

    return " ".join(text.split())


def score_page(page: PdfPageText) -> float:
    """Score a page for usefulness as a golden dataset source.

    Args:
        page: Page text to score.

    Returns:
        float: Higher scores indicate more useful standalone content.
    """

    text = normalize_page_text(page.text)
    if not text:
        return 0.0

    lower_text = text.lower()
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text)
    word_count = len(words)
    sentence_count = len(re.findall(r"[.!?](?:\s|$)", text))
    unique_word_count = len({word.lower() for word in words})
    numeric_tokens = len(re.findall(r"\b\d+(?:[.,]\d+)?\b", text))

    score = min(word_count / 20, 30)
    score += min(sentence_count * 2, 20)
    score += min(unique_word_count / 10, 20)

    if word_count < MIN_USEFUL_WORDS:
        score -= 12
    if sentence_count < 3:
        score -= 15
    if numeric_tokens > max(20, word_count // 3):
        score -= 20
    if any(term in lower_text for term in BOILERPLATE_TERMS):
        score -= 40
    if _looks_like_isolated_list(text):
        score -= 15

    return max(score, 0.0)


def select_significant_pages(
    pages: list[PdfPageText],
    max_pages: int = 10,
) -> list[ScoredPage]:
    """Select the most significant pages from a PDF.

    Args:
        pages: Extracted page texts.
        max_pages: Maximum number of pages to select.

    Returns:
        list[ScoredPage]: Selected pages ordered by source page number.
    """

    if max_pages < 1:
        raise ValueError("max_pages must be greater than zero.")

    scored_pages = [
        ScoredPage(page=page, score=score_page(page))
        for page in pages
        if normalize_page_text(page.text)
    ]
    useful_pages = [
        scored_page for scored_page in scored_pages if scored_page.score > 0
    ]
    selected = sorted(
        useful_pages,
        key=lambda scored_page: (-scored_page.score, scored_page.page.page_number),
    )[:max_pages]
    return sorted(selected, key=lambda scored_page: scored_page.page.page_number)


def _looks_like_isolated_list(text: str) -> bool:
    """Return whether page text is dominated by short list-like lines.

    Args:
        text: Raw page text.

    Returns:
        bool: True when the page appears to be mostly isolated list entries.
    """

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 8:
        return False
    short_lines = [line for line in lines if len(line.split()) <= 5]
    return len(short_lines) / len(lines) > 0.7
