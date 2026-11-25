"""
邮箱通道注册表 — 统一 IMAP 路由配置

替代 app_api.py 中散布的 if/else IMAP 服务器选择逻辑。
新增邮箱只需在 EMAIL_CHANNELS 字典中加一条：域名 -> 通道配置。

字段说明：
- channel_id：同一邮箱服务商共用的通道标识（写入运行证据与真值清单）。
- imap_host / imap_port：IMAP over TLS 服务器与端口。
- requires_id_cmd：登录后是否需要发送 RFC 2971 ID 命令（Coremail 系邮箱）。
- auth_hint：登录失败时提示用户应使用的凭据类型。
- display：面向用户的服务商名称。

未知域名不再静默回落到 QQ 邮箱，而是返回 supported=False 的中性通道，
由调用方给出明确的「暂不支持」提示。
"""

EMAIL_CHANNELS = {
    # 腾讯系
    "qq.com": {
        "channel_id": "qq",
        "imap_host": "imap.qq.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "邮箱授权码",
        "display": "QQ 邮箱",
    },
    "vip.qq.com": {
        "channel_id": "qq",
        "imap_host": "imap.qq.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "邮箱授权码",
        "display": "QQ 邮箱（VIP）",
    },
    "foxmail.com": {
        "channel_id": "qq",
        "imap_host": "imap.qq.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "邮箱授权码",
        "display": "Foxmail 邮箱",
    },
    "exmail.qq.com": {
        "channel_id": "exmail",
        "imap_host": "imap.exmail.qq.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "客户端专用密码",
        "display": "腾讯企业邮箱",
    },
    # 网易系（Coremail，需要 ID 命令）
    "163.com": {
        "channel_id": "163",
        "imap_host": "imap.163.com",
        "imap_port": 993,
        "requires_id_cmd": True,
        "auth_hint": "邮箱授权码",
        "display": "163 邮箱",
    },
    "126.com": {
        "channel_id": "126",
        "imap_host": "imap.126.com",
        "imap_port": 993,
        "requires_id_cmd": True,
        "auth_hint": "邮箱授权码",
        "display": "126 邮箱",
    },
    "188.com": {
        "channel_id": "188",
        "imap_host": "imap.188.com",
        "imap_port": 993,
        "requires_id_cmd": True,
        "auth_hint": "邮箱授权码",
        "display": "188 邮箱",
    },
    "yeah.net": {
        "channel_id": "yeah",
        "imap_host": "imap.yeah.net",
        "imap_port": 993,
        "requires_id_cmd": True,
        "auth_hint": "邮箱授权码",
        "display": "Yeah 邮箱",
    },
    "qiye.163.com": {
        "channel_id": "qiye163",
        "imap_host": "imap.qiye.163.com",
        "imap_port": 993,
        "requires_id_cmd": True,
        "auth_hint": "客户端专用密码",
        "display": "网易企业邮箱",
    },
    # 完美世界
    "88.com": {
        "channel_id": "88",
        "imap_host": "imap.88.com",
        "imap_port": 993,
        "requires_id_cmd": True,
        "auth_hint": "专用密码",
        "display": "88 邮箱",
    },
    # 新浪 / 搜狐 / 21CN / 263
    "sina.com": {
        "channel_id": "sina",
        "imap_host": "imap.sina.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "客户端授权码",
        "display": "新浪邮箱",
    },
    "sina.cn": {
        "channel_id": "sina",
        "imap_host": "imap.sina.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "客户端授权码",
        "display": "新浪邮箱",
    },
    "sohu.com": {
        "channel_id": "sohu",
        "imap_host": "imap.sohu.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "邮箱授权码",
        "display": "搜狐邮箱",
    },
    "21cn.com": {
        "channel_id": "21cn",
        "imap_host": "imap.21cn.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "邮箱授权码",
        "display": "21CN 邮箱",
    },
    "263.net": {
        "channel_id": "263",
        "imap_host": "imap.263.net",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "客户端密码",
        "display": "263 邮箱",
    },
    # 电信 / 移动
    "189.cn": {
        "channel_id": "189",
        "imap_host": "imap.189.cn",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "邮箱授权码",
        "display": "189 邮箱（天翼）",
    },
    "139.com": {
        "channel_id": "139",
        "imap_host": "imap.139.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "邮箱授权码",
        "display": "139 邮箱（移动）",
    },
    # 阿里
    "aliyun.com": {
        "channel_id": "aliyun",
        "imap_host": "imap.aliyun.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "专用密码",
        "display": "阿里邮箱",
    },
    "qiye.aliyun.com": {
        "channel_id": "aliyun",
        "imap_host": "imap.qiye.aliyun.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "专用密码",
        "display": "阿里企业邮箱",
    },
    # 国际邮箱（应用专用密码）
    "gmail.com": {
        "channel_id": "gmail",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用专用密码（需先开启两步验证）",
        "display": "Gmail",
    },
    "googlemail.com": {
        "channel_id": "gmail",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用专用密码（需先开启两步验证）",
        "display": "Gmail",
    },
    "icloud.com": {
        "channel_id": "icloud",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "App 专用密码（需先开启双重认证）",
        "display": "iCloud 邮箱",
    },
    "me.com": {
        "channel_id": "icloud",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "App 专用密码（需先开启双重认证）",
        "display": "iCloud 邮箱",
    },
    "mac.com": {
        "channel_id": "icloud",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "App 专用密码（需先开启双重认证）",
        "display": "iCloud 邮箱",
    },
    "yahoo.com": {
        "channel_id": "yahoo",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用密码",
        "display": "Yahoo 邮箱",
    },
    "ymail.com": {
        "channel_id": "yahoo",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用密码",
        "display": "Yahoo 邮箱",
    },
    "zoho.com": {
        "channel_id": "zoho",
        "imap_host": "imap.zoho.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用专用密码",
        "display": "Zoho 邮箱",
    },
    "yandex.com": {
        "channel_id": "yandex",
        "imap_host": "imap.yandex.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用密码",
        "display": "Yandex 邮箱",
    },
    "gmx.net": {
        "channel_id": "gmx",
        "imap_host": "imap.gmx.net",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用密码",
        "display": "GMX 邮箱",
    },
    "gmx.com": {
        "channel_id": "gmx",
        "imap_host": "imap.gmx.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用密码",
        "display": "GMX 邮箱",
    },
    "aol.com": {
        "channel_id": "aol",
        "imap_host": "imap.aol.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用密码",
        "display": "AOL 邮箱",
    },
    "fastmail.com": {
        "channel_id": "fastmail",
        "imap_host": "imap.fastmail.com",
        "imap_port": 993,
        "requires_id_cmd": False,
        "auth_hint": "应用密码",
        "display": "Fastmail",
    },
}

# 未知域名的中性通道：不连接任何服务器，由调用方明确报错。
UNSUPPORTED_CHANNEL = {
    "channel_id": "custom",
    "imap_host": "",
    "imap_port": 993,
    "requires_id_cmd": False,
    "auth_hint": "授权码或应用专用密码",
    "display": "",
    "supported": False,
}


def _domain_of(email_address: str) -> str:
    return email_address.rsplit("@", 1)[-1].lower() if "@" in email_address else ""


def resolve_channel(email_address: str) -> dict:
    """根据邮箱地址返回对应的通道配置；未知域名返回中性通道。"""
    channel = EMAIL_CHANNELS.get(_domain_of(email_address))
    if channel is None:
        return dict(UNSUPPORTED_CHANNEL)
    return {**channel, "supported": True}


def supported_domains() -> list[str]:
    """返回所有支持的邮箱域名列表（已排序）。"""
    return sorted(EMAIL_CHANNELS)


def is_supported_email(email_address: str) -> bool:
    """检查邮箱是否属于已支持的通道。"""
    return _domain_of(email_address) in EMAIL_CHANNELS
