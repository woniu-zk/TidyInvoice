"""Process-local error types shared by the bridge and admission services."""

from __future__ import annotations


class TruthAuditTimeout(RuntimeError):
    reason_code = "TRUTH_AUDIT_TIMEOUT"
    user_message = "真值审计收尾超时，请查看诊断报告后重试。"


class ProcessingLoopFailure(RuntimeError):
    reason_code = "PROCESSING_FAILED"
    user_message = "处理过程中发生异常，请重试；如持续失败请查看诊断报告。"


class ImapLoginError(RuntimeError):
    reason_code = "IMAP_LOGIN_FAILED"
    user_message = "邮箱登录失败，请检查授权码和 IMAP 设置。"


class ImapCertificateError(RuntimeError):
    reason_code = "IMAP_TLS_CERTIFICATE_INVALID"
    user_message = "邮箱服务器证书验证失败，请检查系统时间或可信根证书。"


class ImapTimeoutError(RuntimeError):
    reason_code = "IMAP_CONNECTION_TIMEOUT"
    user_message = "邮箱连接或读取超时，请检查网络后重试。"


class RemoteAuthError(RuntimeError):
    reason_code = "REMOTE_AUTH_FAILED"
    user_message = "模型 API 身份验证失败，请检查 API Key。"


class QuotaExhaustedError(RuntimeError):
    reason_code = "QUOTA_EXHAUSTED"
    user_message = "模型 API 额度已耗尽，请充值或更换可用的 API Key。"


class TruthAuditEvidenceError(RuntimeError):
    def __init__(self, reason_code, user_message):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.user_message = user_message


class QuotaExceededError(RuntimeError):
    pass
