# QA Platform Runbook

操作手册，覆盖常见故障排查、密钥轮换和数据库维护流程。

---

## 1. worker_lost 排障

**现象**：Run 状态变为 `failed`，`error_message` 包含 `worker_lost`。

**原因**：Worker 心跳（`worker:{id}:heartbeat`，TTL 90s）超时未续期，`reclaim_worker_lost` 将该 Run 标记为失败。

**排查步骤**：

1. 检查 worker 进程是否存活：
   ```bash
   ps aux | grep arq
   # 或 docker ps（容器部署）
   ```
2. 检查 Redis 连通性：
   ```bash
   redis-cli -u $QAP_REDIS_URL ping
   ```
3. 查看 worker 日志中 `worker_heartbeat_set_failed` 条目，确认是 Redis 抖动还是进程崩溃。
4. 若 Redis 抖动：心跳循环会自动恢复（fail-open 设计，见下节）；Run 已失败需手动重新触发。
5. 若进程崩溃：重启 worker，检查 OOM / SIGKILL 原因。

**预防**：确保 Redis 有足够内存，避免 `maxmemory-policy allkeys-lru` 驱逐心跳 key。

---

## 2. Redis 抖动 fail-open / fail-closed 行为

系统在以下场景对 Redis 瞬时故障采用不同策略：

| 场景 | 行为 |
|------|------|
| 心跳写入失败 | 记录 warning，循环继续；不终止 worker |
| JWT 黑名单查询失败 | 放行请求（不拒绝合法用户） |
| Rate limit 中间件尚未拿到 Redis client | 放行请求（避免启动期误杀流量） |
| 非认证高风险端点 rate limit Redis 操作异常 | 放行请求（不误杀普通流量） |
| 认证高风险端点 rate limit Redis 操作异常 | fail-closed，返回 503 + `Retry-After: 5` |

**含义**：Redis 短暂宕机不会整体中断服务，但登录、注册、token、refresh、SSE ticket 等认证高风险端点在限流存储异常时会保守拒绝，避免绕过暴力破解防护。已撤销的 JWT 在 Redis 恢复前可能被短暂接受；Redis 恢复后黑名单立即生效。

**监控**：关注 `worker_heartbeat_set_failed`、`jwt_blacklist_check_failed`、`rate_limit_error` 和 `rate_limit_exceeded` 日志条目频率。

---

## 3. PostgreSQL 故障切换

**主库宕机时**：

1. 确认 standby 已追上 WAL（`pg_stat_replication` lag < 1s）。
2. 提升 standby：
   ```bash
   pg_ctl promote -D /var/lib/postgresql/data
   ```
3. 更新 `QAP_DATABASE_URL` 指向新主库，滚动重启 API 和 worker。
4. 检查 alembic 版本一致性：
   ```bash
   alembic current
   ```

**连接池耗尽**：调大 `QAP_DATABASE_POOL_SIZE`（默认 10）和 `QAP_DATABASE_MAX_OVERFLOW`（默认 20），或检查是否有长事务未提交。

---

## 4. QAP_JWT_SECRET 轮换流程

`QAP_JWT_SECRET` 用于签发和验证 access/refresh token。轮换会使所有现存 token 立即失效，用户需重新登录。

**步骤**：

1. 生成新密钥：
   ```bash
   openssl rand -hex 32
   ```
2. 在部署配置中更新 `QAP_JWT_SECRET`。
3. 滚动重启 API 服务（零停机：先更新一半实例，旧 token 在旧实例上仍有效，直到全部切换完成）。
   > 注意：滚动期间旧实例无法验证新密钥签发的 token，建议在低峰期操作或接受短暂 401。
4. 旧 token 在 `QAP_JWT_ACCESS_TOKEN_TTL`（默认 1h）后自然过期。

---

## 5. QAP_ENCRYPTION_KEY 轮换流程

`QAP_ENCRYPTION_KEY` 用于 AES-256-GCM 加密存储的凭据密文（`Credential.encrypted_value`）。支持多版本密钥（`QAP_ENCRYPTION_KEYS`）。

**步骤**：

1. 生成新密钥（64 hex 字符 = 32 bytes）：
   ```bash
   openssl rand -hex 32
   ```
2. 在 `QAP_ENCRYPTION_KEYS` 中添加新版本（版本号递增，0-15）：
   ```env
   QAP_ENCRYPTION_KEYS={"0": "旧key", "1": "新key"}
   ```
   新版本号最大值自动成为加密写入版本；旧版本仍可解密。
3. 重启服务，新写入的凭据使用新密钥加密。
4. 可选：批量重加密旧凭据（读取 → 解密 → 用新密钥加密 → 写回），完成后移除旧版本。

---

## 6. alembic 004 线上 ALTER NULLABLE 预估锁时间

**Migration**：`004_make_audit_event_tenant_id_nullable.py`

**操作**：`ALTER TABLE audit.event ALTER COLUMN tenant_id DROP NOT NULL`

**锁类型**：`ACCESS EXCLUSIVE`（PostgreSQL ALTER COLUMN 需要）

**预估锁时间**：

- 该操作仅修改列约束，**不重写表数据**，锁持有时间通常 < 100ms（取决于表大小和 catalog 更新速度）。
- `audit.event` 表在 MVP 阶段行数有限，实测锁时间预计 < 50ms。
- 生产执行前建议在 `lock_timeout` 保护下运行：
  ```sql
  SET lock_timeout = '2s';
  ALTER TABLE audit.event ALTER COLUMN tenant_id DROP NOT NULL;
  ```
  若超时则重试，避免长时间阻塞写入。

**执行方式**：
```bash
QAP_DATABASE_URL=<prod_url> alembic upgrade head
```

---

## 7. S3 / MinIO 日志 Lifecycle 策略

Run 日志归档到 S3 bucket（`QAP_S3_BUCKET`），路径格式：`logs/{run_id}.jsonl`。

**建议 Lifecycle 规则**：

- `logs/` 与 `QAP_RETENTION_RUNS_DAYS` 对齐（默认 90 天），避免数据库 Run 记录仍存在时 S3 归档对象已先过期；当前 `main` 仍缺归档日志读回 API / UI，因此不能把 lifecycle 对齐单独视为“日志已可回看”闭环。
- `reports/` 与 `QAP_RETENTION_REPORTS_DAYS` 对齐（默认 30 天），用于 JUnit/Allure 等报告产物。

```json
{
  "Rules": [
    {
      "ID": "expire-run-logs",
      "Filter": {"Prefix": "logs/"},
      "Status": "Enabled",
      "Expiration": {"Days": 90}
    },
    {
      "ID": "expire-run-reports",
      "Filter": {"Prefix": "reports/"},
      "Status": "Enabled",
      "Expiration": {"Days": 30}
    }
  ]
}
```

MinIO 配置：
```bash
mc ilm rule add --expire-days 90 myminio/qa-platform --prefix "logs/"
mc ilm rule add --expire-days 30 myminio/qa-platform --prefix "reports/"
```

**注意**：

- `QAP_RETENTION_RUNS_DAYS`（默认 90）控制数据库 Run 行清理目标；`cleanup_old_runs` 每小时硬删超期终态 Run（`done/failed/cancelled/timeout`）并依赖数据库 FK 级联清理 result/artifact/event。S3 lifecycle 独立配置，两者应保持一致或 S3 日志保留期 ≥ DB Run 保留期，避免 DB 有记录但 S3 日志已删除。
- 归档失败时 `LogStream.archive_logs` 会把 Redis Stream TTL 延长到 24h，并把 Run ID 登记到 `run:logs:archive_failed`；worker 的 `retry_failed_archives` cron 会重试这些失败项，成功后清理登记。
- 当前仍缺归档日志读回 API / UI；因此 lifecycle 与 retry 只能证明“写入和补偿归档”，不能单独视为“用户可回看归档日志”闭环。

---

## 8. trusted_proxies 生产配置

`QAP_TRUSTED_PROXIES` 控制哪些反向代理的 `X-Forwarded-For` 头被信任，用于 rate limiting 的真实客户端 IP 识别。

**默认值**：`[]`（空列表）— 不信任任何代理，直接使用 TCP 连接的 `client.host`。

**生产配置**：将 ingress / load balancer 的 CIDR 填入：

```env
# 单个 CIDR
QAP_TRUSTED_PROXIES=["10.0.0.0/8"]

# 多个 CIDR（内网 + 云 LB）
QAP_TRUSTED_PROXIES=["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
```

**安全注意事项**：

- 只填写你控制的代理 IP/CIDR，不要填写 `0.0.0.0/0`。
- 错误配置（信任了不受控的 IP）会导致攻击者伪造 `X-Forwarded-For` 绕过 rate limiting。
- 变更后滚动重启 API 服务生效。

**验证**：部署后检查 `rate_limit_exceeded` 日志中的 `bucket` 字段。未带 Bearer token 的请求应记录为 `ip:<真实客户端 IP>`，而不是代理 IP；带 Bearer token 的请求会记录为 `token:<hash>`，不会暴露原始 token。

---

## 9. Worker Docker Socket 暴露风险

当前 `docker-compose.yml` 的 worker 服务直接挂载宿主 `/var/run/docker.sock`，用于创建测试执行容器。这是单机开发 / 内部小规模部署的便利方案，不是强隔离生产方案。

**风险**：

- worker 被攻陷后，攻击者可通过 Docker API 管理宿主容器，实际接近宿主 root 权限。
- 不适合多租户公网部署，也不适合作为 untrusted code 的强沙箱边界。

**生产加固选项**：

1. 在宿主运行 `tecnativa/docker-socket-proxy`，只向 worker 暴露必要 Docker API。
2. 使用 rootless Docker / gVisor 等运行时降低宿主影响面。
3. 中长期迁移到 K8s Job 执行后端，避免 worker 直接持有宿主 Docker socket。

**上线前检查**：

```bash
docker compose config | grep -n "docker.sock"
```

如果仍看到 `/var/run/docker.sock:/var/run/docker.sock`，应在部署 checklist 中显式记录风险接受人和补偿措施。
