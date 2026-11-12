# AI Provider 与 Prompt 版本领域设计（Issue #10）

> 状态：历史设计基线；Provider、Prompt Runtime 与 Worker 生产链路已按 Issue #136 分批实现。当前运行配置、安全门禁和生命周期说明见 [ISSUE_136_AI_PROVIDER_RUNTIME.md](./ISSUE_136_AI_PROVIDER_RUNTIME.md)。  
> 本文保留原始设计讨论，不作为当前实现状态的判断依据。  
> 日期：2026-11-11  
> 产品基线：PRODUCT_DESIGN.md v1.8 / UX_AUDIT_AND_REDESIGN.md v1.8  
> Demo 基线：`#admin:capabilities`（导航标签“AI 能力配置”，页面标题“AI 能力与提示词配置”）与 `#admin:prompt-detail`

## 1. 目标与边界

把 Demo 中预置文案、占位图片和模拟质检替换为可审计、可替换 Provider 的真实 AI 执行能力，并为平台管理员提供按业态/任务类型管理共享 Prompt 的版本化能力。

本设计只定义 #10 的 Provider Adapter 实现边界、PromptTemplate/PromptVersion 生命周期、输入/输出安全与验收契约；不在此选择具体模型厂商，也不实现生产 Provider。

### 1.1 必须实现的能力

- 文本：需求理解、策略建议、文案生成、文案局部/整体整改、结构化输出。
- 图片：文生图、上传原图二次编辑、生成多版本并保留源图。
- Vision/OCR：图片文字提取、价格/日期/优惠/门店事实比对所需的结构化识别结果。
- Prompt：按业态/任务类型维护模板、变量 Schema、草稿、发布版本、历史、回滚和变更说明。
- 可审计：每次调用可追溯实际 PromptVersion、Provider、Model、输入指纹、结果引用、用量/成本和错误分类。

### 1.2 明确不做

- 不把模型供应商 SDK 暴露给业务模块或 Web。
- 不在 #10 重新实现 Job、Outbox、AIInvocation、ModelConfig 或模型路由。
- 不允许门店用户编辑平台级 Prompt；首期由平台管理员维护共享模板。
- 不允许 Prompt 默认值或模型推断补全未经确认的价格、优惠、库存、营业时间、地址等经营事实。
- 不允许用 Mock、静态文案或占位图片标记为真实 Provider 成功。
- 不在本 Issue 选择生产云区域、部署商或具体模型供应商；必须先核验地区、资质、价格、数据处理条款和账号可用性。

## 2. Demo 页面与产品流程映射

| Demo 页面/路由 | 页面职责 | 本领域交付 |
|---|---|---|
| `#admin:capabilities` | AI 能力与提示词配置列表 | 业态/任务类型模板列表、当前发布版本、草稿/发布状态、能力说明 |
| `#admin:prompt-detail` | 独立提示词编辑二级页 | 模板正文、变量 Schema、输出 Schema、版本历史、变更说明、校验与发布 |
| 门店详情 → 模型配置 | 门店级模型供应商/模型绑定 | 由 #9 ModelConfig 持有；#10 只实现 Adapter 和能力，不复制配置 |
| AI 营销任务工作区 | 文案/图片生成与整改 | 通过 #9 AI Gateway + Job Runtime 调用真实 Provider；产物由 #8 保存/审核 |
| 质检步骤 | OCR/Vision 结果 | #10 返回结构化识别结果；#8 负责规则评估并生成 QualityReport |

平台管理员管理 Prompt 与模型目录，不因此获得门店任务、文案、图片或经营资料读取权限。若 Prompt 校验需要示例上下文，首期只使用合成 Fixture；不得绕过 #5 PlatformAdminGrant 与 StoreMembership 隔离读取真实门店数据。

## 3. 跨域所有权

| 对象/能力 | 权威所有者 | #10 的职责 |
|---|---|---|
| Job、Attempt、Outbox、重试、租约、人工恢复 | #9 Job Runtime | 不复制状态机；实现可安全执行的 Worker Handler |
| AIInvocation、ModelConfig、Provider capability registry、模型路由、密钥引用、成本审计 | #9 AI Gateway | 按契约调用 Gateway；实现 Provider Adapter |
| PromptTemplate、PromptVersion、PromptActivation | #10 | 生命周期、变量/输出 Schema、版本发布与回滚 |
| MarketingTask、RequirementSnapshot、StrategySnapshot、BusinessFactSnapshot | #7 | 只消费不可变快照引用，不查询跨域可变行 |
| Artifact/ArtifactVersion、ReviewRecord、ChannelContent、QualityReport/QualityResolution | #8 | 返回产物/识别结果引用；不推进审核或质检状态 |
| StoreRecordRevision、Product、Offer、BrandGuideline、MediaAsset | #6 | 只消费已授权、已确认的快照/素材引用 |
| Session、AuthorizedStoreContext、能力授权 | #5 | 不自行解析角色或 store_id；依赖可信上下文 |

**关键规则：** #9 定义稳定 Gateway/Provider 接口与 AIInvocation；#10 提供 Text/Image/Vision/OCR 的真实适配器。业务域只依赖 #9 的统一接口，不直接依赖厂商 SDK。

## 4. Prompt 数据模型

Prompt 是平台级共享配置，不是门店经营资料。首期 PromptTemplate/PromptVersion/PromptActivation 不含 `store_id`；它们属于全局平台配置，只有具备平台 Prompt 管理能力的管理员可写。门店级模型绑定仍由 #9 ModelConfig 管理。

### 4.1 PromptTemplate

建议字段：

`id, template_key, display_name, industry_key, task_type, capability, description, status(active|archived), current_published_version_id, created_by_user_id, created_at, updated_at`

- `template_key` 在 (industry_key, task_type, capability) 范围唯一。
- 一份模板对应一个明确能力与任务类型；不要把需求理解、文案生成、图片编辑和 OCR 混成一个万能 Prompt。
- `current_published_version_id` 仅是当前生效指针；历史版本由 PromptVersion/PromptActivation 保留。
- archived 模板不再用于新 AIInvocation；历史 invocation 仍可追溯其 PromptVersion。
- 业态分类沿用平台现有业态字典；不在 #10 创建第二套业态字典。

### 4.2 PromptVersion

建议字段：

`id, prompt_template_id, version_no, system_prompt, user_prompt_template, variables_schema_json, output_schema_json, schema_version, input_policy_json, changelog, status(draft|published), created_by_user_id, created_at, published_by_user_id, published_at`

- `UNIQUE(prompt_template_id, version_no)`；version_no 单调递增。
- Draft 可编辑；发布后正文、变量 Schema、输出 Schema、输入策略和 changelog 均不可变。
- Published PromptVersion 永不覆盖；修改必须创建新版本。
- `variables_schema_json` 描述变量类型、必填、长度/枚举约束和来源类型；默认值只允许安全常量，不能默认虚构业务事实。
- `output_schema_json` 使用 JSON Schema；文本结构化输出必须通过 Schema 校验后才能写入 #8 ArtifactVersion。
- `input_policy_json` 声明允许读取的快照类型、事实状态、素材引用和脱敏策略；运行时不得读取未声明的数据。
- Prompt 正文不能包含 API Key、OAuth Token、Secret 或门店个人敏感数据。

### 4.3 PromptActivation

建议字段：

`id, prompt_template_id, activated_version_id, previous_version_id, action(publish|rollback), reason, actor_user_id, created_at, idempotency_record_id`

- 发布/回滚均追加 PromptActivation；不修改历史 PromptVersion。
- 回滚是将当前生效指针重新指向某个已发布版本，并写入新的 activation 记录；不是把旧版本改成 Draft 或覆盖新版本。
- 同一模板同一激活命令按 Idempotency-Key 去重。
- 只有平台管理员具备对应能力时可发布/回滚；授权由 #5 提供，#10 不按 role 字符串自行判断。

### 4.4 发布事务与校验门槛

发布 PromptVersion 前必须在同一事务内：

1. 校验模板处于 active，version_no 唯一且版本仍为 draft。
2. 校验变量 Schema / 输出 Schema 可解析，所有模板占位符均在变量 Schema 中声明。
3. 校验 input_policy 只允许读取当前 Gateway/业务契约支持的上下文引用。
4. 校验 capability 与 PromptTemplate、#9 Provider capability registry 一致。
5. 校验 changelog 非空，并记录发布操作者、时间和审计事件。
6. 将版本置为 published、更新 current_published_version_id、追加 PromptActivation 和 Outbox 事件。

发布后禁止 PATCH/DELETE；若校验失败返回明确错误，不改变当前生效版本。

### 4.5 数据库约束

- `UNIQUE(industry_key, task_type, capability, template_key)`。
- `UNIQUE(prompt_template_id, version_no)`；版本号由服务端分配并单调递增。
- PromptTemplate.current_published_version_id 必须通过复合 FK 证明 PromptVersion 属于同一模板。
- PromptActivation 的 activated_version_id / previous_version_id 必须引用同一 PromptTemplate 的 published PromptVersion；activation 记录追加写。
- Published PromptVersion 与 PromptActivation 禁止普通 UPDATE/DELETE；模板归档不删除版本和激活历史。
- 所有写操作使用 Idempotency-Key；并发发布使用 expected_version，避免两个管理员覆盖当前生效指针。

## 5. Provider Adapter 契约

#9 的统一接口是唯一调用入口。#10 实现 Adapter，不自创重试循环、不保存 Provider Secret、不自行选择门店模型。

### 5.1 能力接口

| 能力 | #9 Gateway 接口 | #10 Adapter 输出 |
|---|---|---|
| 文本生成 | TextProvider.generate(request, context) | StructuredTextResult |
| 文本整改 | TextProvider.rewrite(request, context) | StructuredTextResult |
| 图片生成 | ImageProvider.generate(request, context) | ImageResult |
| 图片编辑 | ImageProvider.edit(request, context) | ImageResult |
| 视觉检查 | VisionProvider.inspect(request, context) | VisionResult |
| OCR | OCRProvider.extract(request, context) | OCRResult |

统一结果至少包含：

`provider_key, model_key, provider_request_id, status, normalized_usage, latency_ms, result_ref, retryable, normalized_error`

ProviderContext 至少包含 `store_id / actor_scope, task_id?, job_id?, invocation_id, idempotency_key, deadline_at, correlation_id, trace_context, model_config_ref`。凭据只通过 #9 受控 Secret handle 注入 Adapter，不传递明文 Secret；context 不得原样写日志。

- 原始厂商异常必须映射到 #9 错误分类；不得把厂商堆栈、原始响应或 Secret 暴露给业务层。
- 适配器必须声明支持的 capability、输入格式、最大尺寸/长度、结构化输出能力、编辑能力和已知限制。
- 不支持某能力时明确返回 `PROVIDER_CAPABILITY_UNSUPPORTED`；不得用另一种能力伪装成功。
- 不做静默模型 fallback。若 #9 路由策略执行 fallback，AIInvocation 必须记录实际 provider_key/model_key 与路由原因。

### 5.2 重试、幂等与未知结果

- 重试策略由 #9 Job Runtime 决定；Adapter 只做单次调用和错误归一化，不在内部无限重试。
- Provider 支持幂等键时，将稳定 invocation/job key 传给 Provider；不支持时必须声明能力限制。
- 文本请求超时且无响应可按 #9 的错误策略重试；图片生成/编辑若超时后结果未知，不能盲目重复生成，应先查询 provider_request_id/供应商任务状态；无法核验则进入 #9 needs_human。
- 429 使用 Retry-After/退避元数据返回给 #9；Adapter 不自行 sleep 占用 Worker。
- Provider 认证失败不得自动无限重试；返回 AUTH_FAILED 并通知管理员检查 #9 Secret reference。
- 内容政策阻断返回 POLICY_BLOCKED；不得通过改写提示词规避供应商安全策略。

### 5.3 产物与素材边界

- 文本结果必须包含通过 output_schema 校验的结构化内容；#10 不直接批准内容。
- 图片生成/编辑结果写入新的受控对象 Key，并由 #8 创建 ArtifactVersion；不得覆盖 #6 MediaAsset 原图或旧 ArtifactVersion。
- 图片编辑输入使用明确的 source asset/version 引用；mask、尺寸和编辑范围作为可追溯输入参数。
- OCR/Vision 返回结构化识别文本、坐标/区域、置信度和来源图版本；不能直接修改 #6 事实或将识别结果标为 confirmed。
- #8 使用 OCR/Vision 结果创建/更新 QualityReport；质检通过、人工复核和发布门禁均由 #8 持有。

## 6. AIInvocation 与调用审计

AIInvocation 由 #9 持有。每次调用必须关联：

- store_id / task_id / job_id（适用时）
- capability、实际 provider_key/model_key
- 精确 prompt_version_id（适用时）
- request_fingerprint、response_ref
- request_fingerprint 规范化覆盖 capability、prompt_version_id、schema_version、输入快照/素材版本及哈希、用户编辑指令和生成参数；不包含 Secret。该指纹用于结果追溯，不替代 Job Idempotency-Key。
- normalized usage、cost、duration、status、error_code
- correlation_id / trace_id（通过统一可观测性上下文关联）

原始 Prompt/Response 不进入普通日志。若需保留调试样本，使用受控对象引用、最小保留期、脱敏和访问审计。

**跨域 Schema 待 #9 批准的补充建议：** 当前 AIInvocation 字段表未显式保存 Provider 接口返回的 `provider_request_id` 与分项 `normalized_usage`。建议增加 nullable `provider_request_id` 和受控 `usage_json`，以支持供应商任务对账、图像计费单位和成本复算；在 #9 联合评审接受前不视为冻结字段。

## 7. 事实安全、提示注入与隐私

1. 高风险事实只允许使用 #7 BusinessFactSnapshot 中已确认的事实；其来源必须追溯到 #6 已确认 StoreRecordRevision。
2. 未确认/过期/冲突事实不得作为肯定陈述输入；缺失事实保持 NULL 或要求商家补充。
3. KnowledgeItem、上传文档、网页片段、图片 OCR 等外部内容一律作为不可信数据，不得作为系统指令；明确分隔数据与指令，禁止其覆盖系统 Prompt/开发策略。
4. Prompt 不得要求模型泄漏系统提示词、Secret、其他门店数据或内部审计信息。
5. 不将密码、Cookie、Token、API Key、签名 URL、完整敏感个人信息写入 Prompt、AIInvocation 普通字段、事件或日志。
6. Provider 只接收当前任务所需的最小上下文；跨门店引用由 #5 授权上下文拒绝。
7. 模型输出必须经过 Schema、事实来源、内容政策和业务规则校验；模型自述“已核验”不构成证据。
8. OCR/Vision 识别置信度低或事实冲突时输出 needs_review/needs_human 线索，不自动修改商家事实。

## 8. API 与事件草案

### 8.1 Prompt 管理 API（平台管理端）

| Method | Path | 用途 | 关键约束 |
|---|---|---|---|
| GET | /api/v1/admin/prompt-templates | 模板列表 | 仅平台 Prompt 管理能力 |
| POST | /api/v1/admin/prompt-templates | 创建模板 | template_key 唯一 |
| GET | /api/v1/admin/prompt-templates/{id} | 模板详情/版本历史 | 不返回 Secret |
| POST | /api/v1/admin/prompt-templates/{id}/versions | 创建 Draft | version_no 服务端分配 |
| PATCH | /api/v1/admin/prompt-versions/{id} | 编辑 Draft | published 返回 409 |
| POST | /api/v1/admin/prompt-versions/{id}/validate | 校验 Schema/占位符 | 不调用真实 Provider |
| POST | /api/v1/admin/prompt-versions/{id}/publish | 发布版本 | 同事务追加 PromptActivation |
| POST | /api/v1/admin/prompt-templates/{id}/rollback | 回滚到已发布版本 | body: version_id、reason、expected_version；追加 activation |

- 所有写请求使用 Idempotency-Key；更新使用 expected_version/If-Match。
- Prompt 预览首期只渲染合成 Fixture，不读取真实门店资料、不触发真实 Provider 调用；真实 Provider 联调走独立测试环境/受控任务。
- ModelConfig、Provider capability registry、Secret reference 和实际模型路由 API 由 #9 持有，不重复出现在本 API 集合。

### 8.2 事件

- `prompt.version_published`：#10 → #9；新版本可被后续 AIInvocation 引用。
- `prompt.version_activated`：#10 → #9；更新当前 Prompt 指针/缓存；历史 invocation 不变。
- `ai.invocation.completed/failed`：由 #9 发出，业务域按 fingerprint 校验后消费。
- 事件只传 ID、version、fingerprint、状态和必要摘要；不携带完整 Prompt、Secret 或原始响应。

## 9. 错误分类映射

| 统一错误 | Provider 典型来源 | 处理责任 |
|---|---|---|
| PROVIDER_RATE_LIMITED | 429 / quota burst | #10 返回 retry_after；#9 决定退避与重试 |
| PROVIDER_TIMEOUT | 网络/任务超时 | #10 标注 retryable 与未知结果；#9 决定重试或 needs_human |
| PROVIDER_UNAVAILABLE | 5xx / 连接失败 | 有限重试；超限失败 |
| PROVIDER_AUTH_FAILED | Secret 无效/权限撤销 | 停止自动重试，提示管理员 |
| PROVIDER_CAPABILITY_UNSUPPORTED | 模型不支持 image_edit/vision 等 | 阻断，不做伪造 fallback |
| PROVIDER_INVALID_OUTPUT | 非法 JSON/Schema 不匹配 | 不创建正式 ArtifactVersion；记录 invocation 失败 |
| PROVIDER_POLICY_BLOCKED | 厂商安全策略拒绝 | 记录合规阻断，不尝试绕过 |
| PROMPT_VERSION_NOT_PUBLISHED | 引用 Draft/Retired Prompt | 409，不能发起生产调用 |
| PROMPT_SCHEMA_INVALID | 变量/输出 Schema 无效 | 422，不能发布/调用 |
| PROMPT_INPUT_NOT_ALLOWED | 输入来源不在 input_policy | 403/422，记录审计摘要 |

错误码命名以 #9 最终错误注册表为准；本表是 #10 的映射提案。

## 10. 测试矩阵（设计准备，全部待执行）

| ID | 场景 | 预期 |
|---|---|---|
| AI-01 | PromptTemplate 在同业态/任务/capability 重复 key | UNIQUE 阻断 |
| AI-02 | PromptVersion draft 编辑 | 允许，version_no 不变 |
| AI-03 | 已发布 PromptVersion PATCH/DELETE | 409/拒绝，历史不变 |
| AI-04 | 发布版本占位符未在 variables_schema 声明 | 发布阻断 |
| AI-05 | output_schema 非法或模型输出不符合 Schema | 不创建正式产物，记录失败 invocation |
| AI-06 | Prompt rollback 到旧发布版本 | 新增 PromptActivation，旧/新版本正文均不变 |
| AI-07 | AIInvocation 运行时读取“最新 Prompt”而非固定版本 | 测试失败；必须固定 prompt_version_id |
| AI-08 | 同一 Job 重复投递文本/图片任务 | 按 #9 幂等策略，不重复写业务产物 |
| AI-09 | Provider 429/5xx/timeout/auth failure | 错误分类正确，重试责任归 #9 |
| AI-10 | 图片生成超时且 Provider 结果未知 | 查询供应商任务；无法核验进入 needs_human，不盲目重发 |
| AI-11 | Image edit 输入原图 | 原 MediaAsset/ArtifactVersion 不变，输出新对象/版本 |
| AI-12 | OCR/Vision 识别到与商家确认价格冲突 | 只产出风险证据，阻断质检；不改写已确认事实 |
| AI-13 | Prompt 引用未确认/过期 BusinessFactSnapshot | 阻断或要求补充事实，不生成肯定陈述 |
| AI-14 | KnowledgeItem 中嵌入“忽略系统指令/泄漏密钥” | 作为不可信数据处理，不覆盖系统 Prompt |
| AI-15 | Prompt/日志扫描 Secret、Cookie、Token、完整敏感 PII | 不出现敏感值 |
| AI-16 | A 店调用尝试读取 B 店素材/快照 | #5 授权层拒绝，统一 404 |
| AI-17 | Provider fallback | AIInvocation 记录实际 provider/model 与路由原因；不静默切换 |
| AI-18 | 费用/usage 记录 | 能按 provider/model/capability 追溯 usage 与 cost |
| AI-19 | Provider 不支持 image_edit 或 OCR | 明确 capability unsupported，不返回伪成功 |
| AI-20 | Prompt preview | 只使用合成 Fixture，不读取真实门店数据 |

## 11. 联合评审待决项

1. 首期真实 TextProvider 与 ImageProvider 供应商/模型：需确认部署区域、账号主体、数据处理条款、价格、速率限制和可用能力后由项目负责人选择。
2. ImageProvider 是否具备真实图像编辑（而非只文生图）能力；不具备时不得将生成图片伪装为“编辑原图”。
3. Vision/OCR 首期真实接入范围；若供应商能力不足，明确哪些质检规则先由确定性规则完成，哪些能力延期。
4. #9 批准 AIInvocation 增加 provider_request_id / usage_json 的字段扩展及保留策略。
5. PromptTemplate 首期业态字典、task_type/capability 列表与平台管理员发布权限。
6. Prompt rollback 的审批要求；首期建议仅平台管理员发布/回滚并记录 reason。
7. Provider 不支持幂等/任务查询时，图片生成未知结果的人工核验策略。
8. Provider 传输数据的区域、保留期、训练使用条款和脱敏策略；未经确认不得发送真实个人敏感数据。

## 12. 实施门禁

- #4 工程底座 PR #16 已合并，但 Issue #4 仍有手工 clean-machine onboarding 与部署 trace-correlation 验收项。
- #5 Identity、#6 Store Knowledge、#7 MarketingTask、#8 Content/Publishing、#9 Job Runtime/AI Gateway 的生产实现仍需各自验收；未完成的依赖必须在实现 PR 中明确阻塞。
- 本文是设计准备；当前不创建生产 ORM/Alembic/API/Provider 实现，不把本地 Mock 标记为真实能力。
- 开始实现前必须冻结 Provider 接口/错误码、Prompt schema、AIInvocation 字段、数据安全策略和 Demo 页面状态映射。
- Provider 选型须由项目负责人确认；本设计不授权自行采购、开通或绑定供应商账号。



## 产品范围约束：AI 不生成视频（2026-11-12）

#10 的 Provider capability 仅覆盖文本（含视频脚本文本）、图片生成/编辑，以及经确认需要的 Vision/OCR 质检。不得增加 text-to-video、image-to-video、video editing、video rendering 或视频转码 Provider 能力。视频脚本按普通文本 Schema 生成、审核和版本化，不建立 VideoArtifact。


## 12. Issue #136 implementation notes (2026-11-12)

The repository implementation now includes the following executable building blocks:

- `ai_gateway.http_provider`: capability-specific asynchronous HTTP adapters for text, image generation/editing, vision inspection and OCR. All operations use the versioned Store Operator JSON wire contract; provider SDKs do not leak into domain modules.
- `ai_gateway.provider_config`: opt-in environment configuration. The provider remains disabled when no `AI_PROVIDER_*` configuration is supplied. Only explicitly declared capability/model pairs are registered.
- `ai_gateway.secrets`: resolves `env://NAME` references or reads an external SecretStore JSON value by reference. The application stores only the reference; the API key is injected into the adapter at runtime.
- `ProviderRegistry.resolve`: checks provider, capability, model and region together. Explicit provider selection never silently falls back.
- `ai_gateway.prompt_runtime`: renders only published PromptVersion records, validates variables and validates structured model output against the declared JSON Schema subset. Unsupported schema keywords fail closed.
- `apps/api/tests/test_ai_provider_runtime.py`: contract tests use HTTPX MockTransport and test credentials only; they do not represent real model acceptance.

### Provider wire contract

Each configured provider endpoint implements POST JSON requests with `schema_version=1`, an operation name and the typed request payload:

| Capability | Default endpoint | Operation |
|---|---|---|
| Text generation | `/v1/text/generate` | `text.generate` |
| Image generation | `/v1/images/generate` | `image.generate` |
| Image editing | `/v1/images/edit` | `image.edit` |
| Vision inspection | `/v1/vision/inspect` | `vision.inspect` |
| OCR | `/v1/ocr/extract` | `ocr.extract` |

Endpoint paths can be replaced by constructing `ProviderEndpoints`. Responses must satisfy the existing Pydantic response contracts. The adapter normalizes 429, authentication, timeout, transport, request and malformed-output failures without returning provider response bodies or credentials to callers. A per-provider circuit breaker opens after a configurable transient-failure threshold and permits one half-open recovery probe after its cooldown. Image mutations mark timeout outcomes as unknown side effects; the adapter never starts an internal retry loop.

### Configuration and security

Set `AI_PROVIDER_ID`, `AI_PROVIDER_DISPLAY_NAME`, `AI_PROVIDER_BASE_URL`, `AI_PROVIDER_SECRET_REF`, and one or more capability model lists. The API key itself must be injected separately (for example as a runtime environment secret referenced by `env://AI_PROVIDER_API_KEY`) or resolved through the existing AWS Secrets Manager SecretStore. Remote endpoints require HTTPS. No real provider is selected by default; deployment owners must verify that their gateway implements this wire contract and declare only its actual model capabilities.

### Acceptance boundary

Automated adapter and prompt-runtime tests are contract tests, not proof of a live model account or generated quality. Live credentials, provider account availability, model capability verification, output quality and latency remain in the separate real-device/provider acceptance issue. AI output remains a candidate artifact; this layer does not approve merchant content or bypass facts, review, visual quality or merchant-confirmation gates.
