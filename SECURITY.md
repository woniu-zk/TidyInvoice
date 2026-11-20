# 安全政策

## 支持的版本

安全修复面向仓库最新代码与最新发布版本，更早的版本不单独回补。发布产物见 GitHub Releases 页面。

## 安全模型

本项目是本地优先的电子发票整理工具，提供 Windows / macOS 桌面端、命令行入口与 DeepSeek Harness 插件。安全设计围绕以下边界展开。

### 数据流

- 邮箱通过 IMAP over TLS 只读访问：`mailbox_scanner.py` 使用 `select(..., readonly=True)`，不发送、不删除、不修改邮件，也不修改邮箱状态。
- 发票解析与 OCR 全部在本机完成，不调用模型服务、不需要 API Key，发票内容不上传。
- 归档、分类规则与汇总结果只写入本机的用户目录（输出目录、应用数据目录或用户指定的规则目录），不上传。
- 项目不包含遥测或使用统计，不上报使用数据；诊断日志只写本机磁盘（Windows 位于 `%LOCALAPPDATA%` 下的应用目录，macOS 位于 `~/Library/Caches` 下的应用目录）。

### 凭据保护

- 桌面端的敏感设置（IMAP 授权码等）在 Windows 通过 DPAPI（`CryptProtectData`，当前用户范围）加密后写入设置文件；在 macOS 通过 Keychain（`keyring`）保存，设置文件中只保留引用标记。
- 设置文件位置：Windows 位于 `%APPDATA%` 下的应用目录（`user_settings.json`）；macOS 位于 `~/Library/Application Support` 下的应用目录。
- DeepSeek Harness 插件的授权码保存在 DSH 凭据服务中（引用名 `DSH_INVOICE_IMAP_AUTH_CODE`），不写入插件设置或扫描日志。
- 凭据不得进入日志：运行时错误消息会把邮箱地址替换为通道/账号标签，授权码替换为 `[redacted-auth]`；遗留的 API Key 字段同样替换为 `[redacted-api-key]`。

### URL 恢复的安全约束

当邮件正文包含发票下载链接时，应用会通过 Playwright / HTTP 恢复 PDF。该路径会访问公网，并执行以下约束（实现见 `url_security.py` 与 `pinned_http.py`）：

- 仅允许 `http` / `https`；拒绝带内嵌用户名或密码的 URL；默认只允许 80 / 443 端口，非默认端口需要显式白名单。
- 仅允许**公网单播**地址：拒绝 loopback、私有地址、链路本地、组播、保留地址与未指定地址；`localhost` 直接拒绝。
- **DNS 钉扎**：域名解析结果必须全部是公网地址；直连时把连接固定到已校验的 IP，保留原始 Host / SNI，并在响应后复验实际对端地址；存在代理时额外通过公共 DoH 端点做 DNS 鉴证，并校验连接的对端确实是代理端点。
- 重定向逐跳重新校验；响应体有大小上限（`PinnedHttpTransport.DEFAULT_MAX_RESPONSE_BYTES`，64 MiB）。
- 日志中的 URL 只保留 scheme / host，路径、查询与片段统一脱敏为 `/<redacted>`。

### 本地文件与界面

- 页面到本地能力的桥接只允许访问应用自身的输出目录树与用户确认过的目录；拒绝 UNC 路径与 `..` 穿越。
- 插件只登记位于授权输出目录内的产物，读取时会再次校验真实路径仍在输出根内。
- 桌面前端使用严格 CSP：`default-src 'none'`，脚本与资源仅允许本地来源，`connect-src 'none'`。
- DeepSeek Harness 插件要求 DSH Web 仅监听回环地址且不接受远程可信来源，否则拒绝加载。

### 非目标与已知边界

- 识别逻辑不联网，但“链接发票恢复”功能本身会访问邮件中的公网链接；这是功能需要，不属于漏洞。
- DPAPI 与 Keychain 提供按操作系统用户隔离的保护；已经取得当前用户会话权限的攻击者不在防护范围内。
- 邮件与发票内容的安全性取决于邮箱服务商与本地文件系统权限，本项目不会额外加密归档文件。
- 本项目不是发票真伪校验或税务合规工具。

## 报告漏洞

**请勿通过公开 issue、公开 PR 或社交媒体披露安全漏洞。**

请使用以下私密渠道（任选其一）：

- 发送邮件至安全联系地址：<security-contact>；
- 如果仓库已启用 GitHub 的私密漏洞报告（Private Vulnerability Reporting），也可通过仓库「Security」页面的「Report a vulnerability」提交。

报告中请尽量包含：

- 受影响的版本或提交、操作系统；
- 漏洞类型与影响范围（例如凭据泄露、任意文件写入、SSRF / 内网访问）；
- 最小复现步骤或 PoC；
- 经过脱敏的日志或截图。

请**不要**在报告中包含真实邮箱授权码、发票内容、客户数据或未脱敏的日志。如需证明问题，请使用自建的测试账号与测试数据复现。

## 响应与披露

- 维护者承诺在 **3 个工作日**内确认收到报告，并在 **10 个工作日**内给出初步评估与修复或缓解计划。
- 在修复发布前，请勿公开漏洞细节、利用代码或受影响的实例。
- 修复完成后，维护者会在发布说明或安全公告中说明影响范围；如报告者愿意，可一并致谢。
- 如果维护者在合理时间内没有回复，可以通过同一渠道再次跟进。

## 依赖与构建

- 运行依赖的固定版本记录在 `requirements.release.txt`、`requirements.test.txt` 与插件 `runtime/requirements-headless.txt` 中；升级依赖需同步 `tests/test_packaging_contract.py` 中的版本契约。
- 发布构建由 `.github/workflows/release-desktop.yml` 手动触发，包含测试门禁、冻结发布契约、跨平台构建与产物体检。
