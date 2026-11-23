"""Estimate how many tokens a text is, without the model's tokenizer.

Ollama has no "count tokens" call, and the old rule of thumb (characters / 4) is badly wrong for
anything but plain English: measured on the local model (dolphin3:8b, 2026-11-23) one token was
6.1 characters of English prose, 3.6 of Python, 2.4 of JSON, 1.6 of numeric data and 1.2 of
Chinese. A prompt that "fits" by the old rule can be twice the model's window, and Ollama then
silently drops its beginning.

This estimator counts the pieces a tokenizer splits text into: words, long-word fragments,
digits, punctuation, line breaks, and characters of other scripts. Its coefficients were fitted
to real token counts from the model (tests/fixtures/token_counts.json, 18 kinds of text) and are
checked against them in tests. It leans slightly high, because an over-estimate only leaves some
of the window unused while an under-estimate loses part of the prompt.

The router also compares every real request against the estimate (see ProviderRouter) so that a
model with a very different tokenizer shows up as a recorded mismatch instead of going unnoticed.
"""

from __future__ import annotations

import re

_LATIN_WORD = re.compile(r"[A-Za-z\u00c0-\u024f]+")
_ASCII_ONLY = re.compile(r"^[A-Za-z]+$")
# Alphabets other than Latin whose words are written with spaces (Cyrillic, Greek, Hebrew, Arabic...).
_OTHER_ALPHABET_WORD = re.compile(r"[\u0370-\u05ff\u0600-\u06ff\u0900-\u0dff]+")
_CJK = re.compile(r"[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff66-\uff9f]")

WORD = 0.9  # an ordinary English word is usually one token
LONG_WORD_PART = 0.6  # each further ~6 letters adds a fragment
DIGIT = 0.75
PUNCTUATION = 0.8
LINE_BREAK = 0.6
FOREIGN_LETTERS_PER_TOKEN = 3.2  # Latin-script languages with diacritics (German, Spanish, French)
OTHER_ALPHABET_LETTERS_PER_TOKEN = 3.0  # measured 3.7 for Russian
CJK_CHARACTER = 1.0  # measured 0.74 to 0.87 tokens per character
SYMBOL = 2.5  # emoji and other symbols; measured about 2.1
# Share of words with diacritics above which the text is treated as a non-English language.
FOREIGN_SHARE = 0.02


def estimate_tokens(text: str) -> int:
    """Estimated token count of `text` for a llama-family model. Never less than 1."""

    text = text or ""
    if not text:
        return 1
    latin_words = _LATIN_WORD.findall(text)
    accented = [word for word in latin_words if not _ASCII_ONLY.match(word)]
    total = 0.0
    if latin_words and len(accented) / len(latin_words) >= FOREIGN_SHARE:
        # Not English: words are rarer in the vocabulary and split into more fragments.
        total += sum(max(1.0, len(word) / FOREIGN_LETTERS_PER_TOKEN) for word in latin_words)
    else:
        total += WORD * len(latin_words) + LONG_WORD_PART * sum(max(0, (len(word) - 1) // 6) for word in latin_words)

    other_words = _OTHER_ALPHABET_WORD.findall(text)
    total += sum(max(1.0, len(word) / OTHER_ALPHABET_LETTERS_PER_TOKEN) for word in other_words)

    cjk = len(_CJK.findall(text))
    total += CJK_CHARACTER * cjk

    digits = punctuation = non_ascii = 0
    for character in text:
        code = ord(character)
        if code < 128:
            if character.isdigit():
                digits += 1
            elif not character.isalnum() and not character.isspace():
                punctuation += 1
        else:
            non_ascii += 1
    counted_elsewhere = sum(len(word) for word in accented) - sum(1 for word in accented for ch in word if ord(ch) < 128)
    symbols = non_ascii - counted_elsewhere - sum(len(word) for word in other_words) - cjk
    total += DIGIT * digits + PUNCTUATION * punctuation + LINE_BREAK * text.count("\n") + SYMBOL * max(symbols, 0)
    return max(1, int(total + 0.999))


def characters_for_tokens(text: str, tokens: int) -> int:
    """About how many leading characters of `text` fit in `tokens`, using the text's own density."""

    if tokens <= 0 or not text:
        return 0
    estimated = estimate_tokens(text)
    if estimated <= tokens:
        return len(text)
    return max(0, int(len(text) * tokens / estimated))
