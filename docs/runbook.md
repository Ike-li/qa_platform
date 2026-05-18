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

## 2. Redis 抖动 fail-open 行为

系统在以下场景对 Redis 瞬时故障采用 fail-open（放行）策略：

| 场景 | 行为 |
|------|------|
| 心跳写入失败 | 记录 warning，循环继续；不终止 worker |
| JWT 黑名单查询失败 | 放行请求（不拒绝合法用户） |
| Rate limit Redis 不可用 | 放行请求（不误杀流量） |

**含义**：Redis 短暂宕机不会导致服务中断，但已撤销的 JWT 在 Redis 恢复前可能被短暂接受。Redis 恢复后黑名单立即生效。

**监控**：关注 `worker_heartbeat_set_failed` 和 `jwt_blacklist_check_failed` 日志条目频率。

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

## 4. JWT_SECRET 轮换流程

`JWT_SECRET` 用于签发和验证 access/refresh token。轮换会使所有现存 token 立即失效，用户需重新登录。

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

## 5. ENCRYPTION_KEY 轮换流程

`ENCRYPTION_KEY` 用于 AES-256-GCM 加密存储的凭据（`Credential.value`）。支持多版本密钥（`QAP_ENCRYPTION_KEYS`）。

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

Run 日志归档到 S3 bucket（`QAP_S3_BUCKET`），路径格式：`logs/{run_id}/output.log`。

**建议 Lifecycle 规则**（与 `QAP_RETENTION_REPORTS_DAYS` 对齐）：

```json
{
  "Rules": [{
    "ID": "expire-run-logs",
    "Filter": {"Prefix": "logs/"},
    "Status": "Enabled",
    "Expiration": {"Days": 30}
  }]
}
```

MinIO 配置：
```bash
mc ilm rule add --expire-days 30 myminio/qa-platform --prefix "logs/"
```

**注意**：`QAP_RETENTION_RUNS_DAYS`（默认 90）控制数据库行删除；S3 lifecycle 独立配置，两者应保持一致或 S3 保留期 ≥ DB 保留期，避免 DB 有记录但 S3 日志已删除。

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

**验证**：部署后检查 rate limit 日志中的 `client_ip` 字段是否为真实客户端 IP 而非代理 IP。
