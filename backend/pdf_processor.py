"""PDF text extraction logic with local OCR.

Uses RapidOCR as the primary local OCR path and falls back to Tesseract
when the ONNX runtime engine is unavailable or fails.
"""
import base64
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
import fitz  # PyMuPDF
import httpx

logger = logging.getLogger(__name__)

_OCR_NOT_CONFIGURED_WARNING_SHOWN = False
_rapidocr_engine = None
_rapidocr_available = False
_tesseract_ready = False
_pytesseract_module = None
MAX_OCR_IMAGE_SIZE = 1400
MAX_PARALLEL_OCR_WORKERS = 3
REUSE_TEXT_SIMILARITY_THRESHOLD = float(os.environ.get("OCR_REUSE_TEXT_THRESHOLD", "0.74"))
FAST_OCR_WORD_THRESHOLD = int(os.environ.get("OCR_FAST_WORD_THRESHOLD", "8"))
VISUAL_SIGNATURE_DPI = int(os.environ.get("OCR_VISUAL_SIGNATURE_DPI", "48"))
VISUAL_SIGNATURE_GRID = int(os.environ.get("OCR_VISUAL_SIGNATURE_GRID", "16"))
VISUAL_REUSE_SIMILARITY_THRESHOLD = float(os.environ.get("OCR_VISUAL_REUSE_THRESHOLD", "0.96"))
_timing_lock = threading.Lock()
_ocr_context = threading.local()


def _is_image_ocr_mode() -> bool:
    return bool(getattr(_ocr_context, "image_mode", False))

# Probe RapidOCR availability once to avoid expensive per-page attempts.
try:
    import importlib

    _rapidocr_spec = importlib.util.find_spec("rapidocr")
    if _rapidocr_spec is not None:
        _rapidocr_available = True
    else:
        _rapidocr_available = False
except Exception:
    _rapidocr_available = False


def _init_tesseract_once() -> bool:
    """Initialize pytesseract and configure tesseract binary once.

    Returns True if tesseract is available and configured, False otherwise.
    """
    global _tesseract_ready, _pytesseract_module
    if _tesseract_ready:
        return True
    try:
        import pytesseract

        _pytesseract_module = pytesseract
    except Exception as exc:
        logger.warning("pytesseract import failed: %s", exc)
        return False

    tesseract_cmd = _find_tesseract_binary()
    if not tesseract_cmd:
        _warn_no_ocr_backend()
        return False

    try:
        try:
            _pytesseract_module.pytesseract.tesseract_cmd = tesseract_cmd
        except Exception:
            _pytesseract_module.tesseract_cmd = tesseract_cmd
    except Exception:
        # Not fatal; continue but mark not ready
        logger.debug("Failed to set tesseract_cmd on pytesseract module")
    _tesseract_ready = True
    return True

MUSIC_SYMBOL_RE = re.compile(r"[\u0000-\u001F\u007F]+")
APOSTROPHE_RE = re.compile(r"[’‘`]")
DECORATIVE_NUMBER_RE = re.compile(r"~\s*\d+\s*~")


def clean_pdf_text(text: str) -> str:
    """Keep readable words and numbers, remove chords, notation symbols and glued artifacts."""
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\u00a0", " ")
    text = text.replace("\r", " ").replace("\n", " ")
    text = APOSTROPHE_RE.sub("'", text)
    text = DECORATIVE_NUMBER_RE.sub(" ", text)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))

    # Remove music notation, note/chord tokens and OCR noise.
    text = re.sub(r"[\u0000-\u001F\u007F]", " ", text)
    text = re.sub(r"[œŒ˙…]+", " ", text)
    text = re.sub(r"\b(?:DO|RE|MI|FA|SOL|LA|SI)(?:[#b]|[-/][A-Z0-9#b]+|\d+|maj|min|m|dim|aug|sus|add|7|9|11|13)*\b", " ", text)
    text = re.sub(r"(?<![A-Za-zÀ-ÿ])(?:[A-G](?:#|b)?(?:maj|min|m|dim|aug|sus|add)?\d*(?:/[A-G](?:#|b)?\d*)?)(?![A-Za-zÀ-ÿ])", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=[A-Za-zÀ-ÿ])\s*[-–—]\s*(?=[A-Za-zÀ-ÿ])", "", text)
    text = re.sub(r"[^A-Za-z0-9À-ÿ\s']+", " ", text, flags=re.UNICODE)

    # Split likely OCR-glued words such as "GesùCristo" or words broken across lines.
    text = re.sub(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Ý][a-zà-ÿ])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _content_signature_terms(text: str) -> List[str]:
    """Build a compact token-shingle fingerprint for similarity comparisons."""
    if not text:
        return []

    normalized = normalize_pdf_text(text)
    if not normalized:
        return []

    tokens = _tokenize_text(normalized)
    if not tokens:
        return []

    if len(tokens) <= 2:
        return tokens[:]

    terms: List[str] = []
    seen = set()
    for window_size in (4, 3, 2, 1):
        if len(tokens) < window_size:
            continue
        for start in range(0, len(tokens) - window_size + 1):
            term = " ".join(tokens[start : start + window_size])
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 48:
                return terms
    return terms


def build_content_signature(text: str) -> str:
    """Create a lightweight normalized signature for content-based similarity checks."""
    terms = _content_signature_terms(text)
    return " || ".join(terms)


def _content_signature_similarity(signature_a: str, signature_b: str) -> float:
    if not signature_a or not signature_b:
        return 0.0

    terms_a = [term for term in signature_a.split(" || ") if term]
    terms_b = [term for term in signature_b.split(" || ") if term]
    if not terms_a or not terms_b:
        return 0.0

    set_a = set(terms_a)
    set_b = set(terms_b)
    if not set_a or not set_b:
        return 0.0

    overlap = len(set_a & set_b)
    containment = overlap / max(1, min(len(set_a), len(set_b)))
    jaccard = overlap / max(1, len(set_a | set_b))
    order_ratio = SequenceMatcher(None, signature_a, signature_b).ratio()
    return max(0.0, min(1.0, 0.55 * containment + 0.25 * jaccard + 0.20 * order_ratio))


def normalize_pdf_text(text: str) -> str:
    if not text:
        return ""

    # Normalize line breaks and underscores/hyphens into spaces to avoid spurious joins
    text = text.replace("\r", " ").replace("\n", " ").replace("_", " ")
    text = unicodedata.normalize("NFKD", text)
    # strip combining diacritics (é -> e) for matching
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = APOSTROPHE_RE.sub("'", text)
    # normalize spaces around apostrophes and hyphens
    text = re.sub(r"\s*'\s*", "'", text)
    text = re.sub(r"[-–—]+", " ", text)
    # Remove characters that are not letters/numbers/spaces/apostrophe
    text = re.sub(r"[^A-Za-z0-9\s']+", " ", text, flags=re.UNICODE)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    replacements = {
        r"\bGesu\b": "Gesù",
        r"\bGest\b": "Gesù",
        r"\bDio\b": "Dio",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text


def build_apostrophe_tolerant_regex(text: str) -> str:
    """Build a regex pattern treating spaces and apostrophes between parts as equivalent.

    Example: "dall' amore", "dall'amore", "dall amore", "dallamore" all match.
    """
    if not text:
        return ""
    text = APOSTROPHE_RE.sub("'", text)
    parts = [p for p in re.split(r"[\s']+", text) if p]
    if not parts:
        return re.escape(text)
    pattern = re.escape(parts[0])
    for p in parts[1:]:
        pattern += r"(?:\s*[\'’]\s*|\s*)" + re.escape(p)
    return pattern


def normalize_search_query(text: str) -> str:
    """Normalize a search query to be tolerant of user input errors."""
    if not text:
        return ""

    text = str(text).strip()
    if not text:
        return ""

    text = APOSTROPHE_RE.sub("'", text)
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = text.replace("\r", " ").replace("\n", " ").replace("_", " ")
    text = re.sub(r"\s*'\s*", "'", text)
    text = re.sub(r"[-–—]+", " ", text)
    text = re.sub(r"[^A-Za-z0-9À-ÿ\s']+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def _tokenize_text(text: str) -> List[str]:
    """Tokenize text into words, agnostic to apostrophes and punctuation.
    Also handles single letters followed by spaces (like "d amore" from "d'amore").
    Example:
    - "l'anima" → ["lanima"]
    - "d'amore" → ["damore"]
    - "d amore" → ["damore"]  (from "d'amore" after splitting)
    - "Padre," → ["padre"]
    - "sei." → ["sei"]
    """
    if not text:
        return []
    
    # Normalize unicode and lowercase
    text = unicodedata.normalize("NFKD", text)
    text = APOSTROPHE_RE.sub("'", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)  # strip accents
    text = text.lower()

    # Remove apostrophes and all punctuation except spaces
    text = re.sub(r"['\"`´]", "", text)  # remove apostrophes
    text = re.sub(r"[^a-z0-9\s]", " ", text)  # remove other punctuation
    
    # Merge single letters followed by spaces with next word (for "d amore" → "damore")
    # Accept multi-letter following word to handle cases like "d amore" or "l amore"
    text = re.sub(r"\b([a-z])\s+([a-z]+)", r"\1\2", text)
    
    # Split on whitespace and filter empty
    tokens = [t.strip() for t in text.split() if t.strip()]
    return tokens


def _estimate_text_similarity(text_a: str, text_b: str) -> float:
    """Estimate a similarity score in the [0, 1] range using string and token signals."""
    if not text_a or not text_b:
        return 0.0

    normalized_a = normalize_search_query(text_a)
    normalized_b = normalize_search_query(text_b)
    if not normalized_a or not normalized_b:
        return 0.0
    if normalized_a == normalized_b:
        return 1.0
    if normalized_a in normalized_b or normalized_b in normalized_a:
        return 0.98

    tokens_a = _tokenize_text(normalized_a)
    tokens_b = _tokenize_text(normalized_b)
    if not tokens_a or not tokens_b:
        return SequenceMatcher(None, normalized_a, normalized_b).ratio()

    set_overlap = len(set(tokens_a) & set(tokens_b)) / max(1, min(len(tokens_a), len(tokens_b)))
    ordered_overlap = 0.0
    for q_token, d_token in zip(tokens_a, tokens_b):
        if q_token == d_token:
            ordered_overlap += 1.0
        else:
            break
    ordered_overlap /= max(1, min(len(tokens_a), len(tokens_b)))
    string_ratio = SequenceMatcher(None, normalized_a, normalized_b).ratio()
    return max(0.0, min(1.0, 0.55 * string_ratio + 0.25 * ordered_overlap + 0.20 * set_overlap))


def _find_best_reusable_text(candidate_text: str, known_page_texts: List[str]) -> Tuple[str, float]:
    """Return the best matching known page text and its similarity, if any."""
    if not candidate_text or not known_page_texts:
        return "", 0.0

    cleaned_candidate = clean_pdf_text(candidate_text)
    if _count_text_words(cleaned_candidate) < FAST_OCR_WORD_THRESHOLD:
        return "", 0.0

    best_text = ""
    best_score = 0.0
    for known_text in known_page_texts:
        if not known_text:
            continue
        similarity = _estimate_text_similarity(cleaned_candidate, known_text)
        if similarity > best_score:
            best_score = similarity
            best_text = clean_pdf_text(known_text)
    return best_text, best_score


def _find_best_reusable_text_record(candidate_text: str, known_page_records: List[Dict[str, Any]]) -> Tuple[str, float, Optional[str], Optional[int]]:
    """Return the best matching known page text, score, and source page metadata."""
    if not candidate_text or not known_page_records:
        return "", 0.0, None, None

    cleaned_candidate = clean_pdf_text(candidate_text)
    if _count_text_words(cleaned_candidate) < FAST_OCR_WORD_THRESHOLD:
        return "", 0.0, None, None

    best_text = ""
    best_score = 0.0
    best_pdf_id = None
    best_page = None
    for known_page in known_page_records:
        known_text = known_page.get("text", "")
        if not known_text:
            continue
        similarity = _estimate_text_similarity(cleaned_candidate, known_text)
        if similarity > best_score:
            best_score = similarity
            best_text = clean_pdf_text(known_text)
            best_pdf_id = known_page.get("pdf_id")
            best_page = known_page.get("page")
    return best_text, best_score, best_pdf_id, best_page


def _log_text_reuse_decision(
    page_num: int,
    candidate_count: int,
    best_score: float,
    threshold: float,
    decision: str,
    reason: str,
    source_pdf_id: Optional[str] = None,
    source_page: Optional[int] = None,
) -> None:
    logger.info(
        "TEXT_REUSE_START page=%d candidates=%d",
        page_num,
        candidate_count,
    )
    if decision == "REUSE" and source_pdf_id is not None:
        logger.info(
            "TEXT_REUSE_BEST page=%d source_pdf=%s source_page=%s score=%.3f",
            page_num,
            source_pdf_id,
            source_page,
            best_score,
        )
    logger.info(
        "TEXT_REUSE_DECISION page=%d decision=%s reason=%s threshold=%.3f score=%.3f",
        page_num,
        decision,
        reason,
        threshold,
        best_score,
    )


def _build_visual_signature(page, timings: Dict[str, Any] = None, page_num: int = None) -> Dict[str, Any]:
    """Create a fast visual fingerprint for a page without running OCR."""
    if page is None:
        return {}

    start = time.perf_counter()
    try:
        from PIL import Image
        try:
            from PIL import ImageOps
        except Exception:
            ImageOps = None

        pix = page.get_pixmap(alpha=False, dpi=VISUAL_SIGNATURE_DPI)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        gray = ImageOps.grayscale(img) if ImageOps is not None else img.convert("L")
        if ImageOps is not None:
            gray = ImageOps.autocontrast(gray)

        hash_width = 9
        hash_height = 8
        small = gray.resize((hash_width, hash_height), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
        pixels = list(small.getdata())
        bits = 0
        bit_count = 0
        for row in range(hash_height):
            row_offset = row * hash_width
            for col in range(hash_width - 1):
                bits = (bits << 1) | (1 if pixels[row_offset + col] > pixels[row_offset + col + 1] else 0)
                bit_count += 1

        grid = VISUAL_SIGNATURE_GRID
        coarse = gray.resize((grid, grid), Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR)
        coarse_pixels = list(coarse.getdata())
        row_profile = []
        for row in range(grid):
            values = coarse_pixels[row * grid : (row + 1) * grid]
            row_profile.append(round(sum(values) / max(1, len(values)) / 255.0, 4))

        col_profile = []
        for col in range(grid):
            values = [coarse_pixels[row * grid + col] for row in range(grid)]
            col_profile.append(round(sum(values) / max(1, len(values)) / 255.0, 4))

        ink_density = round(1.0 - (sum(coarse_pixels) / max(1, len(coarse_pixels) * 255.0)), 4)
        aspect_ratio = round((pix.width / pix.height), 4) if pix.height else 0.0
        signature = {
            "dpi": VISUAL_SIGNATURE_DPI,
            "width": pix.width,
            "height": pix.height,
            "aspect_ratio": aspect_ratio,
            "dhash": f"{bits:016x}",
            "bit_count": bit_count,
            "row_profile": row_profile,
            "col_profile": col_profile,
            "ink_density": ink_density,
        }
        if timings is not None:
            _record_timing(timings, "visual_signature_ms", (time.perf_counter() - start) * 1000.0)
        return signature
    except Exception as exc:
        logger.debug("Visual signature failed for page %s: %s", page_num + 1 if page_num is not None else "?", exc)
        return {}


def _profile_similarity(profile_a: List[float], profile_b: List[float]) -> float:
    if not profile_a or not profile_b or len(profile_a) != len(profile_b):
        return 0.0
    total = 0.0
    for left, right in zip(profile_a, profile_b):
        total += 1.0 - min(1.0, abs(left - right))
    return total / len(profile_a)


def _visual_signature_similarity(signature_a: Dict[str, Any], signature_b: Dict[str, Any]) -> float:
    if not signature_a or not signature_b:
        return 0.0

    dhash_a = signature_a.get("dhash", "")
    dhash_b = signature_b.get("dhash", "")
    if not dhash_a or not dhash_b:
        return 0.0

    try:
        bits_a = int(dhash_a, 16)
        bits_b = int(dhash_b, 16)
    except Exception:
        return 0.0

    hamming_distance = (bits_a ^ bits_b).bit_count()
    hamming_similarity = 1.0 - (hamming_distance / max(1, signature_a.get("bit_count", 64)))

    row_similarity = _profile_similarity(signature_a.get("row_profile", []), signature_b.get("row_profile", []))
    col_similarity = _profile_similarity(signature_a.get("col_profile", []), signature_b.get("col_profile", []))

    ink_a = float(signature_a.get("ink_density", 0.0))
    ink_b = float(signature_b.get("ink_density", 0.0))
    ink_similarity = 1.0 - (abs(ink_a - ink_b) / max(ink_a, ink_b, 0.02))
    ink_similarity = max(0.0, min(1.0, ink_similarity))

    aspect_a = float(signature_a.get("aspect_ratio", 0.0))
    aspect_b = float(signature_b.get("aspect_ratio", 0.0))
    aspect_similarity = 1.0 - (abs(aspect_a - aspect_b) / max(aspect_a, aspect_b, 0.02))
    aspect_similarity = max(0.0, min(1.0, aspect_similarity))

    if hamming_similarity < 0.94 or row_similarity < 0.90 or col_similarity < 0.90:
        return 0.0
    if ink_similarity < 0.80 or aspect_similarity < 0.95:
        return 0.0

    score = (
        0.50 * hamming_similarity
        + 0.20 * row_similarity
        + 0.20 * col_similarity
        + 0.05 * ink_similarity
        + 0.05 * aspect_similarity
    )
    return max(0.0, min(1.0, score))


def _find_best_reusable_visual_text(candidate_signature: Dict[str, Any], known_page_records: List[Dict[str, Any]]) -> Tuple[str, float]:
    """Return the best matching known page text for a visual fingerprint."""
    if not candidate_signature or not known_page_records:
        return "", 0.0

    best_text = ""
    best_score = 0.0
    for known_page in known_page_records:
        known_signature = known_page.get("visual_signature")
        known_text = known_page.get("text", "")
        if not known_signature or not known_text:
            continue
        similarity = _visual_signature_similarity(candidate_signature, known_signature)
        if similarity > best_score:
            best_score = similarity
            best_text = clean_pdf_text(known_text)
    return best_text, best_score


def _log_visual_reuse_decision(
    page_num: int,
    known_page_records: List[Dict[str, Any]],
    visual_signature: Dict[str, Any],
    comparison_started: bool,
    candidate_count: int,
    best_score: float,
    threshold: float,
    decision: str,
    reason: str,
) -> None:
    known_records = len(known_page_records) if known_page_records else 0
    records_with_signature = sum(1 for record in (known_page_records or []) if record.get("visual_signature"))
    logger.info(
        "VISUAL_REUSE_START page=%d known_records=%d records_with_signature=%d page_signature=%s comparison_started=%s candidate_count=%d best_score=%.3f threshold=%.3f decision=%s reason=%s",
        page_num,
        known_records,
        records_with_signature,
        "yes" if visual_signature else "no",
        "yes" if comparison_started else "no",
        candidate_count,
        best_score,
        threshold,
        decision,
        reason,
    )


def _quick_ocr_page_text(page, timings: Dict[str, Any] = None, page_num: int = None) -> str:
    """Run a low-cost OCR pass for database-assisted reuse checks before full OCR."""
    if not _init_tesseract_once():
        return ""

    try:
        from PIL import Image
        try:
            from PIL import ImageOps
        except Exception:
            ImageOps = None

        start = time.perf_counter()
        pix = page.get_pixmap(alpha=False, dpi=120)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        if ImageOps is not None:
            gray = ImageOps.grayscale(img)
            gray = ImageOps.autocontrast(gray)
        else:
            gray = img

        lang = os.environ.get("TESSERACT_LANG", "ita+eng")
        text = _pytesseract_module.image_to_string(gray, lang=lang, config="--psm 6 --oem 3")
        cleaned = clean_pdf_text(text)
        if _count_text_words(cleaned) < FAST_OCR_WORD_THRESHOLD:
            return ""
        _record_timing(timings, "fast_ocr_ms", (time.perf_counter() - start) * 1000.0)
        return cleaned
    except Exception as exc:
        logger.debug("Fast OCR failed for page %s: %s", page_num + 1 if page_num is not None else "?", exc)
        return ""


def _token_fuzzy_match(query_token: str, doc_token: str) -> bool:
    if query_token == doc_token:
        return True
    if len(query_token) < 3 or len(doc_token) < 3:
        return False
    if abs(len(query_token) - len(doc_token)) > 1:
        return False

    if len(query_token) == len(doc_token):
        return sum(1 for a, b in zip(query_token, doc_token) if a != b) <= 1

    shorter, longer = (query_token, doc_token) if len(query_token) < len(doc_token) else (doc_token, query_token)
    diff = 0
    i = 0
    j = 0
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue
        diff += 1
        if diff > 1:
            return False
        j += 1
    return True


def _token_sliding_window_match(query_tokens: List[str], doc_tokens: List[str], fuzzy_threshold: float = 0.7) -> bool:
    """Check if query tokens match any consecutive sliding window in doc_tokens.
    
    STRICT matching - only exact phrase or clear subsequence:
    - "padre posso dire" matches "padre posso dire solo questo quando"
    - Requires 70%+ of query tokens to match consecutively OR
    - All query tokens must appear in order with limited gaps
    
    For longer queries (3+ words), implements PARTIAL CREDIT:
    - If 80%+ of tokens match, it's still valid (graceful degradation)
    - If N-1 tokens match exactly and 1 is missing, still valid
    - Avoids sudden invalidation when user adds a word
    
    Returns True if match found, False otherwise.
    """
    if not query_tokens:
        return False
    if not doc_tokens:
        return False
    
    query_len = len(query_tokens)
    doc_len = len(doc_tokens)

    # QUICK CONTAINMENT CHECK (conservative): if the entire doc token sequence
    # is contained in the query token sequence (or vice-versa), that's an obvious
    # phrase match — accept it. This handles cases like
    # query: "dio ti protegga ti benedica" and doc: "dio ti protegga".
    qt = " ".join(query_tokens)
    dt = " ".join(doc_tokens)
    if dt and qt:
        if dt in qt or qt in dt:
            return True

    def token_matches(q_token: str, d_token: str) -> bool:
        if q_token == d_token:
            return True
        allow_fuzzy = fuzzy_threshold < 1.0
        if not allow_fuzzy:
            return False
        return _token_fuzzy_match(q_token, d_token)

    # STRATEGY 1: Try exact consecutive match (highest confidence)
    # Requires 70% of tokens to match in sequence
    for start_idx in range(max(0, doc_len - query_len + 1)):
        window = doc_tokens[start_idx : start_idx + query_len]
        matching = sum(1 for i, q_token in enumerate(query_tokens) if i < len(window) and token_matches(q_token, window[i]))
        match_ratio = matching / query_len if query_len > 0 else 0
        if match_ratio >= fuzzy_threshold:
            return True

    # STRATEGY 2: Try longer windows (query tokens appear in order, but scattered)
    # Only check within limited window size (query_len + 3)
    for window_len in range(query_len + 1, min(doc_len + 1, query_len + 4)):
        for start_idx in range(max(0, doc_len - window_len + 1)):
            window = doc_tokens[start_idx : start_idx + window_len]
            q_idx = 0
            for w_token in window:
                if q_idx < len(query_tokens) and token_matches(query_tokens[q_idx], w_token):
                    q_idx += 1
            # All query tokens must be found in order
            if q_idx == len(query_tokens):
                return True
    
    # STRATEGY 3: PARTIAL CREDIT for longer queries
    # For queries with 3+ words, accept 80%+ token match
    # This provides graceful degradation instead of complete invalidation
    # Example: "padre posso dire solo questo quando" (6 words)
    #          vs "padre posso dire solo questo" (5 words) → 83% match, still valid
    if query_len >= 3:
        for start_idx in range(max(0, doc_len - query_len * 2)):
            if start_idx + query_len > doc_len:
                break
            # Try matching up to query_len words in broader window
            window = doc_tokens[start_idx : min(start_idx + query_len + 2, doc_len)]
            q_idx = 0
            for w_token in window:
                if q_idx < len(query_tokens) and w_token == query_tokens[q_idx]:
                    q_idx += 1
            
            # Accept if 80%+ of query tokens found in order
            match_ratio = q_idx / query_len if query_len > 0 else 0
            if match_ratio >= 0.8:
                return True
    
    # DISABLED: Tier 3 & 4 removed (too permissive, causes false positives)
    # - Tier 3 (50% scattered words): would match "quando" + "sento" in unrelated documents
    # - Tier 4 (40% threshold): accepts too many partial matches
    # 
    # These tiers were causing false positives where "quando qualcosa" 
    # matched query "quando mi sento solo" because they share 50% of words.
    
    return False


def text_matches_query(text: str, query: str, use_fuzzy: bool = True) -> bool:
    """Check if text matches query using token-based, fuzzy-tolerant matching.
    
    This is the main matching function for search:
    - Handles partial phrases
    - Handles incomplete queries
    - Ignores apostrophes and punctuation
    - Lowercase and accent-agnostic
    
    Returns True if query semantically matches the text.
    """
    if not text or not query:
        return False
    
    query_tokens = _tokenize_text(query)
    doc_tokens = _tokenize_text(text)
    
    if not query_tokens or not doc_tokens:
        return False
    
    # Use sliding window matching with fuzzy tolerance if enabled
    threshold = 0.7 if use_fuzzy else 1.0
    return _token_sliding_window_match(query_tokens, doc_tokens, fuzzy_threshold=threshold)


def _calculate_match_quality(text: str, query: str) -> float:
    """Calculate a phrase-aware match quality score for ranking purposes."""
    if not text or not query:
        return 0.0

    normalized_text = normalize_search_query(text)
    normalized_query = normalize_search_query(query)
    if not normalized_text or not normalized_query:
        return 0.0

    query_tokens = _tokenize_text(normalized_query)
    doc_tokens = _tokenize_text(normalized_text)

    if normalized_query == normalized_text:
        return 1.0
    if len(query_tokens) > 1 and (normalized_query in normalized_text or normalized_text in normalized_query):
        return 0.95
    if len(query_tokens) == 1 and normalized_query in normalized_text:
        return 0.8
    if not query_tokens or not doc_tokens:
        return _estimate_text_similarity(normalized_text, normalized_query)

    query_len = len(query_tokens)
    doc_len = len(doc_tokens)
    token_score = 0.0

    for start_idx in range(max(0, doc_len - query_len + 1)):
        window = doc_tokens[start_idx : start_idx + query_len]
        matching = sum(1 for i, q_token in enumerate(query_tokens) if i < len(window) and window[i] == q_token)
        match_ratio = matching / query_len if query_len > 0 else 0
        if match_ratio >= 0.7:
            token_score = 0.95 if matching == query_len else 0.85
            break

    if token_score == 0.0:
        for window_len in range(query_len + 1, min(doc_len + 1, query_len + 4)):
            for start_idx in range(max(0, doc_len - window_len + 1)):
                window = doc_tokens[start_idx : start_idx + window_len]
                q_idx = 0
                max_gap_found = 0
                last_pos = -1
                for w_idx, w_token in enumerate(window):
                    if q_idx < len(query_tokens) and w_token == query_tokens[q_idx]:
                        gap = w_idx - last_pos - 1
                        max_gap_found = max(max_gap_found, gap)
                        last_pos = w_idx
                        q_idx += 1
                if q_idx == len(query_tokens):
                    token_score = 0.90 if max_gap_found <= 1 else 0.80
                    break
            if token_score > 0.0:
                break

    if token_score == 0.0:
        token_score = min(0.65, max(0.0, len(set(query_tokens) & set(doc_tokens)) / max(1, len(query_tokens))))

    lexical_score = _estimate_text_similarity(normalized_text, normalized_query)
    phrase_boost = 0.15 if len(query_tokens) > 1 and len(set(query_tokens) & set(doc_tokens)) >= max(1, len(query_tokens) - 1) else 0.0
    return max(0.0, min(1.0, 0.6 * lexical_score + 0.4 * token_score + phrase_boost))


def extract_page_metadata(text: str) -> dict:
    normalized = normalize_pdf_text(text)
    meter = {}
    match = re.search(r"\b(?:cantico|canto|inno|hymn)\s*#?\s*(\d{1,4})\b", normalized, flags=re.IGNORECASE)
    if not match:
        match = re.match(r"^\s*(\d{1,4})\b", normalized)
    if match:
        try:
            meter["cantico"] = int(match.group(1))
        except ValueError:
            pass
    return meter


def _count_text_words(text: str) -> int:
    return len(re.findall(r"\b[A-Za-zÀ-ÿ0-9]{2,}\b", text))


def _record_timing(timings: Dict[str, Any], key: str, value: float) -> None:
    if timings is not None:
        with _timing_lock:
            timings[key] = timings.get(key, 0.0) + value


def _resize_image_for_ocr(img, max_long_side: int = MAX_OCR_IMAGE_SIZE):
    """Resize large OCR images to a bounded long side before inference."""
    if img is None:
        return img
    if max(img.width, img.height) <= max_long_side:
        return img

    scale = max_long_side / max(img.width, img.height)
    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    try:
        from PIL import Image

        return img.resize(new_size, resample=Image.LANCZOS)
    except Exception as exc:
        logger.debug("Image resize for OCR failed: %s", exc)
        return img


def _choose_ocr_worker_count(ocr_candidates: List[tuple], page_details: List[Dict[str, Any]]) -> int:
    if not ocr_candidates:
        return 0

    image_pages = sum(1 for p in page_details if p.get("page_images"))
    mixed_pages = sum(1 for p in page_details if p.get("dict_text_blocks", 0) > 0 and p.get("dict_image_blocks", 0) > 0)
    total_pages = len(page_details) if page_details else len(ocr_candidates)

    is_scanned_pdf = image_pages >= max(1, int(total_pages * 0.75))
    if is_scanned_pdf:
        return min(2, len(ocr_candidates), MAX_PARALLEL_OCR_WORKERS)
    if mixed_pages > 0:
        return min(3, len(ocr_candidates), MAX_PARALLEL_OCR_WORKERS)
    return min(1, len(ocr_candidates), MAX_PARALLEL_OCR_WORKERS)


def _is_noisy_page_text(cleaned_text: str) -> bool:
    if not cleaned_text:
        return True
    tokens = [t for t in cleaned_text.split() if t]
    if len(tokens) < 6:
        return True

    short_tokens = sum(1 for t in tokens if len(re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", t)) <= 2)
    if short_tokens / len(tokens) > 0.35:
        return True

    uppercase_tokens = sum(1 for t in tokens if len(t) >= 3 and t.isupper())
    if uppercase_tokens >= 3:
        return True

    nonletter_ratio = sum(1 for t in tokens if re.fullmatch(r"[^A-Za-zÀ-ÿ0-9]+", t))
    if nonletter_ratio / len(tokens) > 0.15:
        return True

    return False


def _choose_page_text(native_text: str, ocr_text: str, prefer_ocr: bool = False) -> str:
    cleaned_native = clean_pdf_text(native_text)
    cleaned_ocr = clean_pdf_text(ocr_text)
    if not cleaned_native:
        return cleaned_ocr
    if not cleaned_ocr:
        return cleaned_native

    native_words = _count_text_words(cleaned_native)
    ocr_words = _count_text_words(cleaned_ocr)

    if prefer_ocr and not _is_noisy_page_text(cleaned_ocr):
        if _is_noisy_page_text(cleaned_native) or ocr_words >= native_words + 2:
            return cleaned_ocr

    if _is_noisy_page_text(cleaned_native) and not _is_noisy_page_text(cleaned_ocr):
        return cleaned_ocr

    if ocr_words > native_words + 4:
        return cleaned_ocr

    if cleaned_ocr not in cleaned_native:
        return f"{cleaned_native} {cleaned_ocr}".strip()
    return cleaned_native


def _has_boilerplate_text(cleaned_text: str) -> bool:
    if not cleaned_text:
        return False
    lower = cleaned_text.lower()
    boilerplate_keywords = [
        "scarica",
        "clic",
        "convertitore",
        "foto pdf",
        "foto",
        "photo",
        "created by",
        "generated by",
        "watermark",
        "scan",
        "scansione",
        "download",
        "pdf",
        "free",
        "online",
        "preview",
        "document",
        "convert",
    ]
    matches = sum(1 for token in boilerplate_keywords if token in lower)
    if matches >= 2:
        return True

    words = lower.split()
    if not words:
        return False
    boilerplate_word_set = {"scarica", "clic", "convertitore", "foto", "pdf", "photo", "download", "scan", "scansione", "preview", "free"}
    boilerplate_count = sum(1 for w in words if w in boilerplate_word_set)
    return boilerplate_count >= max(2, len(words) // 5)


def _has_useful_page_text(cleaned_text: str) -> bool:
    if not cleaned_text:
        return False
    if len(cleaned_text) < 40:
        return False
    if _has_boilerplate_text(cleaned_text):
        return False
    return _count_text_words(cleaned_text) >= 6


def _page_has_images(page) -> bool:
    try:
        return bool(page.get_images(full=True))
    except Exception:
        return False


def _extract_embedded_image(page, page_num: int = None):
    """Return a single large embedded image from the page, if available."""
    try:
        image_refs = page.get_images(full=True) or []
    except Exception:
        logger.info("OCR_DIRECT_IMAGE_SKIP page=%s reason=get_images_failed", page_num + 1 if page_num is not None else "?")
        return None

    if not image_refs or len(image_refs) != 1:
        logger.info(
            "OCR_DIRECT_IMAGE_SKIP page=%s reason=image_ref_count count=%s",
            page_num + 1 if page_num is not None else "?",
            len(image_refs),
        )
        return None

    xref = image_refs[0][0]
    doc = getattr(page, "parent", None)
    if doc is None:
        logger.info("OCR_DIRECT_IMAGE_SKIP page=%s reason=no_parent xref=%s", page_num + 1 if page_num is not None else "?", xref)
        return None

    try:
        image_info = doc.extract_image(xref)
    except Exception:
        logger.info("OCR_DIRECT_IMAGE_SKIP page=%s reason=extract_image_failed xref=%s", page_num + 1 if page_num is not None else "?", xref)
        return None

    if not isinstance(image_info, dict):
        logger.info("OCR_DIRECT_IMAGE_SKIP page=%s reason=invalid_image_info xref=%s", page_num + 1 if page_num is not None else "?", xref)
        return None

    image_bytes = image_info.get("image")
    width = int(image_info.get("width", 0) or 0)
    height = int(image_info.get("height", 0) or 0)
    if not image_bytes or width < 500 or height < 500:
        logger.info(
            "OCR_DIRECT_IMAGE_SKIP page=%s reason=small_or_missing_image xref=%s width=%s height=%s has_bytes=%s",
            page_num + 1 if page_num is not None else "?",
            xref,
            width,
            height,
            bool(image_bytes),
        )
        return None

    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            return img.copy(), xref, width, height
    except Exception:
        logger.info("OCR_DIRECT_IMAGE_SKIP page=%s reason=pil_open_failed xref=%s", page_num + 1 if page_num is not None else "?", xref)
        return None


def _ocr_direct_image(page, timings: Dict[str, Any] = None, page_num: int = None) -> str:
    """Try OCR on a single embedded page image before falling back to page rasterization."""
    payload = _extract_embedded_image(page, page_num=page_num)
    if not payload:
        return ""

    img, xref, width, height = payload
    start = time.perf_counter()
    if not _init_tesseract_once():
        return ""

    try:
        img.load()
        img = img.copy()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if max(img.size) > MAX_OCR_IMAGE_SIZE:
            img = _resize_image_for_ocr(img, max_long_side=MAX_OCR_IMAGE_SIZE)

        logger.info("OCR_DIRECT_IMAGE page=%s xref=%s size=%sx%s", page_num + 1 if page_num is not None else "?", xref, width, height)
        logger.info("OCR_DIRECT_IMAGE_IMAGE mode=%s format=%s fp_open=%s", img.mode, getattr(img, "format", None), bool(getattr(img, "fp", None)))
        image_mode = _is_image_ocr_mode()
        lang = os.environ.get("TESSERACT_LANG_IMAGE") if image_mode else os.environ.get("TESSERACT_LANG", "ita+eng")
        if not lang:
            lang = os.environ.get("TESSERACT_LANG", "ita+eng")
        psm = int(os.environ.get("OCR_IMAGE_PSM", "11")) if image_mode else 6
        oem = int(os.environ.get("OCR_IMAGE_OEM") or os.environ.get("OCR_OEM") or os.environ.get("OCR_PRIMARY_OEM", "1")) if image_mode else int(os.environ.get("OCR_OEM") or os.environ.get("OCR_PRIMARY_OEM", "3"))
        config = f"--psm {psm} --oem {oem}"
        logger.info("TESSERACT_VERSION=%s", _pytesseract_module.get_tesseract_version())
        logger.info("OCR_LANGUAGE=%s", lang)
        logger.info("OCR_CONFIG=%s", config)
        logger.info("OCR_DPI=%s", "embedded-image")
        logger.info("OCR_IMAGE_SIZE=%sx%s", img.width, img.height)
        try:
            text = _pytesseract_module.image_to_string(img, lang=lang, config=config)
        except TypeError:
            text = _pytesseract_module.image_to_string(img)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.info("OCR_PAGE_ELAPSED page=%s elapsed_ms=%.0f", page_num + 1 if page_num is not None else "?", elapsed_ms)
        if text:
            _record_timing(timings, "direct_image_pages", 1)
            _record_timing(timings, "direct_image_ms", elapsed_ms)
        return text or ""
    except Exception:
        logger.exception("Direct embedded-image OCR failed")
        return ""


def _find_tesseract_binary() -> str:
    """Resolve the Tesseract binary, validating explicit overrides before using them."""
    explicit = os.environ.get("TESSERACT_PATH") or os.environ.get("TESSERACT_CMD")
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    logger.debug(
        "Searching Tesseract: TESSERACT_PATH=%s, TESSERACT_CMD=%s, PATH=%s",
        os.environ.get("TESSERACT_PATH"),
        os.environ.get("TESSERACT_CMD"),
        path_dirs,
    )

    candidates = []

    if explicit:
        candidates.append(explicit)
        expanded = os.path.expanduser(explicit)
        if expanded != explicit:
            candidates.append(expanded)

    for candidate in candidates:
        logger.debug(f"Checking explicit candidate: {candidate}")
        if os.path.isfile(candidate):
            logger.info(f"Found Tesseract at explicit path: {candidate}")
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            logger.info(f"Found Tesseract via which() for explicit path: {resolved}")
            return resolved

    binary_path = shutil.which("tesseract")
    if binary_path:
        logger.info(f"Found Tesseract via which('tesseract'): {binary_path}")
        return binary_path

    possible_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
        "/usr/share/bin/tesseract",
    ]
    for path in possible_paths:
        logger.debug(f"Checking common Tesseract path: {path}")
        if os.path.isfile(path):
            logger.info(f"Found Tesseract at common path: {path}")
            return path

    logger.warning(
        "Tesseract not found. Checked: explicit=%s, which('tesseract')=None, PATH dirs=%s",
        explicit,
        path_dirs,
    )
    return ""

def _create_rapidocr_engine():
    global _rapidocr_engine
    global _rapidocr_available
    if _rapidocr_engine is not None:
        return _rapidocr_engine

    try:
        from rapidocr import RapidOCR

        _rapidocr_engine = RapidOCR()
        _rapidocr_available = True
        logger.info("RapidOCR engine initialized successfully")
        return _rapidocr_engine
    except Exception as exc:
        logger.warning("RapidOCR initialization failed despite availability flag: %s", exc)
        _rapidocr_available = False
        return None


def _extract_text_with_rapidocr(page, timings: Dict[str, Any] = None) -> str:
    start_total = time.perf_counter()
    engine = _create_rapidocr_engine()
    if engine is None:
        return ""
    render_time = 0.0
    infer_time = 0.0
    try:
        import numpy as np
        from PIL import Image

        start = time.perf_counter()
        pix = page.get_pixmap(alpha=False, dpi=300)
        render_time += time.perf_counter() - start

        try:
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img = _resize_image_for_ocr(img, max_long_side=2000)
            arr = np.asarray(img)
        except Exception:
            arr = pix
        engine = _create_rapidocr_engine()
        if engine is None:
            return ""

        start = time.perf_counter()
        result = engine(arr)
        infer_time += time.perf_counter() - start
        txts = getattr(result, "txts", None)
        if txts is None and isinstance(result, (list, tuple)):
            txts = result

        if isinstance(txts, (list, tuple)):
            text_parts = []
            for item in txts:
                if isinstance(item, str) and item.strip():
                    text_parts.append(item.strip())
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("txt") or ""
                    if text.strip():
                        text_parts.append(text.strip())
            if text_parts:
                return "\n".join(text_parts).strip()

        return ""
    except Exception as exc:
        logger.warning("RapidOCR OCR failed: %s", exc)
        return ""
    finally:
        _record_timing(timings, "rapidocr_render_ms", render_time * 1000.0)
        _record_timing(timings, "rapidocr_infer_ms", infer_time * 1000.0)
        _record_timing(timings, "rapidocr_ms", (time.perf_counter() - start_total) * 1000.0)
        _record_timing(timings, "rapidocr_calls", 1)


def _get_google_vision_auth() -> Tuple[str, str]:
    """Return a tuple (mode, value) for Google Vision HTTP auth.
    mode is either 'key' or 'bearer'.
    """
    api_key = os.environ.get("GOOGLE_VISION_API_KEY") or os.environ.get("GOOGLE_CLOUD_VISION_API_KEY")
    if api_key:
        source = "GOOGLE_VISION_API_KEY" if os.environ.get("GOOGLE_VISION_API_KEY") else "GOOGLE_CLOUD_VISION_API_KEY"
        logger.info("Google Vision auth: using API key from %s", source)
        return "key", api_key

    # Support GOOGLE_APPLICATION_CREDENTIALS as either a service account JSON path or an API key.
    adc_value = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if adc_value:
        if adc_value.startswith("AIza"):
            logger.info("Google Vision auth: using API key from GOOGLE_APPLICATION_CREDENTIALS")
            return "key", adc_value
        if os.path.isfile(adc_value):
            try:
                with open(adc_value, "r", encoding="utf-8") as f:
                    creds_json = json.load(f)
                client_email = creds_json.get("client_email")
                private_key = creds_json.get("private_key")
                if client_email and private_key:
                    logger.info("Google Vision auth: using ADC service account from GOOGLE_APPLICATION_CREDENTIALS path=%s", adc_value)
                    return "adc", adc_value
            except Exception as exc:
                logger.warning("Failed to read GOOGLE_APPLICATION_CREDENTIALS: %s", exc)

    try:
        import google.auth
        from google.auth.transport.requests import Request as GoogleRequest

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not creds.valid:
            creds.refresh(GoogleRequest())
        if creds and creds.token:
            return "bearer", creds.token
    except Exception as exc:
        logger.debug("Google Vision auth unavailable: %s", exc)

    return "", ""


def _extract_text_with_google_vision(page) -> str:
    auth_type, auth_value = _get_google_vision_auth()
    if not auth_type:
        return ""

    try:
        from PIL import Image
        pix = page.get_pixmap(alpha=False, dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_content = base64.b64encode(buf.getvalue()).decode("utf-8")

        url = "https://vision.googleapis.com/v1/images:annotate"
        params = {"requests": [{
            "image": {"content": image_content},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}],
        }]}
        headers = {"Content-Type": "application/json"}
        if auth_type == "key":
            safe_key = f"***{auth_value[-6:]}" if len(auth_value) > 6 else "***"
            url = f"{url}?key={auth_value}"
            logger.info("Google Vision request: sending API key auth (key suffix=%s)", safe_key)
        elif auth_type == "adc":
            # Use OAuth2 access token generated from service account JSON.
            from google.oauth2.service_account import Credentials as ServiceAccountCredentials
            from google.auth.transport.requests import Request as GoogleRequest

            creds = ServiceAccountCredentials.from_service_account_file(auth_value, scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(GoogleRequest())
            if not creds.token:
                raise RuntimeError("Failed to obtain access token from service account credentials")
            headers["Authorization"] = f"Bearer {creds.token}"
            logger.info("Google Vision request: sending ADC bearer auth from %s", auth_value)
        else:
            headers["Authorization"] = f"Bearer {auth_value}"
            logger.info("Google Vision request: sending bearer token auth")

        request_url = url if auth_type != "key" else f"https://vision.googleapis.com/v1/images:annotate?key={safe_key}"
        logger.info("Google Vision request URL: %s", request_url)
        resp = httpx.post(url, json=params, headers=headers, timeout=60.0)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as http_exc:
            logger.warning("Google Vision HTTP error %s: %s", resp.status_code, resp.text[:1000])
            raise
        response_data = resp.json()
        responses = response_data.get("responses", [])
        if not responses:
            return ""
        response = responses[0]
        text = response.get("fullTextAnnotation", {}).get("text")
        if not text:
            text = (response.get("textAnnotations", [{}])[0].get("description") or "")
        return text or ""
    except Exception as exc:
        logger.warning("Google Vision OCR failed: %s", exc)
        if auth_type == "key":
            adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if adc_path and os.path.isfile(adc_path):
                logger.info("Falling back to GOOGLE_APPLICATION_CREDENTIALS after Vision API key failure")
                try:
                    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
                    from google.auth.transport.requests import Request as GoogleRequest

                    creds = ServiceAccountCredentials.from_service_account_file(adc_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
                    creds.refresh(GoogleRequest())
                    if creds.token:
                        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {creds.token}"}
                        resp = httpx.post(url, json=params, headers=headers, timeout=60.0)
                        resp.raise_for_status()
                        response_data = resp.json()
                        responses = response_data.get("responses", [])
                        if not responses:
                            return ""
                        response = responses[0]
                        text = response.get("fullTextAnnotation", {}).get("text")
                        if not text:
                            text = (response.get("textAnnotations", [{}])[0].get("description") or "")
                        return text or ""
                except Exception as exc2:
                    logger.warning("Google Vision OCR ADC fallback failed: %s", exc2)
        if auth_type == "key" and not _has_google_vision_auth():
            logger.warning("Google Vision key fallita e GOOGLE_APPLICATION_CREDENTIALS non valida o non presente.")
        return ""


def _warn_no_ocr_backend():
    global _OCR_NOT_CONFIGURED_WARNING_SHOWN
    if not _OCR_NOT_CONFIGURED_WARNING_SHOWN:
        logger.warning(
            "Nessun backend OCR locale disponibile: installare Tesseract o impostare TESSERACT_PATH/TESSERACT_CMD."
        )
        _OCR_NOT_CONFIGURED_WARNING_SHOWN = True


def _has_google_vision_auth() -> bool:
    return bool(
        os.environ.get("GOOGLE_VISION_API_KEY")
        or os.environ.get("GOOGLE_CLOUD_VISION_API_KEY")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )


def _tesseract_ocr_text(page, timings: Dict[str, Any] = None, page_num: int = None) -> str:
    start_total = time.perf_counter()
    render_time = 0.0
    infer_time = 0.0
    pass_count = 0
    # Initialize pytesseract once to avoid repeated overhead.
    if not _init_tesseract_once():
        return ""

    try:
        from PIL import Image
        try:
            from PIL import ImageFilter, ImageOps, ImageEnhance
        except Exception:
            ImageFilter = None
            ImageOps = None
            ImageEnhance = None
    except Exception as exc:
        logger.warning("Pillow import failed for Tesseract OCR: %s", exc)
        return ""

    results = []
    try:
        image_mode = _is_image_ocr_mode()
        primary_dpi = int(os.environ.get("OCR_IMAGE_DPI") or os.environ.get("OCR_DPI") or os.environ.get("OCR_PRIMARY_DPI", "100" if image_mode else "150"))
        primary_psm = int(os.environ.get("OCR_IMAGE_PSM") or os.environ.get("OCR_PRIMARY_PSM", "11" if image_mode else "6"))
        sufficiency_words = int(os.environ.get("OCR_WORD_THRESHOLD", "12"))

        def do_pass(dpi: int, psm: int):
            nonlocal render_time, infer_time, pass_count, results
            try:
                start = time.perf_counter()
                pix = page.get_pixmap(alpha=False, dpi=dpi)
                render_time += time.perf_counter() - start
            except Exception:
                try:
                    start = time.perf_counter()
                    pix = page.get_pixmap(alpha=False, dpi=dpi)
                    render_time += time.perf_counter() - start
                except Exception as exc:
                    logger.warning("Failed to rasterize page for OCR: %s", exc)
                    return None

            try:
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            except Exception:
                try:
                    img = Image.frombuffer("RGB", (pix.width, pix.height), pix.samples, "raw", "RGB", 0, 1)
                except Exception as exc:
                    logger.warning("Failed to convert pixmap to Image: %s", exc)
                    return None

            # Log image size and dpi for performance debugging
            try:
                logger.info("OCR page %s image size: %sx%s", page_num or "?", pix.width, pix.height)
                logger.info("OCR page %s dpi: %s", page_num or "?", dpi)
            except Exception:
                pass

            try:
                if ImageOps is not None and ImageFilter is not None and ImageEnhance is not None:
                    preprocess_start = time.perf_counter()
                    gray = ImageOps.grayscale(img)
                    grayscale_ms = (time.perf_counter() - preprocess_start) * 1000.0
                    preprocess_start = time.perf_counter()
                    gray = ImageOps.autocontrast(gray)
                    autocontrast_ms = (time.perf_counter() - preprocess_start) * 1000.0
                    medianfilter_ms = 0.0
                    sharpen_ms = 0.0
                    contrast_ms = 0.0
                    if not image_mode:
                        preprocess_start = time.perf_counter()
                        gray = gray.filter(ImageFilter.MedianFilter(size=3))
                        medianfilter_ms = (time.perf_counter() - preprocess_start) * 1000.0
                        preprocess_start = time.perf_counter()
                        gray = gray.filter(ImageFilter.SHARPEN)
                        sharpen_ms = (time.perf_counter() - preprocess_start) * 1000.0
                        preprocess_start = time.perf_counter()
                        enhancer = ImageEnhance.Contrast(gray)
                        gray = enhancer.enhance(1.3)
                        contrast_ms = (time.perf_counter() - preprocess_start) * 1000.0
                    logger.info(
                        "OCR_PREPROCESS mode=%s grayscale_ms=%.0f autocontrast_ms=%.0f medianfilter_ms=%.0f sharpen_ms=%.0f contrast_ms=%.0f total_ms=%.0f",
                        "image-fast" if image_mode else "full",
                        grayscale_ms,
                        autocontrast_ms,
                        medianfilter_ms,
                        sharpen_ms,
                        contrast_ms,
                        grayscale_ms + autocontrast_ms + medianfilter_ms + sharpen_ms + contrast_ms,
                    )
                else:
                    gray = img
            except Exception as exc:
                logger.debug("Image preprocessing failed: %s", exc)
                gray = img

            logger.info("OCR_RUNTIME dpi=%s width=%s height=%s", dpi, pix.width, pix.height)
            logger.info("OCR_TIMING raster_ms=%.0f tesseract_ms=%.0f", render_time * 1000.0, infer_time * 1000.0)
            try:
                lang = os.environ.get("TESSERACT_LANG", "ita+eng")
                if image_mode:
                    lang = os.environ.get("TESSERACT_LANG_IMAGE", lang) or lang
                    oem = int(os.environ.get("OCR_IMAGE_OEM") or os.environ.get("OCR_OEM") or os.environ.get("OCR_PRIMARY_OEM", "1"))
                else:
                    oem = int(os.environ.get("OCR_OEM") or os.environ.get("OCR_PRIMARY_OEM", "3"))
                config = f"--psm {psm} --oem {oem}"
                logger.info("TESSERACT_VERSION=%s", _pytesseract_module.get_tesseract_version())
                logger.info("OCR_LANGUAGE=%s", lang)
                logger.info("OCR_CONFIG=%s", config)
                logger.info("OCR_DPI=%s", dpi)
                logger.info("OCR_IMAGE_SIZE=%sx%s", pix.width, pix.height)
                try:
                    logger.info("Starting Tesseract for page %s (dpi=%s psm=%s)", page_num or "?", dpi, psm)
                    logger.info("OCR_COMPARE dpi=%s page=%s", dpi, page_num + 1 if page_num is not None else '?')
                except Exception:
                    pass
                start = time.perf_counter()
                try:
                    text = _pytesseract_module.image_to_string(gray, lang=lang, config=config)
                except TypeError:
                    text = _pytesseract_module.image_to_string(gray)
                infer_time += time.perf_counter() - start
                try:
                    logger.info("Finished Tesseract for page %s (elapsed %.0f ms)", page_num or "?", (time.perf_counter() - start) * 1000.0)
                    logger.info("OCR_WORDS page=%s words=%d", page_num + 1 if page_num is not None else '?', _count_text_words(clean_pdf_text(text)))
                except Exception:
                    pass
                pass_count += 1
                if text:
                    results.append(text)
            except Exception as exc:
                logger.debug("Tesseract pass failed (dpi=%s psm=%s): %s", dpi, psm, exc)
            return gray
        # Primary OCR pass with lower DPI and fixed PSM.
        do_pass(primary_dpi, primary_psm)
        merged_candidate = "\n".join([ln for r in results for ln in [l.strip() for l in r.splitlines() if l.strip()]])
        cleaned_candidate = clean_pdf_text(merged_candidate)
        words_found = _count_text_words(cleaned_candidate)
        if words_found >= sufficiency_words:
            return cleaned_candidate

        if not results:
            return ""

        lines = []
        for r in results:
            for ln in [l.strip() for l in r.splitlines() if l.strip()]:
                found = False
                for i, exist in enumerate(lines):
                    if ln in exist:
                        found = True
                        break
                    if exist in ln:
                        lines[i] = ln
                        found = True
                        break
                if not found:
                    lines.append(ln)

        merged = "\n".join(lines)
        logger.debug("Tesseract OCR passes produced %d results, merged %d lines", len(results), len(lines))
        return merged
    except Exception as exc:
        logger.warning("Tesseract OCR failed: %s", exc)
        return ""
    finally:
        _record_timing(timings, "tesseract_render_ms", render_time * 1000.0)
        _record_timing(timings, "tesseract_infer_ms", infer_time * 1000.0)
        _record_timing(timings, "tesseract_ms", (time.perf_counter() - start_total) * 1000.0)
        _record_timing(timings, "tesseract_passes", pass_count)
        _record_timing(timings, "tesseract_calls", 1)


def _ocr_page_sync(page, timings: Dict[str, Any] = None) -> str:
    return _ocr_page_text(page, timings=timings, page_num=None)


def _ocr_page_text(page, timings: Dict[str, Any] = None, page_num: int = None) -> str:
    """Module-level OCR wrapper used by workers.

    Tries direct OCR on a single embedded page image first, then falls back to
    Tesseract raster OCR, and only then to RapidOCR as a last resort.
    """
    try:
        direct_text = _ocr_direct_image(page, timings=timings, page_num=page_num)
    except Exception as exc:
        logger.warning("Direct embedded-image OCR failed: %s", exc)
        direct_text = ""

    if direct_text:
        _record_timing(timings, "direct_image_pages", 1)
        logger.info("OCR_PATH=direct-image")
        logger.info("Direct image OCR produced %d chars", len(direct_text))
        return direct_text

    logger.info("OCR_PATH=fallback-raster")
    logger.info("OCR_PATH_REASON=page-raster-fallback")

    # Prefer RapidOCR when available because it is usually cheaper and faster.
    try:
        rapid_text = _extract_text_with_rapidocr(page, timings=timings)
    except Exception as exc:
        logger.warning("RapidOCR invocation failed: %s", exc)
        rapid_text = ""

    if rapid_text:
        _record_timing(timings, "rapidocr_pages", 1)
        logger.info("OCR_PATH=rapidocr-fallback")
        logger.info("RapidOCR OCR produced %d chars", len(rapid_text))
        return rapid_text

    try:
        text = _tesseract_ocr_text(page, timings=timings, page_num=page_num)
    except TypeError:
        try:
            text = _tesseract_ocr_text(page)
        except Exception as exc:
            logger.warning("Tesseract OCR invocation failed: %s", exc)
            text = ""
    except Exception as exc:
        logger.warning("Tesseract OCR invocation failed: %s", exc)
        text = ""

    if text:
        _record_timing(timings, "tesseract_pages", 1)
        return text

    return text


def _ocr_page_worker(page_num: int, page, timings: Dict[str, Any] = None, image_mode: bool = False):
    logger.info("OCR worker started for page %s", page_num + 1)
    start = time.perf_counter()
    previous_image_mode = getattr(_ocr_context, "image_mode", False)
    _ocr_context.image_mode = image_mode
    try:
        text = _ocr_page_text(page, timings=timings, page_num=page_num)
    finally:
        _ocr_context.image_mode = previous_image_mode
    ms = (time.perf_counter() - start) * 1000.0
    return text, ms


def _ocr_needs_page(page_info: Dict[str, Any]) -> bool:
    return page_info.get("ocr_attempted", False)


def extract_pages(pdf_bytes: bytes, timings: Dict[str, Any] = None, known_page_texts: List[str] = None, known_page_records: List[Dict[str, Any]] = None) -> Tuple[List[str], List[str], int, bool, List[str]]:
    """Extract text from each page. OCR logic remains fallback-only.
    Returns (pages_text, raw_texts, total_pages, used_ocr, page_labels).
    """
    if timings is not None:
        timings.setdefault("page_details", [])

    pages_text: List[str] = []
    page_labels: List[str] = []
    used_ocr = False
    start_total = time.perf_counter()
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Failed to open PDF: {e}")
        raise

    labels = None
    try:
        labels = doc.get_page_labels()
    except Exception:
        labels = None

    raw_texts: List[str] = [""] * len(doc)
    ocr_candidates = []
    pages_text: List[str] = [""] * len(doc)
    page_details: List[Dict[str, Any]] = []

    for page_num in range(len(doc)):
        page_info: Dict[str, Any] = {
            "page": page_num + 1,
            "ocr_attempted": False,
            "ocr_used": False,
            "reason": [],
        }
        try:
            page = doc[page_num]
            start = time.perf_counter()
            raw_text = page.get_text("text") or ""
            _record_timing(timings, "page_text_ms", (time.perf_counter() - start) * 1000.0)

            # Also inspect the structured dict output to detect text vs image blocks.
            start = time.perf_counter()
            try:
                text_dict = page.get_text("dict") or {}
            except Exception:
                text_dict = {}
            blocks = text_dict.get("blocks", []) if isinstance(text_dict, dict) else []
            text_blocks = sum(1 for b in blocks if b.get("type") == 0)
            image_blocks = sum(1 for b in blocks if b.get("type") == 1)

            # Reconstruct text from dict spans (more reliable for block-level detection)
            dict_text_parts = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span.get("text") or ""
                        if txt:
                            dict_text_parts.append(txt)
            dict_text = "\n".join(dict_text_parts).strip()
            dict_cleaned = clean_pdf_text(dict_text)

            visual_signature = _build_visual_signature(page, timings=timings, page_num=page_num)
            if visual_signature:
                page_info["visual_signature"] = visual_signature

            # Also check low-level images() as a fallback (may miss inline-painted images)
            try:
                image_xobjs = bool(page.get_images(full=True))
            except Exception:
                image_xobjs = False
            _record_timing(timings, "page_images_ms", (time.perf_counter() - start) * 1000.0)

            # Decide whether page is image-like using both dict blocks and get_images
            # Rules (in order):
            # 1) If dict has significant text blocks, prefer native text and skip OCR.
            # 2) If no text blocks and image blocks exist, treat as image -> OCR.
            # 3) If both exist, consider mixed: use native if native text quality passes threshold, otherwise OCR.
            cleaned = clean_pdf_text(raw_text)
            # Use dict_cleaned when available to evaluate native text quality.
            native_text_for_quality = dict_cleaned if dict_cleaned else cleaned
            has_useful_native_text = _has_useful_page_text(native_text_for_quality)
            has_significant_text_blocks = text_blocks > 0 and has_useful_native_text
            has_any_text_blocks = text_blocks > 0
            has_any_image_blocks = image_blocks > 0 or image_xobjs
            # page_images indicates whether OCR should be considered because page is image-like
            if has_useful_native_text:
                page_images = False
            elif has_significant_text_blocks:
                page_images = False
            elif not has_any_text_blocks and has_any_image_blocks:
                page_images = True
            elif has_any_text_blocks and has_any_image_blocks:
                # Mixed page: choose native if quality sufficient
                page_images = not has_useful_native_text
            else:
                # Fallback to previous heuristic using raw cleaned text
                page_images = _page_has_images(page)

            word_count = _count_text_words(cleaned)
            page_info.update({
                "raw_length": len(raw_text),
                "clean_length": len(cleaned),
                "word_count": word_count,
                "page_images": page_images,
                "is_noisy": _is_noisy_page_text(cleaned),
                "dict_text_blocks": text_blocks,
                "dict_image_blocks": image_blocks,
            })
            
            needs_ocr = (
                (not has_useful_native_text and page_images)  # Has images that need OCR
                or (not has_useful_native_text and len(cleaned) < 40)           # Almost empty page
                or (not has_useful_native_text and word_count < 3)              # No meaningful text
                or (not has_useful_native_text and _is_noisy_page_text(cleaned)) # Noisy native extraction may be improved by OCR
            )
            
            if needs_ocr:
                page_info["ocr_attempted"] = True
                if page_images:
                    page_info["reason"].append("images")
                if len(cleaned) < 40:
                    page_info["reason"].append("short_text")
                if word_count < 3:
                    page_info["reason"].append("no_words")
                if page_info["is_noisy"]:
                    page_info["reason"].append("noisy_text")

                logger.info(
                    "Page %s: OCR attempt - chars=%s words=%s images=%s reason=%s",
                    page_num + 1,
                    len(cleaned),
                    word_count,
                    page_images,
                    "+".join(page_info["reason"]) or "unknown",
                )

                best_score = 0.0
                comparison_started = False
                candidate_count = 0
                decision = "OCR"
                decision_reason = "no_candidates"

                reuse_text = ""
                reuse_similarity = 0.0
                reuse_source_pdf_id = None
                reuse_source_page = None
                reuse_reason = "no_candidate_text"

                candidate_text = native_text_for_quality if has_useful_native_text else cleaned
                if not candidate_text:
                    candidate_text = ""
                if not has_useful_native_text and known_page_records:
                    try:
                        candidate_text = _quick_ocr_page_text(page, timings=timings, page_num=page_num) or candidate_text
                    except Exception:
                        candidate_text = candidate_text

                if candidate_text and (known_page_records or known_page_texts):
                    try:
                        candidate_records = [record for record in known_page_records if record.get("text")] if known_page_records else []
                        candidate_count = len(candidate_records)
                        comparison_started = candidate_count > 0
                        if candidate_count > 0:
                            reuse_text, reuse_similarity, reuse_source_pdf_id, reuse_source_page = _find_best_reusable_text_record(candidate_text, candidate_records)
                            best_score = reuse_similarity
                            if reuse_text and reuse_similarity >= REUSE_TEXT_SIMILARITY_THRESHOLD:
                                decision = "REUSE"
                                decision_reason = "score_above_threshold"
                                reuse_reason = "score_above_threshold"
                                pages_text[page_num] = clean_pdf_text(reuse_text)
                                raw_texts[page_num] = reuse_text
                                page_info["ocr_attempted"] = False
                                page_info["ocr_used"] = False
                                page_info["reason"] = ["reused_existing_text"]
                                page_info["reused_text_similarity"] = reuse_similarity
                                page_info["reused_text_source"] = "database"
                                logger.info(
                                    "Page %s: reused existing database text with similarity %.3f",
                                    page_num + 1,
                                    reuse_similarity,
                                )
                                page_details.append(page_info)
                                if labels and page_num < len(labels) and labels[page_num] is not None:
                                    page_labels.append(labels[page_num])
                                else:
                                    page_labels.append(str(page_num + 1))
                                _log_text_reuse_decision(
                                    page_num + 1,
                                    candidate_count,
                                    reuse_similarity,
                                    REUSE_TEXT_SIMILARITY_THRESHOLD,
                                    decision,
                                    decision_reason,
                                    reuse_source_pdf_id,
                                    reuse_source_page,
                                )
                                continue
                            decision_reason = "score_below_threshold"
                            reuse_reason = "score_below_threshold"
                        else:
                            decision_reason = "no_candidates"
                            reuse_reason = "no_candidates"

                        if not reuse_text and known_page_texts:
                            fallback_text, fallback_similarity = _find_best_reusable_text(candidate_text, known_page_texts)
                            if fallback_text and fallback_similarity >= REUSE_TEXT_SIMILARITY_THRESHOLD:
                                reuse_text = fallback_text
                                reuse_similarity = fallback_similarity
                                best_score = fallback_similarity
                                decision = "REUSE"
                                decision_reason = "score_above_threshold"
                                reuse_reason = "score_above_threshold"
                                pages_text[page_num] = clean_pdf_text(reuse_text)
                                raw_texts[page_num] = reuse_text
                                page_info["ocr_attempted"] = False
                                page_info["ocr_used"] = False
                                page_info["reason"] = ["reused_existing_text"]
                                page_info["reused_text_similarity"] = reuse_similarity
                                page_info["reused_text_source"] = "database"
                                logger.info(
                                    "Page %s: reused existing database text with similarity %.3f",
                                    page_num + 1,
                                    reuse_similarity,
                                )
                                page_details.append(page_info)
                                if labels and page_num < len(labels) and labels[page_num] is not None:
                                    page_labels.append(labels[page_num])
                                else:
                                    page_labels.append(str(page_num + 1))
                                _log_text_reuse_decision(
                                    page_num + 1,
                                    candidate_count or len(known_page_texts),
                                    reuse_similarity,
                                    REUSE_TEXT_SIMILARITY_THRESHOLD,
                                    decision,
                                    decision_reason,
                                    None,
                                    None,
                                )
                                continue
                    except Exception as exc:
                        decision_reason = f"comparison_error:{type(exc).__name__}"
                        reuse_reason = decision_reason
                        logger.debug("Text reuse comparison failed for page %s: %s", page_num + 1, exc)
                else:
                    decision_reason = "no_candidate_text"
                    reuse_reason = "no_candidate_text"

                _log_text_reuse_decision(
                    page_num + 1,
                    candidate_count,
                    best_score,
                    REUSE_TEXT_SIMILARITY_THRESHOLD,
                    "OCR",
                    decision_reason,
                    reuse_source_pdf_id,
                    reuse_source_page,
                )

                if visual_signature and known_page_records:
                    try:
                        candidate_records = [record for record in known_page_records if record.get("visual_signature")]
                        candidate_count = len(candidate_records)
                        comparison_started = candidate_count > 0
                        if candidate_count > 0:
                            reusable_text, similarity = _find_best_reusable_visual_text(visual_signature, candidate_records)
                            best_score = similarity
                            if reusable_text and similarity >= VISUAL_REUSE_SIMILARITY_THRESHOLD:
                                decision = "REUSE_TEXT"
                                decision_reason = "score_above_threshold"
                                pages_text[page_num] = clean_pdf_text(reusable_text)
                                raw_texts[page_num] = reusable_text
                                page_info["ocr_attempted"] = False
                                page_info["ocr_used"] = False
                                page_info["reason"] = ["reused_existing_visual_text"]
                                page_info["reused_text_similarity"] = similarity
                                page_info["reused_text_source"] = "database_visual"
                                logger.info(
                                    "Page %s: reused existing database text from visual signature with similarity %.3f",
                                    page_num + 1,
                                    similarity,
                                )
                                page_details.append(page_info)
                                if labels and page_num < len(labels) and labels[page_num] is not None:
                                    page_labels.append(labels[page_num])
                                else:
                                    page_labels.append(str(page_num + 1))
                                _log_visual_reuse_decision(
                                    page_num + 1,
                                    known_page_records,
                                    visual_signature,
                                    comparison_started,
                                    candidate_count,
                                    best_score,
                                    VISUAL_REUSE_SIMILARITY_THRESHOLD,
                                    decision,
                                    decision_reason,
                                )
                                continue
                            decision_reason = "score_below_threshold"
                        else:
                            decision_reason = "no_candidates_with_signature"
                    except Exception as exc:
                        decision_reason = f"comparison_error:{type(exc).__name__}"
                        logger.debug("Visual signature comparison failed for page %s: %s", page_num + 1, exc)
                elif not visual_signature:
                    decision_reason = "page_signature_failed"
                elif not known_page_records:
                    decision_reason = "no_known_records"

                _log_visual_reuse_decision(
                    page_num + 1,
                    known_page_records,
                    visual_signature,
                    comparison_started,
                    candidate_count,
                    best_score,
                    VISUAL_REUSE_SIMILARITY_THRESHOLD,
                    decision,
                    decision_reason,
                )

                ocr_candidates.append((page_num, page, cleaned, page_info, page_images))

            pages_text[page_num] = cleaned
            raw_texts[page_num] = raw_text
            page_details.append(page_info)
            if labels and page_num < len(labels) and labels[page_num] is not None:
                page_labels.append(labels[page_num])
            else:
                page_labels.append(str(page_num + 1))
        except Exception as e:
            logger.warning(f"Failed to extract page {page_num + 1}: {e}")
            pages_text[page_num] = ""
            raw_texts[page_num] = ""
            page_details.append(page_info)
            if labels and page_num < len(labels) and labels[page_num] is not None:
                page_labels.append(labels[page_num])
            else:
                page_labels.append(str(page_num + 1))

    if ocr_candidates:
        max_workers = _choose_ocr_worker_count(ocr_candidates, page_details)
        logger.info("OCR_POOL workers=%s candidates=%d", max_workers, len(ocr_candidates))
        logger.info("Starting OCR pool: max_workers=%s candidates=%d", max_workers, len(ocr_candidates))

        # If there is only one candidate, avoid ThreadPool overhead and run synchronously.
        if len(ocr_candidates) == 1:
            page_num, page, cleaned, page_info, image_mode = ocr_candidates[0]
            try:
                ocr_text, ocr_ms = _ocr_page_worker(page_num, page, timings, image_mode=image_mode)
            except Exception as exc:
                logger.warning("Page %s OCR failed: %s", page_num + 1, exc)
                ocr_text, ocr_ms = "", 0.0

            logger.info("Page %s OCR time: %.0f ms", page_num + 1, ocr_ms)
            if timings is not None:
                _record_timing(timings, "page_ocr_ms", ocr_ms)

            if ocr_text:
                chosen = _choose_page_text(cleaned, ocr_text, prefer_ocr=image_mode)
                if chosen != cleaned:
                    used_ocr = True
                    page_info["ocr_used"] = True
                    logger.info(
                        "Page %s: OCR yielded better text (native %d words, ocr %d words, final %d words)",
                        page_num + 1,
                        _count_text_words(cleaned),
                        _count_text_words(clean_pdf_text(ocr_text)),
                        _count_text_words(chosen),
                    )
                pages_text[page_num] = chosen
            page_info["ocr_ms"] = ocr_ms
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_page = {
                    executor.submit(_ocr_page_worker, page_num, page, timings, image_mode=image_mode): (page_num, cleaned, page_info)
                    for page_num, page, cleaned, page_info, image_mode in ocr_candidates
                }
                for future in as_completed(future_to_page):
                    page_num, cleaned, page_info = future_to_page[future]
                    ocr_text = ""
                    ocr_ms = 0.0
                    try:
                        ocr_text, ocr_ms = future.result()
                    except Exception as exc:
                        logger.warning("Page %s OCR failed in thread: %s", page_num + 1, exc)

                    logger.info("Page %s OCR time: %.0f ms", page_num + 1, ocr_ms)
                    if timings is not None:
                        _record_timing(timings, "page_ocr_ms", ocr_ms)

                    if ocr_text:
                        chosen = _choose_page_text(cleaned, ocr_text, prefer_ocr=image_mode)
                        if chosen != cleaned:
                            used_ocr = True
                            page_info["ocr_used"] = True
                            logger.info(
                                "Page %s: OCR yielded better text (native %d words, ocr %d words, final %d words)",
                                page_num + 1,
                                _count_text_words(cleaned),
                                _count_text_words(clean_pdf_text(ocr_text)),
                                _count_text_words(chosen),
                            )
                        pages_text[page_num] = chosen
                    page_info["ocr_ms"] = ocr_ms

    if timings is not None:
        for page_info in page_details:
            timings["page_details"].append(page_info)
            _record_timing(timings, "pages_with_ocr", 1 if page_info["ocr_attempted"] else 0)
            _record_timing(timings, "pages_with_ocr_used", 1 if page_info["ocr_used"] else 0)
            if not page_info["ocr_attempted"] and page_info.get("page_images"):
                _record_timing(timings, "image_pages_skipped_ocr", 1)
            if (
                page_info["ocr_attempted"]
                and not page_info.get("page_images")
                and not page_info.get("is_noisy")
                and page_info.get("clean_length", 0) >= 40
                and page_info.get("word_count", 0) >= 3
            ):
                _record_timing(timings, "unnecessary_ocr_pages", 1)
            _record_timing(timings, "page_count", 1)
            if page_info["reason"]:
                for reason in page_info["reason"]:
                    key = f"reason_{reason}"
                    _record_timing(timings, key, 1)

    total = len(doc)
    doc.close()
    if timings is not None:
        _record_timing(timings, "extract_pages_ms", (time.perf_counter() - start_total) * 1000.0)
    return pages_text, raw_texts, total, used_ocr, page_labels


def compress_pdf(pdf_bytes: bytes) -> Tuple[bytes, bool]:
    """Try to compress a PDF using PyMuPDF deflate. Returns (bytes, was_compressed)."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        out = doc.tobytes(garbage=4, deflate=True, clean=True)
        doc.close()
        if len(out) < len(pdf_bytes) * 0.95:
            return out, True
        return pdf_bytes, False
    except Exception as e:
        logger.warning(f"Compression failed: {e}")
        return pdf_bytes, False


def sanitize_snippet_for_api(snippet: str) -> str:
    """Sanitize snippet for API responses: AGGRESSIVELY remove internal markers,
    musical chords and OCR noise while preserving real text. Collapse whitespace
    and join broken lines with ", ".
    This function is safe for presentation and does NOT affect indexed text.
    """
    if not snippet:
        return ""
    s = str(snippet)
    # Replace internal newline marker (U+23CE) and real newlines with a visual separator
    parts = re.split(r"\u23CE|\r?\n", s)
    cleaned_parts = []
    for p in parts:
        # Step 1: Remove all decorative and non-readable glyphs
        p = p.replace("\u00a0", " ")
        p = p.replace("\xa0", " ")
        p = re.sub(r"[œŒ˙…⏎⏭⏮ªº°†‡‰′″‴⁰¹²³⁴⁵⁶⁷⁸⁹]+", " ", p)
        
        # Step 2: Normalize various apostrophes
        p = re.sub(r"[''`´`]+", "'", p)
        
        # Step 3: Remove ALL control characters and invalid unicode
        p = re.sub(r"[\u0000-\u001F\u007F-\u009F\u200B-\u200D\uFEFF]+", " ", p)
        
        # Step 4: AGGRESSIVELY remove musical notation and accordi
        # Remove decorative page numbers like "~ 846 ~" or "~ 123 ~"
        p = re.sub(r"~\s*\d+\s*~", " ", p)
        # Remove notes: DO, RE, MI, FA, SOL, LA, SI with any variants
        p = re.sub(r"\b(?:DO|RE|MI|FA|SOL|LA|SI)(?:[#b\-\d/]*)\b", " ", p, flags=re.IGNORECASE)
        # Remove chord notations: A#m, G7, D/F#, Cmaj7, etc.
        p = re.sub(r"(?<!\w)\b[A-G](?:#|b)?(?:maj|min|m|dim|aug|sus|add)?\d*(?:/[A-G](?:#|b)?\d*)?\b", " ", p, flags=re.IGNORECASE)
        # Remove standalone single-letter tokens that are likely chords
        p = re.sub(r"\b([A-G])\s+(?=[A-GÀ-ÿ#b]|\d|$)", " ", p, flags=re.IGNORECASE)
        # Remove sequences that look like OCR noise: ##, ??, &&, etc.
        p = re.sub(r"([#?&]+)\s*\1+", " ", p)
        
        # Step 5: Remove repeated/malformed punctuation sequences
        p = re.sub(r"(?:[.,;:!?])\s*(?:[.,;:!?])+", ".", p)
        
        # Step 6: Remove common accidental/artifact punctuation sequences
        p = re.sub(r"[^A-Za-z0-9À-ÿ\s'.,;:\-?!()]+", " ", p)
        
        # Step 7: Collapse repeated whitespace
        p = re.sub(r"\s+", " ", p)
        p = p.strip(" .,;:-\n\r\t")
        
        if not p:
            continue
        
        # Step 8: Filter out parts that are mostly non-letters (likely noise)
        words = [w for w in p.split() if re.search(r"[A-Za-zÀ-ÿ0-9]", w)]
        if not words:
            continue
        
        # Step 9: Skip parts that are composed mostly of short tokens (likely pure chord sections)
        short_tokens = sum(1 for w in words if len(re.sub(r"[^A-Za-zÀ-ÿ0-9]","",w)) <= 2)
        if len(words) >= 3 and (short_tokens / len(words)) > 0.6:
            # If all or mostly short tokens in a multi-word line, it's likely a chord line
            continue
        
        # Step 10: Reject if the part looks like ONLY punctuation and numbers (common in OCR)
        letter_ratio = sum(1 for w in words if re.search(r"[A-Za-zÀ-ÿ]", w)) / len(words) if words else 0
        if letter_ratio < 0.5:
            continue
        
        cleaned_parts.append(" ".join(words))
    
    # Join with comma separator for preview
    out = ", ".join(cleaned_parts)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _normalize_text_and_map_for_snippet(text: str) -> Tuple[str, List[int]]:
    """Normalize text similar to normalize_pdf_text but also return a map from
    normalized character index -> original character index. The normalized string
    is lowercase, NFKD, combining diacritics removed, apostrophes normalized to
    single apostrophe, hyphens -> space, and non-alnum (except apostrophe) -> space.
    Consecutive spaces are collapsed.
    """
    if not text:
        return "", []
    s = str(text).replace("\r", " ").replace("\n", " ")
    s = unicodedata.normalize("NFKD", s)
    # We'll remove combining diacritics per-char below; create arrays
    norm_chars = []
    map_norm_to_orig = []
    last_was_space = False
    for i, ch in enumerate(s):
        # remove combining diacritics
        decomposed = unicodedata.normalize("NFKD", ch)
        # take base characters (remove combining marks)
        base = ''.join([c for c in decomposed if not unicodedata.category(c).startswith('M')])
        if not base:
            # treat as separator
            if not last_was_space:
                norm_chars.append(' ')
                map_norm_to_orig.append(i)
                last_was_space = True
            continue
        c = base
        # normalize apostrophe variants
        if APOSTROPHE_RE.search(c):
            out = "'"
        else:
            out = c
        # hyphens/dashes -> space
        if re.match(r"[-–—_]+", out):
            if not last_was_space:
                norm_chars.append(' ')
                map_norm_to_orig.append(i)
                last_was_space = True
            continue
        # keep letters/numbers/apostrophe, else space
        if re.match(r"[A-Za-z0-9']", out):
            # lowercase each character in out (could be multiple characters)
            for ch2 in out:
                norm_chars.append(ch2.lower())
                map_norm_to_orig.append(i)
            last_was_space = False
        else:
            if not last_was_space:
                norm_chars.append(' ')
                map_norm_to_orig.append(i)
                last_was_space = True
    # trim leading/trailing spaces
    while norm_chars and norm_chars[0] == ' ':
        norm_chars.pop(0); map_norm_to_orig.pop(0)
    while norm_chars and norm_chars[-1] == ' ':
        norm_chars.pop(); map_norm_to_orig.pop()
    # collapse multiple spaces in normalized string (map keeps first index of group)
    final_chars = []
    final_map = []
    prev_space = False
    for ch, idx in zip(norm_chars, map_norm_to_orig):
        if ch == ' ':
            if prev_space:
                continue
            prev_space = True
            final_chars.append(' ')
            final_map.append(idx)
        else:
            prev_space = False
            final_chars.append(ch)
            final_map.append(idx)
    normalized = ''.join(final_chars)
    return normalized, final_map


def make_snippet(text: str, query: str, length: int = 200) -> str:
    """Return a snippet of `text` around the first occurrence of `query`.
    Removes decorative numbers (~N~) to avoid confusing the user.

    This implementation locates the match using a normalized version of the
    text (accent/apostrophe-insensitive) and maps the normalized indices back to
    original offsets to extract a user-facing snippet from the original text.
    """
    if not text:
        return ""
    # Remove decorative page numbers before processing snippet
    text = DECORATIVE_NUMBER_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)

    q = (query or "").strip()
    if not q:
        return text[:length]

    # Normalize text with mapping and normalize query similarly
    txt_norm, map_norm_to_orig = _normalize_text_and_map_for_snippet(text)
    q_norm = normalize_search_query(q)
    # normalize_search_query produces capitalized first letter in original function;
    # for matching we lowercase both
    txt_norm_l = txt_norm.lower()
    q_norm_l = (q_norm or "").lower()

    idx = -1
    if q_norm_l:
        idx = txt_norm_l.find(q_norm_l)
    if idx >= 0:
        # Map normalized index range back to original indices
        start_norm_idx = idx
        end_norm_idx = idx + len(q_norm_l) - 1
        # guard indexes
        if start_norm_idx < 0: start_norm_idx = 0
        if end_norm_idx >= len(map_norm_to_orig): end_norm_idx = len(map_norm_to_orig) - 1
        start_orig = map_norm_to_orig[start_norm_idx]
        end_orig = map_norm_to_orig[end_norm_idx] + 1
        # Build snippet around original indices
        start = max(0, start_orig - length // 3)
        end = min(len(text), end_orig + length)
        snippet = text[start:end]
    else:
        # Fallback: previous behavior trying raw lowercase find
        lower = text.lower()
        q_raw = q.lower()
        idx2 = lower.find(q_raw)
        if idx2 < 0:
            first = q_raw.split()[0] if q_raw.split() else q_raw
            idx2 = lower.find(first)
        if idx2 < 0:
            return text[:length].strip()
        start = max(0, idx2 - length // 3)
        end = min(len(text), idx2 + length)
        snippet = text[start:end]

    # Preserve explicit linebreak positions in snippets using a visible marker (U+23CE).
    snippet = re.sub(r"\s*\r?\n+\s*", ".\u23CE", snippet)
    snippet = re.sub(r"\s+", " ", snippet)
    snippet = snippet.strip()
    if start > 0:
        snippet = "… " + snippet
    if end < len(text):
        snippet = snippet + " …"
    return snippet
