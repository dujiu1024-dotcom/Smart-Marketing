# 异步任务运行时与 AI Gateway 契约

> 对应：Issue #9  
> 日期：2026-11-11  
> 状态：核心运行时代码已交付；并发限流、Provider 配置和业务端到端验收仍在进行  
> 技术基线：FastAPI + PostgreSQL + SQLAlchemy/Alembic + Celery/Redis + Pydantic  
> 上位文档：[项目宪法](PROJECT_CONSTITUTION.md)、[技术架构](TECHNICAL_ARCHITECTURE.md)、[技术选型](TECH_STACK_SELECTION.md)、[产品设计](PRODUCT_DESIGN.md)

本文冻结 Job Runtime、Outbox、Celery Worker 和 AI Gateway 的首期契约。它不改变营销领域状态机，也不把系统扩展为通用工作流编排器。

## 1. 决策摘要

1. PostgreSQL 是 Job、执行尝试、事件投递、恢复审计和 AI 调用记录的事实来源。
2. Redis 只承担 Celery Broker（以及经批准的短期缓存/限流用途）；Celery result backend 不作为业务状态来源。
3. 业务事务内同时写入业务变更与 Outbox 事件；独立 Relay 以至少一次语义投递 Celery 消息。
4. Celery 消息只携带 `job_id`（及可选的消息追踪 ID），Worker 必须回 PostgreSQL 原子认领 Job，不能把消息内容当作权威业务参数。
5. Worker 通过租约 token（fencing token）和心跳续租；过期租约由 Sweeper 恢复。旧 Worker 不得在租约失效后提交结果。
6. Job 状态与 MarketingTask、文案审核、图片审核、质检、发布状态完全分离。
7. 对外部副作用采用显式幂等键与操作记录；发布结果不确定时进入人工核验，不自动再次发布。
8. AI Gateway 以能力接口隔离 Provider；密钥只以 Secret Reference 引用，Prompt/模型/参数版本随调用快照记录。

## 2. 范围与非目标

### 范围
- 持久化 Job 生命周期、执行尝试、进度、错误摘要、租约和恢复审计。
- Outbox 事务提交、Relay 发布、重复投递去重和积压恢复。
- Celery Worker 执行、并发限制、超时、重试和优雅关闭。
- AI Provider 能力声明、结构化输入输出、模型路由、调用审计和成本计量。
- 任务追踪、受权限保护的重试/取消/人工恢复接口及测试契约。

### 非目标
- 不实现可视化 DAG、任意节点编排、n8n 工作流或用户自定义任务流。
- 不由 Job Runtime 决定营销业务步骤、审核门槛或版本依赖。
- 不把 Redis、Celery result backend 或进程内 Future 当作持久化任务记录。
- 不让 Worker 绕过 Publishing 领域服务直接发布。
- 不在本设计阶段锁定具体 AI 供应商、生产云厂商或 GPU 运行环境。

## 3. 领域边界与核心流程

### 3.1 创建与执行

1. API 从认证主体解析当前用户和门店权限；不得信任客户端传入的 `store_id`。
2. 应用服务校验营销任务、阶段前置条件和资源归属。
3. 在同一个 PostgreSQL 事务内写入业务变更（如有）、Job 和 Outbox 事件。
4. 事务提交后立即返回业务资源 ID 与可追踪的 job ID；不等待模型/图像/渠道任务执行。
5. Outbox Relay 发布仅含 `job_id` 的 Celery 消息。
6. Worker 从 PostgreSQL 原子认领 Job、创建 JobAttempt、取得租约，再执行对应的注册 Handler。
7. Handler 通过领域应用服务写回业务结果；Job Runtime 记录执行结果和审计事件。
8. 失败、超时或 Worker 丢失由重试策略与 Sweeper 处理；不能安全重试的外部副作用转人工核验。

### 3.2 状态必须分离

- `MarketingTask`：业务任务的流程状态，由 Marketing Orchestrator 管理。
- `Job`：一次可调度的后台执行单元，由 Job Runtime 管理。
- `CopyArtifact` / `ImageArtifact`：各自独立版本与审核状态，由 Content/Media 域管理。
- `PublishOperation`：外部发布操作及平台结果证据，由 Publishing 域管理。

Job succeeded 仅表示该执行单元按契约完成，不代表商家已审核、已发布或已产生经营效果。

## 4. PostgreSQL 数据模型

所有表使用 UUID 主键（应用生成 UUIDv7 或数据库支持的等效策略）；时间统一存储为 UTC `timestamptz`。金额/费用使用 Decimal 与明确币种。所有门店范围数据都必须带 `store_id`，并在服务端授权查询中强制限定。

### 4.1 `jobs`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| id | UUID PK | Job ID |
| store_id | UUID NULL, FK | 门店归属；仅 system scope 可为空，必须由 scope 约束校验 |
| idempotency_scope_type | VARCHAR(20) NOT NULL | store / system，幂等作用域类型 |
| idempotency_scope_id | UUID NOT NULL | 门店 ID 或固定 system scope ID；禁止 NULL 唯一键语义 |
| marketing_task_id | UUID NULL, FK | 关联业务任务 |
| job_type | VARCHAR(100) NOT NULL | 注册表中的稳定类型，如 `copy.generate`、`image.edit`、`channel.validate` |
| status | ENUM/VARCHAR NOT NULL | 见状态机 |
| priority | SMALLINT NOT NULL DEFAULT 0 | 有界优先级，防止任意高优先级饥饿 |
| idempotency_key | VARCHAR(200) NOT NULL | 创建侧幂等键 |
| request_hash | CHAR(64) NOT NULL | 相同幂等键的参数冲突检测 |
| payload_ref | JSONB NOT NULL | 小型、版本化、无 Secret 的参数快照；大对象放对象存储 |
| result_ref | JSONB NULL | 结果资源引用，不保存大文件正文 |
| queue_name | VARCHAR(100) NOT NULL | 逻辑队列 |
| attempt_count | INTEGER NOT NULL DEFAULT 0 | 已开始的执行尝试数 |
| max_attempts | INTEGER NOT NULL | 最大尝试次数 |
| available_at | TIMESTAMPTZ NOT NULL | 最早可执行时间 |
| timeout_seconds | INTEGER NOT NULL | Job 级软/硬超时策略基准 |
| lease_owner | VARCHAR(200) NULL | Worker 实例标识 |
| lease_token | UUID NULL | 每次认领生成的新 fencing token |
| lease_expires_at | TIMESTAMPTZ NULL | 租约到期时间 |
| heartbeat_at | TIMESTAMPTZ NULL | 最近心跳 |
| progress_current / progress_total | BIGINT NULL | 可选进度，不允许作为业务完成判据 |
| error_code | VARCHAR(100) NULL | 稳定错误码 |
| error_summary | VARCHAR(500) NULL | 脱敏、可展示摘要 |
| created_by_user_id | UUID NULL | 发起人（系统任务可空） |
| created_at / updated_at | TIMESTAMPTZ NOT NULL | 审计时间 |
| started_at / finished_at | TIMESTAMPTZ NULL | 首次开始/终结时间 |
| cancelled_at | TIMESTAMPTZ NULL | 取消时间 |

约束与索引：
- UNIQUE (`idempotency_scope_type, idempotency_scope_id, idempotency_key`)；CHECK 保证 store scope 时 scope_id=store_id 且 store_id 非空，system scope 时 store_id 为空且 scope_id 为固定 system scope。不得依赖 NULL 参与普通 UNIQUE 的去重语义。
- CHECK：`attempt_count >= 0`、`max_attempts >= 1`、`timeout_seconds > 0`。
- 索引：(`status, available_at, priority DESC, created_at`)、(`store_id, created_at DESC`)、(`marketing_task_id`)、(`lease_expires_at`)。
- `payload_ref` 必须包含 schema_version；禁止存 API Key、Cookie、访问 Token 或无必要的敏感原文。

### 4.2 `job_attempts`

每次实际认领执行创建一条记录，不复用覆盖历史。

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| id | UUID PK | Attempt ID |
| job_id | UUID FK NOT NULL | 所属 Job |
| attempt_no | INTEGER NOT NULL | 从 1 单调递增 |
| lease_token | UUID NOT NULL | 与本次认领 fencing token 一致 |
| worker_id | VARCHAR(200) NOT NULL | Worker 实例 |
| status | VARCHAR(30) NOT NULL | running/succeeded/failed/lease_expired/cancelled |
| started_at | TIMESTAMPTZ NOT NULL | 开始时间 |
| heartbeat_at | TIMESTAMPTZ NULL | 最近心跳 |
| finished_at | TIMESTAMPTZ NULL | 结束时间 |
| duration_ms | BIGINT NULL | 执行耗时 |
| error_code | VARCHAR(100) NULL | 稳定错误码 |
| error_summary | VARCHAR(500) NULL | 脱敏错误摘要 |
| provider | VARCHAR(100) NULL | 实际 Provider |
| model | VARCHAR(150) NULL | 实际模型 |

唯一约束：UNIQUE (`job_id, attempt_no`)。Attempt 记录追加写，不因后续重试而删除。

### 4.3 `job_events`

Job 生命周期事件追加写，用于审计和排障：`job.queued`、`job.claimed`、`job.heartbeat`（可按采样策略）、`job.retry_scheduled`、`job.succeeded`、`job.failed`、`job.cancelled`、`job.lease_expired`、`job.needs_human`、`job.manually_recovered`。

字段：`id`、`job_id`、`event_type`、`actor_type`、`actor_id`、`attempt_id`、`lease_token`、`data JSONB`（脱敏白名单字段）、`created_at`。索引 (`job_id, created_at`)。

### 4.4 `outbox_events`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| id | UUID PK | Event ID |
| aggregate_type / aggregate_id | VARCHAR / UUID | 业务聚合 |
| event_type | VARCHAR(150) NOT NULL | 稳定事件名 |
| schema_version | INTEGER NOT NULL | 事件契约版本 |
| payload | JSONB NOT NULL | 仅含必要引用和元数据 |
| dedupe_key | VARCHAR(200) NOT NULL UNIQUE | 业务事件去重 |
| status | VARCHAR(20) NOT NULL | pending/publishing/published/dead |
| available_at | TIMESTAMPTZ NOT NULL | 可发布时间 |
| publish_attempts | INTEGER NOT NULL DEFAULT 0 | 发布尝试数 |
| locked_by / locked_until | VARCHAR / TIMESTAMPTZ NULL | Relay 短租约 |
| last_error | VARCHAR(500) NULL | 脱敏错误 |
| created_at / published_at | TIMESTAMPTZ | 创建/成功发布时间 |

Relay 使用 `FOR UPDATE SKIP LOCKED` 分批认领到期事件，短事务内标记 publishing 并设置锁；提交后向 Broker 发布。发布成功再更新 published。若 Broker 已接收消息但 Relay 在写回前崩溃，事件可能再次发布，因此系统明确采用**至少一次投递**，依赖 Job 创建幂等和 Worker 原子认领去重，不宣称 exactly-once。

### 4.5 AI 调用与用量表

- `ai_invocations`：`id`、`store_id`、`marketing_task_id`、`job_id`、`attempt_id`、`provider`、`model`、`capability`、`prompt_template_id`、`prompt_version`、`parameter_snapshot`、`input_schema_version`、`output_schema_version`、`provider_request_id`、`status`、`latency_ms`、`error_code`、`created_at`。
- `ai_usage_records`：`invocation_id`、输入/输出 Token 或图像计量、费用 Decimal、币种、计量来源、记录时间。
- 不在调用表保存明文密钥、完整敏感提示词或未经脱敏的原始用户内容；必要输入快照使用受控对象引用和访问审计。

## 5. Job 状态机与操作语义

### 5.0 幂等作用域

Job 创建幂等键由调用方应用服务生成，不直接复用浏览器随机请求 ID。门店用户写操作按 `store_id + actor_id + operation + idempotency_key` 建立请求幂等记录；Job Runtime 接收该记录派生出的稳定 Job 幂等键，并使用 `idempotency_scope_type/idempotency_scope_id/idempotency_key` 唯一约束。系统级任务使用固定 system scope。相同作用域、Key、request_hash 返回原 Job；同 Key 不同 hash 返回 409。内部事件消费以 event_id/job_id 为稳定幂等边界。

### 5.1 状态

| 状态 | 含义 | 终态 |
|---|---|---|
| queued | 已持久化，等待执行 | 否 |
| running | Worker 已认领并持有有效租约 | 否 |
| retry_wait | 可重试失败，等待 available_at | 否 |
| succeeded | 执行成功 | 是 |
| failed | 不可自动恢复或已耗尽重试 | 是 |
| cancelled | 在安全边界内取消 | 是 |
| needs_human | 外部副作用结果不确定或需要人工判断 | 是（人工动作可创建新 Job） |

合法转换：
- queued → running / cancelled
- retry_wait → running / cancelled
- running → succeeded / retry_wait / failed / cancelled / needs_human
- running → retry_wait / failed / needs_human 也可由 Sweeper 在租约过期后执行；Sweeper 必须在同一事务中将旧 JobAttempt 标为 lease_expired、记录 JobEvent、使旧 lease_token 失效并按副作用风险决定后续状态。
- needs_human 不允许自动回到 running；人工核验后通过受审计的恢复操作创建新执行或显式重置为 queued。
- succeeded / failed / cancelled 不允许静默重开；重做应创建新 Job 并关联 `supersedes_job_id` 或业务操作记录。

### 5.2 创建幂等

- API 应用服务先按 `store_id + actor_user_id + operation + idempotency_key` 校验请求幂等记录，再将稳定的 Job 幂等键映射到 `idempotency_scope_type + idempotency_scope_id + idempotency_key`。同一作用域/Key/Hash 重放返回原 Job；相同 Key、不同 request_hash 返回 409。
- 若相同幂等键对应不同 `request_hash`，返回 409，不覆盖原参数。
- Outbox Relay 重复发布只会传递相同 `job_id`；Worker 原子认领确保只有一个有效租约能推进该 Job。
- 不以 Celery task ID 作为业务幂等键。

### 5.3 认领、租约与 fencing

Worker 收到消息后，使用单条条件更新或事务锁原子认领：
- 仅允许 status 为 queued，或 status 为 retry_wait 且 available_at <= now()。
- 认领时 status=running、attempt_count+1、生成全新 lease_token、写 lease_owner/lease_expires_at/heartbeat_at。
- 同事务创建 JobAttempt 与 job.claimed 事件。
- 心跳和结果提交都必须带 `job_id + lease_token`，并校验租约仍有效。所有外部副作用前还必须执行租约有效性预检，并使用稳定的外部 idempotency key；fencing token 只能阻止旧 Worker 写回本地数据库，不能撤销已发出的网络请求。
- 每次重新认领生成新 token；旧 Worker 即使恢复运行也不能续租、写结果或把 Job 标记成功。
- 租约时长应大于心跳间隔至少 3 倍；初始建议心跳 20 秒、租约 90 秒，后续按实际任务/网络延迟压测调整，不视为不可变常量。

### 5.4 超时、取消与优雅关闭

- Job 配置 `timeout_seconds`；Handler 支持软超时清理，Worker 进程硬超时用于保护执行池。
- 超时按错误分类进入 retry_wait、failed 或 needs_human；不能一律重试。
- 取消 queued/retry_wait 可通过条件更新立即转 cancelled；running 任务只设置 `cancel_requested_at`（或等价标记），Worker 在安全检查点停止。成功提交、取消完成和超时处理必须以带当前 status + lease_token 的 CAS/行锁串行化，确保 succeeded 与 cancelled 不会同时成立。
- 对正在执行的外部发布/支付类不可逆操作，不得假设强制终止意味着外部动作未发生；先查询外部操作状态。
- Worker SIGTERM 时停止接收新任务，尽可能完成/安全中断当前任务；超出租约的任务由 Sweeper 接管。

## 6. Celery Worker 执行契约

### 6.1 消息与 Handler

Celery 消息体只包含：
```json
{
  "job_id": "UUID",
  "dispatch_event_id": "UUID",
  "schema_version": 1
}
```

Worker 入口负责校验消息结构、加载 Job、认领租约、解析 job_type 注册表并调用 Handler。禁止通过消息传入可任意导入的 Python 模块名、函数名或可执行代码。

Handler 契约（概念接口）：
```python
class JobHandler(Protocol):
    job_type: str
    payload_schema: type[BaseModel]
    result_schema: type[BaseModel]

    async def execute(
        self,
        context: JobExecutionContext,
        payload: BaseModel,
    ) -> BaseModel: ...
```

`JobExecutionContext` 提供受控的 DB session/application services、store/task/job/attempt IDs、lease token、取消检查、进度报告、日志脱敏器和 Provider registry。Handler 不得自行改变 Job 状态；由 Runtime 包装层统一完成状态提交。

### 6.2 Celery 配置基线

- 使用 late acknowledgement；Worker 丢失时允许 broker 重投，但 PostgreSQL 认领仍是最终仲裁。
- `worker_prefetch_multiplier=1`，避免长任务被单个 Worker 预取占有。
- 配置任务软/硬时间限制、任务事件监控、优雅关闭与合理的 Redis visibility timeout。
- 不依赖 Celery 自动重试作为唯一重试机制；业务重试策略由 PostgreSQL Job 状态和 Sweeper 驱动，Celery retry 只可用于短暂的投递层异常。
- Redis visibility timeout 必须高于预期最长任务执行窗口与确认窗口；超长任务仍以租约心跳和 Job 状态为准，不能无限放大 visibility timeout 代替恢复设计。
- 队列按资源/外部依赖划分，例如 `ai_text`、`ai_image`、`io_default`、`channel_io`；初期避免按每个业务功能创建大量队列。
- 并发限制至少支持全局、队列、Provider、门店维度；限额配置有上限，防止单店或单 Provider 占满资源。

## 7. 重试、错误分类与 Sweeper

### 7.1 错误分类

| 分类 | 示例 | 默认处理 |
|---|---|---|
| transient | 网络断连、连接重置、部分 5xx | 指数退避 + full jitter，受 max_attempts 限制 |
| rate_limited | Provider 429 / 平台限流 | 优先尊重 Retry-After，再加抖动；降低对应 Provider 并发 |
| permanent | 参数错误、无权限、资源不存在、Schema 不兼容 | failed，不自动重试 |
| output_invalid | 模型输出无法通过 Schema/业务校验 | 有界修复/重试一次或按策略 failed；不得无限重试 |
| timeout_safe | 可证明无外部副作用的超时 | retry_wait |
| side_effect_unknown | 请求可能已被外部接收但响应丢失 | needs_human，先核验外部状态 |
| cancelled | 用户取消或上游业务撤销 | cancelled；清理仅做安全可重复操作 |

建议退避：`min(max_delay, base_delay * 2^(attempt_no-1))` 后乘 full jitter 随机因子；具体 base/max 由 job_type/Provider 策略配置。重试必须有上限、最大任务年龄和成本上限。

### 7.2 Sweeper

独立周期进程/调度任务扫描：
- Outbox pending 且到期的事件；
- publishing 锁过期的 Outbox 事件；
- lease_expires_at 已过期的 running Job；
- retry_wait 到期但未重新投递的 Job；
- 超过最大尝试次数、最大年龄或预算的 Job；
- 需要人工处理但长期未处理的 Job。

Sweeper 使用小批量、行锁跳过已锁行、指标和审计；多实例并发安全。它不得直接执行具体业务 Handler，只修复调度状态并产生新的 Outbox 事件。

### 7.3 租约过期恢复规则

- 纯计算/无副作用任务：租约过期后转 retry_wait（若剩余尝试允许）。
- 有外部幂等键且可查询结果的任务：先调用 Adapter 查询操作状态；确认未完成后再安全重试。
- 发布/草稿保存等状态不确定的外部操作：转 needs_human，禁止自动重复发起。
- 超过 max_attempts 或最大任务年龄：failed 或 needs_human，按副作用风险决定。
- 每次恢复都写 JobEvent 和审计信息，保留旧 Attempt。

## 8. Outbox Relay 契约

1. 业务数据、Job 和 Outbox 在同一 PostgreSQL 事务提交；禁止先提交业务记录再直接发 Redis 消息。
2. Relay 以批量 `FOR UPDATE SKIP LOCKED` 认领事件，锁定时间有限。
3. Broker 发布成功后更新 published_at/status；失败记录 last_error、publish_attempts 和下一次 available_at。
4. Relay 在“Broker 已接收、数据库未标记 published”窗口崩溃会重复发布；消费者必须幂等。
5. 事件 payload 只包含版本化的资源 ID、门店 ID（非授权凭据）、必要的路由元数据；Worker 必须重新从数据库加载并校验资源归属。
6. Outbox 保留期限、归档和清理策略另由运维基线确定；不得删除仍 pending、publishing 或与审计/恢复相关的记录。

## 9. AI Gateway Provider 契约

### 9.1 能力接口

统一以能力为入口，不暴露厂商 SDK 给业务模块：

```python
class TextProvider(Protocol):
    async def generate(self, request: TextGenerateRequest) -> TextGenerateResponse: ...
    async def rewrite(self, request: TextRewriteRequest) -> TextGenerateResponse: ...

class ImageProvider(Protocol):
    async def generate(self, request: ImageGenerateRequest) -> ImageGenerateResponse: ...
    async def edit(self, request: ImageEditRequest) -> ImageGenerateResponse: ...

class VisionProvider(Protocol):
    async def inspect(self, request: VisionInspectRequest) -> VisionInspectResponse: ...

class OCRProvider(Protocol):
    async def extract(self, request: OCRRequest) -> OCRResponse: ...
```

所有 Request/Response 使用 Pydantic Schema，包含 schema_version、业务关联 ID、能力参数、受控资产引用和输出约束。响应必须通过 Schema 校验；再由领域层进行价格、优惠、品牌和渠道等事实校验。

### 9.2 Provider 注册与路由

Provider 声明：
- provider_id、capabilities、supported_models、regions（如适用）；
- 支持的输入/输出格式、文件尺寸限制、上下文长度、图像尺寸；
- 超时、速率限制、并发上限和健康状态；
- 结构化输出、流式、图像编辑等能力支持情况。

路由输入：门店授权的模型配置、能力、任务类型、数据区域约束、成本/质量策略、Provider 健康状态。路由输出必须记录实际 provider/model 和选择原因码。禁止在失败时无审计地切换到未授权或数据区域不兼容的供应商。

### 9.3 调用可靠性

- Gateway 统一处理超时、连接池、限流、熔断、重试分类和成本计量。
- 仅对明确可安全重试的请求自动重试；优先使用供应商支持的 request idempotency。
- 429 尊重 Retry-After；5xx/网络错误采用有界退避；参数/鉴权错误不重试。
- Provider 响应先做 Schema 校验；无效输出不得直接写入可审核交付物。
- 图像输出先写对象存储，再保存对象 key、hash、MIME、尺寸和 Provider 元数据；失败时清理孤儿对象需经过延迟引用检查。
- Prompt 模板 ID、版本、变量 Schema、模型 ID、参数快照、输出 Schema 版本固定记录，确保任务可追溯。
- Secret 通过 Secret Manager/环境注入引用解析；日志中只记录 secret reference ID，不记录密钥值。

### 9.4 统一错误码

建议稳定错误码：
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_TIMEOUT`
- `PROVIDER_AUTH_FAILED`
- `PROVIDER_INVALID_REQUEST`
- `PROVIDER_OUTPUT_INVALID`
- `PROVIDER_CONTENT_REJECTED`
- `PROVIDER_BUDGET_EXCEEDED`
- `PROVIDER_CAPABILITY_UNSUPPORTED`
- `PROVIDER_REGION_NOT_ALLOWED`

错误响应区分 retryable、retry_after_seconds、side_effect_state（none/known/unknown）和 user_safe_summary；内部堆栈仅进入受控脱敏日志。

## 10. API 契约与授权

Job Runtime API 是平台内部/受权限保护的运维能力，不向普通商家暴露 Worker、队列和租约细节。

建议接口：
- `POST /api/v1/internal/jobs`：内部应用服务创建 Job；对业务 API 不开放任意 job_type。
- `GET /api/v1/tasks/{task_id}`：门店用户查询自己有权访问的业务任务及安全摘要。
- `GET /api/v1/admin/jobs/{job_id}`：管理员查看 Job/Attempt/Event 脱敏轨迹。
- `POST /api/v1/admin/jobs/{job_id}/retry`：经授权人工重试；记录操作者、原因和原 Job。
- `POST /api/v1/admin/jobs/{job_id}/cancel`：取消排队任务或请求运行中任务安全停止。
- `POST /api/v1/admin/jobs/{job_id}/resolve`：提交人工核验结果并按规则创建后续执行。

授权约束：
- 所有门店任务查询由认证主体和 StoreMembership 关系确定 store_id；跨门店 IDOR 测试必须覆盖 Job、Attempt、结果引用和恢复操作。
- 平台管理员权限与门店用户权限分离；普通商家不读取内部错误堆栈、Provider 原始响应或其他门店数据。
- 重试/取消/人工恢复必须审计；不能把客户端传入的 store_id、actor_id 或权限标志当成授权事实。
- Issue #5 的身份/门店授权契约是实现前置；在其通过前只能进行不依赖认证实现的领域/契约准备。

## 11. 可观测性与数据保护

结构化日志关联字段：request_id、trace_id、store_id（内部日志）、marketing_task_id、job_id、attempt_id、provider、model、duration_ms、error_code。store_id 和用户标识不得无差别暴露到普通业务日志。

核心指标：
- Outbox pending 数、最老事件年龄、Relay 发布失败率；
- 队列深度、等待时间、任务耗时分位数、成功率、重试率；
- 租约过期数、needs_human 数、failed 数、恢复时长；
- Provider 延迟、429/5xx、Schema 失败率、并发、成本/门店/任务；
- 任务年龄、取消率、资源池利用率。

日志禁止包含密码、Session/Cookie、API Key、Secret、完整 Authorization Header、原始敏感用户内容、未脱敏 Provider 请求/响应。错误摘要必须可展示且经过白名单脱敏。AI 输入输出的留存策略按数据分类、用户告知和权限规则单独确定。

## 12. 测试与验收矩阵

| ID | 场景 | 验收要求 |
|---|---|---|
| JOB-01 | 创建事务回滚 | 业务记录、Job、Outbox 同时回滚，不产生孤立事件 |
| JOB-02 | 相同幂等键重复创建 | 返回同一 Job；参数 hash 不同返回 409 |
| JOB-03 | Relay 发布后崩溃 | 重复投递可发生，但只允许一个有效 Worker 租约 |
| JOB-04 | Worker 在执行中崩溃 | 租约过期后按副作用策略恢复；Attempt 历史保留 |
| JOB-05 | 旧 Worker 恢复运行 | 旧 lease_token 无法续租或提交结果 |
| JOB-06 | 心跳丢失/长任务 | Sweeper 正确检测过期租约，不重复执行不可安全重试的副作用 |
| JOB-07 | 429 / Retry-After | 延迟重试且 Provider 并发受限 |
| JOB-08 | 永久错误/无效参数 | 不进行无意义自动重试 |
| JOB-09 | 发布请求响应丢失 | 进入 needs_human，先核验外部状态，不重复发布 |
| JOB-10 | 取消与并发竞争 | 取消、完成、超时并发时只有合法状态转换成功 |
| JOB-11 | 多 Worker 并发认领 | 同一 Job 不出现两个有效 lease_token |
| JOB-12 | Outbox 积压与 Relay 多实例 | 可恢复投递，不丢事件，不重复产生不可逆副作用 |
| AI-01 | Provider 超时/断连 | 产生可追踪调用记录并按错误分类处理 |
| AI-02 | Provider 429/5xx | 退避、限流、成本和重试记录正确 |
| AI-03 | 无效结构化输出 | Schema 校验失败，不写入审核交付物 |
| AI-04 | Provider 不可用/切换 | 只路由到已授权且满足区域策略的 Provider |
| AI-05 | Secret 泄露检查 | 日志、API 响应、事件和异常中均无密钥值 |
| AI-06 | Prompt/模型版本追溯 | 每次调用能查到固定版本与参数快照 |
| SEC-01 | 跨门店 IDOR | 无权用户无法读取/操作其他门店 Job、Attempt、结果或恢复入口 |
| SEC-02 | 恢复操作审计 | 操作者、原因、时间、前后状态完整记录 |

### 验收门槛
- PostgreSQL 事务提交后，Job 与 Outbox 可恢复；Broker 故障不丢业务任务。
- 重复投递不会产生重复不可逆副作用。
- Worker 崩溃、租约过期、超时和限流均有可验证恢复路径。
- AI 调用可按门店、任务、Job、Provider、模型和 Prompt 版本追溯。
- Secret、敏感业务数据和内部堆栈不泄露到浏览器或普通日志。
- 真实 PostgreSQL 集成测试必须执行；不得以 SQLite/mock 代替。
- 故障注入、并发和跨门店安全测试均需有实际执行记录；未执行项标记“未执行”。

## 13. 实施依赖与分阶段

### 可并行完成（当前设计阶段）
- Job/Attempt/Event/Outbox Schema 与迁移草案。
- Job 状态机、错误分类、Handler Protocol 和 Provider Protocol。
- OpenAPI/Pydantic 契约草案。
- 单元测试设计、故障注入脚本设计和安全测试矩阵。

### 实现前置
- Issue #4：工程骨架、依赖锁定、配置与 Compose 基础。
- Issue #5：认证、Session、StoreMembership 和服务端门店授权；Job 管理 API 必须复用该授权边界。
- Issue #8：营销领域状态机与事件契约；Job payload 只能引用已冻结的领域对象/版本。
- PostgreSQL、Redis 和对象存储本地环境可运行。

### 实施顺序
1. SQLAlchemy 模型与 Alembic migration。
2. Job 创建服务 + Outbox Relay + Sweeper。
3. Celery Worker bootstrap、认领/租约/心跳/状态提交。
4. Job 查询、取消、重试和人工恢复 API。
5. AI Gateway 核心接口、Provider registry、调用审计与成本。
6. 真实 Provider 适配器和对象存储输出。
7. PostgreSQL 集成、故障注入、并发、安全和端到端测试。

## 14. 冻结决策与待实施配置

以下首期架构契约已冻结；参数需通过压测和生产观测校准，不改变状态机与一致性原则：
- PostgreSQL 为唯一 Job/Outbox/Attempt 状态事实源；Celery result backend 非权威。
- Outbox + Relay 采用至少一次投递；消费者通过 DB 原子认领和业务幂等防重。
- 租约 token 是 fencing token；所有续租/结果写入必须校验 token。
- Job 状态采用 queued/running/retry_wait/succeeded/failed/cancelled/needs_human。
- 不确定的外部副作用不自动重试。
- AI Gateway 只暴露 Text/Image/Vision/OCR 能力契约，业务域不依赖厂商 SDK。
- API/Worker 共用模块化单体领域包；Worker 作为独立进程，不拆独立业务微服务。

待实施/校准的参数（不影响已冻结的架构原则）：
- 租约/心跳初始值及不同 job_type 的超时配置；
- 各队列并发、Provider 限流和成本预算；
- Outbox/Job/调用审计保留与归档周期；
- 各 Provider 的真实请求幂等能力及地区限制。

---

**状态声明：** 本文是设计与契约，不代表已创建数据库表、部署 Redis/Celery、接通 AI Provider 或通过任何生产验收。实现和测试状态必须以代码、CI 记录和运行证据更新。


## 15. 实际实现状态（2026-11-11）

### 已进入 main
- PR #42：Provider Protocol、Descriptor、Registry、结构化 Schema、统一错误与副作用状态契约。
- PR #44：Job、JobAttempt、JobEvent、OutboxEvent、AIInvocation、AIUsageRecord ORM 与 migration 0005。
- PR #48：Job + Outbox 原子创建服务、Outbox Relay、租约恢复 Sweeper、Celery Worker Handler Registry、原子认领、心跳、deadline、取消协作、lease fencing、人工 retry/resolve API 和 AIInvocation/AIUsageRecord 生命周期；migration 0006。
- PR #49：幂等记录 actor_user_id 绑定，防止跨操作者重放。
- PR #48 CI Run 42968216381：API/Web/Worker/Contracts/E2E/Infrastructure 六项全部通过。

### 尚未完成的运行时 DoD
- Provider/ModelConfig 持久配置、Secret reference 生命周期、路由和区域策略。
- ProviderDescriptor.max_concurrency 尚未落实为跨 Worker 的并发配额；门店级资源限流、429/Retry-After 协调仍需实现。
- Dead Outbox 的平台管理员审计重驱入口和告警观测仍需补齐。
- Worker/Relay 的崩溃、重复投递、并发认领、租约过期、429/超时及外部副作用未知场景需增加专门故障注入测试。
- #7/#8/#11/#12 的业务 Handler 与真实 Provider Adapter 完成后，补齐端到端联调；真实厂商 SDK/适配器由 #10 负责，渠道发布由 #12 负责。

当前状态是“核心持久化执行链路已交付”，不是“Job Runtime 全部生产验收完成”。Issue #9 在上述限流、故障注入、运维可观测和业务联调完成前保持 Open。


## 2026-11-11 首期门店级 Job 并发配额实现（PR #69）

已增加 Worker claim 阶段的门店级并发门禁：

- 默认每门店最多 3 个 running Job，可通过 `WORKER_MAX_RUNNING_JOBS_PER_STORE` 配置。
- 当达到上限时不创建 JobAttempt、不增加 attempt_count、不消耗重试预算；Job 保持 queued，更新 available_at，并在同一事务创建延迟 Outbox dispatch 事件。
- 门店记录行锁串行化同一门店的 claim + running-count 检查，避免多个 Worker 同时超发配额。
- 通过 `WORKER_CONCURRENCY_DEFER_SECONDS` 配置容量不足时的重投延迟；默认 10 秒。
- 系统级 Job 暂不受门店配额限制；Celery worker pool 仍负责进程级总并发。

测试覆盖：容量满时 deferred、Outbox 重新投递、attempt 不增长、容量释放后可正常 claim。该实现解决首期门店级限流，不等同于 Provider/模型级 max_concurrency、队列级公平调度或成本预算；这些仍待实现与故障注入。
