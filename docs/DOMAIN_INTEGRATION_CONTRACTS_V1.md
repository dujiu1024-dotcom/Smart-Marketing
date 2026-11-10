# 跨领域集成契约 v1

> 覆盖 Issue：#5–#10  
> 产品基线：PRODUCT_DESIGN.md v1.8  
> 技术基线：TECH_STACK_SELECTION.md（FastAPI、PostgreSQL、Celery + Redis、SeaweedFS）  
> 状态：跨域对齐提案，待 B/C/D 轨道联合评审冻结  
> 日期：2026-11-11

## 1. 契约目的与所有权

本文件解决 Identity、Store Knowledge、Marketing Orchestrator、Content/Media/Publishing、Job Runtime、AI Gateway 之间的边界。它是跨模块契约，不替代各领域设计文档；发生冲突时按下列所有权裁决：

| 契约/数据 | 权威所有者 | 消费者 |
|---|---|---|
| User、Store 生命周期、StoreUser、Session、AuthorizedStoreContext | #5 Identity & Store | #6–#10 |
| StoreProfile、Product、Offer、BrandGuideline、KnowledgeItem、MediaAsset | #6 Store Knowledge | #7–#10 |
| MarketingTask、RequirementSnapshot、StrategySnapshot、TaskStep、DependencyEdge、TaskEvent | #7 Marketing Orchestrator | #8–#10 |
| CopyArtifact、ImageArtifact、ArtifactVersion、ReviewRecord、ChannelContent、QualityReport、PublishPackage、PublishConfirmation | #8 Content/Media/Publishing | #7、#9、#10 |
| Job、JobAttempt、JobEvent、OutboxEvent、JobType、lease/retry/recovery | #9 Job Runtime | #7、#8、#10、#11、#12 |
| AIInvocation、ModelConfig、Provider capability registry、Prompt execution metadata、usage/cost | #9 AI Gateway contract; concrete provider adapters #10 | #7、#8、#11 |
| Text/Image/Vision/OCR provider concrete adapters and real integrations | #10 | #9 Gateway |
| API OpenAPI schema generation | API module owner per endpoint | Web client |

AI Gateway 与 Provider 的责任必须区分：#9 定义稳定调用接口、路由策略、调用审计、成本和错误归一化；#10 实现至少一条真实 TextProvider、ImageProvider 和适用的 Vision/OCR adapter。业务域不能直接引用厂商 SDK。

## 2. 全局数据与授权不变量

- 所有门店业务表均含 `store_id UUID NOT NULL`；全局配置/平台目录等非门店数据明确例外并说明访问策略。
- User/Session 不把 store_id 当作认证事实；请求处理由 #5 构造 AuthorizedStoreContext。
- 门店子资源优先使用 `(store_id, id)` 复合唯一键和复合外键；查询必须先限定授权 store_id。
- API 禁止信任 body/query/path 中的 store_id 作为授权依据；若允许 path 中出现 store_id，也必须与服务端上下文匹配。
- 跨门店资源访问统一返回 404；已认证但动作能力不足返回 403。
- 金额 Decimal + currency；时刻 UTC timestamptz；门店本地日历/营业时间保留 IANA timezone；未知事实 NULL。
- 历史快照与产物版本不可变；修改产生新版本，禁止覆盖历史内容。
- 事件追加写入，事件 Schema 必须有版本；敏感认证材料和密钥绝不进入事件或日志。

## 3. 身份上下文与门店成员关系（#5）

规范对象：User、Store、StoreUser、Session、AuthorizedStoreContext。字段、Cookie、Session 轮换、撤销、CSRF 和 API 草案以 `IDENTITY_STORE_SECURITY_DESIGN.md` 为准。

模块调用规则：
- HTTP 层验证 Session，授权服务根据 active StoreUser + active Store 构造上下文。
- 应用服务接收 context 参数，不接受 caller 自己组装的 actor/store/role。
- Worker 不携带用户 Cookie；Job 只保存发起人引用和门店 ID，执行前后按 Job policy 重新验证门店和任务。
- 平台管理员与门店身份分离，不因平台管理员身份默认可读取商家任务、文案、图片或经营数据。

## 4. Store Knowledge（#6）实体契约

建议实体字段（字段类型为 PostgreSQL 语义，最终由 SQLAlchemy/Alembic 迁移确认）：

### StoreProfile
`id, store_id, display_name, business_type, brand_name, address, phone, opening_hours_json, service_description, fact_status, source, confirmed_by, confirmed_at, version, created_at, updated_at`
- UNIQUE(store_id, id)；门店一对一档案可 UNIQUE(store_id)。
- 门店档案只存经营信息；Store.status 与 Store.timezone 的身份域权威字段不可复制写入。营业时间以 Store.timezone 解释，门店可在 Identity 域变更时区并产生审计事件。

### Product
`id, store_id, name, category, sku, specification, price_amount, currency, availability_status, capacity_value, capacity_unit, selling_points_json, fact_status, source, confirmed_by, confirmed_at, version, archived_at, created_at, updated_at`
- price_amount NUMERIC(12,2) NULL；currency CHAR(3) NULL；不得将价格作为 float。
- SKU 若有值，UNIQUE(store_id, sku)；不假设所有业态都有 SKU。
- 库存/产能未知时 NULL；不将 NULL 解释为 0。

### Offer
`id, store_id, title, offer_type, terms_json, applicable_product_ids, starts_at, ends_at, timezone, status, fact_status, confirmed_by, confirmed_at, version, created_at, updated_at`
- 有效期存 UTC timestamptz；门店本地展示和日期边界统一使用 Identity 域 Store.timezone，避免每个 Offer 自行保存互相冲突的 timezone。
- terms_json 必须通过 Pydantic discriminated union 校验：discount_percent {percent}; discount_amount {amount,currency}; fixed_price {amount,currency}; buy_x_get_y {buy_quantity,get_quantity,eligible_product_ids}; gift {gift_description,eligible_product_ids}; threshold_discount {minimum_spend,currency,discount_type,discount_value}。适用商品、限制次数/数量、有效期与适用门店事实单独保存并校验，不能只依赖自由文本。

### BrandGuideline
`id, store_id, positioning, differentiators, tone_of_voice, prohibited_phrases, visual_rules_json, asset_requirements_json, version, status, created_at, updated_at`

### KnowledgeItem
`id, store_id, title, content_ref, source_type, source_ref, fact_status, confirmed_by, confirmed_at, version, created_at, updated_at`
- 大文档/附件存对象存储；DB 保存对象引用、哈希和索引元数据。
- 只有 confirmed 的事实可进入高风险文案/图片事实上下文。

### MediaAsset
`id, store_id, object_key, sha256, mime_type, byte_size, width, height, source_type, source_ref, license_note, parent_asset_id, version, status, created_by, created_at`
- MediaAsset 是门店素材库中的来源资产，不等同于 #8 的 ImageArtifact。#8 产物可引用一个或多个 MediaAsset，但不得覆盖它们。
- 原始素材 immutable；编辑结果若被商家保存回素材库，使用新 asset/version 并关联 parent_asset_id。
- object_key 不可公开；签名 URL 由已授权服务短时签发。

## 5. Marketing Orchestrator（#7）实体契约

完整状态机与依赖规则以 `MARKETING_TASK_DOMAIN_DESIGN.md` 为准。核心字段：

### MarketingTask
`id, store_id, task_type, lifecycle_status, current_requirement_snapshot_id, current_strategy_snapshot_id, version, created_by, created_at, updated_at, completed_at, archived_at`
- UNIQUE(store_id, id)；version 用整数乐观锁。
- lifecycle_status 采用文档中 draft/active/waiting_for_user/blocked/failed/completed/cancelled/archived。

### RequirementSnapshot / StrategySnapshot
不可变：`id, store_id, task_id, version_no, payload_json, content_fingerprint, confirmed_by, confirmed_at, created_at`。
payload_json 必须存可追溯的门店资料引用/版本、关键事实确认状态、需求与策略字段；禁止仅存动态外键。

### TaskStep
`id, store_id, task_id, step_key, status, applicability, input_fingerprint, output_refs_json, block_reason, started_at, finished_at, version`。
- TaskStep status 统一为 pending/running/waiting_for_user/succeeded/failed/skipped/stale。
- 非适用节点由服务端判定并记录原因；适用审核不得跳过。

### DependencyEdge
`id, store_id, task_id, upstream_type, upstream_id, upstream_version, upstream_fingerprint, downstream_type, downstream_id, downstream_version, impact_policy, created_at`。
- 失效以版本 ID + 内容指纹传播，按实际依赖闭包计算。

### TaskEvent
`event_id, store_id, task_id, aggregate_version, event_type, actor_type, actor_id, correlation_id, causation_id, schema_version, payload_json, occurred_at`。
- 事件追加写入；敏感内容不进入事件 payload。

## 6. Content / Media / Publishing（#8）实体契约

### Artifact / ArtifactVersion
逻辑 Artifact 与不可变版本分离。Artifact 保存 `id, store_id, task_id, artifact_type(copy|image|channel_content), current_version_id, created_at`；ArtifactVersion 保存 `id, store_id, artifact_id, version_no, source_type(ai_generated|merchant_upload|manual_edit), source_refs_json, instruction, content_ref/content_json, content_hash, provider_id, model_id, prompt_version_id, input_fingerprint, created_by, created_at`。
- 大图片二进制放 SeaweedFS/S3；DB 仅保存 object key、hash、MIME、尺寸与版本元数据。
- 新版本不能覆盖旧版本；current_version_id 只是当前展示指针，不是历史事实。

### ReviewRecord
`id, store_id, artifact_id, artifact_version_id, review_type(copy|image), decision(approved|revision_requested|rejected), reviewer_id, comment, target_json, created_at`。
- Review 永远绑定确切 version；对旧版本审核不能自动应用于新版本。
- Copy 与 Image review 分开保存和查询。

### ChannelContent
`id, store_id, task_id, channel_key, channel_account_id, copy_version_id, image_version_ids, payload_json, spec_version, input_fingerprint, status, created_at, updated_at`。
- 渠道规则与账号能力分开：spec_version 表示适配规格版本；账号授权和支持能力由 Channel Integration 持有。
- 变体依赖指纹变化时标 stale。

### QualityReport
`id, store_id, task_id, channel_content_id, rule_version, input_fingerprint, result(pass|fail|needs_human), issues_json, created_at`。
- 硬性问题未解决不能冻结发布包；人工复核结果必须有操作者和理由。

### PublishPackage / PublishConfirmation
PublishPackage：`id, store_id, task_id, package_version, channel_content_id, copy_version_id, image_version_ids, quality_report_id, fact_snapshot_ids, content_fingerprint, frozen_at, frozen_by`。
PublishConfirmation：`id, store_id, publish_package_id, package_fingerprint, confirmed_by, confirmed_at, revoked_at`。
- PublishPackage 冻结后不可变；任何上游变更生成新包。
- 最终确认必须绑定包 ID + fingerprint；新包不能继承旧确认。

## 7. Job Runtime（#9）实体与状态契约

### Job
`id, store_id, marketing_task_id NULL, job_type, status, idempotency_key, payload_ref/payload_json, result_ref/result_json, input_fingerprint, attempt_count, max_attempts, available_at, lease_owner, lease_token, lease_expires_at, heartbeat_at, progress_json, error_code, error_summary, created_by, correlation_id, created_at, started_at, finished_at`。
- UNIQUE(store_id, idempotency_key)；若同一门店内多操作域共享 key，额外纳入 job_type/operation namespace。
- 所有门店 Job 必须 store_id NOT NULL；系统级 Job 使用显式 system scope，不允许 NULL 被误解释为任意门店。
- payload/result 有敏感信息时存受控引用，不将密钥/完整敏感 prompt 写入 JSON。
- PostgreSQL 为 Job 状态事实源；Celery/Redis 只负责至少一次投递。

### JobAttempt / JobEvent / OutboxEvent
- JobAttempt：`id, job_id, attempt_no, worker_id, status, started_at, heartbeat_at, finished_at, error_code, error_summary`，UNIQUE(job_id, attempt_no)。
- JobEvent：追加式状态事件，含 event_id、job_id、store_id、event_type、schema_version、payload、occurred_at。
- OutboxEvent：`id, aggregate_type, aggregate_id, store_id, event_type, schema_version, payload_json, occurred_at, published_at, publish_attempts, next_attempt_at`。
- Outbox 与业务记录同事务写入；Relay 投递成功后记录 published_at；消费者必须幂等。

### 唯一 Job 状态枚举（统一 #7/#9）
`queued, running, retry_wait, succeeded, failed, dead, needs_human, cancelled`。
- 不使用 `needs_attention`；所有发布不确定、需人工核验的情况统一 `needs_human`。
- TaskStep 与 Job 状态不同；Job succeeded 不自动表示 TaskStep succeeded。
- Job dead 表示自动重试耗尽/进入死信；needs_human 表示需要人核验或决策；failed 表示本次执行终止但仍允许显式恢复/重试策略。

## 8. AI Gateway / Provider（#9/#10）契约

### AIInvocation（#9 权威）
`id, store_id, task_id NULL, job_id NULL, provider_key, model_key, capability(text_generate|text_rewrite|image_generate|image_edit|vision_inspect|ocr_extract), prompt_version_id, request_fingerprint, response_ref, input_units, output_units, cost_amount, currency, duration_ms, status, error_code, created_at, finished_at`。
- 记录调用元数据和成本；原始敏感 prompt/response 存受控引用或按最小化原则脱敏，不直接写普通日志。
- AIInvocation 状态：queued/running/succeeded/failed/cancelled；它不是 Job，也不拥有营销业务状态。

### Provider 接口（#9 定义，#10 实现）
- TextProvider.generate(request, context) -> StructuredTextResult
- TextProvider.rewrite(request, context) -> StructuredTextResult
- ImageProvider.generate(request, context) -> ImageResult
- ImageProvider.edit(request, context) -> ImageResult
- VisionProvider.inspect(request, context) -> VisionResult
- OCRProvider.extract(request, context) -> OCRResult

Provider 统一返回：provider_key、model_key、provider_request_id、status、normalized_usage、latency_ms、result_ref、retryable、normalized_error。厂商原始异常不能泄漏给业务层或前端。

### 错误分类
- PROVIDER_RATE_LIMITED (429)：可重试，按 Retry-After/退避策略。
- PROVIDER_TIMEOUT：读取型/生成型调用按幂等策略重试；不确定副作用需人工核验。
- PROVIDER_UNAVAILABLE：有限重试。
- PROVIDER_INVALID_OUTPUT：Schema/事实校验失败，不能写正式产物。
- PROVIDER_AUTH_FAILED：不自动无限重试，通知管理员检查 Secret reference。
- PROVIDER_POLICY_BLOCKED：记录合规阻断，不尝试通过提示词绕过安全策略。

## 9. API 与事件的共同约束

- API 版本前缀 `/api/v1`；JSON Schema 由 Pydantic 生成 OpenAPI，TypeScript Client 从 OpenAPI 生成。
- 所有写请求（任务/产物/审核/Job 人工恢复/发布）必须有 Idempotency-Key；更新有 expected_version 或 If-Match。
- 标准错误：`{code, message, request_id, details?}`。跨门店资源 404；能力不足 403；并发冲突 409；字段校验 422；限流 429。
- 列表默认按当前 AuthorizedStoreContext 限定，不允许客户端提供任意 store_id 查询全量数据。
- 对外事件采用 snake_case event_type + schema_version；至少含 event_id、store_id、aggregate_type/id、correlation_id、causation_id、occurred_at。
- 事件 payload 只传引用、状态和必要摘要；大文件和敏感文本不放事件总线。

## 10. 关键 API 契约清单

### #5 Identity
见 `IDENTITY_STORE_SECURITY_DESIGN.md`，以其 OpenAPI 草案为准。

### #6 Store Knowledge
- GET/POST /api/v1/store/profile
- GET/POST /api/v1/store/products；GET/PATCH/DELETE /api/v1/store/products/{product_id}
- GET/POST /api/v1/store/offers；GET/PATCH/DELETE /api/v1/store/offers/{offer_id}
- GET/PATCH /api/v1/store/brand-guideline
- GET/POST /api/v1/store/knowledge-items；GET/PATCH/DELETE /api/v1/store/knowledge-items/{item_id}
- POST /api/v1/store/assets/upload-intents；POST /api/v1/store/assets/complete；GET /api/v1/store/assets/{asset_id}；POST /api/v1/store/assets/{asset_id}/download-url

### #7 Marketing
以 MARKETING_TASK_DOMAIN_DESIGN.md 的 API 契约草案为准；task 创建/更新、需求/策略确认、步骤决策和恢复必须由领域服务执行。

### #8 Content / Publishing
- POST /api/v1/marketing-tasks/{task_id}/artifacts
- POST /api/v1/artifacts/{artifact_id}/versions
- POST /api/v1/artifact-versions/{version_id}/reviews
- POST /api/v1/channel-content
- POST /api/v1/quality-reports/run
- POST /api/v1/publish-packages/freeze
- POST /api/v1/publish-packages/{package_id}/confirm
- POST /api/v1/publish-packages/{package_id}/publish
发布 API 必须在服务端重新校验审核、质检指纹、最终确认、门店状态、账号授权和发布幂等键。

### #9 Job / AI Gateway
- GET /api/v1/jobs/{job_id}
- POST /api/v1/jobs/{job_id}/retry（需授权与幂等）
- POST /api/v1/jobs/{job_id}/cancel
- POST /api/v1/jobs/{job_id}/resolve（仅 needs_human，需原因和审计）
- GET /api/v1/ai/invocations/{invocation_id}
Job API 只暴露授权门店范围内的状态/错误摘要，不返回 Secret 或敏感 payload。

## 11. 跨域事件清单

| Event | Owner | Consumers | 语义 |
|---|---|---|---|
| identity.store_user.activated/removed | #5 | #6–#10 | 成员授权变化，触发权限缓存失效/待执行操作重新评估 |
| identity.store.suspended | #5 | #6–#10 | 阻断新操作；发布副作用前重新验证 |
| store.fact.confirmed/changed | #6 | #7–#10 | 事实版本变化，更新任务快照/依赖指纹 |
| store.asset.created/versioned | #6 | #8/#10 | 新素材可被任务引用 |
| marketing_task.created/activated | #7 | #9 | 业务动作需要异步执行时创建 Job |
| marketing_task.snapshot_changed | #7 | #8/#10 | 依赖变化，按 DependencyEdge 传播 stale |
| artifact.version_created | #8 | #7/#9 | 产物版本变化，更新任务步骤/提交后续 Job |
| artifact.review_decided | #8 | #7 | 审核决定回写任务步骤视图 |
| quality_report.completed | #8 | #7/#9 | 质检完成，领域服务校验输入指纹后推进步骤 |
| publish_package.frozen/confirmed | #8 | #9 | 冻结/确认后可请求草稿或发布 Job |
| job.succeeded/failed/needs_human | #9 | 发起该 Job 的业务域 | 回传执行结果；业务域校验后更新自己的状态 |
| ai.invocation.completed/failed | #9 | #7/#8/#10 | 调用审计/成本与任务关联 |

事件消费者必须幂等；不能仅因收到 job.succeeded 就直接修改 MarketingTask。

## 12. 必须联合验证的跨域场景

1. A 门店用户创建任务，尝试篡改 store_id 创建到 B 门店：拒绝/忽略伪造字段。
2. A 门店用户访问 B 门店 task/artifact/job/file ID：统一 404。
3. 成员移除后已有 Session 访问资料、审核、恢复和发布：后续请求拒绝。
4. 已排队 Job 的发起者被移除：执行前按策略取消/转人工；发布前再校验成员与门店状态。
5. StoreProfile 商品价格版本变化：只让引用该价格的下游文案/图片/质检/发布包 stale。
6. 文案版本变化：文案审核重置到新版本；仅真实依赖它的图片/渠道内容/质检 stale。
7. 图片版本变化：不重置文案审核；相关渠道素材/画面质检/发布包 stale。
8. Worker 成功但 task 输入指纹已变化：拒绝将旧结果挂到当前版本。
9. Outbox 重复投递：消费者幂等，不重复创建版本/审核/外部动作。
10. 发布请求超时：Job needs_human，查询平台结果后才允许恢复。
11. AI Provider 429/超时/无效 JSON：Job 按错误类别重试或转人工，AIInvocation 保留失败审计。
12. AI 返回未经确认的价格/优惠/门店事实：事实校验失败，不进入正式产物。
13. 旧 PublishPackage 确认后上游版本变化：旧包不可修改，新包必须重新确认。
14. 平台管理员访问门店内容：默认拒绝，必要支持访问必须有独立受审计授权。

## 13. 冻结清单与阻塞项

在 B/C/D 轨道联合评审中必须逐项给出 accept / change / defer：
- [ ] #5：平台管理员主体存储、Session 时限、CSRF 方案、门店切换上下文策略、成员邀请/注册流程。
- [ ] #5：owner/member 固定角色和首期能力映射。
- [ ] #6：Offer 结构化优惠规则 schema、库存/产能字段语义、事实确认生命周期。
- [ ] #6：素材上传 intent/complete、签名 URL TTL、对象隔离和原图保留策略。
- [ ] #7：营销状态与 TaskStep 状态、Job 状态完全分离。
- [ ] #8：Artifact 类型/版本/审核单元、质检硬阻断与人工复核规则、发布包 fingerprint 组成。
- [ ] #9：Job 状态枚举唯一化、lease token、重试/死信/人工恢复语义、Outbox Relay/Sweeper。
- [ ] #9/#10：AIInvocation 与 Job 分离、Provider 接口与真实适配器边界、Prompt 版本所有权。
- [ ] 所有门店资源复合外键、统一错误语义、幂等和乐观锁约定。
- [ ] API 路径、请求/响应 Schema 和事件 schema_version 进入 OpenAPI/契约测试。
