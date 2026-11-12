# AI 门店运营官

AI 门店运营官是面向线下门店的 AI 营销执行平台：商家按需提出经营目标，AI 协助完成策略、文案、图片、渠道适配与发布准备，并在数据可用后评估经营效果。

## 项目宪法与产品基线

本仓库的长期协作规则以 **[AI 门店运营官项目宪法](docs/PROJECT_CONSTITUTION.md)** 为准。所有 AI 和开发人员在开展工作前必须阅读宪法及相关基线文档；严格控制产品范围，按批准的 Demo 和业务流程实现，并以真实测试证据验收。

本仓库以 **[产品设计基线 v1.8](docs/PRODUCT_DESIGN.md)** 为唯一产品范围与业务规则来源。

- [项目宪法](docs/PROJECT_CONSTITUTION.md)：长期产品边界、文档优先、Demo 对齐、业务流程、工程质量门禁与变更纪律。
- [产品设计基线 v1.8](docs/PRODUCT_DESIGN.md)：定位、业务边界、信息架构、核心流程与生产能力要求。
- [UI/UX 审查与整改基线 v1.8](docs/UX_AUDIT_AND_REDESIGN.md)：交互原则、体验问题、整改要求与验证边界。
- [Demo 验收矩阵 v1.8](docs/DEMO_ACCEPTANCE_MATRIX.md)：逐项实现状态、静态证据、浏览器验收状态及生产缺口。
- [IterWave 可复用能力审查与整合方案](docs/REUSABLE_CAPABILITIES_FROM_ITERWAVE.md)：跨仓库能力审查、可复用技术底座、产品边界裁剪与 P0–P2 整合路线。
- [技术架构与服务拆分方案](docs/TECHNICAL_ARCHITECTURE.md)：模块化单体决策、业务模块边界、异步任务架构、数据/AI/渠道边界及渐进式微服务拆分路线。
- [首期技术选型决策](docs/TECH_STACK_SELECTION.md)：已由项目负责人确认的前后端、数据库、队列、对象存储、认证、测试、部署与版本基线。
- [开发计划与阶段门禁](docs/DEVELOPMENT_PLAN.md)：Issue 阶段映射、并行契约所有权、P0 最小上线子集与统一 DoD。
- [身份与门店安全设计](docs/IDENTITY_STORE_SECURITY_DESIGN.md)：User、Store、StoreMembership、Session、授权上下文和 IDOR 安全矩阵。
- [门店经营资料领域设计](docs/STORE_KNOWLEDGE_DOMAIN_DESIGN.md)：门店档案、商品/活动、品牌、客群、知识、素材资产及事实版本规则。
- [身份与门店 API 契约](docs/API_CONTRACT_IDENTITY_STORE.md)：Cookie Session、CSRF、X-Store-ID 请求上下文、成员管理 API 与错误语义。
- [身份与门店安全测试矩阵](docs/SECURITY_TEST_MATRIX_IDENTITY_STORE.md)：认证、Session 撤销、跨店 IDOR、Worker、文件和多标签页隔离测试。
- [跨领域集成契约 v1](docs/DOMAIN_INTEGRATION_CONTRACTS_V1.md)：#5–#10 实体字段、API、事件、状态、错误和跨域验收契约。
- [内容生产与发布交付领域设计](docs/CONTENT_DELIVERY_DOMAIN_DESIGN.md)：Issue #8 文案/图片产物、版本审核、渠道适配、质检、多渠道发布包与最终确认契约。
- [AI Provider 与 Prompt 版本领域设计](docs/AI_PROVIDER_PROMPT_DOMAIN_DESIGN.md)：Issue #10 文本/图片/Vision/OCR Provider Adapter、平台级 Prompt 版本、输入事实安全与调用审计契约。
- [渠道账号与官方发布集成领域设计](docs/CHANNEL_INTEGRATION_DOMAIN_DESIGN.md)：Issue #12 官方 OAuth、ChannelSpec/Capability、ChannelAdapter、PublishOperation、幂等与外部结果核验契约。
- [阶段 5 首个渠道候选平台核验](docs/CHANNEL_PLATFORM_PILOT_EVALUATION.md)：抖音/快手/小红书/视频号官方能力初筛、草稿与发布核验差距及项目负责人选择门禁。
- [热点采集与门店营销机会领域设计](docs/HOT_TOPIC_OPPORTUNITY_DOMAIN_DESIGN.md)：Issue #11 来源证据、去重、StoreOpportunity、门店事实匹配、决策记录与 IterWave 复用映射。
- [经营效果、作品归属与归因证据领域设计](docs/EFFECT_EVIDENCE_ATTRIBUTION_DOMAIN_DESIGN.md)：Issue #13 指标分层、作品核验、观察窗口、经营结果证据与归因可信度契约。
- [B/C/D 跨领域契约审查记录](docs/DOMAIN_CONTRACT_REVIEW_LOG.md)：已统一的责任边界、冲突修正、待决项和联合验收场景。 
- [核心数据模型、API Schema 与事件 Schema v1](docs/CORE_DATA_MODEL_AND_API_SCHEMAS_V1.md)：跨域逻辑 ERD、数据库约束、API 请求/响应示例、事件 Envelope 与实现前门禁。

三份文档统一采用 v1.8 作为产品基线版本。修订日期和代码提交用于追踪变更，不另行形成产品版本。历史轮次记录不再作为现行验收依据；如历史结论与当前矩阵冲突，以产品基线和最新验收矩阵为准。

## Demo 结构

入口：`demo/index.html`

- `demo/index.html`：应用入口
- `demo/styles.css`：设计系统与响应式样式
- `demo/data.js`：演示种子数据
- `demo/store.js`：本地状态、持久化与迁移
- `demo/app.js`：门店端路由、页面编排与交互
- `demo/task-renderers.js`：营销任务步骤渲染、状态计算与本地质检规则
- `demo/effect-renderers.js`：经营效果页面渲染
- `demo/store-renderers.js`：门店资料页面渲染
- `demo/admin.js`：平台管理端页面与操作

## 本地运行

在仓库根目录执行：

```bash
python -m http.server 8080
```

浏览器访问：

```text
http://localhost:8080/demo/
```

请通过 HTTP 服务运行，不要直接双击 HTML 文件。

## 当前 Demo 覆盖范围

**门店端**
- AI 营销：按需制作、热点机会、需求理解、策略确认、文案审核、图片审核、渠道适配、质检和发布确认。
- 营销任务：任务列表、执行状态、审核与整改记录、发布状态。
- 账号运营监测：账号状态、已发布作品登记、任务/冻结内容包关联与归属核验状态。
- 经营效果：独立展示内容表现和经营数据；没有真实数据时显示空状态或明确标记的演示样例。
- 门店资料：门店档案、商品与服务、活动优惠、品牌规范、客群经营、知识库、素材库和渠道账号。

**平台管理端**
- 运营总览、门店列表与详情、门店用户、门店级模型配置、AI 运行监控、业态提示词、用量成本、审计日志和系统配置。
- 管理端不负责门店营销制作、门店经营资料维护或营销效果运营。

## Demo 与生产系统边界

仓库同时维护 **产品交互 Demo** 与 **生产系统代码**，两者用途不同：

- `demo/` 是产品页面结构、导航、交互和状态反馈的基准；本地数据与模拟结果仅用于演示。
- `apps/` 等生产工程代码承载 Web、API、Worker、数据库迁移、AI Provider 和渠道集成等真实服务能力。具体模块以仓库当前目录和代码为准。
- 代码已实现、自动化测试通过、真实外部服务验收通过是三个不同状态。不得把 Mock、静态检查或 CI 通过表述为真实模型调用、真实平台发布或真实经营数据验证。

### 产品范围

**纳入范围**
- 门店身份认证、Session、成员关系和服务端门店数据授权。
- 门店经营资料、商品/服务、活动优惠、品牌规范、客群、知识和素材管理。
- 按需营销任务：需求与策略确认、文案和图片产物、独立审核、渠道适配、质检、发布包冻结及商家最终确认。
- AI 文本生成、图片生成/编辑和视觉质检，通过 Provider 抽象接入；视频脚本仅为普通文本产物。
- 热点/营销机会发现，以及独立的经营效果指标与分析工作区。
- 首期渠道为抖音图片图文；是否可真实授权、发布和读回，以官方应用权限及真机验收结果为准。

**明确不做**
- 视频生成、图生视频、剪辑、合成、渲染、转码、视频上传、视频草稿或视频发布。
- ERP、CRM、POS、广告投放/预算管理和通用工作流编排平台。
- 不以本地模拟数据冒充真实热点、模型结果、平台指标或经营结果。

### 关键真实性约束

| 能力 | 对外说明 |
|---|---|
| AI 文本/图片/视觉能力 | 已建设 Provider 生产代码；真实密钥、模型可用性和输出质量仍需真实环境验收 |
| 营销任务与内容交付 | 已建设任务、产物版本、文案/图片双审核、渠道适配、质检、发布包和最终确认等服务流程；具体验收状态以对应 Issue/CI 为准 |
| 抖音渠道 | 已建设 OAuth、账号与图片图文发布相关代码；真实应用授权、权限、发布和作品读回仍需真机验收 |
| 热点与经营效果 | 正在代码补全工作中；真实平台指标和经营数据接入另行验收 |
| 经营结果/ROI | 没有可追溯的订单、到店或核销证据时必须显示暂无数据，不输出虚构增长或 ROI |
| 浏览器体验 | Demo 与生产 Web 的页面/交互验收须有真实浏览器证据；静态检查和 Mock 测试不能替代 |

## 验收状态

项目已进入生产代码补全与集成阶段。2026-11-12 的代码补全任务已拆分为三个独立 Issue；真实 AI 服务、抖音图片图文发布和真实经营数据联调集中跟踪。当前不能据此宣称产品已完成生产验收或可直接正式上线。

截至本次 README 更新，公开跟踪的剩余工作为：
- [Issue #135：核心业务流程、安全隔离与生产质量门禁收尾](https://github.com/dujiu1024-dotcom/Smart-Marketing/issues/135)——代码补全 1/3；以 PR 合并及 CI 证据为完成门槛，人工 Demo/无障碍验收另计。
- [Issue #136：AI 文本与图片生产 Provider、Prompt 和视觉质检](https://github.com/dujiu1024-dotcom/Smart-Marketing/issues/136)——代码补全 2/3；实现 PR 已合并、主干 CI 通过，真实模型调用与效果验收转入真机测试。
- [Issue #137：热点营销机会与经营效果指标分析工作区](https://github.com/dujiu1024-dotcom/Smart-Marketing/issues/137)——代码补全 3/3；继续补齐可在工程环境完成的代码、迁移、页面和自动化测试。
- [Issue #138：真实 AI 服务、抖音图片图文发布与经营数据联调验收](https://github.com/dujiu1024-dotcom/Smart-Marketing/issues/138)——真实账号、密钥、官方权限及经营数据的真机验收，不与代码开发混为一谈。

Demo 浏览器验收、生产 Web 端到端验收、人工无障碍检查和部署环境验证均须按真实证据单独记录。详细状态、验证范围和待办以 [Demo 验收矩阵 v1.8](docs/DEMO_ACCEPTANCE_MATRIX.md)、对应 Issue 和 CI 记录为准。

- [异步任务运行时与 AI Gateway 契约](docs/ASYNC_JOB_RUNTIME_AND_AI_GATEWAY_CONTRACT.md)：Issue #9 的 PostgreSQL Job/Outbox、Celery Worker、租约/重试/恢复及 AI Provider 接口设计。
- [异步运行时与身份/营销领域集成契约](docs/ASYNC_RUNTIME_DOMAIN_INTEGRATION_CONTRACT.md)：对齐 Issue #5/#7/#9 的请求级门店授权、Worker 执行边界、Job 状态和幂等键。
