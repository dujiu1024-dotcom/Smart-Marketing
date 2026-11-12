# Douyin OAuth persistence and publish-operation foundation

## Scope

This change builds the server-side persistence and authorization foundation for the approved first-phase path:

local immutable package -> explicit merchant confirmation -> official Douyin API -> readback verification.

It does not claim that a real Douyin account has been connected or that a production test-account publish has been completed.

## Data model

- `oauth_authorization_attempts`: stores only SHA-256 state hashes, requested scopes, fixed redirect URI, and the initiating user/store/session binding. State expires after ten minutes and is consumed with one conditional UPDATE.
- `channel_accounts`: stores the Douyin `open_id`, granted scopes, status, token expiry metadata, and Secret Manager references. It has no token plaintext columns.
- `publish_operations`: records the package, package item, exact merchant confirmation fingerprint, channel account, idempotency key, platform item ID, readback time, retry state and sanitized error summary.
- The publish operation foreign keys include the store key, preventing cross-store package, confirmation, or channel-account references at the database layer.

## OAuth routes

- `POST /api/v1/channels/douyin/oauth/authorize`: requires an authenticated session, CSRF validation and active store membership. It creates a ten-minute state record bound to the current user, store and session.
- `GET /api/v1/channels/douyin/oauth/callback`: requires the initiating authenticated session, checks that the store and membership are still active, verifies the configured redirect URI, and atomically consumes the state before exchanging the single-use authorization code.

The callback rejects a state replay, expiry, different user/session, removed membership, inactive store, redirect mismatch, missing publishing/readback scopes, or account identity mismatch.

## Credential storage

- OAuth tokens are written as one JSON secret to AWS Secrets Manager. The application database stores only the returned secret ARN/reference.
- AWS region and app credentials are deployment settings; AWS credentials must come from the workload's IAM role/default credential chain, not source code.
- If no Secret Manager region is configured, the callback fails closed and does not create an active channel account.
- Never put Client Secret, access token, refresh token, authorization code or raw OAuth state into logs, browser storage, normal DB columns, Job payloads or Outbox payloads.

## Configuration

Set these deployment environment variables only after the Douyin website application and callback URL have been approved:

- `DOUYIN_CLIENT_KEY`
- `DOUYIN_CLIENT_SECRET`
- `DOUYIN_REDIRECT_URI` (HTTPS and exactly registered with the platform)
- `CHANNEL_SECRET_STORE_REGION`
- Optional `CHANNEL_SECRET_STORE_PREFIX`

All three Douyin OAuth settings must be supplied together. The Secret Manager region is independently required before credentials can be persisted.

## Frozen package account binding

- Freeze items may select `delivery_mode=official_api` and a store-owned active Douyin account.
- The API validates provider, active status and the required `user_info`, `video.create` and `video.list` scopes.
- `channel_account_id` is included in the item fingerprint and immutable frozen package payload.
- Manual handoff rejects channel-account binding; official API mode rejects a missing account.
- A composite same-store foreign key protects the package item account reference.
- Douyin image-text posts use `POST /image/upload/` followed by `POST /image_text/create/`; each image is capped at 20 MiB for the pilot and a post accepts at most 30 images.
- Video posts use `POST /video/upload/` and `POST /video/create/`; direct upload is capped at 128 MiB. Larger video files require the official multipart upload protocol, which remains disabled until implemented.
- `GET /api/v1/channels/douyin/accounts` lists account metadata without exposing Secret Manager references or tokens.
- `POST /api/v1/channels/douyin/accounts/{account_id}/refresh` refreshes credentials server-side and updates the secret only if the account has not changed concurrently.

## Merchant-confirmed publish operation

- `POST /api/v1/marketing-tasks/publish-packages/{package_id}/items/{package_item_id}/publish` requires the exact package fingerprint, item fingerprint, and the persisted `PublishConfirmation` ID.
- The API verifies that the frozen item is `official_api`, is bound to an active same-store Douyin account, and has the required scopes.
- `PublishOperation`, Job and `job.dispatch_requested` Outbox event are created in the same database transaction. The Job payload contains only the operation ID and schema version; it never contains tokens or media bytes.
- `GET /api/v1/marketing-tasks/publish-operations/{operation_id}` returns store-scoped operation state.

## Worker safety and readback

- The first worker implementation supports frozen image-text packages whose image assets are private object-storage objects, rights-approved, JPEG/PNG/WebP, at most 20 MiB each, and 1-30 images total.
- Upload is retryable before content creation. Immediately before `/image_text/create/`, the operation moves to `submitting`.
- Once the create request may have reached Douyin, an unknown response moves the operation to `needs_human`; the worker will not blindly submit a second post.
- On a confirmed response, the `item_id` is persisted before readback. Subsequent retries only call `/video/list/` readback; they never upload or create again.
- A readback match records `processing` with `readback_verified=true`. This does not claim public visibility: Douyin says the post may remain self-visible while platform review is pending.
- Repeated readback absence after bounded retries moves the operation to `needs_human` for reconciliation.

## Remaining integration work

- Add an account revoke/disconnect endpoint and a scheduled token-refresh Worker; the account-list and server-side refresh endpoints are implemented.
- Add the merchant-confirmed PublishOperation creation endpoint and transactional Job/Outbox enqueue.
- Implement a registered Worker handler with upload, submit, readback, lease recovery and needs-human reconciliation. An uncertain create-video result must never trigger a blind second create call.
- Add full DB/API tests and browser acceptance, then execute a real test-account OAuth/upload/create/readback flow after platform credentials, scopes and account are supplied.

This change adds the persistence migration, models, one-time OAuth state consumption, Secret Manager adapter, OAuth routes, account listing/refresh, and official-API package/account binding. It does not complete publishing or prove a real OAuth grant.


## 7. 授权取消 Webhook（2026-11-12）

### 回调验证与验签

- 回调入口：`POST /api/v1/channels/douyin/webhook`，无需商家 Session；这是平台服务器回调，不是用户浏览器 API。
- `verify_webhook` 事件只回显 `content.challenge`，不访问数据库、不修改账户状态。
- 其他事件先校验 `client_key`，再以 `SHA1(client_secret + 原始 HTTP body)` 计算十六进制摘要，并使用 constant-time compare 校验 `X-Douyin-Signature`。
- `unauthorize` 必须提供 `Msg-Id`；按 `(provider, message_id)` 唯一约束去重。重复投递直接成功 ACK，不重复撤销或写入第二条 receipt。
- 只保存 message id、事件类型、外部账号 ID 的 SHA-256、scope 事件证据、影响账户数和时间戳；不保存原始请求体、token 或 client_secret。

### 授权取消处理

- 通过 `client_key` + `from_user_id` 匹配当前 App 下的 Douyin `ChannelAccount`，跨门店撤销同一外部授权主体对应的账户记录。
- `unauthorize` 事件将匹配账户置为 `revoked`、清空有效 granted scopes、写入 `revoked_at`；后续发布 Worker 必须只接受 `active` 账户。
- Webhook 只执行快速数据库操作并立即 ACK；平台要求的短超时与重试通过 `Msg-Id` 去重保证幂等。
- 当前版本不在回调线程中同步调用 Secrets Manager 删除凭据。Secret 仍保留在 Secrets Manager，但账户状态已阻止发布使用；凭据 tombstone/清理与定时 refresh-token renew worker 仍是后续工作项。

### 官方平台契约

- Webhook 验签使用原始 body，不能对解析后再序列化的 JSON 计算签名。
- `Msg-Id` 用于回调消息去重；`verify_webhook` 使用 challenge 响应。
- 真实开放平台应用回调配置与测试账号验收仍未完成；Mock/单元测试不等于真实平台验收。
