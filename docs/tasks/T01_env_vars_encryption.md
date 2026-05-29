# T01: F-PL-02 环境变量加密

> **来源**：feature-catalog.md §4.1（F-PL-02）
> **状态**：已完成并作为验收档案保留。当前实现使用 JSON-safe AES-256-GCM envelope 存入 `Environment.env_vars` JSONB，migration `007` 加密既有数据，API create/fetch/update、AAD 错配 audit、worker 解密注入容器均有自动化证据。
> **必要性**：P0（PRD §3.2 验收项）
> **预计**：M（含数据迁移，历史估算）

## 背景

PRD §3.2 F-PL-02 验收要求"环境变量加密存储"。当前 `Environment.env_vars` 保留 JSONB 列形态，但存储内容是加密 envelope，不再是明文 env var dict。
凭据（Credential）已经通过 `dependencies.py::CryptoService` 做 AES-256-GCM 加密（路由经 `request.app.state.container.crypto_service` 调用），env_vars 应当复用同一套机制，AAD 绑 environment_id 防换位。

## 缺什么

已完成。历史缺口曾包括明文 JSONB、create/update 未加密、worker 未解密、既有数据迁移；当前对应代码和测试已落地。

## 实施起点

- **ORM**：`src/qaplatform/infra/database/models.py` — 改成二进制列（如 `env_vars_encrypted: Mapped[bytes]` + `LargeBinary`）或在原列加密存储。注意 `CryptoService.encrypt(...)` 返回 `bytes`，当前 `env_vars` 是 JSONB；若保留 JSONB 原列，必须存 base64/envelope 字符串或对象，不能把 raw bytes 直接写入 JSONB
- **加密**：`src/qaplatform/dependencies.py::CryptoService` — 复用，AAD 用 `f"env:{environment_id}"`
- **路由**：`src/qaplatform/api/v1/environments.py` — 项目嵌套路由 `/api/v1/projects/{project_id}/environments/{env_id}`；读时 decrypt、写时 encrypt
- **执行侧**：`src/qaplatform/worker/tasks.py` 会在构建 `PipelineConfig` 时解密 `environment_orm.env_vars`，再把明文 dict 传给 executor / runner
- **迁移**：alembic migration `007_encrypt_environment_env_vars.py` 遍历既有 env_vars 数据加密回写

## 设计要点

1. 加密粒度：整个 `env_vars` dict 序列化后整体加密（不要按 key 加密 — 会泄露 key 名）
2. AAD：`f"env:{environment_id}".encode()` 防止把环境 A 的密文搬到环境 B
3. 创建路径：当前 `Environment.id` 由数据库 `server_default` 生成；要么应用侧预生成 UUID 后再 encrypt，要么先 flush 出 id 后再 encrypt/update，不能在没有 environment_id 时生成 AAD
4. 密钥版本：复用 `CryptoService.encrypt` / `decrypt` 的多版本机制，envelope 含 `key_version` header
5. 迁移降级：alembic upgrade 时如果发现已有 envelope 格式则跳过（幂等）

## 验收标准

- [x] `Environment` 表存储为密文 envelope（保留 JSONB 原列，手工 `SELECT env_vars FROM environment` 看不到明文）
- [x] `GET /api/v1/projects/{project_id}/environments/{env_id}` 返回解密后的明文（被授权用户）
- [x] `POST/PUT` 写入路径加密
- [x] create 路径生成密文时已经有稳定 environment_id，AAD 与最终落库 id 一致
- [x] worker 执行 Run 时拿到解密后的明文 env_vars；不得把密文 dict/bytes 传入 executor
- [x] 加密失败/解密失败时返回 500 并写 audit
- [x] alembic upgrade 后既有数据全部加密；downgrade 能解密恢复
- [x] 跨环境 AAD 校验：手工把环境 A 的密文塞给环境 B，解密失败
- [x] 保留 JSONB 原列，密文表示是 JSON-safe envelope，不出现 raw bytes 写 JSONB 的路径
- [x] 单元测试：加密 → 解密往返；AAD 错配；key_version 轮换
- [x] 集成测试：完整 create → fetch → update → fetch 循环；external-stack worker smoke 验证解密 env var 注入真实执行容器

## 约束

- audit 写入必须先用不含 secret/PII 的 schema 或 `value.model_dump()`，再交 `_serialize(...)` 规范化；**不要记录 env_vars 明文**
- 跨租户访问 environment 返回 404
- commit 拆分建议：
  1. `feat: 添加 env_vars 加密 CryptoService 包装` (ORM + crypto)
  2. `feat: environments 路由集成加密读写`
  3. `feat: alembic 迁移加密既有 env_vars 数据`
  4. `test: env_vars 加密往返与 AAD 校验单元测试`

## 不要做

- 不要按 key 单独加密（会泄露 key 名）
- 不要把 env_vars 列改成 plaintext+ciphertext 双写（一致性风险）
- 不要顺手改 Credential 加密逻辑（已稳定）
