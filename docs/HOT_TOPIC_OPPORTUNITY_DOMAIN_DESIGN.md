# 阶段 5 热点采集与门店营销机会领域设计（Issue #11）

> 状态：设计准备 / 实施门禁待解除  
> 日期：2026-11-11  
> 产品基线：PRODUCT_DESIGN.md v1.8  
> Demo 基线：DEMO_ROUTE_STATE_MAP.md

## 1. 目标与边界

为首页「AI 推荐营销」提供真实、可追溯、按门店上下文匹配的机会发现能力。热点只是机会来源之一；商家始终可以绕过热点，直接按需制作营销任务。

本领域拥有公共热点来源采集、原始证据、规范化热点、门店机会匹配结果，以及门店对机会的采纳/忽略/暂缓决策。它不拥有门店经营事实、营销任务状态、Job 执行状态或最终营销策略。

明确不做：
- 不增加独立热点运营后台或复杂选题/排期系统。
- 不把热点设为每个营销任务的必经步骤。
- 不把模型摘要、推测热度或演示数据伪装为原始来源事实。
- 不复制 #6 的 Store/Product/Offer/Audience/Brand 事实，不复制 #7 的 MarketingTask/StrategySnapshot，不复制 #9 的 Job/Outbox。
- 不采集需要登录、绕过验证码、绕过访问限制或违反来源条款的数据。D-01 已决策为路径 A（商家授权抓取），该路径只适用于**商家本人账号的账号/作品指标**，不适用于公共热点采集；热点采集仍只允许公开来源、条款已登记且域名在白名单内的通道。决策与边界见 `docs/FRAMEWORK_SELECTION_AND_REUSE.md` §2.4，真实性档定义见 `docs/EFFECT_EVIDENCE_ATTRIBUTION_DOMAIN_DESIGN.md` §4.4。
- 不因采纳热点自动创建任务；采纳仅作为用户意图与策略输入。

## 2. Demo 页面与交互映射

依据 `docs/DEMO_ROUTE_STATE_MAP.md`：

| Demo 路由 | 页面 | 生产职责 |
|---|---|---|
| `#ai` | AI 营销首页 | 展示少量、排序后的门店机会摘要和「按需制作」入口 |
| `#hotspots` | 发现营销机会 | 搜索、分类/状态筛选、来源/更新时间、机会列表 |
| `#hotspot-detail:<hotspotId>` | 热点机会详情 | 展示原始来源证据、门店匹配理由、适配商品/客群、风险、有效期；采纳/忽略/暂缓 |
| `#task` → strategy | 营销任务策略确认 | 展示用户已采纳的机会及来源引用；允许明确跳过并记录原因 |

生产 API 路由可以按后端规范命名，但必须维持以上页面职责、层级与交互。首页推荐是入口，不增加复杂导航。

## 3. 所有权与依赖

| 对象/能力 | 权威所有者 | #11 的使用方式 |
|---|---|---|
| User / Store / StoreMembership / AuthorizedStoreContext | #5 | 每次门店 API 从请求级上下文取得 store_id；不得信任客户端 store_id 授权 |
| StoreProfile / Product / Offer / BrandGuideline / AudienceProfile / KnowledgeItem | #6 | 只读取已确认且当前有效的门店事实；事实版本变更使匹配结果 stale |
| MarketingTask / RequirementSnapshot / StrategySnapshot / TaskEvent | #7 | 用户采纳机会后，将不可变来源引用交给任务创建/策略确认流程；不推进任务状态 |
| Job / Attempt / Outbox / lease / retry | #9 | 采集、匹配走持久化 Job；不使用请求线程、进程内线程锁或自建队列 |
| AIInvocation / Provider / PromptVersion | #9/#10 | 语义匹配使用 AI Gateway；固定 prompt/model/schema 版本并保留调用审计 |
| HotTopicSource / HotTopic / StoreOpportunity / OpportunityDecision | #11 | 本领域唯一所有者 |

依赖 #5、#6、#7、#9。当前这些 Issue 均仍为 Open，虽然相关基础切片已合并，但不可将其整体 DoD 视为完成。设计可先评审；生产联调必须等依赖接口稳定并经联合验收。

## 4. 领域模型

### 4.1 HotTopicSource（平台级来源配置）

建议字段：
- id、source_key、display_name、source_type（official_api/rss/public_feed/manual）
- endpoint_secret_ref（若来源需要凭证；不得保存明文）
- terms_url、permitted_use、attribution_template
- enabled、poll_interval_seconds、timeout_seconds、rate_limit_policy
- last_success_at、last_failure_at、health_status、created_at、updated_at

来源配置由平台运营侧维护；来源授权/条款和速率限制必须在启用前人工核实。不得将门店用户提交的任意 URL 直接作为服务端抓取目标。

**来源类型与多源支持：**
- `rss`：RSS / Atom 订阅，解析 `channel/item` 或 Atom `entry`。
- `public_feed`：公开热榜 JSON。复用 Easel 的热榜端点清单（Easel 仓库 `skills/shared/hotlist-apis.md` 的 60s API，如 `weibo`、`zhihu`、`douyin`、`baidu`、`bili`、`toutiao`、`rednote` 等）；后台登记表单以预设下拉提供这些端点，但仍必须通过 `terms_url` 登记、允许域名白名单与启用准入，不得绕过。
- 两类来源共用同一套采集、去重、过期与匹配流程；热榜条目的外部链接仅展示、不服务端请求，域名白名单约束的是采集目标本身。

### 4.2 HotTopic（跨门店共享的公共热点事实）

建议字段：
- id、source_id、source_item_id、canonical_url
- title、summary（明确标注模型/规则生成）、raw_excerpt、raw_payload_ref
- published_at（nullable）、discovered_at、last_seen_at、expires_at
- region、industry_tags、topic_tags
- heat_value（nullable）、heat_unit（来源定义）、rank_value（nullable）
- evidence_status（collected/partial/failed/unverified/expired）
- source_fingerprint、content_fingerprint、normalization_version
- created_at、updated_at

规则：
- 共享池仅保存公开热点及其必要证据；不得混入门店私有资料。
- 原始来源 URL、发布时间、采集时间和授权/使用限制可追溯；无法取得发布时间时为 NULL。
- heat_value 未取得或解析失败时为 NULL，不得填 0；不同来源热度单位不可直接比较。
- 原文/摘要与模型生成解释分字段保存，展示时标明来源和生成属性。
- 原始响应仅在来源条款允许时保存；否则只存最小必要字段和不可逆指纹。
- 去重后仍保留 SourceEvidence，不能因合并热点而丢失多来源出处。

### 4.3 StoreOpportunity（门店级匹配快照）

建议字段：
- id、store_id、hot_topic_id
- store_context_fingerprint、matching_version、matching_algorithm_version、prompt_version_id（nullable）
- relevance_score（nullable）、match_method（rules/semantic/hybrid/manual）
- matched_product_ids、matched_offer_ids、matched_audience_profile_ids
- suggested_scenario、content_angle、reason_summary
- risk_flags、eligibility_status（eligible/review_required/ineligible/unassessed）
- matched_at、expires_at、stale_at、created_at

每条机会必须绑定门店与门店事实指纹。机会详情只能在当前 AuthorizedStoreContext 内访问；不得通过猜测 opportunity_id 或 hot_topic_id 跨店读取门店匹配解释。

### 4.4 OpportunityDecision（追加式用户决策）

建议字段：
- id、store_id、opportunity_id、actor_user_id
- decision（adopt/ignore/snooze）、reason（nullable）
- opportunity_fingerprint、created_at

决策记录 append-only；同一用户重复提交由幂等键处理。最新决策用于当前列表状态，历史决策保留审计。采纳必须校验机会未过期、未失效且 eligibility_status 允许；review_required 只能进入人工确认，不得静默视为可用。

## 5. 采集、去重与时效

### 5.1 采集流程

1. Job Runtime 按来源调度或响应手动刷新命令。
2. Source Adapter 访问已批准来源，执行 SSRF 防护、DNS/IP 校验、重定向限制、响应大小限制、超时和速率限制；来源清单与响应解析实现优先复用 Easel（`docs/FRAMEWORK_SELECTION_AND_REUSE.md` §2.3），来源准入规则不变。
3. 将响应解析为统一 SourceEvidence/HotTopic 输入；保留 source_item_id、canonical_url、published_at 与原始来源证据。
4. 以 source_id + source_item_id 建立来源级幂等；无稳定 ID 时使用规范化 URL + 内容指纹。
5. 执行标题规范化和相似事件候选合并；不因标题相似而覆盖来源证据。
6. 写入采集结果与 Job 关联审计；部分失败保留成功来源，不把整批标记为完全成功。
7. 触发匹配 Job；GET 列表/详情只读数据库，不同步抓取外部源。

### 5.2 去重规则

- 来源内唯一键：UNIQUE(source_id, source_item_id)；缺少 source_item_id 时使用唯一 fingerprint。
- 标题规范化：Unicode NFKC、大小写折叠、去空白与标点；规范化算法带版本。
- 跨来源事件聚类：在可配置时间窗内用规范化标题/相似度生成候选；自动合并阈值需离线样本评估，低置信度仅关联不合并。
- 聚类主记录保持稳定；每个来源证据独立保留。
- 过期策略基于来源发布时间/采集时间和行业时效配置；无发布时间时不得伪造。

### 5.3 并发与恢复

- Job 幂等范围按 #9 系统任务契约定义；来源级唯一约束阻止重复导入。
- 同一 source 同时最多一个有效采集 Job；以数据库约束/Job 幂等键保证，不用进程内 Lock。
- 采集请求超时、429、5xx 按 #9 retry policy 退避；来源永久拒绝/授权撤销时停止重试并标记 source health。
- 旧 Job 的迟到结果不能覆盖新快照；提交前检查 Job fencing/claim token，并通过事务校验。
- Worker 崩溃后由 #9 恢复；不创建第二套租约/重试状态机。

## 6. 门店匹配策略

匹配输入只允许使用 #6 已确认且有效的门店事实：
- 门店业态、主营商品/服务、有效活动/优惠。
- 已确认品牌定位、品牌禁用表达。
- 已确认客群画像、经营目标与可服务时段/产能约束。

匹配分层：
1. 硬规则过滤：过期、来源不可信、地区不匹配、禁用/高风险主题、与商品/活动事实冲突，结果为 ineligible 或 review_required。
2. 确定性特征：业态、商品、活动时间窗、客群、季节/节日、地域和门店经营目标。
3. AI 语义排序：仅对规则通过的候选调用 #10 Provider；输出结构化 JSON、理由和引用的事实 ID，不得创造价格、库存、优惠、门店地址或经营结论。
4. 结果校验：模型输出必须引用输入中存在的事实 ID；超出 Schema、引用不存在事实、事实冲突时降级为 unassessed/review_required。
5. 按门店事实 fingerprint + matching_version + matching_algorithm_version + prompt_version 缓存；任何相关事实修订、来源更新、匹配算法或 prompt 版本变化都使旧结果 stale。
6. 未配置真实 Provider 时只允许确定性规则结果，并明确展示“规则匹配”；不得用随机分数或静态演示样例伪装 AI 匹配。

relevance_score 为 NULL 表示尚未计算；0 仅表示真实计算后得出的零分。列表排序优先级为 eligibility、有效期、相关性和来源可信度，不能将不同来源的 heat_value 混合排序。

## 7. API 与事件契约草案

以下为领域契约提案，最终路径/Schema 以实现时 FastAPI OpenAPI 为准。

| Method | Path（提案） | 鉴权/语义 |
|---|---|---|
| GET | /api/v1/opportunities | 当前门店分页列表；支持 query/category/status；只读 |
| GET | /api/v1/opportunities/{id} | 当前门店详情；返回来源证据、匹配理由和风险 |
| POST | /api/v1/opportunities/{id}/decisions | adopt/ignore/snooze；actor-bound idempotency |
| POST | /api/v1/opportunities/refresh | 提交门店匹配/刷新请求，返回 Job 引用；不得同步抓取 |
| GET | /api/v1/hot-topics/{id}/evidence | 仅返回已允许公开的来源证据；不暴露内部 Secret/原始敏感响应 |

事件（提案）：
- hot_topic.collected.v1
- hot_topic.updated.v1
- store_opportunity.matched.v1
- store_opportunity.staled.v1
- store_opportunity.decision_recorded.v1

事件必须使用统一 Event Envelope、schema_version、occurred_at、aggregate_id、store_id（公共热点事件可为空）、correlation_id。跨域消费者幂等处理。

## 8. Demo 状态与产品交互要求

- 首页只显示少量机会摘要：一句话机会、适配门店理由、时效、来源/更新时间、风险提示。
- 发现页支持搜索、分类和状态筛选；详情页显示完整匹配证据。
- 采纳、忽略、暂缓必须有明确反馈并记录决策；过期/失效机会禁用采纳。
- 采纳机会后进入现有营销任务流程，用户可在策略确认中核对/修改；不能自动跳过需求确认、事实确认或发布审核。
- 没有可用热点时展示空态并保留按需制作入口。
- 未接入来源/演示样例明确标注“演示”；来源异常/过期显示最后更新时间与状态，不宣称实时。
- 不增加热点日历、账号组、排期或独立运营后台。

## 9. 复用 IterWave 的结论

已检查 `dujiu1024-dotcom/iterwave-content-ops` 的相关源码。可复用的是实现模式与领域无关逻辑，不应直接复制其 SQLite/账号组/进程内调度实现。

| 旧项目代码 | 已观察到的能力 | 本项目处理 |
|---|---|---|
| `src/core/hot_topics.py` | 多源采集、时间解析、证据状态、热度 NULL 语义、敏感主题过滤 | 按来源适配器重构；证据状态和 NULL 语义采纳 |
| `src/core/hot_topic_dedup.py` | NFKC 标题归一化、来源内去重、跨来源相似事件、保留策略 | 算法可移植并补测试；持久化唯一约束使用 PostgreSQL |
| `src/core/hot_topic_matcher.py` | 规则 + LLM 两级匹配、画像签名、prompt 版本、未研判 NULL | 改造为 StoreContext + StoreRecordRevision 指纹；经 #9/#10 AI Gateway |
| `src/core/hot_topic_service.py` | 采集后匹配、状态和进度反馈 | 只复用流程思路；替换进程内线程状态为 #9 Job/JobEvent |
| `src/core/hot_topic_collection_store.py` | source lease、fencing、快照事务提交 | 不迁移 SQLite lease；直接使用 #9 PostgreSQL Job fencing |
| `src/api/hot_sources.py` | 来源配置脱敏、测试历史和 URL redaction | 复用脱敏原则；来源配置属平台管理能力，权限另行确认 |
| `src/core/safe_http.py` | SSRF 防护、固定公网 IP、限制重定向/响应大小 | 复用安全设计并针对目标运行时审查 |
 
IterWave 仓库声明 Apache-2.0；复制或改写任何代码前仍须核查具体文件头、LICENSE/NOTICE 和依赖许可。当前文档审查不等于代码已迁移、构建通过或生产来源已验证。

## 10. 测试矩阵（实现前冻结）

- HOT-01 来源条款未审核不可启用；HOT-02 SSRF/private IP/重定向拦截；HOT-03 timeout/429/5xx 状态与退避。
- HOT-04 来源稳定 ID 幂等；HOT-05 URL/fingerprint 幂等；HOT-06 相似标题误合并保护；HOT-07 多来源证据保留。
- HOT-08 发布时间未知保持 NULL；HOT-09 热度未知保持 NULL；HOT-10 过期热点不展示为实时。
- HOT-11 同一来源并发采集唯一；HOT-12 旧 fencing token 不可提交；HOT-13 Worker 崩溃恢复。
- HOT-14 未认证/无门店成员拒绝；HOT-15 跨店 opportunity IDOR；HOT-16 门店切换上下文隔离。
- HOT-17 未确认门店事实不得作为匹配输入；HOT-18 事实 revision 变化使机会 stale；HOT-19 prompt/matching 版本变化使机会 stale。
- HOT-20 AI 输出事实 ID 校验；HOT-21 模型超时/非法 JSON 安全降级；HOT-22 高风险主题转人工/不可用。
- HOT-23 adopt/ignore/snooze actor-bound 幂等；HOT-24 过期机会不能采纳；HOT-25 采纳不会自动创建任务。
- HOT-26 GET 不触发外部采集；HOT-27 空态仍可按需制作；HOT-28 浏览器页面层级与 Demo 一致。

## 11. 当前阻塞与实施顺序

当前依赖状态（2026-11-11）：
- #5 Open：PR #36 身份实现需完成合并/验收；不可假设请求级授权已全面生效。
- #6 Open：PR #43/#49 已合并核心资料 API/幂等；MediaAsset 对象存储、上传/扫描等仍未完成。
- #7 Open：PR #52/#53 已合并任务核心模型与创建/查询 API；快照确认、步骤决策和异步 Handler 仍待完成。
- #9 Open：Job/Outbox 核心已合并；业务 Handler 接入、限流和故障注入仍待完成。
- #10 Open：Provider/Prompt 仅完成设计，真实 Provider 未选/未接入。

建议实施顺序：
1. 先合并本领域设计评审，冻结数据/API/事件/测试契约。
2. 选择并核验至少一个合法公开来源（来源条款、地区、频率、归属、展示署名）。
3. 等 #5/#6/#7/#9 最小可用接口与授权门禁通过后，新增 Migration 与只读列表/详情 API。
4. 接入 Job 采集 Handler、来源级幂等、证据持久化和可恢复执行。
5. 接入 #10 真实 Provider 后增加语义匹配；先上线规则匹配也必须明确标注，不得假称 AI。
6. 接入决策 API 与现有任务策略快照；最后完成浏览器验收和 Demo 矩阵更新。

## 12. 验收纪律

本 PR 若仅提交本设计文档，不代表 Issue #11 的生产功能完成。自动化测试、来源合规核验、真实采集、跨店安全、AI 匹配和浏览器 E2E 均须在实现 PR 中逐项记录实际命令与证据；未执行必须明确标注“未执行”。


## 13. Issue #137 implementation status (2026-11-12)

A first executable slice has been added on branch `feat/issue-137-hotspots-effects`:

- PostgreSQL migration `0018_opportunity_effects` and ORM models for sources, normalized topics, store matches, decisions and metric definitions/observations.
- Store-scoped opportunity list/detail/decision APIs; adoption is blocked for expired, stale, ineligible or review-required matches.
- Admin-only RSS source registration and explicit enablement. Feed and terms URLs must be HTTPS and use a host in `HOT_TOPIC_ALLOWED_HOSTS`; the Worker additionally rejects hosts resolving to non-public IP addresses and does not follow redirects.
- Collection/matching is enqueued through the existing #9 Job/Outbox runtime. The Worker normalizes RSS/Atom entries (including RFC 822 RSS and ISO 8601 Atom timestamps), retains source URL and publication time, deduplicates per source, expires stale entries, and applies explainable rule matching against confirmed store profile, industry, service region, product, offer, audience and brand guideline facts.
- Prohibited brand phrases and explicit topic/store region mismatches are surfaced as review risks. Matching scores describe text relevance only. They are not external heat scores, sales predictions or performance outcomes.
- After an explicit merchant adoption, the detail view offers a merchant-triggered “基于此机会制作内容” action. The existing marketing-task creation API validates store scope, eligibility, expiry and the latest adoption decision, then persists a server-generated opportunity evidence snapshot in task options. Requirement edits preserve this snapshot; no task is created automatically.

**Current limits:** no source is pre-enabled or seeded; operators must complete source terms review, host allowlisting and administrator enablement. No real feed has been connected or tested in production. Semantic AI matching, source-level heat normalization, verified geographic evidence adapters and broader ranking calibration remain out of this slice.
