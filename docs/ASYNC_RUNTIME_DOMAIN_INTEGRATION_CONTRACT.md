# Issue #9 与身份/营销领域跨域集成契约

> 状态：跨域对齐提案，随 PR #24 评审；不是生产实现声明。对齐 Issue #5 Identity & Store、Issue #7 Marketing Task、Issue #9 Async Runtime / AI Gateway。

## 1. 模块职责

- Identity & Store：User、Session、Store、StoreMembership、门店授权和身份审计的唯一事实来源。
- Marketing Domain：MarketingTask、TaskStep、快照、产物版本、审核、质检和发布包的唯一事实来源。
- Job Runtime：Job、JobAttempt、JobEvent、OutboxEvent、租约、重试和恢复的唯一事实来源。
- AI Gateway：Provider 能力、路由、调用审计、模型/Prompt 版本和用量；不拥有营销任务状态。
- API 与 Worker 是模块化单体的不同进程。Worker 不因内部身份获得跨门店权限。

模块之间通过应用服务/领域事件通信，不得直接写入其他模块内部表。

## 2. 门店授权上下文

### API 请求

1. Session Cookie 证明登录主体；写请求执行 CSRF 校验。
2. 门店 API 使用 `X-Store-ID` 作为请求门店选择器。它是不可信输入，不是授权凭据。
3. Identity & Store 对每个请求重新验证 Session、Store 状态和 active StoreMembership，构造不可伪造的 request-scoped `AuthorizedStoreContext`。
4. Marketing / Job 应用服务只接受可信上下文；创建记录时从上下文注入 `store_id`、`actor_id`，忽略或拒绝请求体中的身份/门店/角色字段。
5. Session.active_store_id 只用于 UI 默认选择/恢复提示，不替代每请求的 X-Store-ID 和成员关系校验。不同标签页可使用不同门店上下文。

Job 查询 API（包括 GET /api/v1/tasks/{task_id}）同样要求门店上下文，并按 `task_id + authorized store_id` 查询。跨门店资源统一 404。

### Worker 执行

消息只携带 job_id、dispatch_event_id、schema_version。Worker 从 PostgreSQL 加载 Job，不信任 Broker 消息中的 store_id、actor_id、payload 或权限声明。

执行和写回前验证 Job、MarketingTask、TaskStep、Artifact/Version、Asset、PublishPackage 的 store_id 一致；验证 Handler 类型、当前任务状态、输入版本/指纹和租约 fencing token。Worker service identity 只执行 Job 明确委托的操作，不得绕过门店范围或商家确认门禁。

### 成员撤销与门店停用

- 成员被移除、门店停用或权限撤销后，新的用户 API 请求立即拒绝。
- 尚未开始的用户触发 Job 默认取消；无法确定安全取消时转 needs_human。
- 已开始的纯计算/只读 Job 可按策略完成计算，但不得自动产生需要当前授权的外部副作用。
- 发布、草稿提交等外部副作用发起前，必须重新验证门店状态、渠道授权、发布包版本、文案/图片审核、质检和商家最终确认。不得以 Job 创建时的权限快照代替当前检查。
- 撤销与外部副作用并发且无法证明操作未发生时，进入 needs_human，不盲目重试。

## 3. Job 与营销业务状态分离

MarketingTask.lifecycle_status 表示业务任务生命周期；TaskStep.status 表示节点进度/阻断/跳过/stale；文案与图片审核由绑定 ArtifactVersion 的独立 ReviewRecord 表示；Job.status 只表示异步执行单元状态。

Job succeeded 不代表 TaskStep 自动成功。营销应用服务必须校验输出 Schema、业务事实、依赖指纹和当前状态后，才可推进节点。

### 状态规范化提案

Issue #7 与 Issue #9 统一采用 Job 状态：`queued`、`running`、`retry_wait`、`succeeded`、`failed`、`cancelled`、`needs_human`。Job 不包含 `dead`；
- 重试耗尽/超龄进入 `failed`，通过 `terminal_reason` 区分；OutboxEvent 可独立使用 `dead` 表示投递耗尽，不映射为 Job 状态。
- `needs_human` 表示外部副作用不确定或必须人工判断。
- Job 终态不静默重开；人工恢复创建关联的新 Job，保留原 Job 和审计记录。

该项已在当前 Issue #7 与 #9 文档中对齐；联合评审时确认无冲突后冻结。

## 4. 幂等键统一提案

Issue #7 与 #9 当前唯一范围描述略有差异。建议用户 API 写操作统一为：

`store_id + actor_id + operation + idempotency_key`；该作用域由 API 幂等记录层实施，Job Runtime 再映射为非空的 `idempotency_scope_type + idempotency_scope_id + job_idempotency_key`，系统级任务使用固定 system scope

同时保存 request_hash、结果资源 ID、响应状态和创建时间。同一作用域/Key/Hash 重放返回原结果；相同 Key、不同 Hash 返回 409。系统内部消费使用稳定 event_id、job_id、attempt_id 和操作类型形成幂等边界，不伪造用户 actor。生成类操作绑定 task_id、step_key、操作类型、输入指纹和请求轮次；发布幂等键绑定 publish_package_id、channel_account_id 和发布动作。Celery task_id 仅作传输/追踪标识，不作为业务幂等事实。

## 5. 事务与 AI 产物边界

- 业务变更、Job 创建和 OutboxEvent 写入在同一 PostgreSQL 事务中；Outbox 至少一次投递，消费者幂等，不宣称 exactly-once。
- Outbox payload 只含版本化 ID、事件类型、schema_version 和必要路由元数据；不含 Session、Cookie、密钥或可执行代码。
- Marketing Domain 通过应用服务请求创建 Job；Job Runtime 不直接推进 MarketingTask/TaskStep。
- AI Gateway 只返回经过 Pydantic Schema 校验的候选结果。Marketing Domain 负责价格、优惠、库存、有效期、品牌与渠道事实校验，并决定是否创建新产物版本。
- AI 调用成功不等于文案/图片审核通过；两类产物保持独立版本和审核状态。
- Provider 路由满足门店模型配置、能力和区域限制；密钥只以 secret reference 解析。
- 图像写入私有对象存储后登记元数据；签名 URL 生成前重新验证门店归属。

## 6. 跨域验收矩阵

| ID | 场景 | 预期 |
|---|---|---|
| INT-01 | 请求体伪造 store_id / actor_id / role 创建 Job | 只使用 AuthorizedStoreContext |
| INT-02 | 同一 Session 两标签页分别使用门店 A/B | 每个请求独立验证 X-Store-ID，不串上下文 |
| INT-03 | Job.task_id 与 Job.store_id 不一致 | Worker 拒绝并记录安全事件 |
| INT-04 | 用户被移除后队列仍有未开始 Job | 取消或 needs_human，不执行外部副作用 |
| INT-05 | 门店停用与发布 Job 并发 | 外部副作用前重新校验并阻断 |
| INT-06 | Job 成功但 TaskStep 指纹已变化 | 不推进当前节点，保留 Attempt 记录 |
| INT-07 | 同幂等键重放/不同请求体重放 | 原请求返回原结果；不同请求体 409 |
| INT-08 | Outbox 重复投递、多 Worker 并发 | 只有一个有效租约推进 Job，副作用幂等 |
| INT-09 | Provider 输出结构合法但优惠事实错误 | 领域校验拒绝，不创建可审核版本 |
| INT-10 | Worker 绕过审核/最终确认直接发布 | 服务端门禁拒绝 |
| INT-11 | 跨门店读取 Job、Attempt、资产或恢复接口 | 统一 404 |
| INT-12 | 人工恢复终态 Job | 创建关联的新 Job，记录操作者/原因，不重开旧 Job |

## 7. 冻结前待确认

1. Identity & Store 最终 AuthContext 字段名与 X-Store-ID 约定；本提案按 PR #26 的 request-scoped `X-Store-ID` / `AuthorizedStoreContext.request_store_id` 设计使用；Session.active_store_id 仅作为 UI 默认选择，不作为授权上下文。
2. Issue #7/#9 确认 Job 不含 `dead`；OutboxEvent 的投递耗尽状态可独立使用 `dead`，Job 终态原因使用 terminal_reason。
3. Issue #7/#9 共同确认用户 API 幂等键唯一范围。
4. 发布等外部副作用的最后授权检查与平台操作状态核验接口。
5. 成员撤销/门店停用后的在途 Job 策略。

本文件不解除 Issue #4/#5/#7/#9 的实现门禁。并发、Broker 故障、成员撤销竞态、Provider 故障注入及端到端测试必须在实现阶段实际执行并记录证据。
