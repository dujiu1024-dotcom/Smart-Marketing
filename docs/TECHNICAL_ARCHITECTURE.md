# AI 门店运营官技术架构与服务拆分方案

> 日期：2026-11-10  
> 产品基线：v1.8  
> 架构决策：模块化单体 + 独立异步 Worker + 外部 AI/渠道 Provider  
> 状态：目标架构决策，尚非已部署生产架构

## 1. 架构决策摘要

**首期不采用全面微服务，采用模块化单体（Modular Monolith）作为业务核心，配套独立异步任务执行进程；AI 模型、图像处理和外部渠道以 Provider/Adapter 接口隔离。**

原因：

1. 产品是按需触发、流程相对固定的营销执行系统，不是用户可自由编排的通用工作流平台。
2. 首期业务边界仍在快速收敛，过早拆分会引入分布式事务、跨服务调试、部署治理、链路追踪和数据一致性成本。
3. 核心业务对象高度关联：营销任务、策略快照、文案/图片版本、审核、质检、发布包和经营指标需要强一致的业务约束。
4. 图片生成、模型调用、热点采集、渠道同步等任务耗时长、失败模式不同，适合从 Web API 进程中剥离为 Worker；这不要求把每个业务域都拆成独立微服务。
5. 随着任务量和团队规模增长，可以按清晰边界渐进抽取服务，不需要推倒重来。

本决策不否定未来微服务。它明确了当前阶段的默认部署单元和拆分门槛。

## 2. 总体架构

```text
门店 Web / 平台管理端
          |
          v
      API Gateway / BFF
          |
          v
+-----------------------------------------------+
|              业务核心（模块化单体）             |
|                                               |
| 身份与门店权限 | 门店经营资料 | 营销任务与状态机  |
| 营销策略       | 文案与审核   | 图片与审核        |
| 渠道适配编排   | 发布确认     | 经营效果与归因    |
| 提示词/模型配置| 用量成本     | 审计与运营监控    |
+-----------------------------------------------+
      |                 |                  |
      v                 v                  v
 PostgreSQL         Job Queue          Object Storage
 业务事实/版本       持久化任务           原图/生成图/附件
      |                 |
      |                 v
      |          +---------------------+
      |          | Async Worker Pool   |
      |          | 文案/策略生成        |
      |          | 图片生成/编辑        |
      |          | OCR/质检             |
      |          | 热点采集             |
      |          | 草稿/指标同步        |
      |          +---------------------+
      |                 |
      |        +--------+---------+
      |        v                  v
      |   AI Provider        Channel Adapter
      |   文本/图像/OCR      官方 API/授权平台
      |
      v
 Audit / Metrics / Outbox Events
```

部署时，API 与 Worker 可以是同一代码仓库、同一领域模块、不同进程/容器。第一阶段不需要为每个模块单独部署服务。

## 3. 逻辑模块边界

模块化单体内部按领域划分代码、接口和数据访问责任。模块之间通过应用服务接口或领域事件通信，不允许随意跨模块读写内部表。

| 模块 | 核心职责 | 关键对象 | 是否首期独立部署 |
|---|---|---|---|
| Identity & Store | 登录身份、门店归属、StoreUser、服务端数据授权 | Store、StoreUser、Session | 否 |
| Store Knowledge | 门店档案、商品服务、活动优惠、品牌规范、客群、知识库 | StoreProfile、Product、Offer、KnowledgeItem | 否 |
| Marketing Orchestrator | 需求理解、流程推进、状态机、阶段依赖与恢复 | MarketingTask、TaskStage、StrategySnapshot | 否 |
| Strategy & Opportunity | 热点匹配、经营目标分析、营销策略与事实确认 | Opportunity、StrategySnapshot、FactConfirmation | 否 |
| Content Studio | 文案生成、编辑、版本、文案独立审核 | CopyArtifact、ArtifactVersion、ReviewRecord | 否 |
| Media Studio | 原图管理、图片生成/编辑、图片版本与审核 | MediaAsset、ImageArtifact、ReviewRecord | 否 |
| Quality Assurance | 事实、优惠、平台规则、OCR、画质与品牌检查 | QualityReport、QualityIssue | 否 |
| Channel Integration | 渠道能力发现、账号授权、内容适配、草稿、发布和指标读取 | ChannelAccount、ChannelOperation | 否；Worker 执行 |
| Publishing | 冻结发布包、商家确认、发布幂等与结果核验 | PublishPackage、PublishConfirmation | 否 |
| Performance & Attribution | 内容/意向/经营指标、采集来源、观察窗口、归因可信度 | MetricObservation、AttributionEvidence | 否 |
| AI Gateway | 模型路由、供应商配置、结构化输出、超时、重试、成本审计 | ModelConfig、AIInvocation | 可后续独立 |
| Job Runtime | 持久化队列、Worker、租约、重试、死信、人工恢复 | Job、JobAttempt、JobEvent | Worker 独立进程 |
| Platform Admin | 门店管理、门店级模型配置、提示词、用量成本、审计 | PromptVersion、UsageRecord、AuditEvent | 否 |

### 模块依赖规则

- UI 只能调用 API，不直接访问数据库、对象存储或模型供应商。
- Marketing Orchestrator 负责业务流程，不负责亲自执行耗时模型调用。
- Content Studio、Media Studio 分别维护文案和图片的版本与审核状态，不共享一个含混的“内容已审核”状态。
- Publishing 只接受已冻结、审核通过、质检通过且商家已确认的发布包。
- Channel Adapter 不允许绕过 Publishing 的发布门槛直接发布。
- Performance 只消费有来源、统计周期、口径和可信度的指标，不把未知值补成 0。
- AI Gateway 统一托管密钥引用、模型选择、调用审计和成本；前端不得持有模型密钥。
- 跨模块变更通过应用服务或领域事件触发，不通过直接修改其他模块表实现。

## 4. 任务执行与异步架构

### 4.1 同步与异步边界

同步 API 只负责：鉴权、参数校验、读取必要上下文、创建业务记录、提交 Job、返回 task/job ID。

以下操作必须异步执行：

- 大模型需求理解、策略生成、文案生成与改写。
- 图片生成、图像编辑、OCR、画质检查。
- 热点采集、去重、匹配和证据抓取。
- 渠道内容适配与质量检查。
- 草稿保存、发布状态核验、平台指标同步。
- 经营数据导入、聚合和归因计算。

### 4.2 Job 最小字段

`Job` 至少包括：

- `id`、`store_id`、`marketing_task_id`、`job_type`
- `status`：queued / running / retry_wait / succeeded / failed / cancelled / needs_human
- `idempotency_key`、`payload_ref`、`result_ref`
- `attempt_count`、`max_attempts`、`available_at`
- `lease_owner`、`lease_expires_at`、`heartbeat_at`
- `progress`、`error_code`、`error_summary`
- `created_at`、`started_at`、`finished_at`

任务状态、尝试记录和审计事件必须持久化。Worker 重启后可恢复或安全标记中断任务。

### 4.3 可靠性规则

1. 所有会产生外部副作用的任务都必须有幂等键。
2. 仅对可安全重试的错误自动重试；发布结果不确定时进入 `needs_human`，先核验外部状态再决定是否重试。
3. 使用租约/心跳防止 Worker 崩溃后任务永久占用。
4. 任务结果先写业务数据，再记录成功状态；跨数据库与消息队列使用 Outbox 或等价可靠投递模式。
5. 重试采用退避和抖动，设置最大次数与死信/人工处理入口。
6. 业务任务状态机与基础 Job 状态分离：Job 成功不等于营销任务完成，营销任务完成也不代表经营效果已经可分析。
7. 每个 Job 必须携带 store_id，并在服务端验证其与业务对象归属一致。

### 4.4 流程不是可视化工作流引擎

营销主流程由领域状态机和应用服务实现，节点、审核门槛、依赖失效规则均由代码和配置明确管理。首期不引入 n8n 作为主流程控制面，也不把业务状态放入外部工作流平台。

## 5. 数据与存储架构

### 5.1 PostgreSQL：业务事实主库

首期建议使用 PostgreSQL 作为唯一业务关系型主库。采用模块化 Schema 或清晰表前缀管理领域边界；初期不采用每个模块一套数据库。

核心实体关系：

```text
Store
 ├── StoreUser
 ├── StoreProfile / Product / Offer / KnowledgeItem
 ├── ChannelAccount
 └── MarketingTask
       ├── StrategySnapshot
       ├── ArtifactVersion (copy / image / channel content)
       │     └── ReviewRecord
       ├── QualityReport
       ├── PublishPackage
       │     └── PublishOperation
       ├── Job / JobAttempt
       └── MetricObservation / AttributionEvidence
```

强制约束：

- 所有门店业务数据带 `store_id`；权限由服务端身份解析，不信任前端传入的 store_id。
- 金额使用明确币种和 Decimal，不使用浮点数。
- 未知指标使用 NULL，并记录采集状态，不补零。
- 策略、文案、图片和发布包采用不可变版本；更新创建新版本。
- 记录创建人、来源、时间、审核人、变更原因和关联任务。
- 通过迁移工具管理 Schema 变更，禁止生产环境手工改表。

### 5.2 Redis / 队列

Redis 可用于缓存、限流、短期锁和队列 Broker。队列选型应以技术选型文档的最终决议为准；无论选用何种 Broker，业务任务状态必须落 PostgreSQL，不能只保存在 Redis 内存中。

### 5.3 对象存储

图片、视频、上传文档、生成结果和中间产物存储在 S3 兼容对象存储（开发可用 MinIO，生产可用托管对象存储）。数据库保存对象 key、哈希、MIME、尺寸、来源、版本和访问策略，不把大文件存进关系型数据库。

- 原图只读保留，编辑结果另存新对象。
- 通过短时签名 URL 授权上传/下载。
- 对上传类型、大小、像素、文件名和恶意文件进行校验。
- 对象删除采用引用检查和延迟清理，避免误删历史版本。

## 6. AI 与媒体能力架构

### 6.1 AI Gateway

统一接口建议：

- `TextProvider.generate()`
- `TextProvider.rewrite()`
- `ImageProvider.generate()`
- `ImageProvider.edit()`
- `VisionProvider.inspect()`
- `OCRProvider.extract()`

每次调用记录 provider、model、prompt_version、input/output token 或图像计量、耗时、费用、请求 ID、结果状态和脱敏错误。模型输出必须经过结构校验和业务事实校验，不能直接视为可信事实。

### 6.2 图像能力

图片工作室只依赖 ImageProvider 接口，不把某个图像引擎写死在业务流程里。ComfyUI 可作为后续可选的图像执行后端，适用于需要自定义节点、复杂多阶段图像处理或自托管 GPU 工作流的场景；首期不把它设为必需基础设施。若只需调用托管图像 API，直接实现 Provider 通常更简单。

图片生产必须支持：原图引用、编辑指令、模型/工作流版本、输出版本、审核状态、OCR/质量检查结果及失败恢复。

### 6.3 Prompt 管理

提示词模板有业态分类、版本、草稿/发布状态、变量 Schema 和回滚能力。任务创建时固定 prompt_version，确保历史任务可复现。不得静默修改历史任务使用过的提示词版本。

## 7. 渠道适配与外部集成

每个平台实现统一 Adapter 接口，能力逐项声明，不以“已接入平台”笼统表示所有能力可用。

建议能力接口：

- authorize / refresh / revoke
- health_check
- validate_content
- save_draft
- publish（仅在官方授权、产品策略和商家确认均允许时启用）
- fetch_content_metrics
- get_operation_status

每个能力都返回 supported / unsupported / pending_verification / temporarily_unavailable 等明确状态。记录平台请求 ID、内容 ID、账号 ID、请求时间、响应证据和状态。

优先使用官方 API。页面自动化仅作为经过平台规则、账号授权和安全评估的后续备选；验证码、登录失效、限流或结果不确定时停止危险动作并进入人工核实。

## 8. 安全、多门店与管理后台

- 首期按 Store / StoreUser 建立门店归属，不额外引入独立租户层级和租户管理 UI。
- 所有 API 从认证主体解析门店权限，数据库查询强制带门店范围；关键表可进一步启用 PostgreSQL RLS 作为纵深防御。
- 平台管理员权限与门店用户权限分离，管理员仅访问产品定义允许的管理数据。
- 密钥存密钥管理服务或环境密钥引用；数据库仅保存 secret reference，不保存明文 API Key。
- 日志、异常、Prompt 和模型输入输出进行敏感信息脱敏。
- 关键操作审计：模型配置变更、密钥引用变更、审核、发布确认、发布动作、权限变更和人工恢复。
- 对上传文件做访问隔离、病毒扫描和内容类型校验。

## 9. 可观测性与运维

首期需要具备：

- 结构化日志：request_id、trace_id、store_id、task_id、job_id。
- 指标：API 延迟、错误率、队列积压、任务耗时、重试率、模型调用失败率、供应商费用、渠道失败率。
- 分布式追踪：API → Job → Worker → Provider/Adapter。
- 告警：队列积压持续增长、任务租约过期、供应商错误率异常、成本异常、渠道熔断、对象存储失败。
- 管理端可查看任务执行轨迹、AI 调用、错误脱敏信息、成本和恢复动作。

## 10. 微服务拆分路线与触发条件

### 阶段 A：模块化单体（首期）

部署单元：Web/API、Worker、PostgreSQL、Redis（若队列方案需要）、对象存储。

所有业务模块共用一个代码仓库和主数据库，但有明确模块边界。API 与 Worker 可独立扩缩容。

### 阶段 B：优先抽取高负载执行服务

满足以下任意条件且持续出现时，考虑将 AI/媒体执行抽取为独立服务：

- 图像任务需要独立 GPU 节点或特殊运行时。
- AI/媒体任务资源争用影响普通 API 的 SLA。
- 需要独立扩缩容、部署节奏或故障隔离。
- AI Gateway 已有稳定 Provider 接口和清晰数据契约。

候选服务：AI Execution Service（文本/图像/OCR Worker）。业务状态仍由核心业务服务持有。

### 阶段 C：抽取渠道集成服务

满足以下情况时考虑独立 Channel Integration Service：

- 平台连接数量和并发显著增长。
- 不同平台需要独立凭证、网络出口、浏览器运行时或安全隔离。
- 渠道发布/采集故障需要与核心营销系统隔离。
- Adapter 接口稳定，操作结果可通过事件回传。

渠道服务不拥有营销任务主状态，也不能绕过发布确认规则。

### 阶段 D：按需抽取分析服务

当指标采集与分析查询明显影响交易型业务库，或需要独立分析存储/计算时，再抽取 Analytics Service/数据仓库。首期不引入复杂数据湖和实时流平台。

### 不以“模块数量”作为拆分理由

必须同时具备清晰业务边界、独立扩缩容/发布/故障隔离收益、稳定接口和可承担的运维能力。否则继续保留模块化单体。

## 11. 技术选型落地约束

本架构是逻辑与部署架构，不替代仓库中的技术框架选型决议。具体 Web 框架、ORM、迁移工具、任务队列库、对象存储 SDK 和前端框架以技术选型文档为准；实施时不得因为架构图出现某组件就自动引入新依赖。

选型原则：

- 后端框架：优先与既有 Python 任务/模型生态兼容，提供类型化 API、依赖注入和可测试的应用层。
- 数据库：PostgreSQL 优先，事务与约束用于保护核心业务状态。
- 队列：必须支持持久化、可见性/租约、重试、延迟任务和可观测性；业务状态不可只在 Broker。
- 媒体：S3 兼容对象存储；Provider 抽象隔离模型供应商。
- 部署：容器化，API 与 Worker 分开部署和扩容；不为模块数量创建容器。
- 流程：固定流程用领域状态机；不采用通用工作流平台替代业务规则。

## 12. n8n 与 ComfyUI 决策

| 工具 | 首期决策 | 适用边界 |
|---|---|---|
| n8n | 不作为核心流程引擎，不是必需依赖 | 将来用于非核心的通知、内部运营自动化、第三方系统胶水；业务状态和审核门槛仍由本系统掌握 |
| ComfyUI | 不作为必需依赖；保留 ImageProvider 适配可能 | 当需要复杂可视化图像工作流、自定义节点或自托管 GPU 时接入；普通图像 API 场景直接 Provider 调用 |
| 自建营销状态机 | 首期采用 | 固定业务流程、版本失效、审核门槛、发布安全和任务恢复均在业务域内实现 |

## 13. 实施顺序

### P0：生产底座

1. 后端 API、认证和 Store/StoreUser 服务端授权。
2. PostgreSQL 数据模型、迁移和门店数据隔离。
3. MarketingTask 状态机、策略快照、文案/图片版本及独立审核。
4. 持久化 Job、Worker、幂等、租约、重试、失败恢复和 Outbox。
5. 对象存储、原图保护、资产版本和签名 URL。
6. AI Gateway、Provider 配置、密钥引用、调用审计和成本记录。
7. 质检报告、发布包冻结、商家最终确认门槛。
8. 结构化日志、任务监控和关键操作审计。

### P1：外部能力

1. 热点数据源 Adapter 与门店匹配。
2. 渠道账号授权、健康检查和能力矩阵。
3. 平台草稿保存与读回核验。
4. 受控发布适配（仅对已验证平台启用）。
5. 内容指标采集与来源证据。

### P2：经营效果

1. 指标观测模型、统计口径和观察窗口。
2. 意向、到店、订单、销售额、优惠核销数据接入。
3. 归因证据、样本量和置信度分析。
4. 将复盘结果转为下一次按需制作建议。

## 14. 架构验收标准

- 门店 A 的用户无法通过修改请求参数读取门店 B 的资料、素材、任务或指标。
- API 请求不会同步等待图片生成或长耗时模型任务。
- Worker 重启后任务可恢复；重复投递不会重复创建外部发布动作。
- 文案与图片审核状态独立，修改只使受影响的下游版本失效。
- 未审核、未质检或未确认的内容不能进入正式发布动作。
- 原始图片不会被改写覆盖，所有生成/编辑结果可追溯到源素材和指令。
- 未知指标保留 NULL，指标可追溯到来源、口径、周期和采集时间。
- 外部平台返回不确定时进入人工核实，不显示虚假成功。
- AI/媒体、渠道 Worker 可独立扩缩容，而不要求业务模块全面微服务化。
- n8n、ComfyUI 均不是首期系统启动的硬依赖。

---
本方案为目标架构与工程约束。任何真实生产能力仍需通过实现、自动化测试、部署验证和平台联调后，才能标记为已交付。


## 15. Stage 1 技术选型对齐（2026-11-11）

本节与 [TECH_STACK_SELECTION.md](TECH_STACK_SELECTION.md) 配套生效；具体版本与框架以技术选型文档为准。

- Web：React + Vite + TypeScript，登录后 SPA；页面与交互继续严格对齐已冻结 Demo。
- API：Python + FastAPI 模块化单体；API 与 Worker 共用领域代码，独立进程运行。
- 数据：PostgreSQL 为业务事实主库；SQLAlchemy + Alembic 管理访问与迁移。
- 异步：Celery + Redis Broker；Job、JobAttempt、JobEvent、Outbox 持久化于 PostgreSQL。Redis 不作为业务状态主存储，Worker 必须幂等并支持重投递恢复。
- 对象存储：应用只依赖 S3 API。此前“开发可用 MinIO”的建议已废止；MinIO Community 上游仓库已归档。开发环境改用 SeaweedFS S3 mini；生产对象存储供应商待部署区域与预算确认。
- 身份：应用 Identity / StoreUser / Session 由服务端管理；Argon2id 密码哈希、HttpOnly 安全 Cookie、CSRF 防护和会话撤销；每次请求服务端校验门店归属。
- 契约：FastAPI OpenAPI 作为 API 契约来源，生成 TypeScript API client/types。
- 工程门禁：GitHub Actions、Docker Compose、pytest、Vitest、Playwright、Ruff、TypeScript 检查与构建。

首期不引入 Kubernetes、n8n 核心流程编排、ComfyUI 硬依赖或业务微服务群。生产云厂商、区域、托管对象存储、OIDC/SSO 和错误追踪供应商仍需按真实部署约束决策。
