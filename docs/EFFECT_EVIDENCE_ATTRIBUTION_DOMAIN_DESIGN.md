# 经营效果、作品归属与归因证据领域设计

> 对应 Issue：#13（Stage 6）
> 产品基线：PRODUCT_DESIGN.md v1.8
> Demo 基线：#effects、#account-ops、#account-register
> 日期：2026-11-11
> 状态：领域设计提案；待产品/技术评审冻结。不是生产实现、不是正式 OpenAPI、不是已接入真实数据源的声明。

## 1. 目标与边界

经营效果是独立于营销任务的一级业务能力。营销任务负责策略、内容生产、审核、质检、发布和异常恢复；经营效果负责在发布后收集可核验数据、管理观察窗口、展示内容表现与经营结果，并将有证据的经验反馈给后续按需制作。

本设计必须遵守以下不变量：

1. 内容表现、互动意向、真实经营结果分层存储、查询和展示，不得混为一个“效果分”。
2. 每个指标必须携带来源、来源记录标识、采集时间、统计周期、时区、口径版本、真实性/完整性状态和同步状态。
3. 未知值为 NULL/缺失状态，不填 0；无来源数据不生成样例数字。
4. 作品未通过归属核验，不计入营销任务效果。人工登记默认 pending_verification。
5. 作品归属确认只证明“作品属于账号/任务”，不证明“营销导致了经营结果”。
6. 播放、阅读、曝光、点赞等内容指标不能推导订单、到店、营收或 ROI。
7. 没有交易/核销等真实经营证据时，不输出销售增长、到店增长、转化额或 ROI 结论。
8. 观察窗口未结束时显示 collecting；窗口结束但数据源缺失时显示 unavailable/incomplete，不显示 0。
9. 经营效果不作为营销任务完成、发布或任务状态推进的前置条件。
10. 不建设 POS、订单、CRM、会员或广告投放系统；只消费合法授权、可验证且范围明确的数据源。

## 2. Demo 页面、入口与现状对照

根据 `docs/DEMO_ROUTE_STATE_MAP.md` 与当前 `demo/effect-renderers.js`：

| Demo 路由 | 页面 | 当前可见能力 | 生产边界 |
|---|---|---|---|
| `#effects` | 经营效果 | 时间窗口（24小时/7天/30天/自定义）、日期和任务筛选、关联作品、样例报告、口径/可信度说明 | 当前样例报告是 Demo 数据；不得作为真实指标 |
| `#account-ops` | 账号运营监测 | 账号状态、作品登记/关联入口、同步状态工作区 | 账号授权由 #12 持有；本域只读账号和作品观测 |
| `#account-register` | 登记已发布作品 | 人工登记作品及关联线索 | 新登记先 pending_verification，不能直接计入任务归因 |

实现要求：
- 保留独立经营效果中心；不得把即时效果复盘塞回营销任务详情或任务完成页。
- 账号绑定/授权仍由 #12 负责；本域不得持有 OAuth Token 或实现第二套账号模型。
- 页面必须区分“账号作品观察”与“已核验营销任务作品”；账号自然发布内容可按账号维度展示，但不计入本系统任务归因。
- 当前 UI 中“营销效率/获客成本/ROI”只能作为口径说明或明确 unavailable 项；没有成本与经营数据来源时不展示数值。

## 3. 上游依赖与契约所有权

| 依赖 | 提供方 | 本域消费内容 | 当前门禁 |
|---|---|---|---|
| 门店身份与隔离 | #5 | AuthorizedStoreContext、store_id、actor | 生产授权和跨店测试未整体验收 |
| 门店经营事实 | #6 | 已确认 StoreRecordRevision、门店时区、活动/商品引用 | 仍有生产实现与素材链路待完成 |
| 营销任务与快照 | #7 | MarketingTask、任务/策略快照、任务与发布关联 | 仅消费精确 ID/版本，不拥有任务状态 |
| 发布包和最终确认 | #8 | PublishPackage/Item/Confirmation、精确指纹 | 内容/发布业务门禁仍有生产实现待验收 |
| AI 调用 | #10 | 仅用于洞察摘要/建议时消费精确版本和审计；不得生成指标事实 | 真实 Provider 接入状态需单独核验 |
| 渠道账号/作品 API | #12 | ChannelAccount、PublishOperation、外部作品 ID、官方读回证据 | 抖音 Adapter PR #65 尚未合并；凭据、应用权限、测试账号及真实 API 调用未验证 |

#13 只定义 MetricObservation、PublishedWork、WorkOwnershipEvidence、AttributionEvidence 和数据源适配边界。#12 唯一拥有账号授权、Token、平台 API Adapter 与 PublishOperation；#8/#7 的实体保持原所有权。

当前可以并行完成领域设计、口径和纯领域规则测试；依赖真实账号/作品 API 的联调、数据采集和生产效果结论必须等待 #5/#6/#7/#8/#10/#12 对应门禁。不能用 Mock 或 Demo 数据替代真实数据源验收。

## 4. 核心实体

### 4.1 PublishedWork（营销作品/平台作品登记）

字段建议：

- `id UUID`、`store_id UUID NOT NULL`
- `channel_account_id UUID NULL`（复合 FK 到 #12 同店 ChannelAccount）
- `channel_key TEXT NOT NULL`
- `external_work_id TEXT NULL`、`external_work_url TEXT NULL`
- `publish_operation_id UUID NULL`、`publish_package_id UUID NULL`、`publish_package_item_id UUID NULL`
- `marketing_task_id UUID NULL`（复合 FK 到 #7 同店 MarketingTask）
- `registration_source TEXT`：system_publish_readback / official_account_sync / merchant_manual
- `ownership_status TEXT`：pending_verification / verified_system_publish / verified_official_account / merchant_confirmed / rejected
- `ownership_method TEXT NULL`、`ownership_evidence_id UUID NULL`
- `published_at TIMESTAMPTZ NULL`、`first_observed_at TIMESTAMPTZ NULL`
- `created_by_user_id UUID NULL`、`created_at`、`updated_at`、`version INT`

规则：
- #12 发布成功后的 external_work_id + 同账号官方只读读回匹配，是首选强证据；仅有创建接口 accepted/processing 响应不能标记作品公开发布成功。
- 系统发布作品通过 PublishOperation 与 PublishPackageItem 精确关联，不允许仅靠标题/文案相似度自动归因。
- 官方账号作品列表同步到本系统时，默认只确认“账号归属”；若无 PublishOperation/发布包关联，marketing_task_id 保持 NULL。
- 商家手工登记只能创建 pending_verification；商家确认可形成 merchant_confirmed 级别证据，但不能伪装为官方读回。
- 同一门店、渠道账号和 external_work_id 唯一；若平台 ID 不可用，必须用经过评审的来源键，禁止用 URL 猜测强唯一性。
- 归属状态变更追加证据记录；拒绝或撤销核验后，关联任务的指标不再进入正式归因视图，历史原始观察仍保留。

### 4.2 WorkOwnershipEvidence（作品归属证据）

字段建议：

- `id, store_id, published_work_id`
- `evidence_type`：publish_operation_readback / official_account_video_list / merchant_attestation / manual_review
- `source_system, source_record_id, evidence_ref`
- `channel_account_id, external_work_id`
- `observed_at, verified_at, verified_by_user_id`
- `verification_status`：pending / accepted / rejected / expired
- `evidence_fingerprint CHAR(64)`、`created_at`

规则：
- 原始证据引用不可覆盖；必要时追加新证据。
- evidence_ref 指向受控存储中的脱敏响应快照或官方记录引用；不得保存 access_token、refresh_token、Cookie 或 Secret。
- evidence fingerprint 包含账号 ID、作品 ID、来源记录 ID 和规范化证据内容摘要。
- merchant_attestation 与官方平台证据分级展示，不能混成同一 verified 状态。

### 4.3 MetricDefinition（指标口径目录）

平台/来源级口径目录，按版本不可变：

- `id, source_system, channel_key NULL, metric_key, metric_tier`
- `display_name, value_type(count/decimal/duration/rate/currency), unit, currency_required`
- `definition, aggregation_rule, period_semantics`
- `definition_version, effective_from, effective_to, status`

指标层级：
- content_performance：播放、阅读、曝光、点赞、评论、收藏、分享等。
- intent：咨询、私信、点击、预约意向、领券等。
- business_outcome：到店、订单数、销售额、核销数/金额等。

禁止把一个来源的“互动”指标映射为另一个来源的“咨询”指标；每个映射必须由来源 Schema 与指标定义版本明确声明。

### 4.4 MetricObservation（指标观测）

字段建议：

- `id, store_id, published_work_id NULL, channel_account_id NULL, marketing_task_id NULL`
- `metric_definition_id, metric_key, metric_tier`
- `value_numeric NUMERIC(20,6) NULL`、`value_text TEXT NULL`（仅在经评审的非数值指标需要时）
- `unit, currency CHAR(3) NULL`
- `source_system, source_record_id, source_evidence_ref`
- `period_start TIMESTAMPTZ NULL, period_end TIMESTAMPTZ NULL, period_timezone TEXT`
- `collected_at TIMESTAMPTZ NOT NULL, source_updated_at TIMESTAMPTZ NULL`
- `definition_version, integrity_status, authenticity_status, sync_status`
- `deduplication_key CHAR(64), supersedes_observation_id UUID NULL`
- `created_at`

状态建议：
- integrity_status：complete / partial / anomalous / unknown
- authenticity_status：official_api / verified_import / merchant_reported / demo_sample
- sync_status：current / delayed / failed / unavailable
- 对生产正式分析只允许 official_api 或通过来源核验的 verified_import；merchant_reported 单独标注，demo_sample 永远不进入生产聚合。

规则：
- 观察记录 append-only；纠错通过新记录 + supersedes_observation_id，不 UPDATE 覆盖历史值。
- 同一来源记录、指标口径版本和统计周期建立唯一去重键；分页重复同步不会重复计数。
- 未知值不写 0；没有该指标权限/接口时写明 unavailable，不创建伪观测。
- 累计值与区间增量必须区分；累计值按 source_record_id + period_end 做快照，不能直接累加多次采样。
- 同一作品多个时间点的累计值用于趋势/差值计算时，必须保存原始观测并标记计算口径；不能将回退/删除后的数值简单覆盖。

### 4.5 ObservationWindow（观察窗口）

可由查询计算或物化快照实现，不先强制新增独立表。窗口定义：

- anchor：经核验的 published_at（不得用任务创建时间或 API 请求时间替代）
- preset：24h / 7d / 30d / custom
- start_at / end_at：UTC timestamptz
- timezone：展示和自然日边界使用门店 IANA timezone
- status：not_started / collecting / complete / incomplete / unavailable

规则：
- 24 小时、7 天、30 天窗口均按发布锚点计算；自定义窗口必须校验边界。
- 当前时间未达到 end_at，状态为 collecting；达到窗口但来源未同步或权限缺失时为 incomplete/unavailable。
- 不得因“窗口结束”推断数据完整；完整性由来源同步状态和所需指标集合共同决定。

### 4.6 BusinessOutcomeEvidence（经营结果证据）

经营结果必须保留可追溯来源，建议字段：

- `id, store_id, metric_observation_id`
- `outcome_type`：store_visit / order / redemption / revenue / other
- `source_system, source_record_id, evidence_ref`
- `business_period_start, business_period_end, timezone`
- `verification_method, verification_status, verified_by_user_id, verified_at`
- `sample_size, limitations, created_at`

本实体只描述证据，不接管交易系统。首期只允许经评审的授权来源/API 或有原始来源凭证的核验导入；不得把自由文本或人工估计直接作为已核验销售额/到店数。不得直接存储不必要的顾客个人信息。

### 4.7 AttributionEvidence（归因证据）

字段建议：

- `id, store_id, marketing_task_id, publish_package_id, published_work_id`
- `attribution_method`：direct_link / coupon_redemption / time_window_association / merchant_reported / none
- `metric_tier, metric_keys, observation_window`
- `sample_size, evidence_strength`：strong / moderate / weak / insufficient
- `evidence_refs_json, input_observation_ids_json`
- `limitations_json, attribution_version, computed_at`
- `status`：provisional / eligible_for_display / insufficient_evidence / superseded

规则：
- 归因证据是可追溯分析快照，不是因果事实。
- 只有强关联（例如作品/发布包携带唯一优惠码且核销记录匹配，或来源提供明确作品到订单关联）才能支持较强的任务级经营归因。
- 时间相关性、同期销售变化、播放互动增长只能描述关联，不得表述为“营销带来增长”。
- 样本量、窗口、数据缺口和混杂因素必须展示；样本不足时 evidence_strength=insufficient。
- 不能把多渠道、多任务共享的交易重复归因；同一 outcome evidence 的分摊规则必须明确，否则只在门店汇总层展示、不分配到单任务。
- ROI 只有在完整、可信的收入与成本口径都可获得时才允许计算；当前产品不做广告投放，不能凭空引入广告花费或虚构“营销成本”。

## 5. 关联关系与数据库约束

逻辑关系：

- Store 1—N PublishedWork / MetricObservation / WorkOwnershipEvidence / BusinessOutcomeEvidence / AttributionEvidence
- ChannelAccount 1—N PublishedWork / MetricObservation（账号维度观察）
- PublishedWork 1—N WorkOwnershipEvidence / MetricObservation / AttributionEvidence
- MarketingTask 1—N PublishedWork / MetricObservation / AttributionEvidence
- PublishPackage / PublishPackageItem / PublishOperation 1—N 或 1—1 关联按 #8/#12 真实唯一约束确定；#13 不复制拥有这些实体。
- MetricDefinition 1—N MetricObservation
- MetricObservation 1—0..1 BusinessOutcomeEvidence（经营层指标）

数据库要求：
- 所有门店实体 `store_id NOT NULL`；门店子资源唯一键与外键必须包含 store_id。
- PublishedWork 对 (store_id, channel_account_id, external_work_id) 建唯一约束；external_work_id NULL 时不阻断多条待核验登记。
- PublishedWork 到 #7/#8/#12 的跨域引用使用复合 FK；禁止仅凭 UUID 跨店引用。
- MetricObservation 对 (store_id, deduplication_key) 唯一；来源/指标/统计周期构成 deduplication_key。
- MetricObservation 的 published_work_id、channel_account_id、marketing_task_id 必须同店；关联作品未 verified 时，不能写入正式任务归因引用。
- 所有时间为 TIMESTAMPTZ；展示时按 Store.timezone。
- 观测、证据、归因快照 append-only；更正通过 supersedes 或新版本。
- 建索引： (store_id, collected_at DESC)、(store_id, published_work_id, metric_key, period_end)、(store_id, marketing_task_id, metric_tier)、(store_id, channel_account_id, published_at DESC)、(store_id, status)。
- 对 JSONB 证据引用/限制字段定义 schema_version；核心外键和指标值不得只放 JSONB。
- 删除/归档作品不得级联删除原始指标和证据。

## 6. API 契约草案

所有门店 API 遵循现有 Cookie Session、X-Store-ID、CSRF、Idempotency-Key、统一错误和 AuthorizedStoreContext 约定。实际路径以 FastAPI OpenAPI 为准。

| Method | Path | 用途 | 主要约束 |
|---|---|---|---|
| GET | `/api/v1/effects/overview` | 经营效果总览 | 仅当前门店；返回窗口、来源和缺失状态 |
| GET | `/api/v1/effects/observations` | 指标观测列表 | 按 tier/channel/task/work/window 过滤；不返回未经授权的原始敏感资料 |
| GET | `/api/v1/effects/tasks/{task_id}` | 单次任务效果 | 只包含归属 verified 且达到窗口的数据 |
| GET | `/api/v1/effects/works` | 账号作品/任务作品列表 | 区分账号作品和任务作品；显示归属状态 |
| POST | `/api/v1/effects/works/register` | 商家登记作品 | 幂等；始终 pending_verification |
| POST | `/api/v1/effects/works/{work_id}/verify` | 提交人工核验决议 | 权限、理由、证据引用、If-Match；不得伪造 official_api |
| GET | `/api/v1/effects/attributions/{id}` | 归因证据详情 | 返回方法、样本量、限制和来源 |
| POST | `/api/v1/effects/sync` | 请求同步已授权来源 | 创建 #9 Job；不在 HTTP 请求中同步外部 API |

错误语义沿用：
- 401 AUTH_REQUIRED / SESSION_EXPIRED
- 403 ACTION_FORBIDDEN
- 404 RESOURCE_NOT_FOUND（跨店资源统一 404）
- 409 VERSION_CONFLICT / IDEMPOTENCY_KEY_REUSED
- 422 VALIDATION_ERROR
- 429 RATE_LIMITED

POST /sync 必须将请求写入 #9 Job/Outbox，不自建队列；Job 的 store_id/actor 来自 AuthorizedStoreContext。来源授权/能力不满足时返回明确 unsupported/pending_verification，不启动伪同步任务。

## 7. 事件与异步采集

候选事件（schema_version=1）：

- `effects.work.registered`
- `effects.work.ownership_verified`
- `effects.metric_observation.recorded`
- `effects.sync.requested`
- `effects.sync.completed`
- `effects.attribution.computed`

事件只携带 store_id、聚合 ID/version、来源记录引用、指标/状态摘要、correlation_id/causation_id；不包含 Token、原始顾客信息或大 payload。

同步 Job 由 #9 执行，建议 JobType：
- `effects.sync_channel_metrics.v1`
- `effects.reconcile_work_ownership.v1`
- `effects.compute_attribution.v1`

Job 命令需包含 source/channel account ID、时间窗口、cursor、schema version 和 request fingerprint。Worker 每次分页执行前后校验 ChannelAccount 授权状态和 Job lease fencing token；权限撤销、账号解绑、版本过期后停止同步并保留失败原因。

幂等规则：
- 同一 store/account/source/window 的同步请求使用确定性 idempotency key。
- 平台游标与已同步区间持久化；重复页/重复 webhook 通过来源记录 ID + metric + period 去重。
- 429/5xx 依 #9 重试策略退避；401/403 停止自动重试并提示重新授权/能力缺失。
- 结果未知不重复触发有副作用动作；指标同步是只读操作，允许安全重试但仍需去重。
- 归因计算绑定输入 Observation ID 集合及版本指纹；输入新增/更正后创建新 AttributionEvidence，旧结果 superseded。

## 8. 数据来源准入与能力状态

任何数据源在实现前必须形成 DataSourceCapabilitySnapshot，记录：
- source_system/channel_key、官方文档 URL/版本/核验日期
- 所需 scope/应用审核/主体资质/账号类型/地区限制
- 可读取的指标 key、统计周期、分页与延迟语义
- 数据保留/使用限制、展示/导出限制
- 账号级/作品级粒度、读回 ID 是否稳定
- 速率限制、失败码、数据完整性和删除/撤回机制
- support_status：supported / unsupported / pending_verification
- checked_by、checked_at、expires_at

首期抖音指标接口不得仅因已实现视频发布 Adapter 就推断已支持指标读取。#12 当前已实现/拟实现的作品列表读回只证明可查作品，不等于可读取播放、互动等统计指标。必须独立核查抖音官方数据指标 API、scope、审核和真实测试账号权限。没有证据时将指标标记 pending_verification。

门店经营结果数据源不得默认接入 POS/CRM；首期只定义受控导入/来源引用契约。任何来源的授权、合同、隐私和保留条款须单独评审。

### 8.1 抖音官方视频指标能力初步核验（2026-11-11）

已对照抖音开放平台官方文档，确认存在官方只读视频指标接口，但**不代表当前应用已获得权限或真实账号已可调用**：

| 接口 | 官方 Scope | 官方文档明确的能力/限制 | 对本项目的处理 |
|---|---|---|---|
| `POST /video/data/` | `video.data` | 查询授权用户指定公开视频的点赞、播放等数据；仅返回公开作品；需用户授权且申请权限 | 可作为作品级即时指标候选；须先确认应用控制台权限和授权用户 |
| `GET /data/external/item/base/` | `data.external.item` | 获取作品基础数据；仅近 30 天创建的视频；首次授权后次日才产生完整数据，后续约次日刷新 | 可作为延迟型基础指标候选，需记录延迟和 30 天限制 |
| `GET /data/external/item/play/` | `data.external.item` | 获取作品播放数据；仅近 30 天创建的视频；首次授权后次日才产生完整数据 | 可作为按日播放观测候选，不得当作实时数据 |

官方权限说明将 `video.data` 与 `data.external.item` 分列，且均需要申请/用户授权；官方 FAQ 还提示 `video.data` 申请入口可能未出现在管理中心，需通过开放平台渠道确认申请方式。因此，不能把发布/作品列表读回权限视为上述指标权限已开通。

官方参考：
- [查询特定视频的视频数据（video.data）](https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/search-video/video-data/)
- [获取视频基础数据（data.external.item）](https://open.douyin.com/platform/resource/docs/openapi/data-open-service/video-data/get-basic-data/)
- [获取视频播放数据（data.external.item）](https://open.douyin.com/platform/resource/docs/openapi/data-open-service/video-data/get-play-data/)
- [开放平台能力与权限列表](https://open.douyin.com/platform/resource/docs/accession-guide/type-and-permission/)
- [开放平台 FAQ：video.data 权限申请入口](https://open.douyin.com/platform/resource/docs/common-question/faq/)

当前核验结论：`support_status=pending_verification`。尚未检查本项目应用控制台实际 Scope、应用审核资质、真实 OAuth 授权用户、配额或 API 响应；不创建同步 Job，不展示真实指标。后续 #12 应把指标读取能力作为独立 Capability 申请与验收，#13 只消费 #12 输出的能力快照和已脱敏观测证据。

## 9. 安全、隐私与审计

- 全部查询先由 #5 构造 AuthorizedStoreContext；任何 client-supplied store_id 都不是授权事实。
- 所有作品、观测、证据和任务关联必须做同店复合 FK 与服务端校验。
- 账号 Token 只由 #12 管理；#13 不读写 SecretRef 或原始凭据。
- 外部 URL 只允许来自已验证来源/平台域名白名单，防 SSRF；导入文件做 MIME、大小、恶意文件扫描和内容校验。
- 不采集不必要的顾客姓名、手机号、头像或订单明细；经营数据优先使用聚合/去标识化记录。
- 证据快照脱敏；日志只记 request_id/job_id/store_id/来源 ID 和错误码，不记原始响应/Secret。
- 商家人工核验、作品关联变更、来源导入、数据更正和归因重算均写审计事件。
- 数据访问、保留和删除遵循平台政策、商家授权与适用法律；无法确认授权时不采集。

## 10. 验收测试矩阵（EFF-01..EFF-30）

| ID | 场景 | 预期 |
|---|---|---|
| EFF-01 | 跨店查询 PublishedWork | 统一 404，无信息泄露 |
| EFF-02 | 跨店写入 MetricObservation | 拒绝，事务不落库 |
| EFF-03 | 无授权账号请求指标同步 | 不启动 Job，返回能力/授权状态 |
| EFF-04 | 人工登记作品 | ownership=pending_verification |
| EFF-05 | 手工作品未核验参与任务分析 | 不计入任务指标 |
| EFF-06 | PublishOperation processing | 不标记公开发布成功 |
| EFF-07 | 官方读回 external_work_id 匹配 | 追加强归属证据并更新 verified_system_publish |
| EFF-08 | 账号作品无发布包关联 | 仅账号维度展示，task_id=NULL |
| EFF-09 | 标题相同但 external_work_id 不同 | 不自动合并/归因 |
| EFF-10 | 同步重复来源记录 | 唯一去重，不重复计数 |
| EFF-11 | 累计指标多次快照 | 不直接累加累计值 |
| EFF-12 | 指标值缺失 | NULL/unavailable，不填 0 |
| EFF-13 | 数据来源 pending_verification | 不进入正式聚合 |
| EFF-14 | demo_sample 进入生产聚合 | 拒绝 |
| EFF-15 | 观察窗口未结束 | collecting |
| EFF-16 | 窗口结束但数据未同步 | incomplete，不伪装 complete |
| EFF-17 | 门店 timezone 跨日 | 按 Store.timezone 解释 |
| EFF-18 | 指标口径版本变化 | 新 MetricDefinition 版本，旧观察保持原定义 |
| EFF-19 | 作品归属撤销/拒绝 | 从任务正式归因视图剔除，历史证据保留 |
| EFF-20 | 只存在播放/点赞增长 | 不输出订单/销售/到店/ROI 结论 |
| EFF-21 | 时间相关性弱归因 | 显示关联与限制，不宣称因果 |
| EFF-22 | 强优惠码核销证据 | 允许按核销证据形成有范围的强归因快照 |
| EFF-23 | 多任务共享 outcome | 不重复计入任务级经营结果 |
| EFF-24 | 同步 Job lease 过期 | 旧 Worker fencing 失败，不覆盖新状态 |
| EFF-25 | 平台 429 | 按 #9 退避；不丢 cursor |
| EFF-26 | 平台 401/403 | 停止重试，标记授权/权限异常 |
| EFF-27 | 来源指标删除/修订 | 追加 superseding observation，保留历史 |
| EFF-28 | 手工经营数据导入 | 保留来源、导入人、文件哈希和核验状态 |
| EFF-29 | 作品归属 API 幂等重放 | 返回原决议，不产生重复证据 |
| EFF-30 | attribution 输入变化 | 创建新快照，旧版本 superseded |

## 11. 分阶段实现建议

1. **Slice A — 领域/契约冻结**：确认实体、证据等级、指标层级、归因表述、Demo 页面和 API/Job 边界；完成评审记录。
2. **Slice B — 只读作品归属基础**：消费 #12 的 ChannelAccount/PublishOperation/官方读回结果；实现 PublishedWork 与 WorkOwnershipEvidence；人工登记先待核验。
3. **Slice C — 指标定义与观测存储**：MetricDefinition、MetricObservation、幂等去重、观察窗口、数据来源能力快照。
4. **Slice D — 只读同步与展示**：仅在某渠道指标 API 权限通过后实现真实只读同步；没有权限时展示 unsupported/pending 状态和数据接入说明。
5. **Slice E — 经营结果证据与归因**：在真实、合法经营数据源明确后接入；先做描述性统计，再按证据强度提供有限归因。
6. **Slice F — 经验沉淀**：将已验证洞察作为后续按需制作的建议输入，不自动创建营销任务，不自动改写门店画像。

## 12. 当前未完成项与冻结门禁

- [x] 核心 ORM、Alembic 迁移、门店级 API、Worker 发布读回登记和 Effects 工作区已落地；PR #139 持续验收中。
- [x] 机会采纳到营销任务的显式制作入口、服务端机会快照、任务幂等和门店隔离已实现。
- [x] 指标周期聚合、环比、同源同渠道转化率、作品级趋势、观察窗口积累状态、归因撤销和审计已实现。
- [ ] PostgreSQL 迁移升级/回滚、完整 API 契约生成和全部 CI 检查通过；当前 PR 尚未获得最新完整 CI 结果。
- [ ] EFF-01..EFF-30 全量自动化覆盖；目前已补跨店、幂等、归因撤销、作品级统计、零基线、周期缺失和观察窗口等测试，仍需补并发、Job 恢复及来源 API 集成场景。
- [ ] Demo 全流程浏览器验收、真实空状态/数据缺失/观察中/失败态截图。
- [ ] #12 抖音真实账号验收：确认授权 Scope、video.list 读回行为及是否存在可用的官方指标读取接口；代码明确将内容指标读取标为 unsupported，不能用发布授权推定可读指标。
- [ ] 经营结果官方数据源尚未接入；手工录入和 CSV 只保留为商家报告，不得作为已核验经营结果或正式归因。
- [ ] 数据源官方文档、授权范围、数据条款、采集日期和真机测试证据入库。

**状态声明：** 本文档对应的核心代码切片已实现，但 Issue #137 尚未达到关闭条件。没有真实抖音指标数据或已核验经营结果；CI、EFF-01..EFF-30 全量覆盖和浏览器验收仍待完成。真实数据源能力属于待真机/官方能力验证事项，不得伪装成已接入。

## 13. Issue #137 implementation status (2026-11-12)

The first complete code slice for opportunity handoff, published-work ownership and effects evidence is implemented; external data-source verification and full acceptance remain:

- Metric definition dictionary and append-oriented metric observation storage are introduced by migration `0018_opportunity_effects`.
- Store-scoped APIs expose observations, a metric overview, period aggregation, period-over-period comparison and data-quality counts. Trend aggregation requires complete, current, verified observations with explicit period boundaries and uses the metric dictionary aggregation rule.
- Manual observation entry and CSV-text import preserve period, IANA timezone, source reference and deduplication key. These records are always marked `merchant_reported`.
- Manual observation corrections append a new observation with `supersedes_observation_id`; the original record is never overwritten, and a database uniqueness constraint permits only one direct successor per observation.
- Attribution reversals are append-preserving status transitions: the original attribution snapshot is immutable, while reversal reason, actor and timestamp are recorded and audited. Only one active attribution per store/outcome/task is allowed; a reversed record may be replaced without deleting history.
- Attribution input changes create a new monotonically versioned snapshot and mark the prior active version `superseded`; exact input replays return the existing version. Each version links to the prior record within the same store.
- CSV imports create store-scoped import batches with the importing user, row counts and SHA-256 content hash. Replaying identical file content returns the original batch and does not create duplicate observations; new observations retain their batch ID.
- The overview only surfaces values marked `official_api` or `verified_import` with complete/current integrity as available. Merchant-reported and demo-sample values do not become verified results. ROI, sales growth and store-visit growth remain unavailable unless the required real evidence and cost basis exist.
- The opportunity workspace exposes an explicit merchant-triggered handoff to marketing-task creation. The server validates the adopted opportunity and store scope, snapshots the opportunity evidence into the task, and preserves idempotent task creation.
- The Douyin publish worker now changes an operation to `published` only after successful platform readback, then idempotently creates `PublishedWork` and verified `WorkOwnershipEvidence` in the same transaction. The effects workspace registration endpoint remains a reconciliation path for older or externally completed operations; merchant claims remain unverified.
- The effects workspace can snapshot Douyin capability boundaries: `video.list` may support published-work ownership readback, but content-metric reads and business-outcome reads remain explicitly `unsupported` until a verified adapter and scope exist. Capability snapshots are versioned and include granted scopes and assessment reasons.
- `BusinessOutcomeEvidence`, `AttributionEvidence` and `DataSourceCapabilitySnapshot` now have store-scoped models and APIs. Manual business outcomes are always `merchant_reported`; formal attribution requires a verified work, verified ownership evidence, a complete official/verified outcome, a matching task, strong/medium evidence and allocation not exceeding 100%.
- Metric observations may link to verified published works and their originating marketing task. Composite foreign keys enforce store scope.
- The overview aggregates verified metric observations by identical period according to the metric dictionary, and computes period-over-period change only for adjacent equal-duration windows. Zero baselines and insufficient samples are explicitly reported.
- Observation windows whose `period_end` is in the future are labeled `accumulating` and excluded from trend, conversion and work-performance conclusions. Missing period boundaries are labeled `window_unknown`; the workspace surfaces both counts separately.
- Metric trends are partitioned by source system and channel. Conversion rates (clicks/views, consultations/views, booking intents/consultations and orders/booking intents) are calculated only from verified numerator/denominator observations sharing the same source, channel, period and timezone; zero denominators are not converted to a fabricated zero rate.
- Verified content-performance observations are additionally grouped by verified published work and its marketing task. Work-level comparisons require a matching task association and a verified ownership-evidence record; merchant claims and unverified works are excluded.
- The overview emits evidence-bounded insights and next-step suggestions only from verified metric trends; suggestions are operational checks, not causal claims. With no verified metrics, the workspace shows an explicit empty state.
- The UI adds an independent `#effects` workspace and distinguishes content performance, intent and business outcomes, with verified trends, conversion rates, per-work performance comparisons, evidence-bounded insights, data-quality counts, automatic readback registration and reconciliation, capability snapshots and evidence/attribution status.

**Current limits:** official channel metric-read adapters and verified business-outcome import adapters are not yet implemented, so no production outcome can be formally attributed yet. Per-source expected-latency SLAs, late-arrival reconciliation and the full EFF-01..EFF-30 suite remain. Douyin publishing/readback does not imply metric-read permission. No production metric source or business outcome is claimed.
