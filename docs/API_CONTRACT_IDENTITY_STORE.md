# Identity & Store API Contract（Issue #5）

> 状态：设计契约；FastAPI OpenAPI 是最终机器可读来源。前缀 /api/v1。
> 认证：服务端 Cookie Session；所有写请求需要 X-CSRF-Token。

## 通用约定

- JSON 使用 snake_case；时间为 ISO 8601 UTC。
- Cookie：__Host-ai_store_session；Secure、HttpOnly、SameSite=Lax、Path=/，无 Domain。
- POST/PATCH/PUT/DELETE 发送 X-CSRF-Token；错误响应包含 request_id，响应头为 X-Request-ID。
- 未认证 401；跨门店 Store/Resource 统一 404；已认证但权限不足 403。
- 客户端不得提交 user_id、role、permission。所有门店范围业务请求使用 X-Store-ID header 选择请求门店；该值是不可信 selector，不是授权凭据。服务端每个请求必须重新验证 Store.status 和当前用户 StoreMembership.status，并据此生成 request-scoped AuthContext。
- Session.active_store_id 仅用于 UI 默认选择/恢复；不作为所有标签页共享的授权上下文。不同标签页可发送不同 X-Store-ID。
- 创建业务资源时 store_id 由 AuthContext 注入，拒绝客户端指定。

## 1. 认证

### POST /auth/login

Request: email、password。
Response 200：user（id、email）、session（expires_at）、csrf_token；设置新 Session Cookie。
失败统一 401 INVALID_CREDENTIALS，不区分邮箱不存在、密码错误或账号锁定；按 IP 与账号维度限流；不记录密码。

### GET /auth/me

Response 200：user（id、email）、active_store（id、name 或 null，仅 UI 默认选择）、session（expires_at）。

### POST /auth/logout

Response 204；撤销当前 Session 并清 Cookie；幂等。

### POST /auth/logout-all

Response 204；递增 User.auth_version 并撤销全部 Session；要求 CSRF 与近期重新认证。

### POST /auth/csrf

已认证时返回当前 Session 的 CSRF token；不得通过 URL 参数获取。

## 2. 门店列表与切换

### GET /me/stores

Response 200：items[]（id、name、role）和 active_store_id（仅默认选择）。只返回当前用户 active membership 且 Store.status=active 的门店；不接受 user_id 查询参数。

### POST /session/active-store

Request：store_id。
Response 200：active_store（id、name）、membership（role）。该接口更新 Session.active_store_id 作为默认选择，不改变其他标签页的请求授权上下文。
服务端事务内验证目标门店存在、启用且当前用户 membership 为 active；失败统一 404 STORE_NOT_FOUND，原上下文不变；成功写 AuditEvent。

### DELETE /session/active-store

Response 204；清除 active_store_id；后续门店业务 API 必须提供 X-Store-ID；缺失时返回 400 STORE_CONTEXT_REQUIRED。

## 3. 成员管理（platform-admin-only）

### GET /admin/stores/{store_id}/members

返回本门店成员最小必要字段：membership id、user id、email、role、status。仅 PlatformAdminGrant.status=active 且具备 platform.store_members.manage；路径 store_id 是管理目标，不要求管理员成为该门店 StoreMembership。

### POST /admin/stores/{store_id}/members/invitations

Request：email、role（首期只允许 member）。
该端点仅为预留契约。只有注册/邀请、邮箱验证、邮件交付、一次性 token 生命周期和撤销流程经产品/安全评审冻结后才可实现；在此之前不得暴露该路由或返回 202 成功。启用后邀请 token 必须一次性、短时有效，数据库仅保存 verifier。

### PATCH /admin/stores/{store_id}/members/{membership_id}

Request：role/status。Response 返回更新后的 membership 与 revoked_at。
仅具备 platform.store_members.manage 能力且 PlatformAdminGrant.status=active 的平台管理员；owner/member 均不得调用。禁止移除/降级最后 active owner；权限变更同事务写审计，并使被撤销成员后续请求即时失效。

## 4. 门店业务资源授权约定

营销任务、商品、活动、文案/图片资产、发布包、渠道账号、效果记录等资源 API 均要求 X-Store-ID header；服务端将其作为不可信 selector，验证当前用户对此门店的 active membership 后才建立 AuthContext.request_store_id。遵守：
- 列表：服务端从 AuthContext.request_store_id 取值，SQL 强制 WHERE store_id = authorized_store。
- 详情：按 id AND store_id 查询；跨店与不存在均 404。
- 创建：store_id 从 AuthContext 注入；拒绝客户端 body 中的 store_id。
- 更新/删除：SQL 同时约束资源 id 与 store_id。
- 文件：签名 URL 前验证 Asset.store_id；默认短时有效（建议 5 分钟）；bucket 私有。
- Job：创建时服务端注入 store_id、actor_user_id；Worker 执行前校验 Job 与关联资源。
- 批量：全部资源同门店才执行；任一越权对象导致整批失败。
- 搜索/导出/聚合/缓存 key 均带服务端门店上下文。

## 5. 统一错误结构

{
  "error": { "code": "RESOURCE_NOT_FOUND", "message": "Resource not found" },
  "request_id": "req_..."
}

| HTTP | code | 场景 |
|---:|---|---|
| 400 | STORE_CONTEXT_REQUIRED | 已认证但未选门店 |
| 401 | UNAUTHENTICATED / INVALID_CREDENTIALS | 未登录、过期、无效凭证 |
| 403 | FORBIDDEN / CSRF_INVALID | 权限不足或 CSRF 失败 |
| 404 | STORE_NOT_FOUND / RESOURCE_NOT_FOUND | 门店不可访问或资源不属于当前门店 |
| 409 | LAST_OWNER_REQUIRED | 将移除/降级最后 owner |
| 429 | RATE_LIMITED | 登录/邀请反滥用 |
| 503 | AUTHORIZATION_UNAVAILABLE | 授权依赖不可用，fail closed |

## 6. 契约门禁

OpenAPI 是最终来源；此文档是语义评审约定。实现 PR 必须更新 OpenAPI 并生成 TypeScript client；CI 检查生成结果无漂移。Contract tests 覆盖状态码、错误 code、Cookie 属性、CSRF 和响应字段。破坏性变更需 ADR。


## 7. 成员管理权限与产品边界

PRODUCT_DESIGN.md v1.8 将门店用户管理明确归属平台管理员的门店详情管理能力。故本契约中成员管理接口仅允许具备 platform.store_members.manage 的平台管理员调用。owner/member 不拥有成员邀请、移除或角色管理接口。平台管理员响应仅返回成员管理所需的最小字段，不返回门店业务内容。

## 8. 请求级门店上下文强约束

任何门店业务 API 均以 X-Store-ID 作为不可信 selector；服务端必须用当前 Session 的 user_id 查询 active StoreMembership，并验证 Store.status=active，构造 AuthContext.request_store_id。禁止从 Session.active_store_id 自动授权。Session.active_store_id 只用于 UI 默认选择。跨门店、多标签页请求互不影响。


## 9. Platform Admin 授权模型

成员管理端点使用独立的 PlatformAdminGrant。请求必须通过正常 User/Session 认证，再验证 PlatformAdminGrant.status=active 与固定能力 platform.store_members.manage。该权限只覆盖门店成员关系管理，不授予 StoreMembership，不允许通过该身份访问门店任务、经营资料、文案、图片或素材内容。成员管理响应严格字段最小化。

成员邀请接口在开户/邀请、邮箱验证、一次性 token、邮件交付与撤销流程未冻结前不得实现；设计端点不构成已批准上线能力。


## 10. 实现补充

- `POST /auth/login` 没有既有 Session CSRF token，因此以严格 Origin allowlist 验证抵御 login CSRF；认证后的所有写请求必须同时携带 `X-CSRF-Token`。
- `POST /auth/csrf` 只允许已认证 Session 和可信 Origin；它会轮换并返回新 token，不接受 URL 参数。
- `POST /auth/logout-all` 请求体为 `password`，通过当前密码即时重新认证后递增 `User.auth_version` 并撤销全部 Session。
- 初始门店 owner 通过离线命令 `python -m store_operator.cli bootstrap-store-owner --email <email> --store-name <name>` 建立；初始/紧急平台管理员通过 `grant-platform-admin` / `revoke-platform-admin` 命令管理，必须提供 reason。CLI 不发送邀请邮件、不替代未来邀请流程。
- Session 时限的本地开发默认值不是生产策略；生产必须显式配置 `SESSION_IDLE_TIMEOUT_SECONDS`、`SESSION_ABSOLUTE_TIMEOUT_SECONDS` 与强随机 `SESSION_TOKEN_PEPPER`。


## 11. 门店初始化参数

离线命令 `bootstrap-store-owner` 必须同时接收 `--email`、`--store-name` 与 `--timezone`。时区必须是有效 IANA 标识，由服务端校验；不允许以部署服务器时区或隐式 UTC 代替门店时区。
