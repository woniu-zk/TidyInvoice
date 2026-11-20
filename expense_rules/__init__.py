"""Classification-rules core.

Public API (stable; the desktop app and the web rules page import these)::

    from expense_rules import (
        load_rule_set, build_rule_set, classify, explain, result_to_dict,
        read_scope, save_scope, reset_scope, ensure_scope_template,
        is_safe_folder_name,
        sanitize_rule_keyword, format_amount_bound,
        amount_range_folder_suffix, folder_from_keyword,
        folder_from_type_and_amount,
        CUSTOM_TYPES_FILE_NAME, CustomTypeEntry, CustomTypes,
        load_custom_types, save_custom_types, add_custom_type,
        remove_custom_type, custom_type_name_error,
        RuleConfigError, RuleIssue, RuleSet, ClassificationResult,
        CategoryRule, ScopeData,
    )

Layers (lowest precedence first): built-in L0 defaults -> global user rules ->
library rules -> global rule packs -> library rule packs. See
:mod:`expense_rules.loader` for the merge semantics, :mod:`expense_rules.engine`
for the matching order, :mod:`expense_rules.store` for persistence and
:mod:`expense_rules.cli` for the command line tool.
"""

from __future__ import annotations

from .engine import classify, explain, normalize_fields, result_to_dict
from .loader import (
    build_rule_set,
    default_builtin_path,
    default_global_rules_dir,
    load_rule_set,
    resolve_rules_dir,
)
from .model import (
    CATEGORY_SOURCE_BUILTIN,
    CATEGORY_SOURCE_UNKNOWN,
    CATEGORY_SOURCE_USER,
    SOURCE_BUILTIN_KEYWORD,
    SOURCE_BUILTIN_TYPE,
    SOURCE_DICTIONARY,
    SOURCE_RULE_PACK,
    SOURCE_UNKNOWN,
    SOURCE_USER_RULE,
    CategoryRule,
    ClassificationResult,
    RuleConfigError,
    RuleIssue,
    RuleSet,
    ScopeData,
    SourceRef,
    TermEntry,
    amount_range_folder_suffix,
    folder_from_keyword,
    folder_from_type_and_amount,
    format_amount_bound,
    is_safe_folder_name,
    sanitize_rule_keyword,
)
from .store import (
    ensure_scope_template,
    read_scope,
    reset_scope,
    save_scope,
)
from .types import (
    CUSTOM_TYPES_FILE_NAME,
    CustomTypeEntry,
    CustomTypes,
    add_custom_type,
    custom_type_name_error,
    load_custom_types,
    remove_custom_type,
    save_custom_types,
)

__all__ = [
    # stable API
    "load_rule_set",
    "build_rule_set",
    "classify",
    "explain",
    "result_to_dict",
    "read_scope",
    "save_scope",
    "reset_scope",
    "ensure_scope_template",
    "is_safe_folder_name",
    "RuleConfigError",
    "RuleIssue",
    "RuleSet",
    "ClassificationResult",
    "CategoryRule",
    "ScopeData",
    # additive helpers
    "SourceRef",
    "TermEntry",
    "normalize_fields",
    "sanitize_rule_keyword",
    "format_amount_bound",
    "amount_range_folder_suffix",
    "folder_from_keyword",
    "folder_from_type_and_amount",
    # global custom invoice types
    "CUSTOM_TYPES_FILE_NAME",
    "CustomTypeEntry",
    "CustomTypes",
    "load_custom_types",
    "save_custom_types",
    "add_custom_type",
    "remove_custom_type",
    "custom_type_name_error",
    "resolve_rules_dir",
    "default_builtin_path",
    "default_global_rules_dir",
    "CATEGORY_SOURCE_BUILTIN",
    "CATEGORY_SOURCE_USER",
    "CATEGORY_SOURCE_UNKNOWN",
    "SOURCE_DICTIONARY",
    "SOURCE_USER_RULE",
    "SOURCE_RULE_PACK",
    "SOURCE_BUILTIN_KEYWORD",
    "SOURCE_BUILTIN_TYPE",
    "SOURCE_UNKNOWN",
]
