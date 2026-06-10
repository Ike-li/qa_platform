# 报告分享功能

## 概述

报告分享功能允许用户生成公开访问链接，与团队外部成员分享测试执行报告，无需创建账号或登录。

## 功能特性

- **时间限制**：设置分享链接的过期时间（默认 7 天）
- **访问次数限制**：可选设置最大访问次数
- **安全性**：使用加密令牌，支持撤销
- **无需登录**：外部用户通过链接直接访问报告

## API 使用

### 1. 生成分享链接

```bash
POST /api/v1/runs/{run_id}/shares
```

**请求体：**
```json
{
  "expires_in_days": 7,
  "max_access_count": 10
}
```

**响应：**
```json
{
  "id": "uuid",
  "token": "secure-token-string",
  "expires_at": "2026-06-17T00:00:00Z",
  "max_access_count": 10,
  "share_url": "https://your-domain.com/public/reports/{token}"
}
```

### 2. 列出分享链接

```bash
GET /api/v1/runs/{run_id}/shares
```

**响应：**
```json
{
  "data": [
    {
      "id": "uuid",
      "token": "...",
      "created_by": "user-id",
      "expires_at": "2026-06-17T00:00:00Z",
      "is_expired": false,
      "access_count": 3,
      "max_access_count": 10,
      "last_accessed_at": "2026-06-10T12:00:00Z",
      "created_at": "2026-06-10T08:00:00Z"
    }
  ]
}
```

### 3. 撤销分享链接

```bash
DELETE /api/v1/shares/{share_id}
```

**响应：**
```json
{
  "success": true
}
```

### 4. 公开访问报告

```bash
GET /api/v1/public/reports/{token}
```

无需认证，返回完整的测试执行报告。

## 使用示例

### Python 示例

```python
import requests

# 创建分享链接
response = requests.post(
    "https://api.example.com/api/v1/runs/{run_id}/shares",
    headers={"Authorization": "Bearer YOUR_TOKEN"},
    json={
        "expires_in_days": 3,
        "max_access_count": 5
    }
)

share = response.json()
print(f"分享链接: {share['share_url']}")
print(f"有效期至: {share['expires_at']}")
print(f"剩余访问次数: {share['max_access_count']}")
```

### cURL 示例

```bash
# 生成分享链接
curl -X POST "https://api.example.com/api/v1/runs/{run_id}/shares" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "expires_in_days": 7,
    "max_access_count": 10
  }'

# 列出分享链接
curl "https://api.example.com/api/v1/runs/{run_id}/shares" \
  -H "Authorization: Bearer YOUR_TOKEN"

# 撤销分享
curl -X DELETE "https://api.example.com/api/v1/shares/{share_id}" \
  -H "Authorization: Bearer YOUR_TOKEN"

# 公开访问（无需认证）
curl "https://api.example.com/api/v1/public/reports/{token}"
```

## 使用场景

### 1. 与外部团队分享测试结果

```python
# 为外部合作伙伴生成 3 天有效的分享链接
share = create_share(run_id, expires_in_days=3)
send_email(to="partner@example.com", share_url=share['share_url'])
```

### 2. 临时分享给未注册用户

```python
# 生成单次访问链接
share = create_share(
    run_id, 
    expires_in_days=1, 
    max_access_count=1
)
```

### 3. 分享给多个外部审查员

```python
# 生成可访问 20 次的链接
share = create_share(
    run_id,
    expires_in_days=7,
    max_access_count=20
)
```

## 安全建议

1. **设置合理的过期时间**：根据实际需求设置，避免永久有效
2. **限制访问次数**：对敏感报告设置访问次数上限
3. **及时撤销**：分享完成后及时撤销不再需要的链接
4. **定期审查**：定期检查活跃的分享链接，清理过期链接

## 权限要求

- 创建/列出/撤销分享链接：需要项目 `viewer` 及以上角色
- 公开访问报告：无需认证

## 限制

- 单个 Run 可创建的分享链接数量：无限制（建议定期清理）
- 令牌长度：32 字节 URL-safe Base64 编码
- 最大过期时间：无限制（建议不超过 30 天）
- 访问次数：达到上限后链接自动失效

## 实现细节

- **存储位置**：`report_share_token` 表
- **令牌生成**：使用 `secrets.token_urlsafe(32)` 生成安全随机令牌
- **访问计数**：每次成功访问自动递增
- **过期检查**：访问时实时检查，过期返回 403

## 相关 API

- `POST /api/v1/runs/{run_id}/shares` - 创建分享
- `GET /api/v1/runs/{run_id}/shares` - 列出分享
- `DELETE /api/v1/shares/{share_id}` - 撤销分享
- `GET /api/v1/public/reports/{token}` - 公开访问
