## 变更说明

<!-- 说明为什么改、改了什么。不要粘贴真实发票、邮箱地址、授权码或未脱敏日志。 -->

## 变更类型

- [ ] `feat` 新功能
- [ ] `fix` 缺陷修复
- [ ] `docs` 文档
- [ ] `chore` 构建 / 依赖 / 工具
- [ ] `refactor` 重构（不改变外部行为）
- [ ] `test` 测试新增或调整

## 关联 issue

<!-- 例如：Closes #123 -->

## 复现 / 验证步骤

1.
2.
3.

## 测试证据

<!-- 粘贴受影响的命令与结果摘要（已脱敏），或说明未运行的原因与范围 -->

- [ ] `.\.venv\Scripts\python.exe -m pytest -q`（Windows；macOS 用 `.venv/bin/python -m pytest -q`）
- [ ] `.\.venv\Scripts\python.exe -m ruff check .`
- [ ] `node tools/compile-frontend.mjs --check`
- [ ] `node tools/brand/generate.mjs --check`
- [ ] `node tools/brand/check.mjs`
- [ ] 插件改动：`cd plugins/dsh-invoice-downloader && npm ci && npm test && npm run test:package`

## 前端与品牌产物

- [ ] 未改动前端源码或品牌源文件
- [ ] 改动了 `templates/index_app.js`，已运行 `node tools/compile-frontend.mjs` 并提交 `templates/index_app.built.js`
- [ ] 改动了 `brand.json`，已运行 `node tools/brand/generate.mjs` 并提交 `brand_generated.py` 与 `templates/brand.generated.js`
- [ ] 确认没有手动编辑任何生成物

## 发布契约影响

- [ ] 不影响发布契约
- [ ] 影响发布契约，已在下方说明。涉及：`.github/release-contracts/`、打包 / 发布流程、依赖固定版本、README 下载链接、版本号等

<!-- 说明影响范围与验证方式 -->

## 数据与凭据

- [ ] 变更未包含真实发票、邮箱地址、授权码、API Key、个人姓名或未脱敏日志
- [ ] 未引入遥测、外部识别 API 或需要联网的识别路径
- [ ] 每个提交都包含 DCO `Signed-off-by`（`git commit -s`）

## 其他说明

<!-- 审查者需要了解的边界、兼容性、迁移或回滚信息 -->
