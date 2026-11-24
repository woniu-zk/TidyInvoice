"""Tests for the no-API local recognition engine (direct parsing + local OCR)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import local_recognition as lr
from invoice_domain import InvoiceRecord, DocumentIdentity

SAMPLE_EINVOICE_TEXT = """电子发票（普通发票）
发票号码：26112000000012345678
开票日期：2026年03月15日
购买方信息
名称：北京示例科技有限公司
统一社会信用代码/纳税人识别号：91110108MA01ABCDEF
销售方信息
名称：上海滴滴出行科技有限公司
统一社会信用代码/纳税人识别号：91310115MA1K9XYZ12
项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额
*运输服务*客运服务费 1 100.00 100.00 3% 3.00
合计 ¥100.00 ¥3.00
价税合计（大写）壹佰零叁元整 （小写）¥103.00
备注：
"""


class FakeOcrEngine:
    """Deterministic OCR double: returns fixed text blocks regardless of pixels."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.calls = 0

    def __call__(self, _image_bytes):
        self.calls += 1
        blocks = []
        for index, text in enumerate(self._lines):
            y = float(index * 30)
            blocks.append([[[0.0, y], [200.0, y], [200.0, y + 20.0], [0.0, y + 20.0]], text, 0.99])
        return blocks, [0.01]


def _write_pdf_with_text(path: Path, lines: list[str]) -> Path:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72.0, 90.0 + index * 28.0), line, fontname="china-s", fontsize=11)
    document.save(str(path))
    document.close()
    return path


def _write_blank_pdf(path: Path) -> Path:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    document.new_page()  # no text layer at all, like a scanned invoice
    document.save(str(path))
    document.close()
    return path


def _write_ofd(path: Path, lines: list[str]) -> Path:
    text_objects = []
    for index, line in enumerate(lines):
        y = 900 - index * 30
        text_objects.append(
            '<ofd:TextObject ID="%d" Boundary="20 %d 500 20">'
            '<ofd:TextCode X="20" Y="%d">%s</ofd:TextCode>'
            "</ofd:TextObject>" % (index, y, y, line)
        )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ofd:Page xmlns:ofd="http://www.ofdspec.org/2016"><ofd:Content>'
        + "".join(text_objects)
        + "</ofd:Content></ofd:Page>"
    )
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr("OFD.xml", "<ofd:OFD/>")
        archive.writestr("Doc_0/Pages/Page_0/Content.xml", content)
    return path


def _write_invoice_xml(path: Path) -> Path:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Invoice>"
        "<fphm>26112000000012345678</fphm>"
        "<kprq>2026-03-15</kprq>"
        "<gmfmc>北京示例科技有限公司</gmfmc>"
        "<xfmc>上海示例出行科技有限公司</xfmc>"
        "<jshj>103.00</jshj>"
        "</Invoice>",
        encoding="utf-8",
    )
    return path


def test_text_payload_maps_all_core_fields():
    result = lr.extract_invoice_payload(SAMPLE_EINVOICE_TEXT, engine=lr.ENGINE_PDF_TEXT)

    assert result.reason_code == lr.REASON_OK
    payload = result.payload
    assert payload is not None
    assert payload["is_invoice"] is True
    assert payload["InvoiceNumber"] == "26112000000012345678"
    assert payload["Date"] == "2026-03-15"
    assert payload["Seller"] == "上海滴滴出行科技有限公司"
    assert payload["Purchaser"] == "北京示例科技有限公司"
    assert payload["Amount"] == "103.00"
    assert payload["Type"] == "打车"
    assert payload["local_recognition"]["confidence"] >= 0.9


def test_payload_items_keep_full_star_cells():
    payload = lr.extract_invoice_payload(SAMPLE_EINVOICE_TEXT, engine=lr.ENGINE_PDF_TEXT).payload
    assert payload is not None
    assert payload["Item"] == "*运输服务*客运服务费"


def test_item_names_dedupes_and_caps_at_five_cells():
    text = "\n".join(
        [
            "电子发票（普通发票）",
            "*供电*电费 1 84.27",
            "*供电*充电服务费 1 38.54",
            "*餐饮服务*餐费 1 10.00",
            "*餐饮服务*餐费 1 10.00",
            "*住宿服务*住宿费 1 20.00",
            "*运输服务*客运服务费 1 1.00",
            "*信息服务*技术服务费 1 2.00",
        ]
    )

    names = lr._FieldExtractor(text).item_names()

    assert names == (
        "*供电*电费 | *供电*充电服务费 | *餐饮服务*餐费 | *住宿服务*住宿费 | *运输服务*客运服务费"
    )
    assert lr._FieldExtractor(text).item_text() == "*供电*电费"


def test_item_names_falls_back_to_goods_name_row():
    text = "\n".join(
        [
            "电子发票（普通发票）",
            "货物或应税劳务、服务名称",
            "住宿服务 441.15 441.15 6% 26.47",
            "价税合计（小写）¥467.62",
        ]
    )

    assert lr._FieldExtractor(text).item_names() == "住宿服务"


def test_xml_payload_includes_item_and_tax_ids(tmp_path: Path):
    xml = tmp_path / "invoice-item.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Invoice>"
        "<fphm>26112000000012345678</fphm>"
        "<kprq>2026-03-15</kprq>"
        "<gmfmc>北京示例科技有限公司</gmfmc>"
        "<xfmc>上海示例出行科技有限公司</xfmc>"
        "<jshj>103.00</jshj>"
        "<spmc>*餐饮服务*餐费</spmc>"
        "<xfsbh>91310115MA1K9XYZ12</xfsbh>"
        "<gfsbh>91110108MA01ABCDEF</gfsbh>"
        "</Invoice>",
        encoding="utf-8",
    )

    result = lr.recognize_document(xml)

    assert result.payload is not None
    assert result.payload["Item"] == "*餐饮服务*餐费"
    assert result.payload["seller_tin"] == "91310115MA1K9XYZ12"
    assert result.payload["buyer_tin"] == "91110108MA01ABCDEF"


def test_text_payload_survives_ocr_spacing_noise():
    noisy = "\n".join(
        ["电子发票（普通发票）", "发 票 号 码 ： 2 6 1 1 2 0 0 0 0 0 0 0 0 1 2 3 4 5 6 7 8 9 9"]
    )
    result = lr.extract_invoice_payload(SAMPLE_EINVOICE_TEXT.replace("发票号码：", "发 票 号 码 ："), engine=lr.ENGINE_OCR_PDF)
    assert result.payload is not None
    assert result.payload["InvoiceNumber"] == "26112000000012345678"
    # OCR-sourced results must be capped below the deterministic text-layer confidence.
    assert result.payload["local_recognition"]["confidence"] <= 0.85
    # The fully space-separated variant has no valid OCR line, but must not crash.
    empty = lr.extract_invoice_payload(noisy, engine=lr.ENGINE_OCR_PDF)
    assert empty.payload is None or empty.payload["is_invoice"] is True


def test_type_detection_for_catering_and_hotel():
    catering = SAMPLE_EINVOICE_TEXT.replace("*运输服务*客运服务费", "*餐饮服务*餐费").replace("上海滴滴出行科技有限公司", "上海某某餐饮有限公司")
    assert lr.extract_invoice_payload(catering, engine=lr.ENGINE_PDF_TEXT).payload["Type"] == "餐饮"

    hotel = SAMPLE_EINVOICE_TEXT.replace("*运输服务*客运服务费", "*住宿服务*住宿费").replace("上海滴滴出行科技有限公司", "上海某某酒店有限公司")
    assert lr.extract_invoice_payload(hotel, engine=lr.ENGINE_PDF_TEXT).payload["Type"] == "住宿发票"


def test_type_detection_for_beverage_and_charging_details():
    tea_drink = SAMPLE_EINVOICE_TEXT.replace(
        "*运输服务*客运服务费", "*软饮料*茶饮料"
    ).replace("上海滴滴出行科技有限公司", "江北新区啵啵先萃茶饮店（个体工商户）")
    assert (
        lr.extract_invoice_payload(tea_drink, engine=lr.ENGINE_PDF_TEXT).payload["Type"]
        == "餐饮"
    )

    milk_tea = SAMPLE_EINVOICE_TEXT.replace(
        "*运输服务*客运服务费", "*生产生活服务*原叶鲜奶茶10选2"
    ).replace("上海滴滴出行科技有限公司", "广州市番禺区石碁灿暖饮品店（个体工商户）")
    assert (
        lr.extract_invoice_payload(milk_tea, engine=lr.ENGINE_PDF_TEXT).payload["Type"]
        == "餐饮"
    )

    charging = SAMPLE_EINVOICE_TEXT.replace(
        "*运输服务*客运服务费 1 100.00 100.00 3% 3.00",
        "*供电*电费 1 84.27 84.27 13% 10.95\n*供电*充电服务费 1 38.54 38.54 13% 5.01",
    ).replace("上海滴滴出行科技有限公司", "广州市泷泽电子科技有限公司")
    assert (
        lr.extract_invoice_payload(charging, engine=lr.ENGINE_PDF_TEXT).payload["Type"]
        == "充电"
    )

    # 纯电费票不是充电票，避免办公/家用电费被并入充电类目。
    electricity_only = SAMPLE_EINVOICE_TEXT.replace(
        "*运输服务*客运服务费", "*供电*电费"
    ).replace("上海滴滴出行科技有限公司", "广州市泷泽电子科技有限公司")
    assert (
        lr.extract_invoice_payload(
            electricity_only, engine=lr.ENGINE_PDF_TEXT
        ).payload["Type"]
        == "其他"
    )


def test_partial_amount_row_reconciles_total():
    text = SAMPLE_EINVOICE_TEXT.replace(
        "合计 ¥100.00 ¥3.00\n价税合计（大写）壹佰零叁元整 （小写）¥103.00",
        "合计 ¥100.00 ¥3.00",
    )
    payload = lr.extract_invoice_payload(text, engine=lr.ENGINE_PDF_TEXT).payload
    assert payload is not None
    assert payload["Amount"] == "103.00"  # amount + tax fallback


def test_recognize_pdf_text_layer(tmp_path: Path):
    pdf = _write_pdf_with_text(tmp_path / "invoice.pdf", SAMPLE_EINVOICE_TEXT.splitlines())

    result = lr.recognize_document(pdf)

    assert result.engine == lr.ENGINE_PDF_TEXT
    assert result.payload is not None
    assert result.payload["InvoiceNumber"] == "26112000000012345678"
    assert result.payload["Amount"] == "103.00"


def test_recognize_scanned_pdf_uses_ocr(tmp_path: Path):
    pdf = _write_blank_pdf(tmp_path / "scanned.pdf")
    engine = FakeOcrEngine(SAMPLE_EINVOICE_TEXT.splitlines())

    result = lr.recognize_document(pdf, ocr_engine=engine)

    assert engine.calls >= 1
    assert result.engine == lr.ENGINE_OCR_PDF
    assert result.payload is not None
    assert result.payload["InvoiceNumber"] == "26112000000012345678"
    assert result.payload["local_recognition"]["confidence"] <= 0.85


def test_recognize_image_attachment_uses_ocr(tmp_path: Path):
    image = tmp_path / "invoice.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-image")
    engine = FakeOcrEngine(SAMPLE_EINVOICE_TEXT.splitlines())

    result = lr.recognize_document(image, ocr_engine=engine)

    assert result.engine == lr.ENGINE_OCR_IMAGE
    assert result.payload is not None
    assert result.payload["Seller"] == "上海滴滴出行科技有限公司"


def test_recognize_ofd_parses_textcode_nodes(tmp_path: Path):
    ofd = _write_ofd(tmp_path / "invoice.ofd", SAMPLE_EINVOICE_TEXT.splitlines())

    result = lr.recognize_document(ofd)

    assert result.engine == lr.ENGINE_OFD_TEXT
    assert result.payload is not None
    assert result.payload["InvoiceNumber"] == "26112000000012345678"
    assert result.payload["Amount"] == "103.00"
    assert result.payload["Date"] == "2026-03-15"


def test_recognize_xml_uses_structured_aliases(tmp_path: Path):
    xml = _write_invoice_xml(tmp_path / "invoice.xml")

    result = lr.recognize_document(xml)

    assert result.engine == lr.ENGINE_XML
    payload = result.payload
    assert payload is not None
    assert payload["InvoiceNumber"] == "26112000000012345678"
    assert payload["Date"] == "2026-03-15"
    assert payload["Seller"] == "上海示例出行科技有限公司"
    assert payload["Amount"] == "103.00"
    assert payload["seller_tin"] == ""
    assert payload["buyer_tin"] == ""


def test_missing_ocr_engine_fails_closed_without_network(monkeypatch, tmp_path: Path):
    pdf = _write_blank_pdf(tmp_path / "scanned.pdf")
    lr._reset_ocr_engine_for_tests()

    def _boom():
        raise lr.LocalRecognitionUnavailable(lr.REASON_OCR_UNAVAILABLE, "not installed")

    monkeypatch.setattr(lr, "_load_ocr_engine", _boom)
    result = lr.recognize_document(pdf)
    assert result.payload is None
    assert result.reason_code == lr.REASON_OCR_UNAVAILABLE


def test_worker_matches_pipeline_worker_contract(tmp_path: Path):
    ofd = _write_ofd(tmp_path / "invoice.ofd", SAMPLE_EINVOICE_TEXT.splitlines())
    worker = lr.LocalRecognitionWorker(output_dir=str(tmp_path))

    payload = worker.extract_remote_only(None, pdf_path=str(ofd))

    assert payload is not None
    assert payload["InvoiceNumber"] == "26112000000012345678"
    assert worker.last_extraction_trace["engine"] == lr.ENGINE_OFD_TEXT
    assert "local_recognition_ms" in worker.last_timing_trace


def test_shared_runtime_remote_extractor_resolves_local_payload(tmp_path: Path):
    from candidate_pipeline import CandidatePipeline
    from extraction_pipeline import SharedRuntimeRemoteExtractor

    ofd = _write_ofd(tmp_path / "invoice.ofd", SAMPLE_EINVOICE_TEXT.splitlines())
    candidate = CandidatePipeline().collect(
        [{"filepath": str(ofd), "email_id": "mail-1", "original_filename": "invoice.ofd"}]
    )[0]
    sidecar = {
        candidate.identity.document_id: {
            "pdf_path": str(ofd),
            "metadata": {"email_id": "mail-1"},
            "base64_img": None,
        }
    }
    extractor = SharedRuntimeRemoteExtractor(
        owner_extractor=object(),
        sidecar=sidecar,
        sidecar_lock=__import__("threading").Lock(),
        worker_factory=lambda _runtime: lr.LocalRecognitionWorker(),
    )

    outcome = extractor(candidate)

    assert outcome.status == "resolved"
    assert outcome.payload["info_json"]["InvoiceNumber"] == "26112000000012345678"
    assert outcome.payload["extraction_trace"]["engine"] == lr.ENGINE_OFD_TEXT


def test_local_payload_survives_invoice_record_boundary(tmp_path: Path):
    payload = lr.extract_invoice_payload(SAMPLE_EINVOICE_TEXT, engine=lr.ENGINE_PDF_TEXT).payload
    assert payload is not None
    identity = DocumentIdentity(document_id="doc-1", source_filename="invoice.pdf")
    record = InvoiceRecord.from_legacy(payload, identity)
    assert record.invoice_number == "26112000000012345678"
    assert record.seller == "上海滴滴出行科技有限公司"
    assert str(record.amount) == "103.00"
    assert str(record.invoice_date) == "2026-03-15"
    assert record.document_type == "打车"


def test_not_invoice_text_returns_no_payload():
    result = lr.extract_invoice_payload("这是一封普通的会议通知，请按时参加。", engine=lr.ENGINE_PDF_TEXT)
    assert result.payload is None
    assert result.reason_code == lr.REASON_NOT_INVOICE


def test_unsupported_extension_fails_closed(tmp_path: Path):
    other = tmp_path / "note.docx"
    other.write_bytes(b"PK\x03\x04")
    result = lr.recognize_document(other)
    assert result.payload is None
    assert result.reason_code == lr.REASON_UNSUPPORTED


# ---------------------------------------------------------------------------
# Real-engine integration (RapidOCR). Skipped when the optional wheel or a
# Chinese TTF font is unavailable in the environment.
# ---------------------------------------------------------------------------

_WINDOWS_CJK_FONTS = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def _find_cjk_font() -> str | None:
    for candidate in _WINDOWS_CJK_FONTS:
        if Path(candidate).is_file():
            return candidate
    return None


def _render_invoice_image(path: Path, lines: list[str]) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    font_path = _find_cjk_font()
    font = ImageFont.truetype(font_path, 30)
    image = Image.new("RGB", (1500, 1900), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((80, 120 + index * 60), line, fill="black", font=font)
    image.save(str(path))
    return path


def _require_real_ocr():
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:  # pragma: no cover - optional dependency
        pytest.skip("rapidocr-onnxruntime is not installed")
    if _find_cjk_font() is None:  # pragma: no cover - platform dependent
        pytest.skip("no CJK TTF font available to render a scanned fixture")


def test_real_ocr_reads_scanned_image(tmp_path: Path):
    _require_real_ocr()
    image = _render_invoice_image(tmp_path / "scan.png", SAMPLE_EINVOICE_TEXT.splitlines())

    result = lr.recognize_document(image)

    assert result.engine == lr.ENGINE_OCR_IMAGE
    assert result.text_length > 50
    assert result.payload is not None
    assert result.payload["InvoiceNumber"] == "26112000000012345678"
    assert result.payload["Amount"] == "103.00"
    assert result.payload["local_recognition"]["confidence"] <= 0.85


def test_real_ocr_reads_scanned_pdf(tmp_path: Path):
    _require_real_ocr()
    fitz = pytest.importorskip("fitz")
    image = _render_invoice_image(tmp_path / "scan.jpg", SAMPLE_EINVOICE_TEXT.splitlines())
    pdf = tmp_path / "scanned.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(0, 0, 595, 842), filename=str(image))
    document.save(str(pdf))
    document.close()

    result = lr.recognize_document(pdf)

    assert result.engine == lr.ENGINE_OCR_PDF
    assert result.payload is not None
    assert result.payload["InvoiceNumber"] == "26112000000012345678"


def test_app_api_pipeline_resolves_ofd_without_api_key(tmp_path: Path):
    """The production extraction session must resolve OFD with no API key at all."""
    from app_api import InvoiceAppAPI
    from invoice_extractor import InvoiceExtractor

    ofd = _write_ofd(tmp_path / "invoice.ofd", SAMPLE_EINVOICE_TEXT.splitlines())
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    api = InvoiceAppAPI()
    extractor = InvoiceExtractor(api_key="", output_dir=str(tmp_path))
    session = api._create_processing_pipeline_session(
        [{"filepath": str(ofd), "email_id": "mail-1", "original_filename": "invoice.ofd"}],
        "",
        str(output_dir),
        _extractor=extractor,
        _prepare_remote_images=False,
    )
    try:
        outcomes = session.extract()
    finally:
        session.close()

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status == "resolved"
    payload = outcome.to_legacy_payload()
    assert payload["info_json"]["InvoiceNumber"] == "26112000000012345678"
    assert payload["extraction_trace"]["engine"] == lr.ENGINE_OFD_TEXT


def test_start_processing_no_longer_requires_api_key(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    missing_email = api.start_processing("", str(tmp_path), email_address="", auth_code="")
    assert missing_email["success"] is False
    assert "邮箱" in missing_email["message"]


def test_test_connection_without_api_key_reports_local_engine():
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    result = api.test_connection("", "")
    assert result["success"] is False
    assert "授权码" in result["message"]


# ---------------------------------------------------------------------------
# Offline consistency checks + offline guarantee
# ---------------------------------------------------------------------------

def test_chinese_uppercase_amount_parser():
    from decimal import Decimal

    assert lr.parse_chinese_amount("壹佰零叁元整") == Decimal("103.00")
    assert lr.parse_chinese_amount("壹仟贰佰叁拾肆元伍角陆分") == Decimal("1234.56")
    assert lr.parse_chinese_amount("贰万零伍佰元整") == Decimal("20500.00")
    assert lr.parse_chinese_amount("零元整") == Decimal("0")


def test_uppercase_total_mismatch_lowers_confidence():
    text = SAMPLE_EINVOICE_TEXT.replace("壹佰零叁元整", "壹佰零肆元整")
    result = lr.extract_invoice_payload(text, engine=lr.ENGINE_PDF_TEXT)
    assert result.payload is not None
    assert "upper_amount_mismatch" in result.payload["local_recognition"]["warnings"]
    assert result.payload["local_recognition"]["confidence"] < 0.9


def test_uppercase_total_crosscheck_keeps_confidence_high():
    result = lr.extract_invoice_payload(SAMPLE_EINVOICE_TEXT, engine=lr.ENGINE_PDF_TEXT)
    assert result.payload is not None
    assert "upper_amount_mismatch" not in result.payload["local_recognition"]["warnings"]
    assert result.payload["local_recognition"]["confidence"] >= 0.9


def test_recognition_makes_no_network_calls(monkeypatch, tmp_path: Path):
    """Hard guarantee: recognition must work with sockets disabled."""
    import socket

    def _blocked(*_args, **_kwargs):
        raise OSError("network disabled by offline guarantee test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    pdf = _write_pdf_with_text(tmp_path / "invoice.pdf", SAMPLE_EINVOICE_TEXT.splitlines())

    result = lr.recognize_document(pdf)

    assert result.payload is not None
    assert result.payload["InvoiceNumber"] == "26112000000012345678"


def test_embedded_pdf_text_is_cached_per_file_and_invalidated(tmp_path: Path, monkeypatch):
    """The fast-path probes must share one PDF text extraction per source file."""
    import os
    import time

    import fitz

    from invoice_extractor import InvoiceExtractor

    pdf = _write_pdf_with_text(tmp_path / "invoice.pdf", SAMPLE_EINVOICE_TEXT.splitlines())
    extractor = InvoiceExtractor(api_key="", output_dir=str(tmp_path / "extracted"))
    calls = {"count": 0}
    real_open = fitz.open

    def counting_open(*args, **kwargs):
        calls["count"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr("invoice_extractor.fitz.open", counting_open)
    first = extractor._extract_embedded_pdf_text(str(pdf))
    second = extractor._extract_embedded_pdf_text(str(pdf))

    assert first
    assert first == second
    assert calls["count"] == 1

    future = time.time() + 5
    os.utime(pdf, (future, future))
    extractor._extract_embedded_pdf_text(str(pdf))
    assert calls["count"] == 2




