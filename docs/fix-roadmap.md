# QA Platform 修复路线图（合并多 review 共识版）

> 生成日期：2026-05-21
> 输入来源：claude / kimi / glm / xiaomi / deepseek / Antigravity / minimax 共 7 份 review
> 编排原则：每条问题都已通过一手代码验证（grep / sed 已确认存在），剔除误判项；按"安全可利用 → 数据正确性 → 可用性 → 容器/部署 → 测试与一致性"的顺序排布
> 验证基线：`ruff check` 干净；单元测试 608 通过；分支 `main @ a34ced4`

---

## 0. 已剔除的误判项（不要按这些结论修改）

修复前先注意以下 review 中**事实错误**的条目，避免按错误结论改回归：

| Review | 条目 | 实际情况 | 处理 |
|---|---|---|---|
| deepseek 1.5 | "Dockerfile CMD `qaplatform.api:create_app` 不存在" | `src/qaplatform/api/__init__.py` 有 PEP 562 lazy-export shim，路径有效 | **不要改 CMD**；如想统一，把 README 与 Dockerfile 都改成 `qaplatform.main:create_app` 即可 |
| minimax CRITICAL-1 | "JWT 黑名单 fail-open 是 CRITICAL" | `middleware.py:78-90` 注释明确"P1 fail-open: Redis blip must not 500"，是有意识 trade-off；auth 端点已是 fail-closed | 维持现状；可加 metrics + 告警监控 Redis 抖动率，不改默认行为 |
| minimax CRITICAL-2 | "平台管理员 RBAC 跨租户绕过" | `permissions.py:220-225` 注释明确"still scoped to their resolved tenant_id — cross-tenant access is enforced at the request boundary"；`get_for_tenant` 在路由层做了租户校验 | 维持现状；如要补强可在 §3 加单元测试验证 platform_admin 也走 tenant_id |
| xiaomi C-2 | logout 静默吞错标 CRITICAL | kimi §1.3 已纠正：要拆解 `decode 失败`（无风险）与 `revoke 失败`（真漏洞）；只有后者是 P1 | 按 P1 处理（见 §1.5） |
| xiaomi C-5 | docker.sock 标 CRITICAL | 是部署侧风险，不与代码可利用漏洞同级 | 按 P1（容器加固）处理（见 §4.1） |

---

## 第一阶段 — CRITICAL（合并前必须修，预计 1 天）

### §1.1 SQL LIKE 注入 ✅ ecabcc6

**位置**：`src/qaplatform/api/v1/projects.py:45`
**当前**：
```python
pattern = f"%{q}%"
filters.append(or_(ProjectORM.name.ilike(pattern), ProjectORM.description.ilike(pattern)))
```
**问题**：用户输入 `q` 中的 `%`、`_`、`\` 不转义，攻击者可枚举或操纵搜索语义。
**修复**：
```python
def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

pattern = f"%{_escape_like(q)}%"
filters.append(or_(
    ProjectORM.name.ilike(pattern, escape="\\"),
    ProjectORM.description.ilike(pattern, escape="\\"),
))
```
**验证**：单元测试加 `q="%"` / `q="_"` / `q="\\"` 三类输入，断言只匹配字面量。
**来源**：deepseek / xiaomi C-1 / kimi C-1

---

### §1.2 iframe sandbox 逃逸（artifact-preview）✅ ecabcc6

**位置**：`frontend/src/components/runs/artifact-preview.tsx:51`
**当前**：`sandbox="allow-scripts allow-same-origin"`
**问题**：`allow-scripts` + `allow-same-origin` 组合可被 iframe 内脚本编程移除 sandbox 属性，逃逸到父页面访问 localStorage 中的 token。
**修复**（二选一）：
- A：移除 `allow-same-origin`，保留 `allow-scripts`
- B：保留组合但严格白名单 URL 来源（`new URL(url).protocol === "https:" && ALLOWED_HOSTS.includes(host)`）
**验证**：手工跑通 Allure 报告渲染（多数 Allure 不依赖 same-origin）；E2E 加一条恶意 HTML artifact 的 spec。
**来源**：xiaomi C-4 / kimi C-2

---

### §1.3 Run 状态归一化丢失活跃状态 ✅ ecabcc6

**位置**：`frontend/src/hooks/use-runs.ts:23-34`
**当前**：
```ts
const VALID_RUN_STATUSES = new Set(["pending", "running", "passed", "failed", "cancelled", "timed_out"]);
```
**三个错误**：
1. 含后端不存在的 `pending`，缺 `queued` / `preparing` / `collecting` → 这三种状态被默认映射成 `failed`
2. 后端 `done` 无条件映射成 `passed` → 即使有 test failure 也显示"已通过"
3. 后端 `timeout` 映射成 `timed_out` 是对的

**修复**：
```ts
const VALID_RUN_STATUSES = new Set<RunStatus>([
  "queued", "preparing", "running", "collecting",
  "passed", "failed", "cancelled", "timed_out",
]);

function normalizeRun(run: Run | BackendRun): Run {
  const backendRun = run as BackendRun;
  const backendStatus = String(backendRun.status);
  let rawStatus: string;
  if (backendStatus === "done") {
    const failed = backendRun.summary?.failed ?? 0;
    const errors = backendRun.summary?.errors ?? 0;
    rawStatus = failed > 0 || errors > 0 ? "failed" : "passed";
  } else if (backendStatus === "timeout") {
    rawStatus = "timed_out";
  } else {
    rawStatus = backendStatus;
  }
  const status = VALID_RUN_STATUSES.has(rawStatus as RunStatus) ? rawStatus : "failed";
  // ...
}
```
**验证**：vitest（如缺则同步加配置）覆盖 8 种 backend status × {summary 有/无 failed} 的笛卡尔乘积。
**来源**：xiaomi C-3 / kimi C-3 / deepseek 2.3-2.4 / Antigravity 3.3

---

### §1.4 artifact 下载 URL 未验证协议 ✅ ecabcc6

**位置**：`frontend/src/pages/runs/detail.tsx:225`
**当前**：`window.open(url, "_blank");`
**问题**：未验证协议，若后端返回 `javascript:` URL 即触发 XSS。
**修复**：
```ts
const url = await getArtifactDownloadUrl(artifact.id);
let parsed: URL;
try {
  parsed = new URL(url);
} catch {
  toast.error(t("runs.artifacts.invalidUrl"));
  return;
}
if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
  toast.error(t("runs.artifacts.invalidUrl"));
  return;
}
const win = window.open(url, "_blank", "noopener,noreferrer");
if (win) win.opener = null;
```
**来源**：xiaomi H-6 / kimi C-4 / deepseek 2.10

---

## 第二阶段 — P1（合并前应修，预计 2-3 天）

### §2.1 审计写入失败异常向用户传播（19 处 `raise`）✅ 55228e8

**位置**：`src/qaplatform/api/v1/auth.py` — 254、310、368、390、433、513、551、596 等共 9 处 `raise`（含登录失败审计、refresh、logout、token 创建/吊销 等）
**问题**：`api/audit.py:write_audit` 已正确实现 best-effort（log + 吞），但 auth.py 的 `_write_failed_audit` 与各审计 try 块全部在 `rollback` 后 `raise`，把审计 IO 抖动升级成用户 500。
**修复**：所有审计 except 路径统一改为：
```python
except Exception:
    await audit_session.rollback()
    log.warning("audit_write_failed", action=..., exc_info=True)
```
**注意**：本仓库 project memory directive："审计 PII/secret 用 `_serialize(value.model_dump())` 脱敏"已落实在 `api/audit.py`，本条只补"不传播异常"的另一半语义。
**验证**：集成测试模拟 `audit_session.commit` 抛 `OperationalError`，断言 login/logout/refresh 仍返回各自正确状态码（200/204/401），不应得到 500。
**来源**：deepseek 1.1 / claude 2.1 / kimi P1-1 / Antigravity 2.1

---

### §2.2 `jwt_secret` / `encryption_key` 无最小长度校验 ✅ 55228e8

**位置**：`src/qaplatform/config.py:28, 31`
**问题**：裸 `str`，CI 用 11 字节 `test-secret` 已触发 PyJWT `InsecureKeyLengthWarning`。
**修复**：
```python
from pydantic import field_validator

class Settings(BaseSettings):
    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_long_enough(cls, v: str) -> str:
        if len(v.encode()) < 32:
            raise ValueError("jwt_secret must be ≥ 32 bytes (RFC 7518 §3.2)")
        return v

    @field_validator("encryption_key")
    @classmethod
    def _enc_key_is_64_hex(cls, v: str) -> str:
        if len(v) != 64 or not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("encryption_key must be 64 hex chars (32 bytes)")
        return v
```
**配套**：
- 修改 `tests/conftest.py:49` 测试密钥 `"0"*64` → `secrets.token_hex(32)`（也顺便修 P3 secret-scanner 误报）
- 修改 `.github/workflows/ci.yml` 把 `QAP_JWT_SECRET=test-secret` 替换为 64 字符随机串
- 在 `.env.example` 加生成命令注释：`# python -c "import secrets; print(secrets.token_hex(32))"`
**来源**：deepseek 1.3 / claude 2.2 / kimi P1-2 / Antigravity 2.2

---

### §2.3 批量重试丢失原始 Run 的 `priority` ✅ 55228e8

**位置**：`src/qaplatform/api/v1/runs.py:328-338`（`batch_retry_runs`）
**当前**：调用 `repos.run.create()` 创建新 Run 时未传 `priority`，落入默认 1（MEDIUM）。
**修复**：
```diff
 new_run = await repos.run.create(
     tenant_id=original.tenant_id,
     project_id=original.project_id,
     pipeline_id=original.pipeline_id,
     environment_id=original.environment_id,
     git_ref=original.git_ref,
     git_sha=original.git_sha,
+    priority=original.priority,
     triggered_by=user.user_id,
     trigger_type="manual",
     metadata_=dict(original.metadata_ or {}),
 )
```
**验证**：单元测试构造 `priority=0` 的 original，调用 batch_retry，断言 new_run.priority == 0。
**来源**：deepseek 1.2 / claude 2.3 / kimi P1-3 / Antigravity 2.3

---

### §2.4 `docs_url` / `redoc_url` 在 factory 模式下永久关闭 ✅ 55228e8

**位置**：`src/qaplatform/main.py:99-100`
**当前**：`docs_url="/docs" if container and container.settings.debug else None,`
**根因**（取 claude 修正版）：`FastAPI(...)` 构造参数在 `create_app` **同步求值**时计算，uvicorn factory 模式调用 `create_app()` 不传 container，所以条件永远为 False。`lifespan` 内的 `nonlocal container = ...` 无法回填构造参数。
**修复**：
```python
_settings_obj = settings or (container.settings if container else Settings())
_debug = _settings_obj.debug

app = FastAPI(
    ...,
    docs_url="/docs" if _debug else None,
    redoc_url="/redoc" if _debug else None,
    lifespan=lifespan,
)
```
**注意**：当前代码 `main.py:108` 已经计算了 `_settings_obj`，只需把它**提前到 FastAPI 构造之前**即可。
**来源**：deepseek 1.4 / claude 1.2 / Antigravity 2.4

---

### §2.5 logout `revoke()` 失败不应静默 ✅ 55228e8

**位置**：`src/qaplatform/api/v1/auth.py:470-497`（access token + refresh token 两段）
**修复策略**（kimi §1.3 拆解版）：
- `decode_token` 失败 → `pass` 即可，token 本就无效
- `revoke()` 失败 → 必须 `log.warning("token_revoke_failed", jti=jti, exc_info=True)`，否则用户以为已登出实际仍有效
```python
try:
    payload = jwt_svc.decode_token(refresh_token)
except jwt.InvalidTokenError:
    pass
else:
    jti = payload.get("jti"); exp = payload.get("exp")
    if jti and exp:
        ttl = max(0, int(exp) - int(time.time()))
        try:
            await jwt_svc.revoke(jti, ttl)
        except Exception:
            log.warning("token_revoke_failed", jti=jti, exc_info=True)
```
**来源**：xiaomi C-2 / kimi §1.3 / minimax CRITICAL-1（仅采纳 logout 部分，不采纳 fail-open 改造）

---

### §2.6 API token 认证在 session 关闭后访问 ORM 属性 ✅ 55228e8

**位置**：`src/qaplatform/api/auth/middleware.py:172-178`
**问题**：`async with container.db_session_factory() as session:` 块结束后，仍访问 `token.user.role` / `token.user.tenant_id`。这是 SQLAlchemy relationship，可能触发 `DetachedInstanceError`（取决于加载策略）。
**修复**：把 `CurrentUser(...)` 构造移入 `async with` 块内，或在块内显式 `eager_role = token.user.role; eager_tid = token.user.tenant_id`。
**验证**：集成测试用 lazy-load relationship 模式跑 API token 认证一遍。
**来源**：kimi P1-8 / xiaomi H-2 / glm 类似议题

---

### §2.7 Webhook `RESERVED_KEYS` 大小写绕过 ✅ 55228e8

**位置**：`src/qaplatform/api/v1/webhooks.py:89-97`
**修复**：
```python
RESERVED_KEYS = {"git_url", "credential_id", "shallow_clone", "default_branch"}
_RESERVED_LOWER = {k.lower() for k in RESERVED_KEYS}
metadata.update({
    k: v for k, v in body.metadata.items()
    if k.lower() not in _RESERVED_LOWER
})
```
**来源**：xiaomi H-3 / kimi P1-9

---

### §2.8 `CreateTokenRequest.expires_days` 无上界 ✅ 55228e8

**位置**：`src/qaplatform/api/v1/auth.py:59`
**修复**：`expires_days: int = Field(default=90, ge=1, le=365)`
**来源**：kimi P1-10（独家）/ xiaomi M-2

---

### §2.9 nginx 缺安全响应头（前端静态资源）✅ 55228e8

**位置**：`frontend/nginx.conf` — 当前只有 `Cache-Control`
**修复**：在 `server` 块加：
```nginx
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
```
**注意**：CSP 不在这里写死（Vite chunk 哈希命名易冲突），由后端反向代理统一插入。
**来源**：claude 2.7 / kimi P1-6 / deepseek 4.3

---

## 第三阶段 — Glm/Antigravity 独家发现（其他 review 漏掉的真问题）

### §3.1 executor / tasks 双重写入终端状态（glm 独家）✅ 18196f6

**位置**：
- `src/qaplatform/engine/executor.py:250` — 调用 `finish_if_current(...)`
- `src/qaplatform/worker/tasks.py:225` — 又调用一次 `finish_if_current(...)`

**已验证**：两处都做了相同的"将正在 collecting 的 run 推进到终端状态"。`finish_if_current` 是条件 update（`WHERE status IN (...)`），第二次调用会 rowcount=0，所以**不影响正确性**，但语义重复且容易在日志/metrics 上产生迷惑。
**修复**：明确职责边界——
- 选项 A（推荐）：让 `executor.execute()` **只返回** 终端状态，不写库；`tasks.execute_run()` 是唯一写终端状态的地方
- 选项 B：保留 executor 写入路径，tasks 仅在 `executor.execute()` 抛异常时兜底写 FAILED

无论哪个选项，要把另一处对 `finish_if_current` 的调用删掉。

**验证**：单元测试断言"正常完成"路径只有一次 finish_if_current 调用（用 `AsyncMock` 计数）。
**来源**：glm 4.1（独家发现，其他 6 份均未提）

---

### §3.2 `Artifact` / `TestResult` / `RunEvent` 缺 `tenant_id` 列（glm 独家）

**已验证**：`infra/database/models.py:443/479/502` 三个表均无 `tenant_id` 列；隔离依赖 join `Run.tenant_id`。
**风险**：如果后续有 repo 方法绕过 `Run` join、直接按 `run_id` / `id` 查询这三类资源，理论上可跨租户。当前所有 repo 方法都通过 `Run` join，但**没有 ORM 级硬约束兜底**。
**修复（中长期）**：
- 短期：加一个 lint check 或 grep CI，禁止直接 `SELECT FROM artifact / test_result / run_event WHERE id=?` 不带 join 的写法
- 长期：在三个表加 `tenant_id` 冗余列 + FK，迁移时回填，并加 `CHECK (tenant_id = (SELECT tenant_id FROM run WHERE id=run_id))` 约束（PG 不支持，可改 trigger）

**验证**：现有 `tests/integration/test_cross_tenant_isolation.py` 已覆盖 11 端点，建议追加 `/api/v1/artifacts/{id}` 和 `/api/v1/runs/{id}/test-results` 的跨租户用例。
**来源**：glm §3.2（独家）✅ c243372

---

### §3.3 SQLAlchemy 2.0 `overlaps` 警告（Antigravity 独家）✅ ba63ae9

**位置**：`src/qaplatform/infra/database/models.py`
**已验证**：以下 relationship 在多对一映射上确实存在列重叠（多个 relationship 同时写 `Run.project_id` 或 `ProjectMember.tenant_id`），但都没声明 `overlaps=`：
- `Run` 的 `pipeline` / `project` 关系（共写 `project_id`）
- `ProjectMember` 的 `user` / `project` 关系（共写 `tenant_id`）

**警告样例**：
```
SAWarning: relationship 'Run.pipeline' will copy column pipeline.project_id to column run.project_id, which conflicts with relationship(s): 'Run.project' ...
```
**修复**：按警告提示加 `overlaps=` 显式声明：
```python
# class Run
pipeline: Mapped[Pipeline] = relationship(
    "Pipeline", back_populates="runs", lazy="joined",
    overlaps="project",
)

# class ProjectMember
user: Mapped[AppUser] = relationship(
    "AppUser", lazy="joined",
    overlaps="members,project",
)
```
**验证**：`pytest -W error::sqlalchemy.exc.SAWarning tests/unit -q` 应不再报。
**来源**：Antigravity 2.6（独家发现）

---

### §3.4 Mock 协程未 await 的 RuntimeWarning（Antigravity 独家）

**现象**：`pytest tests/unit -q` 输出多处：
```
RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
```
**含义**：被测代码 `await` 了 mock 出的同步 `MagicMock` 而非 `AsyncMock`，或测试体内 `mock.return_value = some_async_method` 但没 `await`。这意味着测试通过可能是"虚假通过"。
**修复**：
1. 跑 `pytest -W error::RuntimeWarning tests/unit -q` 把所有警告升为错误
2. 逐一修复：把 mock 异步函数的地方统一改用 `AsyncMock`
3. CI 中持续保留 `-W error::RuntimeWarning`

**重点检查**：`test_executor.py`、`test_log_stream.py`、`test_projects.py`（Antigravity 提名）
**来源**：Antigravity 4.3（独家）✅ 88962f0

---

## 第四阶段 — 容器与 DevOps 加固（预计 1-2 天）

### §4.1 worker 容器挂载 `/var/run/docker.sock`

**位置**：`docker-compose.yml:127-128`
**风险**：worker 一旦被攻陷（执行用户 image + setup_script，攻击面大），可 `docker run --privileged -v /:/host` 拿宿主 root。
**修复路径**：
- 单机：宿主端跑 `tecnativa/docker-socket-proxy`，worker 通过 TCP 只暴露 `containers, images, exec` API
- 严肃部署：迁到 K8s Job 后端（`engine/docker_backend.py` 已是 Protocol，可替换）
- 至少：在 README/runbook 中标红"本镜像不适合多租户公网部署"
**注意**：本条不是代码可利用漏洞，**不是 CRITICAL**（更正 xiaomi C-5 的级别）。✅ c243372
**来源**：deepseek 4.1 / claude 2.4 / kimi P1-4 / xiaomi C-5

---

### §4.2 Dockerfile 缺 `USER`（应用容器以 root 运行）✅ abbbccd

**位置**：`Dockerfile`
**修复**：
```dockerfile
RUN useradd -u 1000 -m app
USER app:app
```
**注意**：worker 容器还要保证 `app` 用户在 `docker.sock` 的 GID 上（与 §4.1 联动）。
**来源**：claude 2.5 / kimi P1-5 / xiaomi H-10 / deepseek 4.2

---

### §4.3 E2E 测试在 CI 中被禁用 ⚠️ abbbccd（部分完成）

**位置**：`.github/workflows/ci.yml:138-139`（`if: false`）
**当前**：`tests/e2e/` 已有 3 个 spec + 完整 playwright config 但不跑。
**修复**：先把 `auth-flow.spec.ts` 启用（最稳定），其余暂时改 `if: github.event_name == 'workflow_dispatch'` 以便手工拉起。
**配套**：修复 `tests/e2e/global-setup.ts:88-90` 硬编码 `admin:admin123`，改用 `E2E_ADMIN_PASSWORD` 环境变量。
**实际状态（2026-05-25 复核）**：`ci.yml:139` 全部 E2E spec 改为 `workflow_dispatch` 手动触发；`auth-flow.spec.ts` 的 push 触发**未启用**。视为部分完成，剩余工作记入 `feature-catalog.md` §4.2。
**来源**：claude 2.8 / kimi P1-7 / deepseek 4.3 / xiaomi M-15

---

## 第五阶段 — 数据库与测试整理（预计 1 天）

### §5.1 `admin_user` fixture 类型错误 ✅ 2479ec8

**位置**：`tests/conftest.py:85-97`
**问题**：导入 Pydantic `User`（`qaplatform.domain.models.user.User`）传给 `AsyncSession.add()`，会抛 `InvalidRequestError`。当前无测试用，是"埋雷"。
**修复**：改为 `from qaplatform.infra.database.models import AppUser as User`，或直接删除 fixture。
**来源**：deepseek 3.1 / Antigravity 4.1

---

### §5.2 迁移 005 给 `__soft_deletable__=False` 的表加了 `deleted_at` ✅ 1f2e578

**位置**：`alembic/versions/005_add_soft_delete_deleted_at.py:27-43`
**已验证**：`TestResult` / `RunEvent` / `NotificationLog` 在 ORM 模型中标 `__soft_deletable__ = False`（物理删除），但迁移仍向它们加 `deleted_at` 列 + 部分索引。语义矛盾且浪费存储。
**修复**：从 `TABLES` 列表删除 `test_result`、`run_event`、`notification_log` 三项，再写一个 `006_remove_unused_deleted_at.py` 迁移把三个表的 `deleted_at` 列和对应索引删掉。
**注意**：降级路径要谨慎——若已有 NULL 数据可直接 drop column；若线上库有非 NULL 数据需先确认无业务依赖。
**来源**：deepseek 3.2 / Antigravity 4.2

---

### §5.3 测试 fixture 中 `dependency_overrides` 共享字典竞争

**位置**：`tests/integration/conftest.py:444-495`
**修复**：每个测试用副本，或 yield 后 try/finally 还原。
**来源**：deepseek 3.9 / kimi P2-4.10

> pytest 默认顺序执行，当前无并发问题。标记为已知限制。

---

## 第六阶段 — P2 一致性与可读性（按需排期）

| # | 文件 | 问题 | 修复要点 |
|---|---|---|---|
| 6.1 | `engine/executor.py:637` | artifact 上传将整个文件读入内存 | `put_object(Body=open(path, "rb"))` 流式上传 | ✅ 5b08402 |
| 6.2 | `engine/executor.py:443` | runner 加载失败回退到 `stage.config["command"]` 注入 `sh -c` | get_runner 直接 raise，无 fallback | ✅ 18196f6 |
| 6.3 | `auth.py:398-416` | refresh 端点在用户查找前撤销旧 token | 撤销移到用户验证成功后 | ✅ d08ff3c |
| 6.4 | `rate_limit.py:157` | 用 `time.time()` 作 Redis score，时钟回拨重置限流 | 改 Redis `TIME` | ✅ acdc2fc |
| 6.5 | `frontend/components/ui/switch.tsx:11` | `data-[state=state=unchecked]` 笔误（unchecked 状态背景失效） | 改 `data-[state=unchecked]` | ✅ 5b08402 |
| 6.6 | `frontend/components/layout/command-palette.tsx:22` | `enabled` 当 API param 泄露给后端 | hook 内剥离 `enabled` 给 useQuery | ✅ b354c35 |
| 6.7 | `frontend/pages/projects/detail.tsx:52` + `create-project-modal.tsx:29` | 同名 `createProjectSchema` 不同实现 | 提到 `lib/validations.ts`，重命名 `createProjectSchema` / `updateProjectSchema` |
| 6.8 | `hooks/use-runs.ts:19` + `use-projects.ts:5` | `unwrapPaginated` 重复定义 | 提到 `lib/utils.ts` | ✅ 5b08402 |
| 6.9 | `worker/tasks.py:303` | `base_image` 无白名单 | Docker 镜像名格式校验 | ✅ 36bf038 |
| 6.10 | `frontend/package.json` | `lucide-react ^1.16.0` / `typescript ~6.0.2` / `vite ^8.0.12` 版本号反常 | 干净机器跑 `npm ci` 验证锁文件能装；如装不上回到 lucide-react `^0.x` |
| 6.11 | `frontend/src/hooks/use-sse.ts:83` | SSE ticket URL 拼接未 encode | `?ticket=${encodeURIComponent(ticket)}` | ✅ 18196f6 |
| 6.12 | `frontend/pages/runs/detail.tsx:120` | 可取消状态硬编码与后端无契约 | 暴露 `/api/v1/runs/{id}` 返回 `cancellable: bool` 字段 |

---

## 第七阶段 — P3 文档与代码清理

| # | 内容 |
|---|---|
| 7.1 | 同步 `docs/TODO.md`：F-AU-02（API Token）已实现，标记从 ❌ 改 ✅ | ✅ 9915d94 |
| 7.2 | 修正 `README.md` 架构图："Vue 3" → "React 19" | 已无 Vue 引用，跳过 |
| 7.3 | `auth.py` 内函数 `from argon2 import PasswordHasher` 提到模块级单例 | ✅ 9915d94 |
| 7.4 | `runs.py:286-287` 裸 `except Exception` 收窄为 `(SQLAlchemyError, ValueError)` | ✅ 9915d94 |
| 7.5 | `engine/executor.py` 673 行 / `auth.py` 642 行可拆分（stages.py / login.py + tokens.py） | 重构，不阻塞发版 |
| 7.6 | 注册端点用 `Role.OWNER.value` 替代硬编码 `"owner"` 字符串 | ✅ 9915d94 |

---

## 工作量与排期建议

| 阶段 | 工作量 | 解锁条件 |
|---|---|---|
| 第一阶段（CRITICAL §1.1-1.4） | 1 天 | 立即开始；阻塞合并 |
| 第二阶段（P1 §2.1-2.9） | 2-3 天 | 在第一阶段完成后排序入 |
| 第三阶段（独家发现 §3.1-3.4） | 1-2 天 | 与第二阶段并行 |
| 第四阶段（容器加固 §4.1-4.3） | 1-2 天 | 与运维确认部署后续 |
| 第五阶段（数据库/测试 §5.1-5.3） | 1 天 | 第二阶段完成后 |
| 第六阶段（P2） | 滚动排期 | 不阻塞合并 |
| 第七阶段（P3） | 可选 | 不阻塞合并 |

**推荐合并 gate**：`第一 + 第二 + §3.1 + §3.3 + §3.4 + §5.1 + §5.2` 完成后即可发版（约 5 个工作日）。

---

## 修复进度跟踪建议

每条 §x.y 在 PR 描述中引用本文件锚点，commit 风格遵循 project memory directive：
- 中文 commit message + semantic prefix
- 单一意图，宁拆勿合
- 例：`fix: §1.1 SQL LIKE 注入 — projects.q 参数转义通配符`

完成后在本文件每条目末尾加 `✅ {commit-sha}`，便于回溯。
