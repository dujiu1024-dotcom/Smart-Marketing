# 渠道账号与官方发布集成领域设计（Issue #12）

> 状态：设计提案；首个渠道平台尚未选择  
> 日期：2026-11-11  
> 产品基线：PRODUCT_DESIGN.md v1.8 / UX_AUDIT_AND_REDESIGN.md v1.8  
> Demo 基线：门店资料 channels、营销任务 task 的 channel / publish 步骤

## 1. 目标与边界

建立真实、可审计、可恢复的渠道官方授权与发布能力。首期只选择一个经项目负责人确认、官方 API/OAuth 条件明确的平台完成端到端试点；证明真实授权、能力探测、内容校验、草稿/发布、状态核验和幂等恢复可用后，再逐个扩展。

本领域负责门店渠道账号、平台规格/能力、OAuth Token 生命周期、官方 ChannelAdapter 和外部 PublishOperation。它不负责营销任务、内容产物、质检、Job 调度或经营归因。

### 1.1 明确不做

- 不把渠道连接做成平台管理员后台一级模块；渠道账号归门店前端的门店资料。
- 不把四个平台的 UI 展示当作四个平台已接通。
- 不默认使用浏览器自动化、Cookie 注入、验证码绕过或非官方私有接口。
- 不伪造平台成功、作品 ID、发布 URL、草稿或规则校验结果。
- 不把 PublishOperation 的状态复制为 Job 状态；不重新实现 Outbox、租约和重试调度。
- 不做广告投放、付费推广、营销预算、CRM/POS 数据接入。
- 不在本 PR 默认选择具体平台；必须通过首个渠道选择门禁。

## 2. Demo 页面与产品流程映射

| Demo 页面/路由 | 产品职责 | #12 生产职责 |
|---|---|---|
| store:channels | 门店渠道账号管理 | 连接/断开账号、授权范围、连接状态、能力状态、重新授权 |
| task → channel | 渠道内容适配 | 消费 #8 ChannelContent 与 ChannelSpecVersion；执行真实平台能力校验（平台支持时） |
| task → publish | 最终发布确认 | 消费 #8 已冻结且已确认的 PublishPackage；为 official_api PackageItem 创建 PublishOperation |
| 账号运营监测 | 作品登记、账号状态 | 提供平台账号/作品的可核验证据；作品归因和经营效果由 #13 负责 |

Demo 的连接、校验和发布目前均为本地演示，不是真实 OAuth 或平台 API。生产实现必须保留现有页面层级和交互，不新增独立“渠道管理中心”。

## 3. 跨域所有权

| 对象/能力 | 权威所有者 | #12 职责 |
|---|---|---|
| Session、AuthorizedStoreContext、门店授权 | #5 | 每个请求验证当前 store 与 membership；#12 不自行按 role 判断 |
| StoreRecordRevision、MediaAsset、门店资料 | #6 | 只读取已授权引用，不复制门店事实 |
| MarketingTask、目标渠道、BusinessFactSnapshot | #7 | 消费任务快照和目标渠道，不推进任务主状态 |
| Artifact、ChannelContent、PublishPackage、PackageItem、PublishConfirmation、QualityReport | #8 | 校验包确认与 fingerprint；不重写内容产物/审核/质检状态 |
| Job、Attempt、Outbox、租约、重试 | #9 | 通过 Job Runtime 执行异步适配器调用，不复制 Job 状态机 |
| Prompt/Provider Adapter/AIInvocation | #10 / #9 | 不持有 AI Prompt 或模型路由 |
| ChannelAccount、ChannelSpecVersion、ChannelCapabilitySnapshot、PublishOperation | #12 | 本领域唯一权威所有者 |
| 原始渠道指标、经营归因 | #12 提供原始证据；#13 负责归因 | 不在 #12 生成经营效果结论 |

**关键状态区分：** Job succeeded 只表示 Worker 处理完成；PublishOperation.published 必须有平台真实证据。不得用 Job 成功推断外部作品已发布。

## 4. 领域模型

### 4.1 ChannelAccount（门店级）

建议字段：

**id, store_id, channel_key, external_account_id, display_name, authorization_status(pending|active|reauth_required|revoked|error), granted_scopes_json, access_token_secret_ref, refresh_token_secret_ref, token_expires_at, authorized_by_user_id, authorized_at, last_verified_at, version, created_at, updated_at**

- Token 不落普通数据库明文；只保存 Secret Manager/Vault 的引用。
- UNIQUE(store_id, channel_key, external_account_id)；同一门店可连接多个账号，同一外部账号是否允许跨门店连接需由平台策略决定。
- access/refresh token 的创建、轮换、撤销由 Secret Manager 完成；DB 只记录引用和状态。
- external_account_id 是平台返回的稳定主体 ID，不使用昵称作为唯一标识。
- ChannelAccount 仅属于一个 store；所有读写必须经过 #5 AuthorizedStoreContext。
- PlatformAdminGrant 不因此获得门店渠道账号、作品、Token 或内容读取权。

### 4.2 OAuthAuthorizationAttempt

建议字段：

**id, store_id, channel_key, requested_by_user_id, state_hash, nonce, pkce_verifier_secret_ref, redirect_uri_key, expires_at, consumed_at, result, created_at**

- state 原文不存数据库；只保存 hash，单次使用，建议 TTL 5–10 分钟。
- 支持 PKCE 的平台必须启用；不支持时使用一次性 state + nonce + 严格 redirect URI。
- callback 必须验证 state hash、TTL、未消费、发起人仍有该 store membership、redirect URI 与预期一致。
- OAuth code 只在服务端交换，不写日志、事件或前端存储。
- 一次授权 attempt 只能成功消费一次；重复 callback 返回幂等结果，不重复创建账号。

### 4.3 ChannelSpecVersion（平台级不可变规格）

建议字段：

**id, channel_key, spec_version, text_constraints_json, media_constraints_json, hashtag_constraints_json, link_constraints_json, schedule_constraints_json, draft_supported, publish_supported, status(published|superseded), published_at, source_document_ref, created_at**

- ChannelSpecVersion 是平台公开规则的结构化快照；无 store_id。
- 规格更新创建新版本；旧 ChannelContent/PublishPackage 继续引用原版本，不静默改变历史内容。
- 规则来源必须保存官方文档 URL/版本/检查日期；未核验项标记 pending_verification。
- 文本长度、图片格式/尺寸/比例、标签数量、链接/定位、定时发布等能力逐项表达，不用一个泛化 supports_publish 布尔值覆盖。

### 4.4 ChannelCapabilitySnapshot（账号级能力快照）

建议字段：

**id, store_id, channel_account_id, channel_key, spec_version, capability_key, support_status(supported|unsupported|pending_verification), evidence_ref, reason, checked_at, expires_at, created_at**

- 能力属于具体账号/应用授权上下文；不能只根据平台名称推断。
- capability_key 示例：account_read、draft_create、draft_read、publish_text、publish_image、publish_video、publish_schedule、publish_status_query、metrics_read。
- 每次授权、Token scope 变化、平台 API 版本变化或定期刷新后重新探测。
- pending_verification / unsupported 必须在 UI 明确展示；不能伪装成已接通。
- ChannelCapabilitySnapshot 是历史快照；新探测创建新记录，不覆盖旧证据。

### 4.5 PublishOperation（外部发布业务结果）

建议字段：

**id, store_id, publish_package_id, package_item_id, package_fingerprint, channel_account_id, action(save_draft|publish), status(requested|queued|submitting|processing|draft_saved|published|failed|needs_human|cancelled), idempotency_key, request_fingerprint, external_request_id, external_post_id, external_url, response_evidence_ref, error_code, error_summary, requested_by_user_id, created_at, started_at, finished_at**

- 每个官方 API PackageItem/Action 对应一个 PublishOperation；manual_handoff 不创建 PublishOperation。
- UNIQUE(store_id, package_item_id, channel_account_id, action, package_fingerprint)，并以稳定 idempotency_key 防重复。
- operation 必须绑定 #8 的确切 PublishPackage fingerprint 和 PackageItem；不得发布未确认、已变化或跨店的内容。
- draft_saved 只代表平台确认草稿保存；published 必须有可核验平台响应/作品记录。
- processing 表示平台已接受异步任务但最终结果未确认。
- needs_human 表示结果未知、无法安全自动重试或平台需要人工处理。
- failed 只用于明确的失败证据；网络超时不等同于失败。
- cancelled 仅允许在外部提交前安全取消；提交后的撤销由平台能力决定，不能伪装本地取消。

### 4.6 PublishOperationAttempt

建议字段：

**id, store_id, publish_operation_id, attempt_no, adapter_version, request_fingerprint, provider_request_id, response_evidence_ref, normalized_status, error_code, retryable, started_at, finished_at**

- 保存每次外部平台调用的证据和归一化结果；与 #9 JobAttempt 区分。
- JobAttempt 是 Worker 执行尝试；PublishOperationAttempt 是外部平台 API 调用事实。
- 响应正文按最小化原则保存受控引用；不得存 Token、授权码或完整敏感头。

## 5. ChannelAdapter 接口

每个官方平台一个 Adapter，遵循 #12 统一接口；业务域不得直接调用厂商 SDK。

| 方法 | 用途 | 平台不支持时 |
|---|---|---|
| build_authorization_url | 生成 OAuth 授权地址 | 明确 unsupported |
| exchange_code | 服务端授权码交换 | 失败归一化 |
| refresh_token | 刷新/轮换 Token | 失效转 reauth_required |
| revoke_token | 撤销授权 | 若平台不支持，明确标注并本地清理 Secret |
| get_account_profile | 读取外部账号 ID/昵称 | 未验证不标 active |
| discover_capabilities | 探测账号能力 | 输出 CapabilitySnapshot |
| validate_content | 官方字段/素材校验 | 不支持时只做本地预检，UI 标明非官方校验 |
| save_draft | 创建草稿 | unsupported 不可假成功 |
| read_draft | 读回草稿并核验 | 不支持时由项目负责人批准替代 DoD |
| publish | 提交正式发布 | 需确认包 fingerprint 和账号能力 |
| get_operation_status | 查询提交结果 | 不支持时未知结果进入 needs_human |
| get_published_item | 读取作品 ID/URL/发布时间 | 无法核验不标 published |
| fetch_raw_metrics | 获取原始平台指标 | 只存原始证据，#13 负责归因 |

统一 Adapter 结果至少包含：**channel_key, external_request_id, external_post_id, external_url, normalized_status, response_evidence_ref, retryable, retry_after, normalized_error**。

## 6. OAuth 与凭据安全

1. OAuth start 由已认证门店用户发起；服务端从 AuthorizedStoreContext 注入 store_id / user_id。
2. state/nonce/PKCE 一次性、短 TTL、绑定 store/user/channel/redirect_uri；禁止信任 callback query 中的 store_id。
3. callback 验证发起用户当前仍有 active StoreMembership，门店仍 active；否则拒绝保存 Token。
4. OAuth code、access token、refresh token 只在服务端处理；写入受控 Secret Manager，DB 只存 secret_ref。
5. Token refresh 使用行锁/CAS 与 token version 防并发刷新；refresh token rotation 成功后原子更新 SecretRef。
6. invalid_grant、scope 撤销或账号失效时，标记 reauth_required；不得无限刷新/重试。
7. disconnect 记录审计、调用官方 revoke（若支持）、删除/禁用 SecretRef，并将 ChannelAccount 标记 revoked。
8. Secret 不进入 API 响应、前端、日志、异常文本、Outbox payload 或普通数据库字段。
9. 账号与能力查询统一按 store_id 过滤；跨店 IDOR 采用 #5 统一 404。
10. OAuth client secret 是平台级部署 Secret，放 Secret Manager/部署环境；不新增平台管理员渠道连接页面。

## 7. 发布命令、幂等与未知结果

### 7.1 发布前门禁

创建 PublishOperation 前，服务端必须重新校验：

- #5 当前请求的 AuthorizedStoreContext 和 StoreMembership 仍 active。
- Store.status 仍 active。
- #8 PublishPackage 处于 frozen，PublishConfirmation 存在且 package_fingerprint 完全匹配。
- PackageItem 仍引用当前冻结版本、ChannelContent 和 QualityReport；没有 stale/blocked 依赖。
- ChannelAccount 属于同一 store 且 authorization_status=active。
- 当前 ChannelCapabilitySnapshot 对应同一 account、spec_version 和 capability，且未过期。
- 内容符合 ChannelSpecVersion；如只有本地预检，不能声称官方校验通过。
- 用户确认的发布时间/发布动作与 PackageItem fingerprint 一致。

### 7.2 状态边界

- #9 Job 状态：queued/running/retry_wait/succeeded/failed/needs_human/cancelled，表示执行调度。
- #12 PublishOperation 状态：requested/queued/submitting/processing/draft_saved/published/failed/needs_human/cancelled，表示外部平台业务结果。
- Worker 返回 succeeded 不得直接把 PublishOperation 标记 published；必须检查平台真实响应或查询结果。
- PublishOperation.published 需要 external_post_id 或平台提供的等价可验证证据；external_url 可选但建议保存。
- Job failed 不必然等于 PublishOperation failed；应先读取 OperationAttempt 和平台状态。

### 7.3 幂等与结果未知

- 稳定幂等键由 store_id + package_item_id + channel_account_id + action + package_fingerprint 生成。
- 同一 PackageItem 同一账号同一 action 重复请求返回原 PublishOperation，不创建第二次发布。
- 支持平台幂等键时传递该 key；不支持时必须记录能力限制。
- 超时后优先按 external_request_id、平台任务 ID 或作品查询接口核验；不得仅凭本地 timeout 重发。
- 无法查询结果、平台不支持幂等且外部请求可能已受理时，状态置 needs_human，等待账号运营监测/人工核验。
- 对 Webhook 必须验证签名、时间戳、事件 ID，并以平台事件 ID 去重；不支持 Webhook 时使用受控 polling。

## 8. API 与事件草案

### 8.1 门店渠道账号 API

| Method | Path | 用途 |
|---|---|---|
| GET | /api/v1/stores/{store_id}/channel-accounts | 当前门店账号列表（服务端仍验证 AuthorizedStoreContext） |
| POST | /api/v1/stores/{store_id}/channel-accounts/{channel_key}/oauth/start | 创建 OAuthAuthorizationAttempt 并返回授权 URL |
| GET | /api/v1/channel-oauth/{channel_key}/callback | 服务端 OAuth callback；不信任 query 中 store_id |
| POST | /api/v1/stores/{store_id}/channel-accounts/{id}/refresh | 触发受控 Token 刷新/重新验证 |
| POST | /api/v1/stores/{store_id}/channel-accounts/{id}/disconnect | 撤销/断开账号 |
| POST | /api/v1/stores/{store_id}/channel-accounts/{id}/capabilities/refresh | 重新探测能力 |
| GET | /api/v1/stores/{store_id}/channel-accounts/{id}/capabilities | 读取能力快照 |

### 8.2 PublishOperation API（内部/任务执行）

| Method | Path | 用途 |
|---|---|---|
| POST | /api/v1/publish-operations | #8/#9 内部命令创建操作；校验 package confirmation |
| GET | /api/v1/publish-operations/{id} | 读取外部发布状态与证据 |
| POST | /api/v1/publish-operations/{id}/reconcile | 对结果未知的操作执行受控核验 |
| POST | /api/v1/channel-webhooks/{channel_key} | 官方 Webhook 接收；签名验证、事件去重 |

所有门店请求由 #5 解析授权上下文；客户端传入 store_id 仅是 selector，不是授权证据。所有写请求使用 Idempotency-Key；状态变更使用 expected_version/If-Match。

### 8.3 事件

- channel.account_authorized / channel.account_reauth_required / channel.account_revoked
- channel.capabilities_refreshed
- channel.publish_operation_created / channel.publish_operation_updated / channel.publish_operation_published / channel.publish_operation_needs_human
- #12 发事件时只包含 store_id、account_id、operation_id、fingerprint、状态和外部证据引用；不包含 Token/授权码。

## 9. 首个平台选择门禁

本 PR 不选平台。产品负责人确认前，只冻结通用 Adapter/领域边界，不创建平台专属 SDK、OAuth 配置或“假发布”。

候选平台对比至少核验：

| 维度 | 必须取得的证据 |
|---|---|
| 官方 API/OAuth | 官方开放平台文档、申请入口、API 版本和可用地区 |
| 主体资质 | 企业/个体资质、行业限制、应用审核周期 |
| 授权范围 | 实际可申请 scopes、账号归属和撤销机制 |
| 内容能力 | 文本/图片/视频/话题/链接/定位字段及限制 |
| 草稿 | 是否支持 create + read-back；官方文档或测试结果 |
| 发布 | 发布接口、审核/异步状态、作品 ID/URL |
| 查询与幂等 | 状态查询、Webhook、幂等键或可检索 request ID |
| 账号权限 | 测试账号、沙箱、应用审核后的真实权限 |
| 运营限制 | 限流、每日配额、内容政策、风险控制 |
| 成本与合规 | 接入费用、数据区域、隐私政策、内容数据保留 |

首个渠道选择由项目负责人确认；如果草稿/发布权限未获批，明确阻塞，不以页面自动化替代官方 API。

## 10. 测试矩阵（设计准备，全部待执行）

| ID | 场景 | 预期 |
|---|---|---|
| CH-01 | OAuth state 不存在/过期/重复 callback | 拒绝，不能创建账号 |
| CH-02 | OAuth state 与 store/user/channel/redirect_uri 不匹配 | 拒绝并审计 |
| CH-03 | PKCE verifier 错误 | 拒绝 code exchange |
| CH-04 | OAuth callback 时成员已撤销/门店已停用 | 拒绝保存 Token |
| CH-05 | Token/refresh token/授权码进入 API 响应或日志 | 安全测试失败 |
| CH-06 | refresh token 并发轮换 | 只发生一次有效轮换，SecretRef 原子更新 |
| CH-07 | invalid_grant / scope revoked | account 进入 reauth_required，不无限重试 |
| CH-08 | 跨 store 读取/断开 ChannelAccount | 统一 404 |
| CH-09 | ChannelCapabilitySnapshot 过期/unsupported | 禁止对应操作，UI 明确标识 |
| CH-10 | ChannelSpecVersion 更新 | 旧 ChannelContent/Package 保留旧 spec 版本 |
| CH-11 | 未确认/指纹不匹配 PublishPackage 发起发布 | 阻断，不创建外部请求 |
| CH-12 | PackageItem 与 ChannelAccount 不属于同一 store | 阻断并审计 |
| CH-13 | 同一 idempotency key 重复提交 | 返回原 PublishOperation，不重复发布 |
| CH-14 | 外部发布 timeout 但平台已受理 | 查询/对账，不盲目重发 |
| CH-15 | 平台不支持状态查询且结果未知 | needs_human |
| CH-16 | Worker Job succeeded 但无平台成功证据 | PublishOperation 不得标 published |
| CH-17 | 平台返回明确审核拒绝/字段错误 | failed，保留外部证据和可解释原因 |
| CH-18 | Webhook 签名错误/重放/重复 event ID | 拒绝或幂等去重 |
| CH-19 | manual_handoff PackageItem | 不创建 PublishOperation，不伪造官方发布 |
| CH-20 | unsupported draft/publish capability | UI 显示 unsupported，不能假成功 |
| CH-21 | PublishOperation published | 必须有 external_post_id 或等价平台证据 |
| CH-22 | 原始渠道指标 | 只写原始证据，不直接计算归因或经营效果 |

## 11. 联合评审待决项

1. 首个试点平台及官方 API/OAuth 申请主体、区域和测试账号。
2. 平台是否真实支持草稿 create/read-back；若不支持，由产品负责人批准替代 DoD。
3. 是否支持异步发布状态查询、Webhook、幂等键；不支持时的人工核验流程。
4. ChannelSpecVersion 的来源更新频率、版本冻结和过期策略。
5. Token Secret Manager 的具体实现、加密/轮换/删除 SLA。
6. 同一外部账号是否允许跨门店绑定；首期建议默认允许由业务授权决定，但数据记录始终按 store 隔离。
7. 发布后是否支持平台侧删除/撤回；首期不承诺撤回能力。
8. #13 原始指标读取范围、频率、平台限制和数据保留。
9. #8 PublishPackageItem 的 channel_account_id 绑定时点：最终确认时绑定，还是发布命令创建时绑定；首期建议确认时冻结账号引用。
10. #9 Job 与 #12 PublishOperationAttempt 的重试/对账边界及 needs_human 事件消费者。

## 12. 实施门禁

- #4 工程基础 PR #16 已合并；Issue #4 仍有人工 clean-machine onboarding/trace-correlation 验收项。
- #5 Identity、#6 Store Knowledge、#7 MarketingTask、#8 Content/Publishing、#9 Job Runtime、#10 AI Provider/Prompt 的生产实现尚未全部验收。
- #12 设计可先行；特定平台实现必须等产品负责人确认首个平台和官方权限。
- 本文是通用设计提案；不实现真实 OAuth、Token 存储、平台 SDK 或 PublishOperation 生产代码。
- 所有 Mock/演示连接必须标注模拟，不得作为真实渠道接通证据。
