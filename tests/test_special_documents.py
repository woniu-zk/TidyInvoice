"""Classification for supporting documents: toll summary sheets and invoice QR codes."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import pytest

import local_recognition as lr
from document_types import (
    DOCUMENT_TYPES,
    get_archive_folder,
    is_exempt_type,
    normalize_document_type,
)
from invoice_extractor import InvoiceExtractor

CHARGING_INVOICE_TEXT = """电子发票（普通发票）
发票号码：26442000012806743906
开票日期：2026年11月07日
购买方信息
名称：广州华伟医疗设备有限公司
统一社会信用代码/纳税人识别号：91440113MAE19LB505
销售方信息
名称：广州市泷泽电子科技有限公司
统一社会信用代码/纳税人识别号：914401015961809535
项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额
*供电*电费 1 134.27 134.27 13% 17.46
*供电*充电服务费 1 38.54 38.54 13% 5.01
合计 ¥172.81 ¥22.47
价税合计（大写）壹佰玖拾伍圆贰角捌分 （小写）¥195.28
备注：
"""

TOLL_SUMMARY_TEXT = """收费公路通行费电子票据汇总单
（按票据索引）
汇总单号:
开票申请日期: 2026-10-26
车牌号码
粤ACP9636
交易金额
¥76.47
购买方名称
广州华伟医疗设备有限公司
行程数量
14
票据数量
4
纳税人识别号
91440113MAE19LB505
票据信息
行程信息
共4张票据
¥76.47
¥2.23
共14段行程
¥76.47
价税合计（大写）
柒拾陆元肆角柒分
（小写）
¥76.47
"""

BAIWANG_QR = (
    "https://bwfp.baiwang.com/invoice/issue-scan/r.do?offline="
    "91440101MA59GKWR0R!!4E9536F73231F50CC08C4B80A1E3CB533CB8A801901554D6!1"
)


def _qr_image(path: Path, payload: str = BAIWANG_QR) -> Path:
    encoder = cv2.QRCodeEncoder_create()
    matrix = encoder.encode(payload)
    image = cv2.resize(matrix, None, fx=12, fy=12, interpolation=cv2.INTER_NEAREST)
    image = cv2.copyMakeBorder(image, 80, 80, 80, 80, cv2.BORDER_CONSTANT, value=255)
    cv2.imwrite(str(path), image)
    return path


def test_document_type_registry_supports_new_categories():
    assert DOCUMENT_TYPES["通行费汇总单"]["archive_folder"] == "通行费汇总单"
    assert DOCUMENT_TYPES["开票二维码"]["archive_folder"] == "开票二维码"
    assert is_exempt_type("通行费汇总单") is True
    assert is_exempt_type("开票二维码") is True
    assert normalize_document_type("收费公路通行费电子票据汇总单") == "通行费汇总单"
    assert normalize_document_type("扫码开票") == "开票二维码"
    assert get_archive_folder("通行费汇总单") == "通行费汇总单"
    assert get_archive_folder("开票二维码") == "开票二维码"


def test_charging_document_type_registry_and_text_aliases():
    assert DOCUMENT_TYPES["充电"]["archive_folder"] == "充电"
    # 充电票的购买方校验与其他类目一致，不做豁免（个人充电票仍会被分流）。
    assert is_exempt_type("充电") is False
    assert get_archive_folder("充电") == "充电"
    assert normalize_document_type("充电服务费") == "充电"
    assert normalize_document_type("充电桩服务费") == "充电"
    assert normalize_document_type("茶饮") == "餐饮"
    assert normalize_document_type("饮品店") == "餐饮"
    # 纯电费不是充电，办公电费票不能被吞进充电类目。
    assert normalize_document_type("电费") == "其他"


def test_charging_invoice_text_is_classified_and_archived(tmp_path: Path):
    result = lr.extract_invoice_payload(CHARGING_INVOICE_TEXT, engine=lr.ENGINE_PDF_TEXT)

    payload = result.payload
    assert payload is not None
    assert payload["Type"] == "充电"
    assert payload["category"] == "充电"
    assert payload["Date"] == "2026-11-07"
    assert payload["Amount"] == "195.28"
    assert payload["Seller"] == "广州市泷泽电子科技有限公司"

    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "charging-invoice.pdf"
    document = fitz.open()
    page = document.new_page()
    for index, line in enumerate(CHARGING_INVOICE_TEXT.splitlines()):
        page.insert_text((40, 60 + index * 20), line, fontname="china-s", fontsize=10)
    document.save(str(pdf))
    document.close()

    extractor = InvoiceExtractor(api_key="", output_dir=str(tmp_path / "out"))
    success, final_path = extractor.route_and_rename_file(str(pdf), payload)

    assert success is True
    assert Path(final_path).parent.name == "充电"
    assert "充电" in Path(final_path).name
    assert "195.28" in Path(final_path).name


def test_pure_electricity_invoice_stays_other():
    text = (
        CHARGING_INVOICE_TEXT.replace("*供电*充电服务费 1 38.54 38.54 13% 5.01\n", "")
        .replace("合计 ¥172.81 ¥22.47", "合计 ¥134.27 ¥17.46")
        .replace("壹佰玖拾伍圆贰角捌分", "壹佰伍拾壹圆柒角叁分")
        .replace("（小写）¥195.28", "（小写）¥151.73")
    )

    payload = lr.extract_invoice_payload(text, engine=lr.ENGINE_PDF_TEXT).payload

    assert payload is not None
    assert payload["Amount"] == "151.73"
    assert payload["Type"] == "其他"
    # 类型不是「其他」时才会拿到这条置信度加成，确保负例没有被顺带加分。
    assert "upper_amount_mismatch" not in payload["local_recognition"]["warnings"]


def test_toll_summary_text_is_classified_with_fields():
    result = lr.extract_invoice_payload(TOLL_SUMMARY_TEXT, engine=lr.ENGINE_PDF_TEXT)

    assert result.engine == lr.ENGINE_PDF_TEXT
    payload = result.payload
    assert payload is not None
    assert payload["Type"] == "通行费汇总单"
    assert payload["category"] == "通行费汇总单"
    assert payload["Date"] == "2026-10-26"
    assert payload["Amount"] == "76.47"
    assert payload["Purchaser"] == "广州华伟医疗设备有限公司"
    assert "粤ACP9636" in payload["Seller"]
    assert result.warnings == []
    assert result.confidence >= 0.85


def test_toll_summary_pdf_is_classified_end_to_end(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "toll-summary.pdf"
    document = fitz.open()
    page = document.new_page()
    for index, line in enumerate(TOLL_SUMMARY_TEXT.splitlines()):
        page.insert_text((40, 60 + index * 20), line, fontname="china-s", fontsize=10)
    document.save(str(pdf))
    document.close()

    result = lr.recognize_document(pdf)

    assert result.payload is not None
    assert result.payload["Type"] == "通行费汇总单"
    assert result.payload["Amount"] == "76.47"
    extractor = InvoiceExtractor(api_key="", output_dir=str(tmp_path / "out"))
    assert extractor._has_minimum_archive_fields(result.payload) is True


def test_qr_payload_detection_and_provider_mapping():
    assert lr._is_invoice_issuing_qr(BAIWANG_QR) is True
    assert lr._is_invoice_issuing_qr("https://nuonuo.com/invoice/abc") is True
    assert lr._is_invoice_issuing_qr("https://example.com/menu") is False
    assert lr._qr_provider_label(BAIWANG_QR) == "百望云"
    assert lr._qr_host(BAIWANG_QR) == "bwfp.baiwang.com"


def test_real_qr_image_decodes(tmp_path: Path):
    image = _qr_image(tmp_path / "qr.png")

    payloads = lr.decode_qr_payloads(image)

    assert BAIWANG_QR in payloads


def test_qr_image_is_classified_as_invoice_qr(tmp_path: Path, monkeypatch):
    image = _qr_image(tmp_path / "receipt.png")
    receipt_text = "\n".join(
        [
            "商品",
            "158.80",
            "饮料",
            "总计",
            "扫一扫领取电子发票",
            "2026-10-25 14:58:26",
        ]
    )
    monkeypatch.setattr(lr, "read_image_ocr_text", lambda *_args, **_kwargs: receipt_text)

    result = lr.recognize_document(image)

    assert result.engine == lr.ENGINE_QR_IMAGE
    payload = result.payload
    assert payload is not None
    assert payload["Type"] == "开票二维码"
    assert payload["Seller"] == "百望云"
    assert payload["Amount"] == "158.80"
    assert payload["Date"] == "2026-10-25"
    recognition = payload["local_recognition"]
    assert recognition["qr_provider"] == "百望云"
    assert len(recognition["qr_payload_sha256"]) == 64
    # The raw QR payload can contain a token; only its hash/provider may persist.
    assert BAIWANG_QR not in json.dumps(payload, ensure_ascii=False)


def test_qr_text_hint_classifies_when_payload_undecoded(tmp_path: Path, monkeypatch):
    image = tmp_path / "receipt-photo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-image")
    receipt_text = "\n".join(["电子发票", "扫码获取电子发票", "合计 66.00", "2026-11-01"])
    monkeypatch.setattr(lr, "read_image_ocr_text", lambda *_args, **_kwargs: receipt_text)
    monkeypatch.setattr(lr, "decode_qr_payloads", lambda *_args, **_kwargs: [])

    result = lr.recognize_document(image)

    assert result.payload is not None
    assert result.payload["Type"] == "开票二维码"
    assert result.payload["Amount"] == "66.00"
    assert "qr_payload_not_decoded" in result.warnings


def test_qr_minimum_archive_fields_and_naming(tmp_path: Path):
    extractor = InvoiceExtractor(api_key="", output_dir=str(tmp_path / "out"))
    payload = {
        "is_invoice": True,
        "Date": "2026-10-25",
        "Amount": "158.80",
        "Seller": "百望云",
        "Type": "开票二维码",
        "InvoiceNumber": "",
    }
    assert extractor._has_minimum_archive_fields(payload) is True

    source = tmp_path / "receipt.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nstub")
    success, final_path = extractor.route_and_rename_file(
        str(source), payload, custom_rules={"开票二维码": "开票二维码"}
    )
    assert success is True
    assert Path(final_path).parent.name == "开票二维码"
    assert "开票二维码" in Path(final_path).name
    assert "158.80" in Path(final_path).name


def test_toll_summary_minimum_fields_and_naming(tmp_path: Path):
    extractor = InvoiceExtractor(api_key="", output_dir=str(tmp_path / "out"))
    payload = {
        "is_invoice": True,
        "Date": "2026-10-26",
        "Amount": "76.47",
        "Seller": "通行费电子票据平台·粤ACP9636",
        "Type": "通行费汇总单",
        "InvoiceNumber": "",
    }
    assert extractor._has_minimum_archive_fields(payload) is True

    source = tmp_path / "summary.pdf"
    source.write_bytes(b"%PDF-1.4\nstub")
    success, final_path = extractor.route_and_rename_file(
        str(source), payload, custom_rules={"通行费汇总单": "通行费汇总单"}
    )
    assert success is True
    assert Path(final_path).parent.name == "通行费汇总单"
    assert "76.47" in Path(final_path).name

    missing_amount = dict(payload, Amount="")
    assert extractor._has_minimum_archive_fields(missing_amount) is False
