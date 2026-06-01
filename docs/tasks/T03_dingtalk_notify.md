# T03: F-NT-02 钉钉通知渠道

> **来源**：feature-catalog.md §4.1（F-NT-02 钉钉通知）
> **必要性**：P1（PRD §8 中国大陆网络硬约束）
> **预计**：S
> **状态**：已完成（`DingtalkChannel` + `ChannelRouter` + 前端通知规则表单 + unit/frontend contract 验证）

## 背景

PRD §8 显式约束"需要支持中国大陆网络环境（钉钉/企业微信集成）"。当前 `worker/notifications/channels.py` 已实现 Email、Webhook、DingTalk、WeCom，前端通知规则表单也可创建 DingTalk 渠道；本文保留为实现与验收口径记录。

## 实施起点

- **文件**：`src/qaplatform/worker/notifications/channels.py`
- **参考实现**：`WebhookChannel` 的 `ChannelResult` / `httpx.AsyncClient` 调用模式；不要改动既有 `WebhookChannel.TIMEOUT = 30`，钉钉渠道按本任务单独使用 10s 超时
- **路由器**：`ChannelRouter` 注册新渠道
- **官方文档**：钉钉自定义机器人 https://open.dingtalk.com/document/orgapp/custom-robot-access

## API 设计

钉钉自定义机器人 webhook：
- URL：`https://oapi.dingtalk.com/robot/send`，用 `httpx` 的 `params` 传 `access_token`，有 secret 时再传 `timestamp` / `sign`；不要手工拼完整 URL 后再进入日志/错误分支
- Method：POST application/json
- Body：
  - text：`{"msgtype": "text", "text": {"content": message}}`
  - markdown：`{"msgtype": "markdown", "markdown": {"title": title, "text": message}}`，`title` 可来自 config，默认 `QA Platform Notification`
- 加签（有 `secret` 时启用）：`string_to_sign = f"{timestamp}\n{secret}"`，`sign = base64(HMAC-SHA256(secret, string_to_sign))`；通过 `params` 交给 httpx 编码，避免漏掉 URL encode

## ChannelConfig schema

通知规则配置时，channel_config 形如：
```json
{
  "access_token": "xxx",
  "secret": "SECxxx",   // 可选，启用加签验证
  "msgtype": "markdown", // 可选，默认 text
  "title": "QA Platform Notification" // markdown 可选
}
```

## 验收标准

- [x] `DingtalkChannel.send(config, message) -> ChannelResult` 实现
- [x] 注册到 `ChannelRouter`，type 名为 `dingtalk`
- [x] 支持加签（HMAC-SHA256 + base64）
- [x] 支持 text / markdown 两种 msgtype，payload 字段分别为 `text.content` / `markdown.title + markdown.text`
- [x] HTTP 超时 10s；非 2xx 返回 ChannelResult(success=False, error=...)
- [x] 钉钉 errcode != 0（API 层错误）也算失败
- [x] 单元测试：成功 / 加签 / 超时 / errcode 非 0 / msgtype markdown 5 种用例（不要引入 `pytest-httpx`；沿用 patch `httpx.AsyncClient` 的本地测试风格）

## 约束

- **不要把 access_token / secret 记入日志或错误信息**；当前仓库没有通用 token/key redaction helper，构造错误时只返回 HTTP status / 钉钉 `errcode` 等非敏感信息，不回显完整 URL、签名串或配置
- commit：`feat: 通知渠道支持钉钉自定义机器人（含加签）`
- 不引入新依赖（标准库 `hmac` + 已有 `httpx`）

## 不要做

- 不要做 ActionCard 等富格式（YAGNI，PRD 没要求）
- 不要做钉钉企业内部应用 API（自定义机器人足够）
- 不要在 channel_config 里存 webhook URL 完整路径（暴露 token），只存 access_token
