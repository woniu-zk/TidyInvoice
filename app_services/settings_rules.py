"""Settings and classification-rules bridge extracted from InvoiceAppAPI."""

from __future__ import annotations

import os
from pathlib import Path

from document_types import (
    get_document_type_names,
)
from glm_runtime import normalize_provider
from user_settings import get_library_rules_dir, get_rules_dir


class SettingsRulesMixin:
    def load_user_settings(self):
        self._refresh_run_context()
        defaults = self._default_user_settings()
        stored = self._settings_store.load()

        merged = dict(defaults)
        merged.update({key: value for key, value in (stored or {}).items() if key in merged})
        merged["ai_provider"] = normalize_provider(merged.get("ai_provider"))
        merged["save_path"] = self._normalize_user_save_path(merged.get("save_path", ""))
        merged["task_mode"] = self._normalize_task_mode(merged.get("task_mode"))
        merged["local_input_dir"] = str(merged.get("local_input_dir") or "")
        merged["local_output_dir"] = str(merged.get("local_output_dir") or "")

        return {
            "success": True,
            "settings": merged,
            "settings_path": self._settings_store.settings_path,
        }

    def save_user_settings(self, settings):
        with self._settings_lock:
            return self._save_user_settings_locked(settings)

    def _save_user_settings_locked(self, settings):
        incoming = dict(settings or {})
        existing = self._settings_store.load() or {}
        merged = self._default_user_settings()
        remember_settings = incoming.get("remember_settings", True)
        if remember_settings:
            merged.update({key: value for key, value in existing.items() if key in merged})
            merged.update({key: value for key, value in incoming.items() if key in merged})
            merged["remember_settings"] = True
        else:
            merged["remember_settings"] = False
        merged["ai_provider"] = normalize_provider(merged.get("ai_provider"))
        merged["save_path"] = self._normalize_user_save_path(merged.get("save_path", ""))
        merged["task_mode"] = self._normalize_task_mode(merged.get("task_mode"))
        merged["local_input_dir"] = str(merged.get("local_input_dir") or "")
        merged["local_output_dir"] = str(merged.get("local_output_dir") or "")
        raw_save_path = str(merged.get("save_path") or "")
        if raw_save_path.startswith("\\\\") or ".." in Path(raw_save_path).parts:
            return {"success": False, "message": "保存路径不可用"}
        self._settings_store.save(merged)
        return {"success": True, "message": "设置已保存", "path": self._settings_store.settings_path}

    def clear_user_settings(self):
        self._settings_store.clear()
        return {"success": True, "message": "本地设置已清除"}

    # ------------------------------------------------------- expense rules
    def _rule_settings_paths(self, settings=None):
        settings = dict(settings or self._settings_store.load() or {})
        paths = []
        for value in (
            settings.get("save_path"),
            settings.get("local_input_dir"),
            settings.get("local_output_dir"),
            self.get_default_save_path(),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            try:
                paths.append(os.path.realpath(os.path.abspath(text)))
            except (OSError, ValueError):
                continue
        return paths

    def _rule_active_library_dir(self, settings=None):
        settings = dict(settings or self._settings_store.load() or {})
        mode = self._normalize_task_mode(settings.get("task_mode"))
        if mode == "local":
            raw = settings.get("local_output_dir") or settings.get("local_input_dir")
        else:
            raw = settings.get("save_path") or self.get_default_save_path()
        text = str(raw or "").strip()
        if not text:
            return ""
        try:
            return os.path.realpath(os.path.abspath(text))
        except (OSError, ValueError):
            return ""

    def _rule_library_allowed(self, path):
        text = str(path or "").strip()
        if not text:
            return False
        if text.startswith(("\\\\", "//")):
            return False
        if ".." in Path(text).parts:
            return False
        try:
            resolved = os.path.realpath(os.path.abspath(text))
        except (OSError, ValueError):
            return False
        if not os.path.isabs(resolved):
            return False
        candidates = list(self._rule_settings_paths())
        for value in (
            self._effective_save_path,
            self._requested_save_path,
            (self._run_context or {}).get("output_dir"),
            (self._run_context or {}).get("run_root"),
        ):
            value_text = str(value or "").strip()
            if value_text:
                try:
                    candidates.append(os.path.realpath(os.path.abspath(value_text)))
                except (OSError, ValueError):
                    continue
        candidates.extend(self._bridge_allowed_roots())
        for root in candidates:
            try:
                if os.path.commonpath([resolved, str(root)]) == str(root):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _resolve_rule_library_dir(self, library_dir=""):
        requested = str(library_dir or "").strip()
        if requested:
            if not self._rule_library_allowed(requested):
                return ""
            try:
                return os.path.realpath(os.path.abspath(requested))
            except (OSError, ValueError):
                return ""
        return self._rule_active_library_dir()

    def _rule_scope_dir(self, scope, library_dir=""):
        scope = str(scope or "global").strip().lower()
        if scope == "global":
            return get_rules_dir()
        if scope != "library":
            return ""
        library = self._resolve_rule_library_dir(library_dir)
        if not library or not os.path.isdir(library):
            return ""
        return get_library_rules_dir(library)

    @staticmethod
    def _rule_issue_payload(exc):
        issues = []
        for item in getattr(exc, "issues", ()) or ():
            if isinstance(item, dict):
                file_value = str(item.get("file") or "")
                line_value = int(item.get("line") or 0)
                message = str(item.get("message") or "")
                severity = str(item.get("severity") or "error")
            else:
                file_value = str(getattr(item, "file", "") or "")
                line_value = int(getattr(item, "line", 0) or 0)
                message = str(getattr(item, "message", "") or "")
                severity = str(getattr(item, "severity", "error") or "error")
            issues.append(
                {
                    "file": file_value,
                    "line": line_value,
                    "message": message,
                    "severity": severity,
                    "text": f"{file_value}:{line_value}: {message}"
                    if file_value and line_value
                    else message,
                }
            )
        if not issues:
            issues.append(
                {
                    "file": "",
                    "line": 0,
                    "message": str(exc),
                    "severity": "error",
                    "text": str(exc),
                }
            )
        return issues

    @staticmethod
    def _rule_amount_bound(value):
        if value is None:
            return None
        try:
            from decimal import Decimal

            return float(Decimal(str(value)))
        except Exception:
            return None

    def _rule_category_payload(
        self,
        category,
        *,
        default_source_layer: str = "",
        library_rules_dir: str = "",
    ):
        if isinstance(category, dict):
            payload = {
                key: value
                for key, value in category.items()
                if not str(key).startswith("_")
            }
            payload.setdefault("id", "")
            payload.setdefault("name", "")
            payload.setdefault("archive_folder", "")
            payload.setdefault("priority", 0)
            payload.setdefault("auto_folder", False)
            payload.setdefault("target_type", "")
            payload.setdefault("enabled", True)
            payload.setdefault("match", "any")
            payload.setdefault("keywords", [])
            payload.setdefault("exclude_keywords", [])
            payload.setdefault("invoice_types", [])
            payload.setdefault("amount_range", [])
            payload.setdefault("source_layer", default_source_layer)
            payload.setdefault("source_file", "")
            payload.setdefault("source_line", 0)
        elif hasattr(category, "to_dict"):
            payload = dict(category.to_dict())
        else:
            payload = {
                "id": str(getattr(category, "id", "") or ""),
                "name": str(getattr(category, "name", "") or ""),
                "archive_folder": str(getattr(category, "archive_folder", "") or ""),
                "priority": int(getattr(category, "priority", 0) or 0),
                "auto_folder": bool(getattr(category, "auto_folder", False)),
                "target_type": str(getattr(category, "target_type", "") or ""),
                "enabled": bool(getattr(category, "enabled", True)),
                "match": str(getattr(category, "match", "any") or "any"),
                "invoice_types": [
                    str(item)
                    for item in (getattr(category, "invoice_types", ()) or ())
                ],
                "keywords": [
                    str(item)
                    for item in (getattr(category, "keywords", ()) or ())
                ],
                "exclude_keywords": [
                    str(item)
                    for item in (getattr(category, "exclude_keywords", ()) or ())
                ],
                "amount_range": [],
                "source_file": str(getattr(category, "source_file", "") or ""),
                "source_line": int(getattr(category, "source_line", 0) or 0),
                "scope": str(getattr(category, "scope", "") or ""),
                "layer_kind": str(getattr(category, "layer_kind", "") or ""),
            }
        for key in ("keywords", "exclude_keywords", "invoice_types"):
            value = payload.get(key)
            if isinstance(value, (list, tuple, set)):
                payload[key] = [str(item) for item in value]
            else:
                payload[key] = []
        match_value = str(payload.get("match") or "any")
        payload["match"] = (
            "any" if match_value in {"seller_item", "any", ""} else match_value
        )
        raw_range = payload.get("amount_range")
        amount_range = []
        if isinstance(raw_range, (list, tuple)) and raw_range:
            for bound in list(raw_range)[:2]:
                amount_range.append(self._rule_amount_bound(bound))
            while len(amount_range) < 2:
                amount_range.append(None)
            if amount_range == [None, None]:
                amount_range = []
        payload["amount_range"] = amount_range
        payload["auto_folder"] = bool(payload.get("auto_folder", False))
        payload["target_type"] = str(payload.get("target_type") or "")
        source_file = str(payload.get("source_file") or "")
        source_layer = str(payload.get("source_layer") or "")
        if not source_layer:
            if not source_file:
                source_layer = default_source_layer or "builtin"
            elif f"{os.sep}rules.d{os.sep}" in source_file:
                source_layer = "pack"
            elif source_file.startswith(get_rules_dir()):
                source_layer = "global"
            elif library_rules_dir and source_file.startswith(library_rules_dir):
                source_layer = "library"
            else:
                source_layer = default_source_layer or "builtin"
        payload["source_layer"] = source_layer
        payload["source_line"] = int(payload.get("source_line") or 0)
        payload["priority"] = int(payload.get("priority") or 0)
        payload["enabled"] = bool(payload.get("enabled", True))
        return payload

    def _rule_scope_payload(self, data, scope=""):
        if data is None:
            return {"categories": [], "terms": [], "fallback": "", "type_categories": {}}
        scope_name = str(scope or getattr(data, "scope", "") or "")
        categories = [
            self._rule_category_payload(
                item, default_source_layer=scope_name or "user"
            )
            for item in (getattr(data, "categories", ()) or ())
        ]
        terms = self._rule_terms_payload(
            getattr(data, "terms", None), scope_name or "user"
        )
        return {
            "categories": categories,
            "terms": terms,
            "fallback": str(getattr(data, "fallback", "") or ""),
            "type_categories": dict(getattr(data, "type_categories", {}) or {}),
        }

    @staticmethod
    def _rule_terms_payload(terms, scope=""):
        result = []
        if isinstance(terms, dict):
            for term, category in terms.items():
                result.append(
                    {
                        "term": str(term or ""),
                        "category": str(category or ""),
                        "source_layer": str(scope or ""),
                    }
                )
        elif isinstance(terms, (list, tuple)):
            for item in terms:
                if isinstance(item, dict):
                    result.append(
                        {
                            "term": str(
                                item.get("term")
                                or item.get("seller_name")
                                or item.get("seller_tin")
                                or ""
                            ),
                            "category": str(item.get("category") or ""),
                            "source_layer": str(
                                item.get("source_layer") or scope or ""
                            ),
                            "seller_tin": str(item.get("seller_tin") or ""),
                            "seller_name": str(item.get("seller_name") or ""),
                        }
                    )
        return result

    @staticmethod
    def _rule_categories_for_storage(categories):
        """Convert UI category entries to the loader's persisted schema."""
        stored = []
        for entry in categories:
            if not isinstance(entry, dict):
                stored.append(entry)
                continue
            item = {
                key: value
                for key, value in entry.items()
                if key
                in {
                    "id",
                    "name",
                    "archive_folder",
                    "priority",
                    "auto_folder",
                    "target_type",
                    "enabled",
                    "match",
                    "invoice_types",
                    "keywords",
                    "exclude_keywords",
                    "amount_range",
                    "description",
                }
            }
            if str(item.get("match") or "") == "any":
                item["match"] = "seller_item"
            if item.get("amount_range") in ([], (), "", None):
                item["amount_range"] = []
            stored.append(item)
        return stored

    @staticmethod
    def _rule_terms_mapping(terms):
        mapping = {}
        if isinstance(terms, dict):
            for term, category in terms.items():
                key = str(term or "").strip()
                if key:
                    mapping[key] = str(category or "").strip()
            return mapping
        if isinstance(terms, (list, tuple)):
            for item in terms:
                if isinstance(item, dict):
                    key = str(
                        item.get("term")
                        or item.get("seller_name")
                        or item.get("seller_tin")
                        or ""
                    ).strip()
                    category = str(item.get("category") or "").strip()
                else:
                    key = str(item or "").strip()
                    category = ""
                if key:
                    mapping[key] = category
        return mapping

    def _rule_unclassified_rows(self):
        rows = []
        seen = set()
        for source in (
            list(getattr(self, "processed_invoices", []) or []),
            list(getattr(self, "error_invoices", []) or []),
        ):
            for row in source:
                document_id = str(row.get("document_id") or "")
                key = document_id or str(row.get("path") or "")
                if key in seen:
                    continue
                is_unknown = (
                    str(row.get("classification_source") or "") == "unknown"
                    or str(row.get("reason") or "") == "CLASSIFICATION_UNKNOWN"
                )
                if not is_unknown:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "document_id": document_id,
                        "date": row.get("date", ""),
                        "amount": row.get("amount", ""),
                        "merchant": row.get("merchant", ""),
                        "type": row.get("type", ""),
                        "category": row.get("category", ""),
                        "path": row.get("path", ""),
                    }
                )
        return rows

    def _rule_files_payload(self, library_dir=""):
        files = []
        for scope, directory in (
            ("global", get_rules_dir()),
            ("library", get_library_rules_dir(library_dir) if library_dir else ""),
        ):
            if not directory:
                continue
            for name in ("categories.yaml", "user_terms.yaml"):
                path = os.path.join(directory, name)
                files.append(
                    {
                        "scope": scope,
                        "path": path,
                        "exists": os.path.isfile(path),
                    }
                )
            packs = os.path.join(directory, "rules.d")
            if os.path.isdir(packs):
                for name in sorted(os.listdir(packs)):
                    if not name.lower().endswith((".yaml", ".yml")):
                        continue
                    path = os.path.join(packs, name)
                    if os.path.isfile(path):
                        files.append(
                            {"scope": scope, "path": path, "exists": True}
                        )
        return files

    def _classification_rules_error(self, library_dir):
        """Return a user-facing validation error, or '' when rules are usable."""
        from expense_rules import RuleConfigError, load_rule_set

        try:
            load_rule_set(library_dir or None)
        except RuleConfigError as exc:
            issues = self._rule_issue_payload(exc)
            lines = [item.get("text") or item.get("message") for item in issues]
            return "归类规则配置有误，请先修正：\n" + "\n".join(lines[:10])
        except Exception as exc:
            return f"归类规则加载失败：{exc}"
        return ""

    def _rule_classification_stats(self):
        summary = {}
        try:
            summary = self._summarize_stats() or {}
        except Exception:
            summary = {}
        return {
            "classification_breakdown": dict(
                summary.get("classification_breakdown") or {}
            ),
            "classification_source_breakdown": dict(
                summary.get("classification_source_breakdown") or {}
            ),
            "unclassified_count": int(summary.get("unclassified_count", 0) or 0),
            "dictionary_hit_count": int(
                summary.get("dictionary_hit_count", 0) or 0
            ),
        }

    def get_classification_rules_status(self):
        """Startup-friendly validation of the global + active-library rules."""
        from expense_rules import RuleConfigError, load_rule_set

        library = self._rule_active_library_dir()
        library_available = bool(library and os.path.isdir(library))
        issues = []
        try:
            load_rule_set(library if library_available else None)
        except RuleConfigError as exc:
            issues = self._rule_issue_payload(exc)
        except Exception as exc:
            issues = self._rule_issue_payload(exc)
        return {
            "success": True,
            "issues": issues,
            "global_rules_dir": get_rules_dir(),
            "library_dir": library,
            "library_available": library_available,
            "library_rules_dir": get_library_rules_dir(library)
            if library_available
            else "",
        }

    def load_classification_rules(self, library_dir=""):
        from expense_rules import (
            RuleConfigError,
            load_rule_set,
            read_scope,
        )

        library = self._resolve_rule_library_dir(library_dir)
        library_available = bool(library and os.path.isdir(library))
        payload = {
            "success": True,
            "message": "",
            "library_dir": library,
            "library_available": library_available,
            "global_rules_dir": get_rules_dir(),
            "library_rules_dir": get_library_rules_dir(library)
            if library_available
            else "",
            "effective_categories": [],
            "global": {"categories": [], "terms": [], "fallback": "", "type_categories": {}},
            "library": {"categories": [], "terms": [], "fallback": "", "type_categories": {}},
            "fallback": "other",
            "builtin_types": list(get_document_type_names()),
            "custom_types": [],
            "document_types": list(get_document_type_names()),
            "custom_types_path": "",
            "builtin_category_ids": [],
            "files": self._rule_files_payload(library),
            "issues": [],
            "warnings": [],
            "unclassified_invoices": self._rule_unclassified_rows(),
            "stats": self._rule_classification_stats(),
        }
        try:
            rule_set = load_rule_set(library if library_available else None)
        except RuleConfigError as exc:
            payload["success"] = False
            payload["message"] = "归类规则配置有误"
            payload["issues"] = self._rule_issue_payload(exc)
            type_info = self._classification_type_payload()
            for key in (
                "builtin_types",
                "custom_types",
                "document_types",
                "custom_types_path",
                "builtin_category_ids",
            ):
                payload[key] = type_info[key]
            return payload
        except Exception as exc:
            payload["success"] = False
            payload["message"] = "归类规则加载失败"
            payload["issues"] = self._rule_issue_payload(exc)
            type_info = self._classification_type_payload()
            for key in (
                "builtin_types",
                "custom_types",
                "document_types",
                "custom_types_path",
                "builtin_category_ids",
            ):
                payload[key] = type_info[key]
            return payload

        payload["effective_categories"] = [
            self._rule_category_payload(
                item,
                library_rules_dir=(
                    get_library_rules_dir(library) if library_available else ""
                ),
            )
            for item in (getattr(rule_set, "categories", ()) or ())
        ]
        payload["builtin_types"] = list(get_document_type_names())
        payload["custom_types"] = list(
            getattr(rule_set, "custom_types", ()) or ()
        )
        payload["document_types"] = list(
            getattr(rule_set, "document_types", ()) or ()
        )
        payload["custom_types_path"] = str(
            getattr(rule_set, "custom_types_path", "") or ""
        )
        payload["builtin_category_ids"] = list(
            getattr(rule_set, "builtin_category_ids", ()) or ()
        )
        payload["fallback"] = str(
            getattr(rule_set, "fallback_id", "other") or "other"
        )
        payload["warnings"] = [
            {
                "file": str(getattr(item, "file", "") or ""),
                "line": int(getattr(item, "line", 0) or 0),
                "message": str(getattr(item, "message", "") or ""),
                "severity": str(getattr(item, "severity", "warning") or "warning"),
                "text": str(item),
            }
            for item in (getattr(rule_set, "warnings", ()) or ())
        ]
        try:
            payload["global"] = self._rule_scope_payload(
                read_scope("global", ""), "global"
            )
        except Exception:
            pass
        if library_available:
            try:
                payload["library"] = self._rule_scope_payload(
                    read_scope("library", library), "library"
                )
            except Exception:
                pass
        return payload

    def save_classification_rules(self, payload):
        from expense_rules import RuleConfigError, save_scope

        data = dict(payload or {})
        scope = str(data.get("scope") or "global").strip().lower()
        if scope not in {"global", "library"}:
            return {"success": False, "message": "规则作用范围无效", "issues": []}
        library = ""
        if scope == "library":
            library = self._resolve_rule_library_dir(data.get("library_dir", ""))
            if not library or not os.path.isdir(library):
                return {
                    "success": False,
                    "message": "当前发票库不存在，无法保存库内规则",
                    "issues": [],
                }
        categories = data.get("categories")
        terms = data.get("terms")
        if not isinstance(categories, list) or not isinstance(terms, list):
            return {
                "success": False,
                "message": "规则数据格式不正确",
                "issues": [],
            }
        try:
            categories_payload = self._rule_categories_for_storage(categories)
            terms_payload = self._rule_terms_mapping(terms)
            save_scope(
                scope,
                library if scope == "library" else None,
                categories_payload,
                terms_payload,
                fallback=data.get("fallback") or None,
            )
        except RuleConfigError as exc:
            return {
                "success": False,
                "message": "规则校验失败",
                "issues": self._rule_issue_payload(exc),
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"规则保存失败: {exc}",
                "issues": self._rule_issue_payload(exc),
            }
        return {
            "success": True,
            "message": "规则已保存，下一次整理生效",
            "scope": scope,
            "library_dir": library,
        }

    def reset_classification_rules(self, scope, library_dir=""):
        from expense_rules import reset_scope

        scope_text = str(scope or "global").strip().lower()
        if scope_text not in {"global", "library"}:
            return {"success": False, "message": "规则作用范围无效"}
        library = ""
        if scope_text == "library":
            library = self._resolve_rule_library_dir(library_dir)
            if not library or not os.path.isdir(library):
                return {"success": False, "message": "当前发票库不存在"}
        try:
            backups = reset_scope(
                scope_text, library if scope_text == "library" else ""
            )
        except Exception as exc:
            return {"success": False, "message": f"恢复默认失败: {exc}"}
        return {
            "success": True,
            "message": "已恢复默认规则",
            "backups": list(backups or ()),
        }

    def _classification_type_payload(self, custom_types=None):
        from expense_rules import load_custom_types

        builtin = list(get_document_type_names())
        custom = []
        issues = []
        path = ""
        if custom_types is not None:
            custom = [
                str(item).strip()
                for item in custom_types
                if str(item).strip()
            ]
        else:
            try:
                loaded = load_custom_types(get_rules_dir())
                custom = list(loaded.names)
                issues = [
                    {
                        "file": str(getattr(item, "file", "") or ""),
                        "line": int(getattr(item, "line", 0) or 0),
                        "message": str(getattr(item, "message", "") or ""),
                        "severity": str(
                            getattr(item, "severity", "error") or "error"
                        ),
                        "text": str(item),
                    }
                    for item in (getattr(loaded, "issues", ()) or ())
                ]
                path = str(getattr(loaded, "path", "") or "")
            except Exception as exc:
                issues = [
                    {
                        "file": "",
                        "line": 0,
                        "message": str(exc),
                        "severity": "error",
                        "text": str(exc),
                    }
                ]
        document_types = builtin + [
            name for name in custom if name not in builtin
        ]
        return {
            "builtin_types": builtin,
            "custom_types": custom,
            "document_types": document_types,
            "custom_types_path": path,
            "builtin_category_ids": [],
            "issues": issues,
        }

    def create_classification_type(self, payload):
        from expense_rules import RuleConfigError, add_custom_type

        data = dict(payload or {}) if isinstance(payload, dict) else {}
        name = str(data.get("name") or "").strip()
        if not name:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": "请填写票种名称",
                    "issues": [],
                }
            )
            return result
        try:
            added = add_custom_type(name, get_rules_dir())
        except RuleConfigError as exc:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": "票种创建失败",
                    "issues": self._rule_issue_payload(exc),
                }
            )
            return result
        except Exception as exc:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": f"票种创建失败: {exc}",
                    "issues": [],
                }
            )
            return result
        payload_out = self._classification_type_payload(added.names)
        payload_out.update(
            {
                "success": True,
                "message": "票种已创建，全局规则和当前发票库规则都可以使用。",
            }
        )
        return payload_out

    def delete_classification_type(self, payload):
        from expense_rules import RuleConfigError, load_rule_set, remove_custom_type

        data = dict(payload or {}) if isinstance(payload, dict) else {}
        name = str(data.get("name") or "").strip()
        if not name:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": "请填写要删除的票种",
                    "issues": [],
                }
            )
            return result
        library = self._resolve_rule_library_dir(data.get("library_dir", ""))
        library_available = bool(library and os.path.isdir(library))
        references = []
        try:
            rule_set = load_rule_set(library if library_available else None)
        except Exception as exc:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": f"删除前检查规则失败: {exc}",
                    "issues": [],
                }
            )
            return result
        for category in getattr(rule_set, "categories", ()) or ():
            if str(getattr(category, "target_type", "") or "").strip() != name:
                continue
            references.append(
                {
                    "file": str(getattr(category, "source_file", "") or ""),
                    "line": int(getattr(category, "source_line", 0) or 0),
                    "message": f"票种「{name}」正在被规则 {getattr(category, 'id', '')} 使用，不能删除",
                    "severity": "error",
                    "text": (
                        f"{getattr(category, 'source_file', '')}:"
                        f"{getattr(category, 'source_line', 0)}: 票种「{name}」正在被规则 "
                        f"{getattr(category, 'id', '')} 使用，不能删除"
                    ),
                }
            )
        if references:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": "票种正在被规则使用，不能删除",
                    "issues": references,
                }
            )
            return result
        try:
            removed = remove_custom_type(name, get_rules_dir())
        except RuleConfigError as exc:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": "票种删除失败",
                    "issues": self._rule_issue_payload(exc),
                }
            )
            return result
        except Exception as exc:
            result = self._classification_type_payload()
            result.update(
                {
                    "success": False,
                    "message": f"票种删除失败: {exc}",
                    "issues": [],
                }
            )
            return result
        payload_out = self._classification_type_payload(removed.names)
        payload_out.update({"success": True, "message": "票种已删除。"})
        return payload_out

    def reset_builtin_classification_rules(self, payload):
        from expense_rules import (
            RuleConfigError,
            load_rule_set,
            read_scope,
            save_scope,
        )

        data = dict(payload or {}) if isinstance(payload, dict) else {}
        scope = str(data.get("scope") or "global").strip().lower()
        if scope not in {"global", "library"}:
            return {"success": False, "message": "规则作用范围无效", "issues": []}
        library = self._resolve_rule_library_dir(data.get("library_dir", ""))
        library_available = bool(library and os.path.isdir(library))
        if scope == "library" and not library_available:
            return {"success": False, "message": "当前发票库不存在", "issues": []}
        scope_mode = str(data.get("scope_mode") or "current").strip().lower()
        if scope_mode not in {"current", "all"}:
            return {"success": False, "message": "恢复范围无效", "issues": []}
        category_id = str(data.get("category_id") or "").strip()

        try:
            rule_set = load_rule_set(library if library else None)
        except RuleConfigError as exc:
            return {
                "success": False,
                "message": "内置规则恢复失败：当前规则文件有误",
                "issues": self._rule_issue_payload(exc),
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"内置规则恢复失败: {exc}",
                "issues": [],
            }
        builtin_ids = {
            str(value).strip()
            for value in (getattr(rule_set, "builtin_category_ids", ()) or ())
            if str(value).strip()
        }
        if not builtin_ids:
            return {"success": False, "message": "没有可恢复的内置规则", "issues": []}
        if category_id and category_id not in builtin_ids:
            return {
                "success": False,
                "message": "指定的规则不是内置规则",
                "issues": [],
            }
        target_ids = {category_id} if category_id else builtin_ids
        scopes = ["global"]
        if library:
            scopes.append("library")
        if scope_mode == "current":
            scopes = [scope]

        removed = 0
        changed_scopes = []
        try:
            for scope_name in scopes:
                scope_library = library if scope_name == "library" else ""
                current = read_scope(scope_name, scope_library)
                categories = [
                    dict(entry)
                    for entry in (current.categories or ())
                    if str(entry.get("id") or "").strip() not in target_ids
                ]
                if len(categories) == len(current.categories or ()):
                    continue
                save_scope(
                    scope_name,
                    scope_library,
                    categories,
                    current.terms,
                    current.fallback or None,
                )
                removed += len(current.categories or ()) - len(categories)
                changed_scopes.append(scope_name)
        except Exception as exc:
            return {
                "success": False,
                "message": f"内置规则恢复失败: {exc}",
                "issues": [],
            }
        if not changed_scopes:
            return {
                "success": True,
                "message": "没有需要恢复的自定义覆盖。",
                "removed": 0,
                "scopes": [],
            }
        label = "当前作用范围" if scope_mode == "current" else "全局+当前发票库"
        return {
            "success": True,
            "message": f"已恢复 {label} 的内置规则默认值。",
            "removed": removed,
            "scopes": changed_scopes,
        }

    @staticmethod
    def _rule_result_payload(result):
        if hasattr(result, "to_dict"):
            try:
                return result.to_dict()
            except Exception:
                pass
        return {
            "category_id": str(getattr(result, "category_id", "") or ""),
            "category_name": str(getattr(result, "category_name", "") or ""),
            "archive_folder": str(getattr(result, "archive_folder", "") or ""),
            "category_src": str(getattr(result, "category_src", "") or ""),
            "source": str(getattr(result, "source", "") or ""),
            "rule_id": str(getattr(result, "rule_id", "") or ""),
            "keyword": str(getattr(result, "keyword", "") or ""),
            "priority": int(getattr(result, "priority", 0) or 0),
            "source_file": str(getattr(result, "source_file", "") or ""),
            "source_line": int(getattr(result, "source_line", 0) or 0),
            "chain": list(getattr(result, "chain", ()) or ()),
        }

    def test_classification_rules(self, payload):
        import expense_rules
        from expense_rules import (
            RuleConfigError,
            classify,
            load_rule_set,
        )

        data = dict(payload or {})
        fields = dict(data.get("fields") or {})
        scope = str(data.get("scope") or "global").strip().lower()
        library = self._resolve_rule_library_dir(data.get("library_dir", ""))
        library_available = bool(library and os.path.isdir(library))
        draft = data.get("draft")
        overrides = None
        if isinstance(draft, dict):
            draft_payload = {
                "categories": self._rule_categories_for_storage(
                    draft.get("categories") or []
                ),
                "terms": self._rule_terms_mapping(draft.get("terms") or []),
                "fallback": draft.get("fallback") or None,
                "type_categories": dict(draft.get("type_categories") or {}),
            }
            overrides = {scope: draft_payload}
        try:
            builder = getattr(expense_rules, "build_rule_set", None)
            if overrides is not None and callable(builder):
                rule_set = builder(
                    library if library_available else None,
                    overrides=overrides,
                )
            else:
                rule_set = load_rule_set(library if library_available else None)
                if overrides is not None:
                    overrides = None
            result = classify(fields, rule_set)
        except RuleConfigError as exc:
            return {
                "success": False,
                "message": "规则校验失败",
                "issues": self._rule_issue_payload(exc),
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"规则测试失败: {exc}",
                "issues": self._rule_issue_payload(exc),
            }
        return {
            "success": True,
            "result": self._rule_result_payload(result),
            "draft_used": bool(overrides is not None),
        }

    @staticmethod
    def _open_directory_path(path):
        import platform
        import subprocess as _subprocess

        os.makedirs(path, exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            _subprocess.Popen(["open", path])
        else:
            _subprocess.Popen(["xdg-open", path])

    def open_rules_folder(self, scope, library_dir=""):
        from expense_rules import ensure_scope_template

        scope_text = str(scope or "global").strip().lower()
        if scope_text not in {"global", "library"}:
            return {"success": False, "message": "规则作用范围无效"}
        directory = self._rule_scope_dir(scope_text, library_dir)
        if not directory:
            return {"success": False, "message": "当前发票库不存在，无法打开规则目录"}
        try:
            os.makedirs(directory, exist_ok=True)
            template_library = (
                os.path.dirname(directory) if scope_text == "library" else ""
            )
            ensure_scope_template(scope_text, template_library)
            self._open_directory_path(directory)
        except Exception as exc:
            return {"success": False, "message": f"打开规则目录失败: {exc}"}
        return {"success": True, "message": "已打开规则目录", "path": directory}

