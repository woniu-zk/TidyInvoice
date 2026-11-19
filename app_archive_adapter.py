from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Callable

from archive_pairing_service import reconcile_archive_pairs
from archive_service import ArchiveDecision, ArchiveReport
from extraction_pipeline import ExtractionOutcome

class AppArchiveAdapter:
    """Product rule adapter used by ArchiveService's serialized owner loop."""

    def __init__(
        self,
        *,
        api: Any,
        extractor: Any,
        save_path: str,
        business_records: dict[str, Any],
        trace_store: Any,
        acceptance_service: Any | None = None,
        pairing_finalizer: Callable[[ArchiveReport, Path], None] | None = None,
        dry_run: bool = False,
        flat_layout: bool = False,
        classification_rule_set: Any | None = None,
    ) -> None:
        self.api = api
        self.extractor = extractor
        self.save_path = save_path
        self.business_records = business_records
        self.trace_store = trace_store
        self.dry_run = bool(dry_run)
        # Local mode without category subfolders: invoices archive into the
        # output root. Tool buckets (待人工复核/_audit_retention) keep their
        # folders so unreadable or retained material stays separable.
        self.flat_layout = bool(flat_layout)
        if classification_rule_set is None:
            from expense_rules import load_rule_set

            classification_rule_set = load_rule_set(save_path)
        self.classification_rule_set = classification_rule_set
        if acceptance_service is None:
            from document_acceptance import DocumentAcceptanceService

            acceptance_service = DocumentAcceptanceService(api)
        self.acceptance_service = acceptance_service
        self.pairing_finalizer = pairing_finalizer
        self.pairing_metadata: dict[str, dict[str, Any]] = {}
        self.business_keys_by_document_id: dict[str, str] = {}

    @staticmethod
    def _classification_row_fields(info_json: dict[str, Any]) -> dict[str, Any]:
        info_json = info_json or {}
        return {
            "type": str(info_json.get("Type") or ""),
            "category_id": str(info_json.get("category_id") or ""),
            "category_src": str(info_json.get("category_src") or ""),
            "classification_source": str(
                info_json.get("classification_source") or ""
            ),
            "classification_rule": str(info_json.get("classification_rule") or ""),
        }

    @staticmethod
    def _classification_reason_code(result: Any) -> str:
        source = str(getattr(result, "source", "") or "")
        if source == "dictionary":
            return "CLASSIFIED_BY_USER_TERM"
        if source in {"user_rule", "rule_pack"}:
            return "CLASSIFIED_BY_USER_RULE"
        if source == "builtin_keyword":
            return "CLASSIFIED_BY_BUILTIN_KEYWORD"
        if source == "builtin_type":
            return "CLASSIFIED_BY_INVOICE_TYPE"
        if source == "unknown":
            return "CLASSIFICATION_UNKNOWN"
        return ""

    @staticmethod
    def _classification_display_rule(result: Any) -> str:
        source = str(getattr(result, "source", "") or "")
        rule_id = str(getattr(result, "rule_id", "") or "")
        keyword = str(getattr(result, "keyword", "") or "")
        if source == "unknown":
            return "未命中"
        if source == "builtin_type":
            return rule_id or "票种兜底"
        if keyword:
            return f"{rule_id}:{keyword}" if rule_id else keyword
        return rule_id or source

    def _apply_expense_classification(
        self,
        *,
        payload: dict[str, Any],
        info_json: dict[str, Any],
        reason_codes: list[str],
    ) -> None:
        """Classify a safely archivable invoice and record the explanation."""
        from document_types import get_archive_folder, normalize_document_type
        from expense_rules import classify

        doc_type = normalize_document_type(info_json.get("Type", ""))
        info_json["Type"] = doc_type
        payload["info_json"] = info_json
        archive_status = str(payload.get("archive_status") or "")
        manual_reason = str(payload.get("manual_reason_code") or "")
        isolated_types = {"非目标公司发票", "个人非报销发票"}

        if archive_status in {"retained", "acceptance_rejected"} or manual_reason:
            folder = get_archive_folder(doc_type)
            payload.update(
                {
                    "category": folder,
                    "category_id": "",
                    "category_src": "builtin",
                    "archive_folder": folder,
                    "classification_source": "skipped",
                    "classification_rule": "",
                    "classification_explain": {
                        "status": "skipped",
                        "reason": manual_reason or archive_status,
                        "category": folder,
                    },
                }
            )
            return

        if doc_type in isolated_types:
            folder = get_archive_folder(doc_type)
            payload.update(
                {
                    "category": folder,
                    "category_id": "",
                    "category_src": "builtin",
                    "archive_folder": folder,
                    "classification_source": "isolation",
                    "classification_rule": doc_type,
                    "classification_explain": {
                        "status": "isolation",
                        "reason": "SAFETY_ISOLATION_TYPE",
                        "category": folder,
                    },
                }
            )
            return

        result = classify(
            {
                "seller": info_json.get("Seller", ""),
                "seller_tin": info_json.get("seller_tin")
                or info_json.get("Seller_TIN", ""),
                "item": info_json.get("Item") or info_json.get("item_name", ""),
                "type": doc_type,
                "amount": info_json.get("Amount", ""),
                "purchaser": info_json.get("Purchaser", ""),
            },
            self.classification_rule_set,
        )
        reason_code = self._classification_reason_code(result)
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)
        display_rule = self._classification_display_rule(result)
        payload.update(
            {
                "category": result.category_name,
                "category_id": result.category_id,
                "category_src": result.category_src,
                "archive_folder": result.archive_folder,
                "classification_source": result.source,
                "classification_rule": display_rule,
                "classification_explain": result.to_dict()
                if hasattr(result, "to_dict")
                else dict(getattr(result, "__dict__", {})),
            }
        )
        info_json.update(
            {
                "category": result.category_name,
                "category_id": result.category_id,
                "category_src": result.category_src,
                "classification_source": result.source,
                "classification_rule": display_rule,
            }
        )
        if result.source == "unknown":
            payload["archive_status"] = "manual_review"
            payload["manual_reason_code"] = "CLASSIFICATION_UNKNOWN"

    def _append_success_state(
        self,
        outcome: ExtractionOutcome,
        info_json: dict[str, Any],
        category: str,
        path: str,
    ) -> None:
        import time

        self.api.discovered_categories.add(category)
        self.api.processed_invoices.append(
            {
                "id": f"inv_{time.time()}_{outcome.candidate.sequence}",
                "document_id": outcome.candidate.identity.document_id,
                "date": info_json.get("Date", "---"),
                "amount": f"¥ {info_json.get('Amount', '0.00')}",
                "category": category,
                "merchant": info_json.get("Seller", "未知开票方"),
                "path": path,
                **self._classification_row_fields(info_json),
            }
        )
        self.api.stats["invoices"] = int(self.api.stats.get("invoices", 0)) + 1

    def _append_prefilter_error_state(
        self,
        outcome: ExtractionOutcome,
        path: str,
    ) -> None:
        import time

        is_manual = outcome.status == "manual_review"
        self.api.stats["errors"] = int(self.api.stats.get("errors", 0)) + 1
        self.api.error_invoices.append(
            {
                "id": f"inv_prefilter_{time.time()}_{outcome.candidate.sequence}",
                "document_id": outcome.candidate.identity.document_id,
                "date": "---",
                "amount": "---",
                "category": "人工复核" if is_manual else "预过滤保全",
                "merchant": "低置信度候选" if is_manual else "高/中置信度候选",
                "path": path,
                "name": os.path.basename(path),
                "sColor": "bg-yellow-500" if is_manual else "bg-blue-500",
                "status": "待人工复核" if is_manual else "已保全待判断",
                "reason": outcome.reason_code
                or ("P0_C_MANUAL_REVIEW" if is_manual else "P0_B_RETENTION"),
                "rColor": (
                    "text-yellow-600 border-yellow-200 bg-yellow-50"
                    if is_manual
                    else "text-blue-600 border-blue-200 bg-blue-50"
                ),
            }
        )

    def _append_classified_manual_state(
        self,
        outcome: ExtractionOutcome,
        info_json: dict[str, Any],
        category: str,
        path: str,
        reason_code: str,
    ) -> None:
        import time

        self.api.stats["errors"] = int(self.api.stats.get("errors", 0)) + 1
        self.api.error_invoices.append(
            {
                "id": f"inv_{time.time()}_{outcome.candidate.sequence}",
                "document_id": outcome.candidate.identity.document_id,
                "date": info_json.get("Date", "---"),
                "amount": f"¥ {info_json.get('Amount', '0.00')}",
                "category": category,
                "merchant": info_json.get("Seller", "未知开票方"),
                "path": path,
                "name": os.path.basename(path),
                "artifact_kind": "manual_check",
                "sColor": "bg-yellow-500",
                "status": "待人工复核",
                "reason": reason_code,
                "rColor": "text-yellow-600 border-yellow-200 bg-yellow-50",
                **self._classification_row_fields(info_json),
            }
        )

    def normalize(self, outcome: ExtractionOutcome) -> dict[str, Any]:
        import time

        from app_api import normalize_document_type_for_archive
        from company_rules import classify_purchaser_relation
        from document_types import (
            apply_strong_train_evidence_override,
            classify_cwt_document_type,
            is_exempt_type,
        )

        payload = outcome.to_legacy_payload()
        info_json = dict(payload.get("info_json") or {})
        metadata = dict(payload.get("metadata") or {})
        file_name = os.path.basename(
            payload.get("pdf_path") or outcome.candidate.source_path
        )
        pdf_path = str(payload.get("pdf_path") or outcome.candidate.source_path)
        pdf_health = self.api._inspect_pdf_health(pdf_path)
        acceptance = self.acceptance_service.evaluate(
            metadata,
            info_json,
            pdf_path,
            pdf_health=pdf_health,
        )
        payload["document_acceptance"] = acceptance
        payload["acceptance_pdf_health"] = pdf_health
        self.trace_store.set_fields(
            outcome.candidate.identity.document_id,
            document_acceptance=acceptance,
        )
        acceptance_rejected = not acceptance.get("accepted", True)
        if acceptance_rejected:
            payload["archive_status"] = "acceptance_rejected"
        else:
            from document_acceptance import DocumentAcceptanceService

            normalized_snapshot = self.acceptance_service.normalized_snapshot(info_json)
            DocumentAcceptanceService.write_canonical_fields(
                info_json, normalized_snapshot
            )
        original_type = str(info_json.get("Type") or "")
        seller = str(info_json.get("Seller") or "")
        is_cwt = (
            "citsgbt.com" in str(metadata.get("sender") or "").lower()
            or any(
                keyword in seller
                for keyword in (
                    "国旅运通",
                    "CWT",
                    "Carlson Wagonlit",
                    "citsgbt",
                    "GBT Travel",
                )
            )
            or any(
                keyword in str(metadata.get("subject") or "").lower()
                for keyword in ("citsgbt", "国旅运通", "cwt", "cits gbt", "scct")
            )
            or any(
                keyword in file_name.lower()
                for keyword in ("citsgbt", "国旅运通", "cwt", "scct")
            )
        )
        extraction_trace = dict(payload.get("extraction_trace") or {})
        if is_cwt:
            doc_type, reason_codes = classify_cwt_document_type(
                info_json,
                metadata,
                file_name,
                local_cits_fast_path=(
                    extraction_trace.get("engine") == "local_cits_gbt_pdf"
                    or extraction_trace.get("reason_code")
                    == "LOCAL_CITS_GBT_PDF_FAST_PATH"
                ),
            )
        else:
            doc_type, reason_codes = normalize_document_type_for_archive(
                info_json, file_name
            )
            preview_reader = getattr(self.api, "_extract_pdf_preview_text", None)
            doc_type, train_reason_codes = apply_strong_train_evidence_override(
                doc_type,
                original_type,
                seller,
                info_json,
                metadata,
                file_name,
                preview_loader=(
                    lambda: preview_reader(pdf_path, max_pages=1)
                    if callable(preview_reader)
                    else ""
                ),
            )
            reason_codes.extend(train_reason_codes)
            if (
                not train_reason_codes
                and original_type in {"住宿确认单", "航班行程单", "差旅服务费"}
            ):
                doc_type = original_type
                reason_codes.append("PRESERVED_REGISTERED_SUPPORTING_TYPE")
        info_json["Type"] = doc_type
        is_exempt = is_exempt_type(doc_type)
        payload["classification_reason_codes"] = reason_codes
        payload["is_exempt"] = is_exempt
        if (
            not acceptance_rejected
            and not bool(info_json.get("is_invoice", True))
            and not is_exempt
        ):
            payload["archive_status"] = "retained"
        elif not acceptance_rejected and not is_exempt:
            relation = classify_purchaser_relation(
                str(info_json.get("Purchaser") or ""),
                self.api._resolve_active_company(),
            )
            if relation == "non_target":
                info_json["Type"] = "非目标公司发票"
                message = (
                    "购买方与目标公司不匹配，已分流到非目标公司发票 "
                    "[CLASSIFIED_AS_NON_TARGET_COMPANY]"
                    if outcome.candidate.identity.source_kind == "url"
                    else (
                        "购买方与目标公司不匹配 "
                        f"({str(info_json.get('Purchaser') or '')})，已分流到非目标公司发票 "
                        "[CLASSIFIED_AS_NON_TARGET_COMPANY]"
                    )
                )
                try:
                    self.api.logs.append(
                        {
                            "time": time.strftime("[%H:%M:%S]"),
                            "type": "拦截:",
                            "color": "text-yellow-400",
                            "msg": message,
                        }
                    )
                except Exception:
                    pass
            elif relation == "unknown":
                payload["archive_status"] = "manual_review"
                payload["manual_reason_code"] = "COMPANY_PURCHASER_UNKNOWN"
        cwt_classified = any(
            reason.startswith("CLASSIFIED_AS_CWT_") or reason.startswith("CWT_")
            for reason in reason_codes
        )
        if (
            not acceptance_rejected
            and int(metadata.get("tier", 0) or 0) == 3
            and not cwt_classified
        ):
            payload["archive_status"] = "manual_review"
            payload["manual_reason_code"] = "TIER3_MANUAL_REVIEW"
        if not acceptance_rejected and info_json.get("_cwt_cancellation"):
            payload["archive_status"] = "manual_review"
        self._apply_expense_classification(
            payload=payload,
            info_json=info_json,
            reason_codes=reason_codes,
        )
        payload["classification_reason_codes"] = reason_codes
        if (
            payload.get("archive_status") not in {"retained", "acceptance_rejected"}
            and payload.get("manual_reason_code") != "COMPANY_PURCHASER_UNKNOWN"
            and payload.get("classification_source") != "unknown"
        ):
            self.api.discovered_categories.add(payload["category"])
        return payload

    @staticmethod
    def classify(payload: dict[str, Any]) -> str:
        return str(payload.get("category") or "其他")

    @staticmethod
    def dedupe_key(outcome: ExtractionOutcome, payload: dict[str, Any]) -> str:
        from app_api import build_business_record_key

        info_json = payload.get("info_json") or {}
        code = str(info_json.get("InvoiceCode") or "").strip()
        number = str(info_json.get("InvoiceNumber") or "").strip()
        if code or number:
            return build_business_record_key(
                code, number, info_json, outcome.candidate.source_filename
            )
        return outcome.candidate.identity.document_id

    # ------------------------------------------------------------------ preview
    @staticmethod
    def _planned_manual_path(save_path: str, filename: str, reason_prefix: str) -> str:
        from document_types import MANUAL_REVIEW_FOLDER

        return os.path.join(
            save_path,
            MANUAL_REVIEW_FOLDER,
            f"{reason_prefix}_{os.path.basename(filename)}",
        )

    @staticmethod
    def _planned_retention_path(save_path: str, bucket: str, filename: str) -> str:
        return os.path.join(
            save_path,
            "_audit_retention",
            str(bucket or "preview"),
            os.path.basename(filename),
        )

    def _append_preview_success_state(self, outcome, info_json, category, path):
        import time

        self.api.discovered_categories.add(category)
        self.api.processed_invoices.append(
            {
                "id": f"inv_preview_{time.time()}_{outcome.candidate.sequence}",
                "document_id": outcome.candidate.identity.document_id,
                "date": info_json.get("Date", "---"),
                "amount": f"¥ {info_json.get('Amount', '0.00')}",
                "category": category,
                "merchant": info_json.get("Seller", "未知开票方"),
                "path": path,
                "source": outcome.candidate.source_filename,
                "status": "预览归档",
                "preview": True,
                **self._classification_row_fields(info_json),
            }
        )
        self.api.stats["invoices"] = int(self.api.stats.get("invoices", 0)) + 1

    def _append_preview_error_state(
        self, outcome, path, info_json, category, reason, *, manual
    ):
        import time

        info_json = dict(info_json or {})
        self.api.stats["errors"] = int(self.api.stats.get("errors", 0)) + 1
        self.api.error_invoices.append(
            {
                "id": f"inv_preview_{time.time()}_{outcome.candidate.sequence}",
                "document_id": outcome.candidate.identity.document_id,
                "date": info_json.get("Date", "---"),
                "amount": (
                    f"¥ {info_json.get('Amount')}"
                    if info_json.get("Amount")
                    else "---"
                ),
                "category": category or ("人工复核" if manual else "证据保全"),
                "merchant": info_json.get("Seller", "未知开票方"),
                "path": path,
                "name": os.path.basename(path),
                "source": outcome.candidate.source_filename,
                "artifact_kind": "preview_manual" if manual else "preview_retention",
                "sColor": "bg-yellow-500" if manual else "bg-blue-500",
                "status": "预览-待人工确认" if manual else "预览-仅保全",
                "reason": reason,
                "rColor": (
                    "text-yellow-600 border-yellow-200 bg-yellow-50"
                    if manual
                    else "text-blue-600 border-blue-200 bg-blue-50"
                ),
                "preview": True,
                **self._classification_row_fields(info_json),
            }
        )

    def preview_operation(
        self,
        outcome: ExtractionOutcome,
        payload: dict[str, Any] | None,
        category: str,
        root: Path,
    ) -> ArchiveDecision:
        """Compute the planned outcome without copying, renaming, or persisting."""
        del category, root
        from document_types import MANUAL_REVIEW_FOLDER, get_archive_folder

        info_json = dict((payload or {}).get("info_json") or {})
        metadata = (
            dict(payload.get("metadata") or {})
            if isinstance(payload, dict)
            else outcome.candidate.to_legacy()
        )
        source_candidates = (
            (payload.get("pdf_path") if isinstance(payload, dict) else None),
            outcome.artifact_path,
            metadata.get("filepath"),
            outcome.candidate.source_path,
        )
        source_path = next((str(path) for path in source_candidates if path), "")
        base_name = (
            os.path.basename(source_path)
            or outcome.candidate.source_filename
            or "document"
        )

        if outcome.status != "resolved":
            if outcome.status == "manual_review":
                reason = outcome.reason_code or "PIPELINE_MANUAL_REVIEW"
                planned = self._planned_manual_path(self.save_path, base_name, reason)
                self._append_preview_error_state(
                    outcome, planned, {}, "人工复核", reason, manual=True
                )
                return ArchiveDecision(
                    path=planned, status="manual_review", reason_code=reason
                )
            planned = self._planned_retention_path(
                self.save_path, f"pipeline_{outcome.status}", base_name
            )
            self._append_preview_error_state(
                outcome,
                planned,
                {},
                "预过滤保全",
                outcome.reason_code or outcome.status,
                manual=False,
            )
            return ArchiveDecision(
                path=planned,
                status="unresolved",
                reason_code=outcome.reason_code or outcome.status,
            )

        archive_status = str((payload or {}).get("archive_status") or "")
        if archive_status == "acceptance_rejected":
            acceptance = dict((payload or {}).get("document_acceptance") or {})
            reason = acceptance.get("reason_code") or "DOCUMENT_ACCEPTANCE_REJECTED"
            planned = self._planned_retention_path(
                self.save_path,
                acceptance.get("bucket") or "provider_guard_rejected",
                base_name,
            )
            self._append_preview_error_state(
                outcome, planned, info_json, "验收拦截", reason, manual=False
            )
            return ArchiveDecision(
                path=planned, status="unresolved", reason_code=reason
            )
        if bool(info_json.get("_cwt_cancellation")):
            planned = self._planned_manual_path(
                self.save_path, base_name, "CWT_HOTEL_CANCELLATION"
            )
            self._append_preview_error_state(
                outcome,
                planned,
                info_json,
                MANUAL_REVIEW_FOLDER,
                "CWT_HOTEL_CANCELLATION",
                manual=True,
            )
            return ArchiveDecision(
                path=planned,
                status="manual_review",
                reason_code="CWT_HOTEL_CANCELLATION",
            )
        if archive_status == "manual_review":
            reason = str(
                (payload or {}).get("manual_reason_code") or "PIPELINE_MANUAL_REVIEW"
            )
            planned = self._planned_manual_path(self.save_path, base_name, reason)
            self._append_preview_error_state(
                outcome,
                planned,
                info_json,
                str((payload or {}).get("category") or MANUAL_REVIEW_FOLDER),
                reason,
                manual=True,
            )
            return ArchiveDecision(
                path=planned, status="manual_review", reason_code=reason
            )
        if archive_status == "retained":
            planned = self._planned_retention_path(
                self.save_path, "model_rejected", base_name
            )
            self._append_preview_error_state(
                outcome,
                planned,
                info_json,
                "保留记录",
                "MODEL_REJECTED_NON_INVOICE",
                manual=False,
            )
            return ArchiveDecision(
                path=planned,
                status="retained",
                reason_code="MODEL_REJECTED_NON_INVOICE",
            )

        type_folder = get_archive_folder(info_json.get("Type", ""))
        mapped_folder = str(
            (payload or {}).get("archive_folder") or type_folder
        )
        from expense_rules import is_safe_folder_name

        if mapped_folder and not is_safe_folder_name(mapped_folder):
            mapped_folder = type_folder
        category_name = str(
            (payload or {}).get("category") or mapped_folder
        )
        custom_rules = (
            {info_json.get("Type", ""): mapped_folder}
            if mapped_folder != type_folder
            else None
        )
        previewer = getattr(self.extractor, "preview_archive_target", None)
        if not callable(previewer):
            raise RuntimeError("extractor does not support archive preview")
        layout_kwargs = {"flat_layout": True} if self.flat_layout else {}
        preview = previewer(
            source_path, info_json, custom_rules=custom_rules, **layout_kwargs
        )
        planned = str(preview.get("planned_path") or "")
        target_folder = str(preview.get("target_folder") or "")
        if preview.get("status") == "manual_check" or MANUAL_REVIEW_FOLDER in target_folder:
            reason = str(preview.get("reason_code") or "ROUTE_TO_MANUAL_CHECK")
            self._append_preview_error_state(
                outcome,
                planned,
                info_json,
                target_folder or MANUAL_REVIEW_FOLDER,
                reason,
                manual=True,
            )
            return ArchiveDecision(
                path=planned, status="manual_review", reason_code=reason
            )

        classification_result = {
            "status": "classified",
            "category": category_name,
            "category_id": str((payload or {}).get("category_id") or ""),
            "archive_folder": mapped_folder,
            "source": str((payload or {}).get("classification_source") or ""),
            "rule": str((payload or {}).get("classification_rule") or ""),
            "unmatched": str((payload or {}).get("classification_source") or "")
            == "unknown",
        }
        self.trace_store.set_fields(
            outcome.candidate.identity.document_id,
            normalized_fields=info_json,
            classification_result=classification_result,
            naming_result={
                "status": "preview",
                "target_folder": target_folder,
                "final_filename": os.path.basename(planned),
                "final_path": planned,
            },
            archive_target=planned,
        )
        self._append_preview_success_state(outcome, info_json, category_name, planned)
        return ArchiveDecision(path=planned, status="archived")

    def archive_operation(
        self,
        outcome: ExtractionOutcome,
        payload: dict[str, Any] | None,
        category: str,
        root: Path,
    ) -> ArchiveDecision:
        if self.dry_run:
            return self.preview_operation(outcome, payload, category, root)
        del category, root
        from app_api import record_business_success
        from document_types import MANUAL_REVIEW_FOLDER, get_archive_folder

        metadata = (
            dict(payload.get("metadata") or {})
            if isinstance(payload, dict)
            else outcome.candidate.to_legacy()
        )
        source_candidates = (
            (payload.get("pdf_path") if isinstance(payload, dict) else None),
            outcome.artifact_path,
            metadata.get("filepath"),
            outcome.candidate.source_path,
        )
        source_path = next(
            (str(path) for path in source_candidates if path and os.path.isfile(path)),
            str(next((path for path in source_candidates if path), "")),
        )
        if outcome.status != "resolved":
            if outcome.status == "manual_review":
                path = self.api._send_to_manual_check(
                    self.save_path,
                    source_path,
                    outcome.reason_code or "PIPELINE_MANUAL_REVIEW",
                    metadata=metadata,
                    is_url=outcome.candidate.identity.source_kind == "url",
                )
                self._append_prefilter_error_state(outcome, path)
                return ArchiveDecision(path=path, status="manual_review")
            path = self.api._retain_artifact(
                self.save_path,
                source_path,
                f"pipeline_{outcome.status}",
                outcome.reason_code or outcome.status,
                metadata,
            )
            if outcome.status == "retained":
                self._append_prefilter_error_state(outcome, path)
            if outcome.status == "quota_exhausted":
                self.api._mark_quota_exhausted()
            return ArchiveDecision(path=path, status="unresolved")

        archive_status = str(payload.get("archive_status") or "")
        if archive_status == "acceptance_rejected":
            acceptance = dict(payload.get("document_acceptance") or {})
            snapshot = self.acceptance_service.normalized_snapshot(
                dict(payload.get("info_json") or {})
            )
            diagnostic_metadata = self.api._attachment_diag_metadata(
                metadata,
                file_name=os.path.basename(source_path),
                document_id=outcome.candidate.identity.document_id,
                extra={
                    "tier": metadata.get("tier", 0),
                    "pdf_health": dict(payload.get("acceptance_pdf_health") or {}),
                    "normalized_snapshot": snapshot,
                    "document_acceptance": acceptance,
                },
            )
            path = self.api._retain_artifact(
                self.save_path,
                source_path,
                acceptance.get("bucket") or "provider_guard_rejected",
                acceptance.get("message")
                or "Downloaded result rejected by document acceptance gate.",
                diagnostic_metadata,
            )
            self.api.stats["errors"] = int(self.api.stats.get("errors", 0)) + 1
            try:
                import time

                self.api.logs.append(
                    {
                        "time": time.strftime("[%H:%M:%S]"),
                        "type": "保全:",
                        "color": "text-yellow-400",
                        "msg": f"下载结果被文档验收闸门拦截: {os.path.basename(path)}",
                    }
                )
            except Exception:
                pass
            self.trace_store.set_fields(
                outcome.candidate.identity.document_id,
                normalized_fields=snapshot,
                classification_result={
                    "status": "rejected",
                    "reason_code": acceptance.get("reason_code"),
                    "provider_family": acceptance.get("provider_family", ""),
                },
                naming_result={
                    "status": "skipped",
                    "reason_code": acceptance.get("reason_code"),
                },
                combine_keys={
                    "status": "not_applicable",
                    "reason_code": "COMBINE_NOT_APPLICABLE",
                },
                combine_result={
                    "status": "not_applicable",
                    "reason_code": "COMBINE_NOT_APPLICABLE",
                },
                archive_target=path,
            )
            record_failure = getattr(self.trace_store, "record_failure_event", None)
            if callable(record_failure):
                record_failure(
                    outcome.candidate.identity.document_id,
                    acceptance.get("reason_code") or "DOCUMENT_ACCEPTANCE_REJECTED",
                    "document_acceptance",
                    acceptance.get("message")
                    or "Downloaded result rejected by document acceptance gate.",
                    severity="failure",
                )
            return ArchiveDecision(
                path=path,
                status="unresolved",
                reason_code=acceptance.get("reason_code")
                or "DOCUMENT_ACCEPTANCE_REJECTED",
            )
        if bool((payload.get("info_json") or {}).get("_cwt_cancellation")):
            path = self.api._send_to_manual_check(
                self.save_path,
                source_path,
                "CWT_HOTEL_CANCELLATION",
                metadata={
                    "subject": metadata.get("subject", ""),
                    "file_name": os.path.basename(source_path),
                },
                is_url=outcome.candidate.identity.source_kind == "url",
            )
            registry = getattr(self.api, "_cwt_cancellation_registry", None)
            if registry is None:
                registry = []
                self.api._cwt_cancellation_registry = registry
            registry.append(
                {
                    "file_name": os.path.basename(source_path),
                    "manual_check_path": path,
                }
            )
            self.trace_store.set_fields(
                outcome.candidate.identity.document_id,
                archive_target=path,
                naming_result={
                    "status": "manual_check",
                    "reason_code": "CWT_HOTEL_CANCELLATION",
                },
            )
            return ArchiveDecision(
                path=path,
                status="manual_review",
                reason_code="CWT_HOTEL_CANCELLATION",
            )
        if archive_status == "manual_review":
            reason_code = str(
                payload.get("manual_reason_code") or "PIPELINE_MANUAL_REVIEW"
            )
            path = self.api._send_to_manual_check(
                self.save_path,
                source_path,
                reason_code,
                metadata=metadata,
                is_url=outcome.candidate.identity.source_kind == "url",
            )
            self._append_classified_manual_state(
                outcome,
                dict(payload.get("info_json") or {}),
                str(payload.get("category") or "待人工复核"),
                path,
                reason_code,
            )
            return ArchiveDecision(
                path=path,
                status="manual_review",
                reason_code=reason_code,
            )
        if archive_status == "retained":
            info_json = dict(payload.get("info_json") or {})
            path = self.api._retain_artifact(
                self.save_path,
                source_path,
                "model_rejected",
                "模型判定为非票据，转人工复核保全",
                {
                    "subject": metadata.get("subject", ""),
                    "tier": metadata.get("tier", 0),
                    "file_name": os.path.basename(source_path),
                    "rejection_reason": info_json.get("rejection_reason", ""),
                    "model_type": info_json.get("Type", ""),
                },
            )
            self.api.stats["errors"] = int(self.api.stats.get("errors", 0)) + 1
            self.api.error_invoices.append(
                {
                    "id": f"inv_{__import__('time').time()}_{outcome.candidate.sequence}",
                    "document_id": outcome.candidate.identity.document_id,
                    "date": info_json.get("Date", "---"),
                    "amount": f"¥ {info_json.get('Amount', '0.00')}",
                    "category": "保留记录",
                    "merchant": info_json.get("Seller", "未知开票方"),
                    "path": path,
                    "name": os.path.basename(path),
                    "artifact_kind": "retention",
                    "sColor": "bg-yellow-500",
                    "status": "已保全待确认",
                    "reason": info_json.get(
                        "rejection_reason", "模型判定为非票据，原件已保全"
                    ),
                    "rColor": "text-yellow-600 border-yellow-200 bg-yellow-50",
                }
            )
            return ArchiveDecision(path=path, status="retained")

        info_json = payload["info_json"]
        from app_api import canonical_artifact_role

        category_name = str(payload.get("category") or "其他")
        type_folder = get_archive_folder(info_json.get("Type", ""))
        mapped_folder = str(payload.get("archive_folder") or type_folder)
        from expense_rules import is_safe_folder_name

        if mapped_folder and not is_safe_folder_name(mapped_folder):
            mapped_folder = type_folder
        artifact_role = canonical_artifact_role(
            info_json, os.path.basename(source_path)
        )
        pairing_roles = {
            "ride_invoice",
            "ride_itinerary",
            "hotel_invoice",
            "hotel_folio",
        }
        if artifact_role in pairing_roles and mapped_folder != type_folder:
            # Keep pairing artifacts in their document-type folder until the
            # pairing finalizer has paired/renamed them. They are moved to the
            # configured category folder afterwards, as a pair.
            route_folder = type_folder
        else:
            route_folder = mapped_folder
        custom_rules = (
            {info_json.get("Type", ""): route_folder}
            if route_folder != type_folder
            else None
        )
        success, path = self.extractor.route_and_rename_file(
            source_path,
            info_json,
            custom_rules=custom_rules,
            **({"flat_layout": True} if self.flat_layout else {}),
        )
        if not success:
            retained = self.api._retain_artifact(
                self.save_path,
                source_path,
                "archive_failures",
                "ARCHIVE_STAGE_FAILED",
                metadata,
            )
            return ArchiveDecision(path=retained, status="unresolved")
        naming_trace = getattr(self.extractor, "last_route_trace", {}) or {}
        if MANUAL_REVIEW_FOLDER in str(path) or naming_trace.get("used_manual_check"):
            reason_code = str(
                naming_trace.get("reason_code") or "ROUTE_TO_MANUAL_CHECK"
            )
            self._append_classified_manual_state(
                outcome,
                info_json,
                category_name,
                path,
                reason_code,
            )
            return ArchiveDecision(
                path=path,
                status="manual_review",
                reason_code=reason_code,
            )
        code = str(info_json.get("InvoiceCode") or "").strip()
        number = str(info_json.get("InvoiceNumber") or "").strip()
        if code or number:
            business_key = record_business_success(
                self.business_records,
                code,
                number,
                info_json,
                os.path.basename(path),
            )
            self.business_keys_by_document_id[outcome.candidate.identity.document_id] = business_key

        artifact_role = canonical_artifact_role(info_json, os.path.basename(path))
        if info_json.get("Type") == "住宿确认单":
            artifact_role = "hotel_order"
        elif info_json.get("Type") == "航班行程单":
            artifact_role = "flight_itinerary"
        self.pairing_metadata[str(path)] = {
            "document_id": outcome.candidate.identity.document_id,
            "source_message_uid": outcome.candidate.identity.source_message_uid,
            "email_id": outcome.candidate.identity.source_message_uid,
            "source_kind": outcome.candidate.identity.source_kind,
            "provider_group_key": outcome.candidate.identity.provider_group_key,
            "provider_family": metadata.get("provider_family", ""),
            "seller": info_json.get("Seller", ""),
            "date": info_json.get("Date", ""),
            "amount": info_json.get("Amount", ""),
            "artifact_role": artifact_role,
            "pairing_required": artifact_role
            in {"ride_invoice", "ride_itinerary", "hotel_invoice", "hotel_folio"},
        }
        self.trace_store.set_fields(
            outcome.candidate.identity.document_id,
            normalized_fields=info_json,
            classification_result={
                "status": "classified",
                "category": category_name,
                "category_id": str(payload.get("category_id") or ""),
                "archive_folder": mapped_folder,
                "source": str(payload.get("classification_source") or ""),
                "rule": str(payload.get("classification_rule") or ""),
                "unmatched": str(payload.get("classification_source") or "")
                == "unknown",
                "artifact_role": artifact_role,
                "pairing_deferred": artifact_role in pairing_roles
                and mapped_folder != type_folder,
            },
            naming_result=dict(naming_trace) or {"status": "archived"},
            archive_target=path,
        )
        self.api._safe_emit_artifact_event(
            "archived",
            path,
            document_id=outcome.candidate.identity.document_id,
            category=category_name,
        )
        self._append_success_state(outcome, info_json, category_name, path)
        return ArchiveDecision(path=path, status="archived")

    @staticmethod
    def _is_linklike_path(path: str) -> bool:
        import stat

        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError:
            return True
        if stat.S_ISLNK(info.st_mode):
            return True
        return bool(getattr(info, "st_reparse_tag", 0))

    @staticmethod
    def _is_inside_root(path: str, root: str) -> bool:
        try:
            resolved = os.path.realpath(path)
            base = os.path.realpath(root)
            return os.path.commonpath([resolved, base]) == base
        except (OSError, ValueError):
            return False

    def _move_file_into_folder(
        self, root: str, source: str, folder: str
    ) -> str | None:
        """Move one archived file into a category folder without overwriting."""
        from expense_rules import is_safe_folder_name

        if not folder or not is_safe_folder_name(folder):
            return None
        if not source or not os.path.isfile(source):
            return None
        if not self._is_inside_root(source, root):
            return None
        target_dir = os.path.join(root, folder)
        if not self._is_inside_root(target_dir, root):
            return None
        if self._is_linklike_path(target_dir):
            return None
        try:
            if os.path.exists(target_dir) and not os.path.isdir(target_dir):
                return None
            os.makedirs(target_dir, exist_ok=True)
        except OSError:
            return None
        name = os.path.basename(source)
        target = os.path.join(target_dir, name)
        stem, suffix = os.path.splitext(name)
        index = 2
        while os.path.exists(target):
            target = os.path.join(target_dir, f"{stem}_{index}{suffix}")
            index += 1
        try:
            os.replace(source, target)
        except OSError:
            try:
                import shutil

                shutil.move(source, target)
            except OSError:
                return None
        return target

    def _update_processed_row(
        self, document_id: str, *, category: dict[str, Any], path: str
    ) -> None:
        for row in list(getattr(self.api, "processed_invoices", []) or ()):
            if str(row.get("document_id") or "") != document_id:
                continue
            row["path"] = path
            if "name" in row:
                row["name"] = os.path.basename(path)
            row["category"] = category.get("category", row.get("category", ""))
            row["category_id"] = category.get(
                "category_id", row.get("category_id", "")
            )
            row["category_src"] = category.get(
                "category_src", row.get("category_src", "")
            )
            row["classification_rule"] = category.get(
                "rule", row.get("classification_rule", "")
            )

    def _relocate_deferred_categories(self, root: Path) -> dict[str, str]:
        """Move pairing artifacts to their configured category folder.

        Pairing must run in the document-type folders first. Once pairing has
        produced the final names, the invoice's expense category decides where
        the pair lives; both members move together and share the invoice's
        category so reports and filesystem agree.
        """
        if self.flat_layout:
            return {}
        iterator = getattr(self.trace_store, "iter_records", None)
        if not callable(iterator):
            return {}
        rows = [row for row in iterator() if isinstance(row, dict)]
        if not rows:
            return {}

        by_name = {}
        for row in rows:
            target = str(row.get("archive_target") or "")
            if target:
                by_name.setdefault(os.path.basename(target), row)

        pairing_roles = {
            "ride_invoice",
            "ride_itinerary",
            "hotel_invoice",
            "hotel_folio",
        }
        primary_roles = {"ride_invoice", "hotel_invoice"}
        root_text = str(root)

        def classification(row: dict[str, Any]) -> dict[str, Any]:
            value = row.get("classification_result")
            return dict(value) if isinstance(value, dict) else {}

        def role(row: dict[str, Any]) -> str:
            return str(classification(row).get("artifact_role") or "")

        def desired_folder(row: dict[str, Any]) -> str:
            return str(classification(row).get("archive_folder") or "").strip()

        def is_deferred(row: dict[str, Any]) -> bool:
            return bool(classification(row).get("pairing_deferred"))

        groups: list[list[dict[str, Any]]] = []
        visited: set[str] = set()
        for row in rows:
            document_id = str(row.get("document_id") or "")
            if not document_id or document_id in visited:
                continue
            if role(row) not in pairing_roles:
                continue
            counterpart_name = str(
                (row.get("combine_result") or {}).get("paired_with") or ""
            )
            counterpart = by_name.get(os.path.basename(counterpart_name))
            if counterpart is not None and counterpart is not row:
                group = [row, counterpart]
            else:
                group = [row]
            if not any(is_deferred(item) for item in group):
                continue
            groups.append(group)
            visited.update(str(item.get("document_id") or "") for item in group)

        moved: dict[str, str] = {}
        for group in groups:
            primary = next(
                (item for item in group if role(item) in primary_roles),
                group[0],
            )
            primary_classification = classification(primary)
            folder = str(
                primary_classification.get("archive_folder") or ""
            ).strip()
            if not folder:
                folder = desired_folder(group[0])
            if not folder:
                continue
            for item in group:
                document_id = str(item.get("document_id") or "")
                source = str(item.get("archive_target") or "")
                if not document_id or not source:
                    continue
                current_folder = os.path.basename(os.path.dirname(source))
                if current_folder == folder:
                    target = source
                else:
                    target = self._move_file_into_folder(
                        root_text, source, folder
                    ) or ""
                if not target:
                    continue
                inherited = item is not primary
                updated = dict(classification(item))
                updated.update(
                    {
                        "category": primary_classification.get(
                            "category", updated.get("category", "")
                        ),
                        "category_id": primary_classification.get(
                            "category_id", updated.get("category_id", "")
                        ),
                        "archive_folder": folder,
                        "pair_category_inherited": inherited,
                    }
                )
                if target != source:
                    move = getattr(self.trace_store, "move_archive_target", None)
                    if callable(move):
                        move(source, target)
                self.trace_store.set_fields(
                    document_id,
                    archive_target=target,
                    classification_result=updated,
                )
                category_payload = {
                    "category": updated.get("category", ""),
                    "category_id": updated.get("category_id", ""),
                    "category_src": updated.get("category_src", ""),
                    "rule": updated.get("rule", ""),
                }
                self._update_processed_row(
                    document_id, category=category_payload, path=target
                )
                if target != source:
                    moved[document_id] = target
        return moved

    def finalize(self, report: ArchiveReport, root: Path) -> dict[str, str] | None:
        if self.dry_run:
            # A preview must not rename paired files or move CWT cancellations.
            return None
        if self.pairing_finalizer is not None:
            return self.pairing_finalizer(report, root)
        reconcile_archive_pairs(
            root,
            event_sink=lambda event: self.api._safe_emit_stage_event(
                "archive_pairing", "result", event
            ),
            trace_store=self.trace_store,
            artifact_metadata=self.pairing_metadata,
        )
        moved_paths = self.api._cwt_cancellation_matching(str(root)) or {}
        if moved_paths:
            for row in self.trace_store.iter_records():
                old_path = str(row.get("archive_target") or "")
                if old_path in moved_paths:
                    self.trace_store.set_fields(
                        str(row["document_id"]), archive_target=moved_paths[old_path]
                    )
        self._relocate_deferred_categories(root)
        iterator = getattr(self.trace_store, "iter_records", None)
        if not callable(iterator):
            return None
        rows = [row for row in iterator() if isinstance(row, dict)]
        history_folders: list[str] = []
        for category in getattr(self.classification_rule_set, "categories", ()) or ():
            folder = str(getattr(category, "archive_folder", "") or "").strip()
            if folder:
                history_folders.append(folder)
        root_text = str(root)
        file_folders: dict[str, str] = {}
        for row in rows:
            target = str(row.get("archive_target") or "")
            if not target or not self._is_inside_root(target, root_text):
                continue
            classification = row.get("classification_result")
            classification = (
                dict(classification) if isinstance(classification, dict) else {}
            )
            desired_folder = str(
                classification.get("archive_folder") or ""
            ).strip()
            parent_folder = os.path.basename(os.path.dirname(target))
            folder = desired_folder or parent_folder
            if (
                folder
                and os.path.dirname(os.path.abspath(target))
                != os.path.abspath(root_text)
            ):
                history_folders.append(folder)
            if folder:
                file_folders[os.path.basename(target)] = folder
        recorder = getattr(self.api, "_record_archive_folder_history", None)
        if callable(recorder):
            try:
                recorder(self.save_path, history_folders, file_folders)
            except Exception:
                pass
        return {
            str(row.get("document_id")): str(row.get("archive_target"))
            for row in rows
            if row.get("document_id") and row.get("archive_target")
        }
