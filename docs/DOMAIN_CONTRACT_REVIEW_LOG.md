# B/C/D 跨领域契约审查记录

> 日期：2026-11-11  
> 审查对象：Issues #5–#10 与相关设计文档  
> 状态：第一轮审查完成；存在待联合评审决议项  
> 本记录不表示领域设计已经最终冻结或生产能力已经实现。

## 1. 已统一并修正的冲突

| 项目 | 统一结论 | 权威文档 |
|---|---|---|
| 身份与门店归属 | User/Store/StoreMembership/Session 由 #5 所有；每个门店请求通过 X-Store-Id 表达上下文并由服务端重新验证成员关系；Session 不保存授权性 current_store_id | IDENTITY_STORE_SECURITY_DESIGN.md |
| Store 时区 | Store.status 与 Store.timezone 由 #5 持有；#6 StoreProfile/Offer 不得复制权威 timezone，Offer 时间使用 UTC 并按 Store.timezone 解释 | DOMAIN_INTEGRATION_CONTRACTS_V1.md |
| 经营资料 | Product/Offer/BrandGuideline/KnowledgeItem/MediaAsset 由 #6 持有；MediaAsset 是素材库源资产，不等于营销 ImageArtifact | DOMAIN_INTEGRATION_CONTRACTS_V1.md |
| 营销流程 | MarketingTask/RequirementSnapshot/StrategySnapshot/TaskStep/DependencyEdge 由 #7 持有 | MARKETING_TASK_DOMAIN_DESIGN.md |
| 内容审核与发布包 | Artifact/ArtifactVersion/ReviewRecord/ChannelContent/QualityReport/PublishPackage/PublishConfirmation 由 #8 持有 | DOMAIN_INTEGRATION_CONTRACTS_V1.md |
| 渠道账号与发布执行 | ChannelAccount/平台凭据/能力状态/PublishOperation 由 #12 持有；#8 只负责门禁与业务命令 | DOMAIN_INTEGRATION_CONTRACTS_V1.md |
| Job 状态 | 已合并 PR #29：Job 使用 queued/running/retry_wait/succeeded/failed/needs_human/cancelled；Outbox 投递状态独立管理；#7/#9 仍需冻结 terminal_reason、调度阈值等实现参数 | ASYNC_JOB_RUNTIME_AND_AI_GATEWAY_CONTRACT.md |
| CSRF 与门店上下文 | Cookie Session 写请求采用 Session 绑定 synchronizer token + Origin/Referer 校验；所有门店 API 要求服务端校验的 X-Store-Id | IDENTITY_STORE_SECURITY_DESIGN.md |
| AI Gateway | #9 定义 AIInvocation、调用审计、成本、错误归一化与 Provider 接口；#10 实现真实 Provider 和 PromptVersion 管理 | DOMAIN_INTEGRATION_CONTRACTS_V1.md |
| 数据库/队列 | PostgreSQL 是 Job/Attempt/Outbox 事实源；Celery + Redis 仅做至少一次投递；必须有 Outbox Relay 与 Sweeper | TECH_STACK_SELECTION.md + DOMAIN_INTEGRATION_CONTRACTS_V1.md |

## 2. 当前明确的模块责任

- #5：认证、Session、门店成员关系、授权上下文和授权审计。
- #6：门店经营资料、事实确认、知识条目、素材库和对象存储元数据。
- #7：营销任务聚合、业务状态机、快照、依赖图、业务事件。
- #8：文案/图片产物与独立审核、渠道内容、质检、冻结发布包、商家最终确认。
- #9：Job Runtime、Outbox、Worker 租约/重试/恢复、AI Gateway 调用契约与成本审计。
- #10：真实 Text/Image/Vision/OCR Provider 适配、PromptTemplate/PromptVersion 版本管理。
- #12：ChannelAccount、OAuth/授权凭据、平台能力矩阵、平台 API 与 PublishOperation。
- 领域间只通过应用服务接口、版本化事件和显式命令协作；禁止跨模块直接写表。

## 3. 联合评审仍需决议的项目

以下事项不能靠文档作者擅自替项目负责人或安全评审作决定：

1. 平台管理员主体的存储、初始化和恢复流程。
2. Session idle/absolute timeout 的最终数值（设计建议 idle 30 分钟、absolute 12 小时）。
3. owner/member 首期能力映射：当前 `IDENTITY_STORE_SECURITY_DESIGN.md` 的能力矩阵采用“业务动作同权、owner 仅作归属/生命周期标识”的默认提案，但 Issue #5 仍标记待决。该提案尚未获得本轮负责人明确确认，实施前必须确认接受或调整；在此之前授权策略应集中封装，避免散落硬编码。
4. 门店成员邀请/注册/密码重置的交互和邮件交付机制。
5. Offer 的结构化规则是否覆盖当前所有目标业态；如有缺项先扩 Schema，不允许落回自由文本。
6. 素材上传签名 URL 的有效期、文件限制、恶意文件扫描和删除/保留策略。
7. 质检硬阻断与人工复核的可覆盖范围及审计要求。
8. Outbox Relay/Sweeper 的调度频率、锁策略、积压告警阈值。
9. PromptVersion 的发布审批权限与回滚权限。
10. #12 首个真实渠道平台选择与主体资质/授权 scope。

## 4. 必须通过的跨域契约测试

- A 店用户篡改 store_id 或访问 B 店 task/artifact/job/file：拒绝，跨店资源统一 404。
- 成员移除后复用已有 Session：后续门店请求拒绝。
- Store timezone 变化：营业时间和 Offer 日期按权威门店时区解释，不出现双时区字段冲突。
- Product/Offer 事实变更：仅使实际引用该事实的下游产物失效。
- 文案版本变化：文案审核重新执行；只使真实依赖该版本的图片/渠道内容/质检/发布包 stale。
- 图片版本变化：不重置文案审核。
- Worker 迟到结果：若输入指纹变化，拒绝挂接当前任务版本。
- Outbox 重复投递：消费者幂等，不重复创建产物/审核/外部副作用。
- 发布超时：Job 进入 needs_human，核验渠道结果前不盲目重发。
- AI Provider 429/超时/无效结构/凭据错误：按错误分类恢复，AIInvocation 与 Job 状态分别记录。
- 平台管理员访问门店内容：默认拒绝，必要支持访问必须有单独授权和审计。

## 5. 新增工程化 Schema 草案\n\n已新增 `docs/CORE_DATA_MODEL_AND_API_SCHEMAS_V1.md`，覆盖 Identity/Store、Store Knowledge、Marketing/Content、Job/AI 的逻辑 ERD、API 请求约定、错误 Schema、事件 Envelope、并发/幂等数据库约束和实现前检查项。该文件是评审草案，不替代 Pydantic/OpenAPI/JSON Schema 或 Alembic 迁移。\n\n## 6. 本轮审查范围与验证状态

- 已完成：文档字段归属、状态枚举、接口边界、跨域事件和关键安全规则的静态交叉审查；发现的职责重叠与字段冲突已在权威文档和 Issues 中修订。
- 已确定的设计选择：门店作用域请求使用服务端验证的 X-Store-Id；Cookie Session 写请求采用 Session 绑定 synchronizer CSRF token + Origin/Referer 校验；Store.timezone 由 #5 独占；Offer 时间以 UTC 存储；Job 人工处理状态统一 needs_human。
- 未执行：代码级 Schema 校验、OpenAPI 生成、Alembic 迁移测试、PostgreSQL 约束验证、API/Worker 集成测试和浏览器 E2E。当前是文档设计审查，不能把它们标记为通过。

## 7. 开发门禁

在 B/C/D 轨道联合评审记录完成前：
- 可以继续做接口 Schema、状态图、迁移草案和测试用例准备。
- 不得开始依赖争议字段/接口的业务实现。
- #5/#6 的基础模型可先完成设计评审；#7/#8/#9/#10 的联调契约必须以本文件和各领域文档为准。
- 契约变更必须同步更新本记录、权威文档、OpenAPI 和相关 Issue，不允许只改代码。


## 7. Identity & Store 第二轮修订（PR #26，2026-11-11）

本轮审查基于 PRODUCT_DESIGN.md v1.8 与最新 main，确认并记录以下规则；PR #26 尚未合并，因此它们属于待评审契约，不代表已冻结实现：

1. 每个门店业务请求使用 X-Store-ID 作为不可信 request selector；服务端逐请求校验 Store.status 与 StoreMembership.status，并构造 AuthContext.request_store_id。
2. Session.active_store_id 仅用于 UI 默认选择/恢复提示，不得作为请求授权上下文；多标签页的请求门店互不影响。
3. 平台管理员按产品文档负责在门店详情管理门店成员。owner/member 不额外获得成员管理权限或新增审批层级。
4. 平台管理员通过独立 PlatformAdminGrant 获得 platform.store_members.manage；该权限不自动授予 StoreMembership，也不授予门店营销正文、素材或经营资料读取权。
5. 12h idle / 7d absolute 是待安全评审的建议值；邀请/注册/密码重置流程、管理员 bootstrap/恢复和 RLS 启用策略仍待决议。
6. PR #22/#23 为过期版本；PR #26 从最新 main 重建并已合并。安全测试矩阵仍待实现阶段执行。

对营销域的影响：#7/#8/#9 只能消费 AuthContext.request_store_id 与 actor_user_id；不得读取 Session.active_store_id 决定资源归属。营销任务、产物、Job、资产的所有权仍以持久化 store_id + 服务端授权上下文双重校验为准。


## 8. B/D 联合授权边界同步（2026-11-11）

- Identity 最新评审入口为 PR #26；此前 PR #22、#23 已关闭，不再作为当前契约依据。
- Async Runtime 的 PR #20 已按 PR #26 的 AuthorizedStoreContext 字段补充 Worker 映射：user_id、request_store_id、membership_id；Session.active_store_id 仅为 UI 默认选择。
- 用户触发 Job 的 store_id/created_by_user_id 从可信上下文注入；system Job 使用显式 system scope 与 actor_type=system，不伪造用户。
- PlatformAdminGrant 的成员管理能力不等于 StoreMembership，也不授予 Job、营销任务、产物或门店资料访问权限。
- PR #26（Identity）、PR #27（Store Knowledge）、PR #25（Marketing Task）、PR #29（Async Runtime）均已合并进入 main。它们只完成设计契约入库，不表示认证、经营资料 CRUD、营销状态机、Job Runtime 或 AI Provider 已实现；对应 Issues #5/#6/#7/#9 保持 Open。安全、数据库和故障恢复测试仍待执行。


## 9. PR 合并与 Issue 关闭核对（2026-11-11）

| PR | 领域 | 合并状态 | Issue 状态与关闭理由 |
|---|---|---|---|
| #26 | #5 Identity / Store Security | 已合并 | #5 保持 Open：仅设计契约，生产认证/授权和 IDOR 测试未实现 |
| #27 | #6 Store Knowledge | 已合并 | #6 保持 Open：仅领域设计，CRUD/迁移/上传未实现 |
| #25 | #7 Marketing Task | 已合并 | #7 保持 Open：仅状态机/版本契约修订，生产实现未完成 |
| #29 | #9 Async Runtime / AI Gateway | 已合并 | #9 保持 Open：仅运行时设计，Job/Outbox/Worker/Provider 未实现 |
| #16 | #4 Engineering Foundation | Draft，CI 最新运行中 | #4 保持 Open：最新 CI 尚未结束，OTel/干净环境验收仍待证据 |
| #1 | 旧开发计划 PR | 已关闭（被现行 DEVELOPMENT_PLAN.md 取代） | 不涉及关闭 Issue |

本次没有关闭 #2/#4/#5/#6/#7/#8/#9/#10 等生产交付 Issue。Issue #3 已是 Closed。关闭任何 P0 生产 Issue 必须有其 DoD 对应的代码、迁移、自动化测试和可复核验收证据。


## 10. Issue #8 内容生产与发布交付领域审查（2026-11-11）

审查基线：PRODUCT_DESIGN.md v1.8、Demo `#task` 的 copy/image/channel/quality/publish 步骤、DOMAIN_INTEGRATION_CONTRACTS_V1.md §6/§9/§10、CORE_DATA_MODEL_AND_API_SCHEMAS_V1.md。

### 已明确的责任边界
- #7 拥有 MarketingTask、需求/策略快照、TaskStep、依赖图和业务状态；#8 不复制任务状态机。
- #8 拥有 Artifact/ArtifactVersion、ReviewRecord、ChannelContent、QualityReport、PublishPackage/Item/Confirmation。
- #6 拥有 MediaAsset 和已确认经营事实；#8 只引用资产 ID/hash，不拥有源素材。
- #9 拥有 Job/Outbox/Worker；#8 只提交命令并校验结果指纹。
- #10 拥有真实 AI Provider 和 PromptVersion；#8 不持有 Provider 凭据。
- #12 拥有 ChannelAccount、OAuth/平台凭据、能力发现、PublishOperation 和外部发布证据；#8 只拥有发布门禁和业务意图。

### 本轮发现并修正的契约缺口
1. Demo 的最终发布确认一次汇总多个渠道，但旧 PublishPackage 字段只有单个 channel_content_id。现已提出 `PublishPackage + PublishPackageItem` 聚合模型：一个任务交付包、多条渠道 item，整包 fingerprint 与最终确认原子绑定。
2. ChannelContent 必须是按渠道和输入指纹生成的不可变快照；QualityReport 必须绑定 ChannelContent、规则版本和指纹。
3. manual_handoff 与 official_api 必须分开；无账号连接时不能伪造 PublishOperation 或已发布状态。
4. #8 发布请求是受门禁约束的命令；外部发布状态只由 #12 的 PublishOperation 证据确认，#9 Job succeeded 不等于渠道发布成功。
5. 文案/图片审核按确切 ArtifactVersion 独立进行；旧版本通过不能批准新版本。

### 本轮交付
- 新增 `CONTENT_DELIVERY_DOMAIN_DESIGN.md`：Demo 映射、实体、状态、指纹、API/事件、事务/幂等、数据库约束和 CNT-01 至 CNT-26 测试矩阵。
- 更新 `DOMAIN_INTEGRATION_CONTRACTS_V1.md` §6/§10/§11/§12/§13。
- 更新 `CORE_DATA_MODEL_AND_API_SCHEMAS_V1.md` 的 Content ERD、多渠道 Freeze Schema 和数据库约束。
- 该方案仍需 #7/#9/#12 联合评审；PackageItem 聚合、manual_handoff 和人工质检复核规则不得未经评审直接进入生产实现。

**验证状态：** 仅完成静态文档交叉审查；CNT-01 至 CNT-26、OpenAPI Schema、Alembic 约束、API/Worker 集成和浏览器回归均待执行。
