# AI 门店运营官开发计划

> 版本：1.0  
> 日期：2026-11-11  
> 产品基线：v1.8  
> 仓库：dujiu1024-dotcom/Smart-Marketing  
> 状态：执行基线；阶段完成以 Issue 验收证据为准

## 1. 目标与约束

本计划将产品、UX、架构和技术选型基线映射为可验收的开发阶段。产品定位为「AI 门店运营官」，采用按需制作、完整营销执行官模式，以可验证经营效果为长期壁垒。

强制依据：
- `docs/PROJECT_CONSTITUTION.md`
- `docs/PRODUCT_DESIGN.md`（v1.8）
- `docs/UX_AUDIT_AND_REDESIGN.md`（v1.8）
- `docs/DEMO_ACCEPTANCE_MATRIX.md`（v1.8）
- `docs/TECHNICAL_ARCHITECTURE.md`
- `docs/TECH_STACK_SELECTION.md`
- `docs/IDENTITY_STORE_SECURITY_DESIGN.md`
- `docs/DOMAIN_INTEGRATION_CONTRACTS_V1.md`
- `docs/DOMAIN_CONTRACT_REVIEW_LOG.md`

不做 ERP、CRM、POS、广告投放/预算管理、通用工作流编排。固定营销流程由领域状态机控制；首期采用模块化单体 + 独立 Worker + Provider/Adapter，不拆业务微服务，不将 n8n 或 ComfyUI 设为硬依赖。

## 2. 阶段与 Issue 映射

| 阶段 | Issue | 优先级 | 目标 | 依赖/门禁 |
|---|---|---|---|---|
| Stage 0 产品基线 | #2 | P0 | Demo 全量浏览器验收、缺陷清单、产品/UX 基线冻结 | 后续生产开发门禁；口头确认不能代替证据 |
| Stage 1 工程基础 | #4、PR #16 | P0 | Web/API/Worker 工程骨架、CI、Compose、迁移和开发文档 | #3 技术选型；PR #16 是 #4 的实现切片，不独立替代 #4 |
| Stage 2 身份与经营资料 | #5、#6 | P0 | Session、StoreUser、服务端门店授权；门店资料/商品/活动/品牌/素材 | #4 验收后进入实现；#5 先于 #6 |
| Stage 3 营销领域与交付 | #7、#8 | P0 | 任务状态机、快照、版本依赖、文案/图片双审核、质检、发布包 | #5/#6；#7 先冻结业务状态与依赖契约，#8 消费该契约 |
| Stage 4 异步运行时与 AI | #9、#10 | P0 | PostgreSQL Job/Outbox、Celery Worker、AI Gateway、真实 Provider | #9 与 #8 并行契约设计；#10 依赖 Provider 契约 |
| Stage 5 外部能力 | #11、#12 | P1 | 热点来源与机会匹配；首个真实渠道授权/草稿/发布核验 | #11 依赖 #5/#6/#7/#9；#12 依赖 #7/#8/#9/#10 |
| Stage 6 经营效果 | #13 | P2 | 指标证据、观察窗口、归因可信度 | #6/#8/#10/#12 |
| Stage 7 上线门禁 | #14 | P0 持续门禁 | 安全、恢复、监控、备份、回滚和端到端验收 | 覆盖实际交付能力；任何生产上线前必须通过 |

## 3. P0 核心上线最小子集

生产试点至少必须具备以下真实能力，缺一不可：
1. 身份认证、Session 生命周期、服务端 StoreUser 授权和跨门店 IDOR 防护（#5）。
2. 可信门店经营资料、关键事实确认、素材原图保护和版本追溯（#6）。
3. MarketingTask 状态机、需求/策略快照、版本依赖失效、并发/幂等和异常恢复（#7）。
4. 文案与图片独立审核、渠道内容、质检、冻结发布包和最终商家确认（#8）。
5. PostgreSQL 持久化 Job/Outbox、Worker 租约/重试/恢复及 AI Gateway 的安全调用基础（#9、#10）。
6. 可验证的首个真实渠道授权、草稿/发布结果核验；若不开放发布能力，必须明确标注产品限制并经负责人批准替代路径（#12）。
7. 日志脱敏、审计、备份恢复演练、监控告警、回滚和安全测试（#14）。

热点机会（#11）不是每次按需制作的必经节点。经营效果分析（#13）是发布后的独立能力，不是营销任务“完成”的前置条件。任何未接入真实 Provider、渠道或数据源的能力必须明确标记，不得用 Mock 伪装生产能力。

## 4. 并行与契约所有权

- #5 定义认证主体、Store、StoreUser、Session、当前门店上下文及授权错误语义；其他模块不得另建门店身份模型。
- #7 拥有 MarketingTask 生命周期、业务阶段、RequirementSnapshot、StrategySnapshot、ArtifactVersion 依赖指纹和业务领域事件的定义权。
- #8 拥有 Copy/Image Artifact、ReviewRecord、ChannelContent、QualityReport、PublishPackage 与 PublishConfirmation 的内容交付契约；必须消费 #7 的任务/版本契约，不重复定义任务状态。
- #9 拥有 Job、JobAttempt、OutboxEvent、租约、重试和执行事件契约；业务域只提交明确的 Job command，不自行维护 Worker 状态。
- #10 拥有 TextProvider、ImageProvider、Vision/OCR Provider 及 AIInvocation/成本审计契约；不得让领域模块直接依赖厂商 SDK。
- #8 与 #9 可并行设计：#8 定义业务动作及所需异步能力，#9 定义执行基础设施；双方通过版本化 JobType/command schema 和结果事件对齐。#9 不拥有营销业务状态，#8 不实现第二套队列。
- #11/#12/#13 均消费上述已冻结契约，不得反向侵入核心状态机。

## 5. 领域契约基线

#5–#10 的跨域实体、字段、API、事件、状态枚举和错误语义统一以 `docs/DOMAIN_INTEGRATION_CONTRACTS_V1.md` 为评审入口；身份域细节以 `docs/IDENTITY_STORE_SECURITY_DESIGN.md` 为准，营销任务状态机以 `docs/MARKETING_TASK_DOMAIN_DESIGN.md` 为准。上述文档目前均为设计提案，只有完成 B/C/D 联合评审并记录决议后才视为冻结契约。

## 6. 统一交付定义（DoD）

每个 Issue 完成前必须逐项勾选：
- [ ] 范围、非目标、Demo 页面/路由和相关状态已明确。
- [ ] 数据实体、字段、约束、索引、归属和迁移已评审（涉及数据时）。
- [ ] API/事件/Provider 契约及错误语义已评审（涉及接口时）。
- [ ] 实现与产品/UX/Demo 基线一致，无静态假交互或 Mock 冒充真实交付。
- [ ] 单元、集成、契约、安全或 E2E 测试按风险执行；列出精确命令和结果。
- [ ] 构建、Lint、类型检查和 CI 结果已记录；未执行项明确标记。
- [ ] 异常、重试、幂等、并发、权限和恢复路径按适用范围验证。
- [ ] 相关文档、API Schema、Demo 验收矩阵和变更记录已同步。
- [ ] 浏览器验收附真实截图/录屏或可复现步骤；静态检查不能替代浏览器证据。
- [ ] Issue 说明交付内容、测试证据、未完成项、风险和后续 Issue。

建议测试命令以仓库 Makefile 为统一入口；提交前至少核对 `make help`（若存在）、`make test`、`make lint`、`make typecheck`、`make build` 和对应服务的专项测试。若命令尚未实现，应在该 Issue 中补齐并记录实际命令，禁止声称未执行的测试已通过。

## 7. 当前状态解释

- Issue 状态、PR 状态和验收状态是不同事实。PR 合并不自动关闭所有相关 Issue；Issue 关闭必须有对应验收证据。
- Stage 0 只有在浏览器验收报告、缺陷清单、矩阵更新和基线证据入库后才可关闭 #2。
- PR #16 覆盖 #4 的工程骨架切片；其正文已明确未交付/未验证项。#4 保持为总体验收 Issue，直至锁文件、干净环境启动、迁移往返、Playwright E2E、日志脱敏等验收项有证据。
- #14 是生产上线持续门禁，不意味着可以等到最后才做安全和恢复设计。
- 本计划仅描述计划与门禁，不宣称任何未验证能力已经完成。
