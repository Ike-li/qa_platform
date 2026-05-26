# T04: F-NT-02 企业微信通知渠道

> **来源**：feature-catalog.md §4.1（F-NT-02 企业微信通知）
> **必要性**：P1（PRD §8 中国大陆网络硬约束）
> **预计**：S

## 背景

PRD §8"中国大陆网络"约束的第二个渠道。模式与钉钉非常相似但更简单（无加签）。

## 实施起点

- **文件**：`src/qaplatform/worker/notifications/channels.py`
- **参考实现**：`WebhookChannel` 的 `ChannelResult` / `httpx.AsyncClient` 调用模式；若当前分支已包含 T03，则参考 `DingtalkChannel` 的错误处理与测试风格；不要改动既有 `WebhookChannel.TIMEOUT = 30`，企微渠道按本任务单独使用 10s 超时
- **官方文档**：企微群机器人 https://developer.work.weixin.qq.com/document/path/91770

## API 设计

企微群机器人 webhook：
- URL：`https://qyapi.weixin.qq.com/cgi-bin/webhook/send`，用 `httpx` 的 `params` 传 `key`；不要手工拼完整 URL 后进入日志/错误分支
- Method：POST application/json
- Body：
  - text：`{"msgtype": "text", "text": {"content": message}}`
  - markdown：`{"msgtype": "markdown", "markdown": {"content": message}}`
- 鉴权：URL 里的 `key` 即凭证，**无加签机制**

## ChannelConfig schema

```json
{
  "webhook_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "msgtype": "markdown"  // 可选，默认 text
}
```

## 验收标准

- [ ] `WecomChannel.send(config, message) -> ChannelResult` 实现
- [ ] 注册到 `ChannelRouter`，type 名为 `wecom`
- [ ] 支持 text / markdown 两种 msgtype，payload 字段分别为 `text.content` / `markdown.content`
- [ ] HTTP 超时 10s；非 2xx 返回失败
- [ ] 企微 errcode != 0 也算失败
- [ ] 单元测试：成功 / 超时 / errcode 非 0 / msgtype markdown 4 种用例（不要引入 `pytest-httpx`；沿用 patch `httpx.AsyncClient` 的本地测试风格）

## 约束

- **不要把 webhook_key 记入日志或错误信息**；构造错误时只返回 HTTP status / 企微 `errcode` 等非敏感信息，不回显完整 URL 或配置
- commit：`feat: 通知渠道支持企业微信群机器人`
- 不引入新依赖

## 不要做

- 不要做企微应用消息（需要企业 corp_id + 应用 secret，复杂度高，PRD 没要求）
- 不要做图文/卡片消息（YAGNI）
- 不要在 channel_config 里存 webhook URL 完整路径，只存 `webhook_key`
