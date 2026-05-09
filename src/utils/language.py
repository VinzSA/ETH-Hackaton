"""
Language detection and translation.
Detects language with langdetect, translates non-English text via Helsinki-NLP/opus-mt.
Supports de, fr, it → en (the three non-English languages in Swiss clinical practice).
"""
from __future__ import annotations

import threading
from functools import lru_cache

_model_lock = threading.Lock()
_translators: dict[str, object] = {}  # lang_code → pipeline

SUPPORTED_LANGS = {"de", "fr", "it"}  # languages we can translate
TRANSLATE_CHUNK = 512                  # max tokens per Helsinki-NLP chunk


def detect_language(text: str) -> str:
    """
    Return ISO 639-1 language code (e.g. 'en', 'de', 'fr', 'it').
    Falls back to 'en' on any error.
    """
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 42  # deterministic
        return detect(text[:2000])
    except Exception:
        return "en"


def translate_to_english(text: str, source_lang: str) -> str:
    """
    Translate `text` from `source_lang` to English using Helsinki-NLP opus-mt.
    Downloads the model on first call (~300MB per language, cached by HuggingFace).
    Returns original text unchanged if language is unsupported or translation fails.
    """
    if source_lang not in SUPPORTED_LANGS:
        return text

    try:
        pipeline = _get_translator(source_lang)
        # Split into chunks to respect model token limits
        chunks = _split_text(text, TRANSLATE_CHUNK)
        translated_chunks = [pipeline(chunk)[0]["translation_text"] for chunk in chunks]
        return " ".join(translated_chunks)
    except Exception:
        return text  # degrade gracefully — extract from original rather than crash


def detect_and_translate(text: str) -> tuple[str, str]:
    """
    Detect language and translate to English if needed.
    Returns (translated_text, detected_language_code).
    """
    lang = detect_language(text)
    if lang == "en" or lang not in SUPPORTED_LANGS:
        return text, lang
    translated = translate_to_english(text, lang)
    return translated, lang


@lru_cache(maxsize=3)
def _get_translator(source_lang: str):
    """Load (and cache) the Helsinki-NLP pipeline for a given source language."""
    from transformers import pipeline as hf_pipeline

    model_name = f"Helsinki-NLP/opus-mt-{source_lang}-en"
    with _model_lock:
        if source_lang not in _translators:
            _translators[source_lang] = hf_pipeline(
                "translation",
                model=model_name,
                device=-1,  # CPU
            )
    return _translators[source_lang]


def _split_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks, current = [], []
    current_len = 0

    for sentence in text.replace("\n", " ").split(". "):
        sentence = sentence.strip()
        if not sentence:
            continue
        if current_len + len(sentence) > max_chars and current:
            chunks.append(". ".join(current) + ".")
            current, current_len = [], 0
        current.append(sentence)
        current_len += len(sentence) + 2

    if current:
        chunks.append(". ".join(current))

    return chunks or [text]
