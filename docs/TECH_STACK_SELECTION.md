# AI 门店运营官首期技术选型决策

> 文档版本：1.0  
> 决策日期：2026-11-11  
> 产品基线：v1.8  
> 架构基线：模块化单体 + 独立异步 Worker + Provider / Adapter  
> 状态：**已由项目负责人于 2026-11-11 确认，作为首期技术基线**  
> 对应：GitHub Issue #3

## 1. 决策摘要

| 层次 | 首期选择 | 说明 |
|---|---|---|
| Web 前端 | React 19.3 + TypeScript 6 + Vite 8 | 登录后 SPA 工作台，不需要 SSR |
| 路由 / 服务端状态 | React Router 7 + TanStack Query 5 | URL 管理导航，Query 管理服务端数据 |
| 表单 | React Hook Form + Zod | 复杂表单统一校验 |
| UI 样式 | CSS Modules + CSS Variables；必要时 Radix primitives | 严格复刻冻结 Demo，不套用整套默认主题 |
| API | Python 3.13 + FastAPI + Pydantic 2 | 模块化单体 |
| ORM / 迁移 | SQLAlchemy 2.0 + Alembic | 统一事务与迁移 |
| 业务数据库 | PostgreSQL 18 | 唯一业务事实主库 |
| 异步任务 | Celery 5.7 + Redis 8.2 LTS | Redis 只做 Broker，Job 状态以 PostgreSQL 为准 |
| 对象存储 | S3 API + boto3 | 本地 SeaweedFS；生产供应商待区域确认 |
| 身份与会话 | 应用内 Identity / StoreUser / Session；Argon2id；服务端 Cookie Session | 不把 JWT 放入 localStorage；预留 OIDC |
| 前端测试 | Vitest + React Testing Library + Playwright | 单元、组件、E2E 分层 |
| 后端测试 | pytest + HTTPX | 单元、API、数据库集成 |
| API 契约 | FastAPI OpenAPI + openapi-typescript / openapi-fetch | 生成前端类型 |
| Python 工具链 | uv + Ruff + mypy | 依赖锁定、Lint、格式化、类型检查 |
| JS 工具链 | pnpm + ESLint + TypeScript | lockfile 固定依赖 |
| 本地环境 | Docker Engine + Docker Compose | 不引入 Kubernetes |
| CI | GitHub Actions | PR 质量门禁 |
| 可观测性 | JSON 结构化日志 + OpenTelemetry OTLP | 首期不自建复杂监控平台 |

**架构形态不变：** 一个业务 API 模块化单体 + 独立 Worker 进程；不拆业务微服务，不引入 n8n 作为营销状态机，不把 ComfyUI 设为首期硬依赖。

## 2. 选型原则

1. 产品定位和 v1.8 Demo 是约束，不因技术选型改变页面、导航、状态语义和业务流程。
2. 首期优先单一主语言承载业务后端与 Worker。AI、图像和 OCR 能力通过 Provider 接口调用，不提前拆成 Python 微服务群。
3. 数据库是业务事实来源；队列只是投递和唤醒机制，不能成为业务任务唯一状态存储。
4. AI、对象存储和渠道 API 均通过服务端 Provider / Adapter 隔离。
5. 使用维护活跃的稳定版本；依赖通过 lockfile 固定，按月安全更新、按季度评估次版本升级。
6. 不因“未来可能需要”提前部署 Kubernetes、Kafka、服务网格、n8n、ComfyUI 或独立微服务。

## 3. 关键技术比较与决策

### 3.1 前端框架与构建

| 候选 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|
| React + Vite | SPA 启动快、部署简单、组件生态成熟；与当前 Demo 客户端交互模型接近 | 不提供 SSR，需要自行组合路由与数据请求 | **选用** |
| Next.js | SSR/RSC、路由和服务端能力完整 | 本产品是登录后的高交互工作台，SSR 收益有限，增加运行时复杂度 | 不选 |
| Vue 3 + Vite | 轻量、易上手、生态完整 | 需要引入第二套团队技能，没有抵消 React 生态优势的明确收益 | 不选 |

决定：React 19.3.x、Vite 8.x、TypeScript 6.x。React Router 7 负责路由，TanStack Query 5 负责服务端状态。导航、筛选和可分享页面状态尽量落 URL；避免把服务端数据复制进全局状态库。复杂全局客户端状态确有需求再评估 Zustand。

样式采用 CSS Modules 与 CSS Variables。设计令牌、页面层级、间距、组件尺寸和交互状态必须沿用冻结 Demo；Radix 只作为无样式交互原语，不允许套用默认主题重做 UI。表单使用 React Hook Form + Zod。API 类型从 OpenAPI 生成，不手工维护重复 DTO。

### 3.2 后端语言与 API 框架

| 候选 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|
| Python + FastAPI | 与 IterWave 已审查的 Python 执行能力一致；Pydantic 校验与 OpenAPI 自动生成；AI/图像/OCR SDK 生态成熟 | CPU 密集工作必须放 Worker；异步与同步库混用需治理 | **选用** |
| TypeScript + NestJS | 模块组织、依赖注入和工程规范完整；前后端统一语言 | AI/图像领域仍可能需要 Python 服务；引入跨语言边界与重复模型 | 不选 |
| Django + DRF | ORM、Admin、认证和后台能力成熟 | 产品已有自定义领域工作台；Django 全栈约定对当前 API 需求并非必要 | 不选 |

决定：Python 3.13.x（锁定最新安全补丁）、FastAPI 0.156.x、Pydantic 2.14.x。API 只负责鉴权、参数校验、事务、创建业务记录和提交异步 Job；耗时 AI、图像、OCR、热点和渠道操作进入 Worker。

首期不同时引入 NestJS、Django 或独立 AI 微服务。未来只有在模型推理需要独立 GPU/运行时隔离、资源伸缩或团队独立部署时，才考虑抽出专用推理服务。

### 3.3 数据库与 ORM

| 候选 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|
| PostgreSQL 18 | 事务、约束、JSONB、索引和生态成熟；适合复杂业务关系与审计查询 | 需要备份、迁移和连接池治理 | **选用** |
| MySQL 8.4 LTS | 成熟、托管选择多、团队普遍熟悉 | 本项目无必须选择 MySQL 的现有约束；PostgreSQL 对复杂约束和 JSONB 更合适 | 不选 |
| SQLite | 本地轻量、测试方便 | 不适合作为多门店生产主库和并发业务主库 | 不作为应用数据库 |

| ORM / 迁移 | 比较 | 决策 |
|---|---|---|
| SQLAlchemy 2.0 + Alembic | SQL 表达能力完整、事务控制明确、生态成熟 | **选用** |
| SQLModel | 与 Pydantic 集成方便、样板代码少 | 复杂关系、数据访问边界和迁移控制方面，直接 SQLAlchemy 更可控 |
| 其他代码生成 ORM | 类型体验较好 | Python 生态与复杂事务/迁移工作流的综合成熟度不如 SQLAlchemy |

决定：PostgreSQL 18.x、SQLAlchemy 2.0.x 维护线 + Alembic。首期统一一个数据库实例，按模块边界划分 Python package、表命名与数据访问接口；不为每个模块创建独立数据库。金额使用 Decimal + 币种，未知指标使用 NULL；所有门店业务表带 store_id。连接池初期使用 SQLAlchemy pool，只有并发与连接数证据表明需要时再引入 PgBouncer。

### 3.4 持久化异步任务与 Broker

| 候选 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|
| Celery 5.7 + Redis | 成熟任务队列生态；重试、路由、Worker 并发、监控和远程控制完善 | 配置项较多；Redis visibility timeout、重复投递和确认策略必须理解 | **选用** |
| Dramatiq + Redis/RabbitMQ | API 简洁、默认重试和中间件设计清晰 | 周边监控、运维工具和团队可复用经验少于 Celery | 不选 |
| RQ | 简单、易部署 | 复杂任务路由、可观测性和执行控制能力相对有限 | 不选 |
| RabbitMQ | 消息确认、路由和队列语义强 | 增加一套 Broker 运维；首期业务量不足以证明必要 | 暂不选，作为升级候选 |

决定：Celery 5.7.x + Redis 8.2 LTS。Redis 只负责 Broker，不配置为业务 Job 的唯一结果存储；不依赖 Celery result backend 作为业务状态来源。PostgreSQL 的 Job、JobAttempt、JobEvent、Outbox 表是事实来源。

可靠性要求：
- 业务事务同时写入 Job 与 Outbox；Outbox Relay 投递 Celery 消息，Sweeper 扫描未投递/超时 Job，支持从数据库恢复。
- Job 必须有 idempotency_key、store_id、业务对象 ID、attempt、lease/heartbeat、error_code 和状态事件。
- Worker 按至少一次投递设计，所有副作用操作必须幂等；不能假设消息只执行一次。
- 对可安全重试的错误退避重试；发布状态不确定时进入 needs_human，先核验平台状态，不盲目重发。
- Redis Broker 使用独立实例/资源池，启用持久化与访问控制，设置 maxmemory-policy=noeviction；不得与高淘汰风险的缓存共享同一 Redis DB/实例。
- Celery Redis visibility_timeout 高于允许的最长执行窗口，并对所有 Worker 保持一致；长任务应拆分/续租，不以无限增大 timeout 代替任务设计。

### 3.5 对象存储

| 候选 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|
| MinIO Community | 曾广泛用于本地 S3 兼容开发 | 上游 minio/minio 仓库于 2026-04-25 归档并标记不再维护；AGPLv3 也需评估 | **不选** |
| SeaweedFS | Apache-2.0；提供 S3 API；可单机 mini 模式本地运行，也可扩展 | 运维概念比单容器对象存储多；生产部署需单独做容量、备份和恢复验证 | **本地开发选用** |
| Garage | S3 兼容，适合小规模分布式部署 | AGPLv3；部分 S3 语义能力与 AWS S3 不完全一致 | 不选 |
| 云厂商托管 S3 兼容存储 | 运维、持久性和扩展性由云服务承担 | 费用、区域、合规和供应商锁定需评估 | **生产优先，供应商待区域确认** |

决定：应用只依赖 S3 API 与 boto3，不依赖特定对象存储厂商 SDK。开发环境用 SeaweedFS mini；生产优先选目标部署区域的托管 S3 兼容对象存储。图片原图不可覆盖，编辑结果写入新 Object Key；数据库记录 key、SHA-256、MIME、尺寸、来源、版本、权限和保留策略。通过短时签名 URL 上传/下载，禁止把对象存储密钥下发浏览器。

### 3.6 身份认证、Session 与门店授权

| 候选 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|
| 应用内 Identity + 服务端 Session + OIDC 标准接入 | StoreUser 与门店授权模型可直接贴合产品；不绑定特定 SaaS；会话可撤销 | 必须严谨实现密码、Session、CSRF、轮换、限流和审计 | **首期选用** |
| Keycloak | 完整 OIDC/OAuth2、MFA、用户管理和管理界面 | 额外部署与升级负担；首期身份需求较简单 | 后续企业身份需求候选 |
| Auth0 / Clerk 等托管身份服务 | 上线快，安全能力和运营功能丰富 | 区域可用性、费用、数据驻留和供应商依赖未确定 | 部署区域确定后评估 |

首期由 Identity 模块管理 User、StoreUser、Session。密码使用 Argon2id；会话采用高熵随机不透明 Token，Cookie 设置 HttpOnly、Secure、SameSite=Lax，服务端只保存 Token verifier/hash，支持撤销、过期、轮换和审计。所有写操作实施 CSRF 防护；登录、重置流程和敏感操作限流。不得将认证 Token 存入 localStorage。OIDC 预留标准接入点，企业 SSO 需求明确后再接入 OIDC Provider。

**安全约束：** store_id 不是权限凭据。每次 API 请求都从已认证用户和 StoreUser 关系解析可访问门店，服务端校验资源归属。密码哈希参数按 OWASP 当前建议配置并定期复核。此模块必须在 Issue #5 进行安全专项审查，不得仅以“能登录”作为验收。

### 3.7 测试工具

| 层次 | 候选 | 决策 |
|---|---|---|
| 前端单元/组件 | Vitest + React Testing Library；Jest 作为替代 | Vitest，与 Vite 配置共享，选用 |
| 浏览器 E2E | Playwright；Cypress 作为替代 | Playwright，跨 Chromium/Firefox/WebKit，选用 |
| 后端单元/API | pytest + HTTPX；unittest 作为替代 | pytest + HTTPX，选用 |
| 数据库集成 | PostgreSQL 容器 + Alembic migration test | 使用真实 PostgreSQL，不用 SQLite 冒充生产数据库行为 |
| 契约 | OpenAPI schema lint + 生成 TypeScript client | 选用 |
| 视觉回归 | Playwright screenshot baseline | 首期建立关键页面基线；更新需人工审阅 |

PR 必须执行：格式化检查、Lint、类型检查、单元/组件测试、后端测试、前端构建、OpenAPI 生成一致性检查；核心流程 Playwright smoke suite 必须运行。不得用 mock 测试替代数据库集成测试或真实 Provider 联调。

### 3.8 部署、CI 与环境管理

| 候选 | 优点 | 代价 / 风险 | 结论 |
|---|---|---|---|
| Docker Compose | 本地依赖一键启动；开发/CI 环境可复现；适合 API + Worker 模块化单体 | 不提供生产级调度、弹性伸缩与高可用 | **本地开发选用** |
| Kubernetes | 弹性调度、声明式部署和生态完善 | 集群、网络、存储、监控与运维复杂度高 | 首期不选 |
| 单台 VM + Docker | 成本低、运维简单 | 单点故障；需自行备份、监控、升级与恢复 | 小规模试运行备选 |
| 云托管容器服务 | 容器运行、扩缩容与基础设施托管 | 供应商和区域绑定；价格需按负载评估 | **生产部署优先评估** |

CI 使用 GitHub Actions。所有服务构建 OCI 镜像；开发使用 Docker Compose 启动 PostgreSQL、Redis、SeaweedFS、API、Worker 和 Web。生产运行环境暂不锁定：需要先确认部署国家/区域、数据驻留要求、预算、流量和团队运维能力，再在托管容器服务与 VM 方案中做成本/可用性决策。禁止在这些条件不明时擅自选定云厂商或地域。

环境分为 local / test / staging / production。配置由环境变量注入，提交 .env.example 不提交 Secret；生产 Secret 使用云 Secret Manager 或等价服务。数据库迁移在部署流水线中执行，需有备份和回滚/前向修复策略。

### 3.9 日志、追踪、监控与错误追踪

- 应用日志输出 JSON，统一 request_id、trace_id、store_id（仅内部安全日志）、actor_id、job_id；严禁记录密码、Cookie、Token、API Key、完整敏感提示词或未脱敏用户数据。
- 使用 OpenTelemetry SDK 与 OTLP 统一导出 Trace / Metrics；本地可使用轻量 Collector/Console exporter。
- 健康检查分为 /health/live（进程存活）和 /health/ready（数据库、Broker、对象存储等关键依赖就绪）。
- 错误追踪供应商（Sentry 或自托管方案）暂不锁定；先定义统一接口和脱敏规则，部署区域确定后评估。
- 首期不部署完整 ELK、Kafka、Prometheus/Grafana 集群；达到日志/指标规模后再按真实需求补齐。

## 4. 首期工程结构建议

    /
    ├── apps/
    │   ├── web/                 # React + Vite 门店端/平台管理端
    │   ├── api/                 # FastAPI 模块化单体
    │   └── worker/              # Worker 启动入口，复用 api 领域模块
    ├── packages/
    │   ├── api-client/          # OpenAPI 生成的 TS client/types
    │   └── ui/                  # 与 Demo 对齐的共享 UI primitives
    ├── infra/
    │   ├── compose/             # 本地 Docker Compose
    │   └── containers/          # Dockerfiles
    ├── docs/
    ├── scripts/
    ├── .github/workflows/
    ├── Makefile
    └── pnpm-workspace.yaml

Python API 与 Worker 共享一个 Python workspace/package，Worker 不是另一个业务微服务。领域代码建议按模块组织：identity_store、store_knowledge、marketing_orchestrator、strategy_opportunity、content_studio、media_studio、quality_assurance、channel_integration、publishing、performance_attribution、platform_admin、job_runtime。

每个模块按 api / application / domain / infrastructure 分层；模块间只通过应用服务接口或领域事件通信。Web 只能调用 API，不能直接连接 PostgreSQL、Redis、对象存储或模型供应商。

## 5. 不采纳项与明确边界

- 不采用微服务群：当前模块共享强一致领域状态，微服务会提前引入分布式事务与部署治理成本。
- 不采用 n8n 作为核心流程引擎：营销流程固定，状态机与审核门槛由领域代码负责。
- 不强制引入 ComfyUI：图片能力通过 ImageProvider；只有复杂节点式图像生产流程、可视化模型编排和自托管 GPU 成本收益明确时才评估。
- 不把 Redis 当数据库：Job、审计、版本、审核和业务状态必须持久化在 PostgreSQL。
- 不把 MinIO Community 作为默认方案：上游仓库已归档，不再维护；本地改用 SeaweedFS。
- 不把浏览器自动化当官方渠道 API 的替代品：渠道能力必须按平台授权范围逐项验证，发布始终保留商家确认。

## 6. 待决项（不阻塞工程骨架）

| 待决事项 | 现在不锁定的原因 | 前置条件 |
|---|---|---|
| 生产云厂商与地域 | 未确认数据驻留、预算、合规和目标客户地域 | 用户确认部署区域、预算与可接受运维方式 |
| 生产对象存储供应商 | 取决于云厂商/区域和数据生命周期成本 | 云部署选型完成；验证签名 URL、跨域、生命周期和恢复 |
| OIDC / 企业 SSO 供应商 | 首期身份模型可独立实现；企业 SSO 需求未明确 | 确认首批客户是否要求企业身份联邦 |
| 错误追踪 SaaS | 区域可用性、数据驻留与费用未知 | 云区域和脱敏策略确定 |
| 图像推理运行方式 | 取决于 Provider、模型许可、GPU 成本与并发 | 完成真实 ImageProvider POC 和成本测试 |
| 渠道 API 接入顺序 | 受平台主体资质、授权 scope、审核和地区政策影响 | 每个平台逐项完成准入与能力核验 |

## 7. 版本策略

- Node.js：26.x Active LTS；禁止使用 Alpha/Current 作为生产基线。
- React：19.3.x；Vite：8.3.x；TypeScript：6.0.x；React Router：7.x；TanStack Query：5.x。
- Python：3.13.x；FastAPI：0.156.x；Pydantic：2.14.x；SQLAlchemy：2.0.x；Celery：5.7.x。
- PostgreSQL：18.x；Redis：8.2 LTS。
- Playwright：1.65.x 起；其余测试工具锁定当前稳定版。
- 以上是选型兼容范围，不是允许自动浮动的生产依赖。工程骨架建立时生成并提交 pnpm-lock.yaml、uv.lock、容器镜像版本记录；CI 使用 lockfile 安装。补丁版本按安全策略更新，次版本更新必须跑完整 CI；主版本更新需 ADR。

## 8. 技术架构文档同步清单

1. 更新 docs/TECHNICAL_ARCHITECTURE.md：将本地对象存储从 MinIO 改为 SeaweedFS；明确 Celery + Redis Broker 与 PostgreSQL Job/Outbox 的职责分离；补充 Session 安全边界和 OpenAPI 类型生成。
2. README 增加技术选型文档链接和“当前为目标选型、非生产已部署”的状态说明。
3. Issue #4 按本文件建立工程目录、依赖和 Compose，不得另行选框架。
4. Issue #5 按本文件实现服务端 Identity / StoreUser / Session 和门店授权；认证与权限必须专项安全审查。
5. Issue #9 按本文件实现 Job / Outbox / Celery Worker；不得仅依赖 Celery result backend。

## 9. ADR 记录

### ADR-001：采用 React SPA + FastAPI 模块化单体
- 日期：2026-11-11；状态：已由项目负责人确认。
- 决策：React + Vite 负责交互工作台；FastAPI 承载模块化业务 API；Worker 与 API 共用 Python 领域包，独立进程运行。
- 原因：符合登录后高交互工作台形态；复用 IterWave 已有 Python 执行经验；降低跨语言和微服务运维成本。
- 放弃方案：Next.js SSR、NestJS 全栈、Django 全栈。
- 影响：前后端分离部署；API 契约由 OpenAPI 维护；领域规则只能在服务端实现。

### ADR-002：PostgreSQL 为业务事实主库，Celery/Redis 只承担异步投递
- 日期：2026-11-11；状态：已由项目负责人确认。
- 决策：PostgreSQL 保存业务、Job、Attempt、Outbox 和审计；Celery/Redis 执行异步消息投递。
- 原因：任务状态可审计、可恢复；Broker 故障不导致业务状态丢失。
- 放弃方案：Redis-only job state、RQ、Dramatiq。
- 影响：需要 Outbox Relay、Sweeper、幂等和 Worker 恢复机制。

### ADR-003：本地对象存储改用 SeaweedFS，不使用已归档的 MinIO Community
- 日期：2026-11-11；状态：已由项目负责人确认。
- 决策：本地 SeaweedFS S3 API；生产采用经区域和成本评估的托管 S3 兼容服务。
- 原因：MinIO Community 上游仓库已归档；SeaweedFS 使用 Apache-2.0 并提供 S3 API。
- 影响：应用通过 boto3/S3 API 访问，禁止耦合厂商 SDK。

## 10. 参考资料与核验来源

以下为 2026-11-11 选型核验时查阅的官方或上游资料；工程建立时必须再次核验并锁定版本。

- React 版本与发布记录：https://react.dev/versions
- Vite 支持版本与发布策略：https://vite.dev/releases
- React Router 升级与兼容策略：https://reactrouter.com/upgrading/v7
- TypeScript 6.0 发布说明：https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/
- Node.js 官方 LTS 时间表：https://github.com/nodejs/Release
- FastAPI 发布说明：https://fastapi.tiangolo.com/release-notes/
- Python 版本发布列表：https://www.python.org/doc/versions/
- SQLAlchemy 版本状态：https://www.sqlalchemy.org/download.html
- Celery Broker 支持矩阵：https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/
- Celery Redis Transport 说明：https://docs.celeryq.dev/projects/kombu/en/latest/reference/kombu.transport.redis.html
- PostgreSQL 版本支持策略：https://www.postgresql.org/support/versioning/
- Redis OSS 版本支持策略：https://redis.io/docs/latest/operate/oss_and_stack/install/version-mgmt/
- SeaweedFS 上游与许可证：https://github.com/seaweedfs/seaweedfs
- MinIO Community 上游归档说明：https://github.com/minio/minio
- OWASP Password Storage Cheat Sheet：https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- OWASP Session Management Cheat Sheet：https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- Playwright：https://playwright.dev/
- GitHub Actions：https://docs.github.com/actions

---

**最终状态：** 首期技术栈已由项目负责人于 2026-11-11 确认，作为工程骨架和后续实现的唯一技术选型依据；任何替换必须通过 ADR 和项目宪法规定的重大决策流程。
