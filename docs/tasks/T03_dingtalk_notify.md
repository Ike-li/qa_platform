# T03: F-NT-02 钉钉通知渠道

> **来源**：feature-catalog.md §4.1 #3
> **必要性**：P1（PRD §8 中国大陆网络硬约束）
> **预计**：S

## 背景

PRD §8 显式约束"需要支持中国大陆网络环境（钉钉/企业微信集成）"。当前 `worker/notifications/channels.py` 已实现 Email 和 Webhook，钉钉缺。

## 实施起点

- **文件**：`src/qaplatform/worker/notifications/channels.py`
- **参考实现**：`WebhookChannel`（line 103-173）
- **路由器**：`ChannelRouter`（line 175+）注册新渠道
- **官方文档**：钉钉自定义机器人 https://open.dingtalk.com/document/orgapp/custom-robot-access

## API 设计

钉钉自定义机器人 webhook：
- URL：`https://oapi.dingtalk.com/robot/send?access_token=<token>` + 可选 `&timestamp=<ts>&sign=<sign>`
- Method：POST application/json
- Body：`{"msgtype": "text", "text": {"content": "..."}}`（或 markdown 类型）
- 加签（可选但推荐）：`sign = base64(HMAC-SHA256(secret, f"{timestamp}\n{secret}"))`

## ChannelConfig schema

通知规则配置时，channel_config 形如：
```json
{
  "access_token": "xxx",
  "secret": "SECxxx",   // 可选，启用加签验证
  "msgtype": "markdown" // 可选，默认 text
}
```

## 验收标准

- [ ] `DingtalkChannel.send(config, message) -> ChannelResult` 实现
- [ ] 注册到 `ChannelRouter`，type 名为 `dingtalk`
- [ ] 支持加签（HMAC-SHA256 + base64）
- [ ] 支持 text / markdown 两种 msgtype
- [ ] HTTP 超时 10s；非 2xx 返回 ChannelResult(success=False, error=...)
- [ ] 钉钉 errcode != 0（API 层错误）也算失败
- [ ] 单元测试：成功 / 加签 / 超时 / errcode 非 0 / msgtype markdown 5 种用例（用 httpx_mock）

## 约束

- **不要把 access_token / secret 记入日志**（用 redact）
- commit：`feat: 通知渠道支持钉钉自定义机器人（含加签）`
- 不引入新依赖（标准库 `hmac` + 已有 `httpx`）

## 不要做

- 不要做 ActionCard 等富格式（YAGNI，PRD 没要求）
- 不要做钉钉企业内部应用 API（自定义机器人足够）
- 不要在 channel_config 里存 webhook URL 完整路径（暴露 token），只存 access_token
