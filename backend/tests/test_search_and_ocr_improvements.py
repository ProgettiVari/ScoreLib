import sys
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf_processor import _calculate_match_quality, _estimate_text_similarity


def test_build_content_signature_is_stable_for_equivalent_text():
    from pdf_processor import build_content_signature, _content_signature_similarity

    text_a = "  Ero perso nel peccato, Gesù mi ha trovato  "
    text_b = "Ero perso nel peccato Gesu mi ha trovato"

    signature_a = build_content_signature(text_a)
    signature_b = build_content_signature(text_b)

    assert _content_signature_similarity(signature_a, signature_b) >= 0.8
    assert build_content_signature("") == ""


def test_visual_signature_similarity_distinguishes_obviously_different_pages():
    from pdf_processor import _visual_signature_similarity

    same_a = {
        "dhash": "ffffffffffffffff",
        "bit_count": 64,
        "row_profile": [0.1] * 16,
        "col_profile": [0.1] * 16,
        "ink_density": 0.1,
        "aspect_ratio": 1.0,
    }
    same_b = dict(same_a)
    different = {
        "dhash": "0000000000000000",
        "bit_count": 64,
        "row_profile": [0.9] * 16,
        "col_profile": [0.9] * 16,
        "ink_density": 0.9,
        "aspect_ratio": 1.8,
    }

    assert _visual_signature_similarity(same_a, same_b) >= 0.99
    assert _visual_signature_similarity(same_a, different) == 0.0


def test_extract_pages_reuses_text_match_before_visual_or_ocr(monkeypatch):
    import pdf_processor
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as reportlab_canvas

    buf = io.BytesIO()
    canvas = reportlab_canvas.Canvas(buf, pagesize=(300, 420))
    image = Image.new("RGB", (180, 120), "white")
    drawer = ImageDraw.Draw(image)
    drawer.rectangle((10, 10, 170, 110), outline="black", width=4)
    drawer.text((20, 40), "Ero perso nel peccato", fill="black")
    canvas.drawImage(ImageReader(image), 60, 150, width=180, height=120)
    canvas.showPage()
    canvas.save()
    pdf_bytes = buf.getvalue()

    known_signature = {
        "dhash": "ffffffffffffffff",
        "bit_count": 64,
        "row_profile": [0.1] * 16,
        "col_profile": [0.1] * 16,
        "ink_density": 0.1,
        "aspect_ratio": 1.0,
    }

    monkeypatch.setattr(pdf_processor, "_build_visual_signature", lambda page, timings=None, page_num=None: known_signature)
    monkeypatch.setattr(pdf_processor, "_find_best_reusable_visual_text", lambda candidate_signature, known_page_records: ("VISUAL_REUSE", 0.99))
    monkeypatch.setattr(pdf_processor, "_quick_ocr_page_text", lambda *args, **kwargs: "Ero perso nel peccato")
    monkeypatch.setattr(pdf_processor, "_ocr_page_worker", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full OCR should not run when text reuse matches")))
    monkeypatch.setattr(pdf_processor, "_find_best_reusable_text_record", lambda candidate_text, known_page_records: ("TESTO RIUSATO", 0.99, "pdf-1", 3))

    pages_text, raw_texts, total_pages, used_ocr, page_labels = pdf_processor.extract_pages(
        pdf_bytes,
        known_page_texts=["TESTO RIUSATO"],
        known_page_records=[{"text": "TESTO RIUSATO", "visual_signature": known_signature, "pdf_id": "pdf-1", "page": 3}],
    )

    assert total_pages == 1
    assert pages_text[0] == "TESTO RIUSATO"
    assert raw_texts[0] == "TESTO RIUSATO"
    assert used_ocr is False


def test_text_pages_persist_visual_signature_without_ocr():
    import io
    from reportlab.pdfgen import canvas as reportlab_canvas
    import pdf_processor

    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 10)
    c.drawString(100, 700, "Cristo mi guida ancora oggi")
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    timings = {}
    pages_text, raw_texts, total_pages, used_ocr, page_labels = pdf_processor.extract_pages(pdf_bytes, timings=timings)

    assert total_pages == 1
    assert used_ocr is False
    assert pages_text[0]
    assert timings["page_details"][0]["visual_signature"]


def test_extract_pages_logs_visual_reuse_success(monkeypatch):
    import pdf_processor
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as reportlab_canvas

    buf = io.BytesIO()
    canvas = reportlab_canvas.Canvas(buf, pagesize=(300, 420))
    image = Image.new("RGB", (180, 120), "white")
    drawer = ImageDraw.Draw(image)
    drawer.rectangle((10, 10, 170, 110), outline="black", width=4)
    drawer.text((20, 40), "Ero perso nel peccato", fill="black")
    canvas.drawImage(ImageReader(image), 60, 150, width=180, height=120)
    canvas.showPage()
    canvas.save()
    pdf_bytes = buf.getvalue()

    known_signature = {
        "dhash": "ffffffffffffffff",
        "bit_count": 64,
        "row_profile": [0.1] * 16,
        "col_profile": [0.1] * 16,
        "ink_density": 0.1,
        "aspect_ratio": 1.0,
    }
    log_calls = []

    monkeypatch.setattr(pdf_processor, "_build_visual_signature", lambda page, timings=None, page_num=None: known_signature)
    monkeypatch.setattr(pdf_processor, "_find_best_reusable_visual_text", lambda candidate_signature, known_page_records: ("TESTO RIUSATO", 0.99))
    monkeypatch.setattr(pdf_processor, "_quick_ocr_page_text", lambda *args, **kwargs: "")
    monkeypatch.setattr(pdf_processor, "_ocr_page_worker", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full OCR should not run when visual reuse matches")))
    monkeypatch.setattr(
        pdf_processor,
        "_log_visual_reuse_decision",
        lambda page_num, known_page_records, visual_signature, comparison_started, candidate_count, best_score, threshold, decision, reason: log_calls.append({
            "page_num": page_num,
            "decision": decision,
            "reason": reason,
            "candidate_count": candidate_count,
            "best_score": best_score,
            "threshold": threshold,
        }),
    )

    pages_text, raw_texts, total_pages, used_ocr, page_labels = pdf_processor.extract_pages(
        pdf_bytes,
        known_page_texts=["TESTO RIUSATO"],
        known_page_records=[{"text": "TESTO RIUSATO", "visual_signature": known_signature}],
    )

    assert total_pages == 1
    assert pages_text[0] == "TESTO RIUSATO"
    assert used_ocr is False
    assert log_calls and log_calls[0]["decision"] == "REUSE_TEXT"
    assert log_calls[0]["reason"] == "score_above_threshold"


def test_text_only_pdf_does_not_trigger_ocr(monkeypatch):
    import io
    import pdf_processor
    from reportlab.pdfgen import canvas as reportlab_canvas

    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 10)
    c.drawString(100, 700, "Ciao mondo")
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    monkeypatch.setattr(pdf_processor, "_page_has_images", lambda page: True)
    monkeypatch.setattr(pdf_processor, "_quick_ocr_page_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OCR should not run for text-only PDFs")))
    monkeypatch.setattr(pdf_processor, "_ocr_page_worker", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OCR should not run for text-only PDFs")))

    pages_text, raw_texts, total_pages, used_ocr, page_labels = pdf_processor.extract_pages(pdf_bytes)

    assert total_pages == 1
    assert used_ocr is False
    assert pages_text[0]
    assert "Ciao mondo" in pages_text[0]


def test_failed_visual_match_falls_back_to_text_reuse(monkeypatch):
    import io
    import pdf_processor
    from reportlab.pdfgen import canvas as reportlab_canvas

    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 10)
    c.drawString(100, 700, "Ero perso nel peccato")
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    known_signature = {
        "dhash": "ffffffffffffffff",
        "bit_count": 64,
        "row_profile": [0.1] * 16,
        "col_profile": [0.1] * 16,
        "ink_density": 0.1,
        "aspect_ratio": 1.0,
    }

    monkeypatch.setattr(pdf_processor, "_build_visual_signature", lambda page, timings=None, page_num=None: known_signature)
    monkeypatch.setattr(pdf_processor, "_find_best_reusable_visual_text", lambda candidate_signature, known_page_records: ("", 0.0))
    monkeypatch.setattr(pdf_processor, "_quick_ocr_page_text", lambda *args, **kwargs: "Ero perso nel peccato")
    monkeypatch.setattr(pdf_processor, "_find_best_reusable_text", lambda candidate_text, known_page_texts: ("TESTO RIUSATO", 0.99))
    monkeypatch.setattr(pdf_processor, "_ocr_page_worker", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full OCR should not run when text reuse fallback matches")))

    pages_text, raw_texts, total_pages, used_ocr, page_labels = pdf_processor.extract_pages(
        pdf_bytes,
        known_page_texts=["TESTO RIUSATO"],
        known_page_records=[{"text": "TESTO RIUSATO", "visual_signature": known_signature}],
    )

    assert total_pages == 1
    assert pages_text[0] == "TESTO RIUSATO"
    assert used_ocr is False


def test_calculate_match_quality_prioritizes_phrase_similarity_over_single_word():
    target = "Cristo salvò col Suo prezioso sangue"
    phrase_query = "cristo salvo sangue"
    single_word_query = "sangue"

    phrase_quality = _calculate_match_quality(target, phrase_query)
    single_quality = _calculate_match_quality(target, single_word_query)

    assert phrase_quality >= 0.55
    assert phrase_quality > single_quality


def test_estimate_text_similarity_is_high_for_nearly_identical_phrases():
    text_a = "Cristo salvò col Suo prezioso sangue"
    text_b = "Cristo salvò col suo prezioso sangue"
    unrelated = "Dio mio ti benedica"

    assert _estimate_text_similarity(text_a, text_b) >= 0.9
    assert _estimate_text_similarity(text_a, unrelated) < 0.35


def test_typo_tolerant_ranking_still_prefers_phrase_like_queries():
    target = "Quando sei afflitto"
    typo_query = "qundo sei afflitto"
    single_word_query = "afflitto"

    typo_quality = _calculate_match_quality(target, typo_query)
    single_quality = _calculate_match_quality(target, single_word_query)

    assert typo_quality >= 0.8
    assert typo_quality > single_quality


def test_sanitize_snippet_for_api_drops_musical_noise():
    from pdf_processor import sanitize_snippet_for_api

    noisy = "& ? b b 26 œœ œ œœb œ chie - do se_il Si -"
    sanitized = sanitize_snippet_for_api(noisy)

    assert sanitized == ""
