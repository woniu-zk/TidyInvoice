"""生成文件，请勿手改。

来源：brand.json（品牌单一事实源）
生成：node tools/brand/generate.mjs
"""

BRAND_NAME = "整票"
BRAND_NAME_EN = "TidyInvoice"
BRAND_SLUG = "tidyinvoice"
BRAND_PACKAGE = "tidyinvoice"
BRAND_TAGLINE = "发票整理与报销准备"
BRAND_TAGLINE_EN = "Invoice organization for reimbursement"
BRAND_FOOTER_STAMP = "Woniu"
BRAND_COPYRIGHT_HOLDER = "蜗牛"
BRAND_LICENSE = "Apache-2.0"
BRAND_YEAR = 2026
BRAND_REPO_URL = "https://github.com/woniu-zk/tidyinvoice"
BRAND_ISSUES_URL = "https://github.com/woniu-zk/tidyinvoice/issues"
BRAND_RELEASES_URL = "https://github.com/woniu-zk/tidyinvoice/releases/latest"
BRAND_REPO_LABEL = "GitHub 仓库"

UPSTREAM_PROJECT_NAME = "Invoice Downloader"
UPSTREAM_BRAND_NAME = "InvoiceFlowAI"
UPSTREAM_AUTHOR = "EthanYoQ / Yong Qi"
UPSTREAM_HANDLE = "EthanYoQ"
UPSTREAM_NPM_SCOPE = "ethanyoq"
UPSTREAM_REPO_URL = "https://github.com/EthanYoQ/Invoice-Downloader"

APP_DIR_NAME = "TidyInvoice"
LEGACY_APP_DIR_NAMES = (
    "InvoiceFlowAI",
    "InvoiceFlowAI External Test",
)
SINGLE_INSTANCE_MUTEX_NAME = "Local\\TidyInvoice.SingleInstance"
TEMP_FILE_PREFIX = "TidyInvoice"
TEMP_DIR_PREFIX = "tidyinvoice"
NODE_PRELOAD_PREFIX = "tidyinvoice-hide-windows-"
SESSION_STORAGE_PREFIX = "tidyinvoice"
IMAP_CLIENT_NAME = "TidyInvoice"
RULE_FILE_HEADER = "# 整票"
THREAD_NAME_TRUTH_AUDIT = "TidyInvoiceTruthAudit"
THREAD_NAME_WORKER = "TidyInvoiceWorker"
BUILD_IDENTITY_NAME = "TidyInvoice"

WEBVIEW2_MODE_ENV = "TIDYINVOICE_WEBVIEW2_MODE"
RUN_CONTEXT_ENV_VAR = "TIDYINVOICE_RUN_CONTEXT_PATH"
PLAYWRIGHT_SMOKE_ENV_VAR = "TIDYINVOICE_PLAYWRIGHT_RUNTIME_SMOKE"
CANDIDATE_REVISION_ENV_VAR = "TIDYINVOICE_CANDIDATE_REVISION"
