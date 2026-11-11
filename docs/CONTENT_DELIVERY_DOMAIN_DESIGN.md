# 内容生产、媒体审核与发布交付领域设计（Issue #8）

> 产品基线：`PRODUCT_DESIGN.md v1.8`  
> UI/流程基线：`demo/app.js`、`demo/task-renderers.js`、`DEMO_ACCEPTANCE_MATRIX.md`  
> 跨域权威：`DOMAIN_INTEGRATION_CONTRACTS_V1.md` §6、§9、§10  
> 状态：设计准备稿，待 #5/#6/#7/#9/#12 联合评审；不代表生产能力已实现。

## 1. 目标与范围

Issue #8 负责把营销任务中的内容生产结果转化为可审核、可追溯、可质检、可冻结和可交付的内容资产。

包含：
- 文案、图片与渠道内容的逻辑产物和不可变版本。
- 文案审核、图片审核及版本级审核记录。
- 多渠道内容适配与本地/官方规格校验结果。
- 内容质量报告及输入指纹。
- 多渠道发布包冻结、商家最终确认和发布命令门禁。
- 与营销任务、经营资料、AI Job、Provider 和渠道发布服务的跨域契约。

不包含：
- 营销目标/策略/任务生命周期（#7）。
- 门店商品、优惠、品牌规范、素材源资产及事实确认（#6）。
- Job/Outbox/Worker 租约与重试实现（#9）。
- 真实 LLM/图像/Vision/OCR Provider 和 PromptVersion 管理（#10）。
- ChannelAccount、OAuth/凭据、平台能力发现、厂商 SDK、PublishOperation 与外部发布证据（#12）。

**禁止把 #8 做成第二套营销任务状态机、工作流引擎或渠道连接中心。** #8 只消费上游已确认的任务/事实/资产快照，并向 #12 发出受门禁约束的发布意图。

## 2. 与 Demo 的页面和交互映射

当前 Demo 的营销任务详情路由是 `#task`，内容生产不是独立一级菜单；它属于任务工作区的步骤页签。生产实现必须保留这一信息架构，不新增独立“内容管理 ERP”。

| Demo 步骤 | 现有交互 | #8 生产职责 | 外部依赖 |
|---|---|---|---|
| `copy` 文案工作室 | 按渠道编辑标题/正文/标签；保存草稿；审核通过；提交修改要求；粘贴/上传商家文案 | Artifact/ArtifactVersion、版本历史、文案审核、整改请求 | #9 Job、#10 Text Provider、#6 商品/品牌事实 |
| `image` 图片工作台 | 信息图/原图改造；选择商品、比例、标题、风格、指令、源素材；上传商家图片 | 图片 Artifact/Version、源素材引用、图片独立审核 | #6 MediaAsset、#9 Job、#10 Image/Vision Provider |
| `channel` 多平台适配 | 小红书/抖音/快手/视频号独立预览和基础字段检查 | ChannelContent 快照、平台规格版本引用、适配指纹 | #12 平台能力/规格快照、#7 目标渠道 |
| `quality` 发布前质检 | 显示检查项、阻断原因、重新执行质检 | QualityReport、规则版本、输入指纹和人工复核记录 | #6 事实快照、#12 渠道规格 |
| `publish` 最终发布内容包 | 汇总需求/策略、文案、图片、质检、渠道授权、计划时间；勾选确认并填写说明 | 多渠道 PublishPackage、PackageItem、PublishConfirmation、发布门禁命令 | #5 授权、#7 Task Snapshot、#9 Job、#12 PublishOperation |

Demo 中“AI 生成/整改”“图片生成/改造”“渠道校验”“发布”均是本地模拟或预览，不是真实 Provider、官方规则校验或真实外部发布。生产实现替换服务端能力，不改变商家已熟悉的任务步骤顺序与页面层级。

## 3. 领域模型与权属

### 3.1 Artifact / ArtifactVersion

- `Artifact` 是逻辑产物：`id, store_id, task_id, artifact_type(copy|image), current_version_id, created_at`。
- `ArtifactVersion` 是不可变版本：`id, store_id, artifact_id, version_no, source_type(ai_generated|merchant_upload|manual_edit), source_refs_json, instruction, content_ref/content_json, content_hash, provider_id, model_id, prompt_version_id, input_fingerprint, created_by, created_at`。
- 大图片/二进制放对象存储；DB 只保存受控 object key、hash、MIME、尺寸和版本元数据。不得返回永久公开 URL。
- `current_version_id` 是展示/业务当前版本指针，不是历史事实；版本内容和来源信息禁止覆盖。
- AI 生成、AI 整改、手工编辑、商家上传都创建新 ArtifactVersion。商家上传不自动通过审核。

### 3.2 ReviewRecord

`ReviewRecord`：`id, store_id, artifact_id, artifact_version_id, review_type(copy|image), decision(approved|revision_requested|rejected), reviewer_id, comment, target_json, idempotency_record_id, created_at`。

- Copy 与 Image 是独立审核单元；审核记录必须绑定确切 `artifact_version_id`。
- `waiting_for_review / revision_requested / approved / rejected` 是该版本的审核投影状态；权威历史是只追加的 ReviewRecord。
- 新版本创建后从 waiting_for_review 开始；旧版本的 approved 只对旧版本有效，不能批准新版本。
- `revision_requested` 必须有整改说明；局部修改使用 `target_json` 表达文本范围/图片区域，但不直接改写旧版本。
- 审核请求必须带 `expected_version` 或 `If-Match`；同一版本并发审核以行锁/CAS 串行化。

### 3.3 ChannelContent

`ChannelContent` 是某个渠道的不可变内容快照：`id, store_id, task_id, channel_key, copy_version_id, payload_json, spec_version, input_fingerprint, status, created_at, updated_at`。图片版本通过 `ChannelContentArtifactRef` 子表按顺序引用，API 可投影为 `image_version_ids[]`。

- 每个目标渠道独立生成一条 ChannelContent；修改上游版本或重新适配时创建新记录，不覆盖旧 payload。
- `copy_version_id` 必须引用已通过审核的精确版本；图片引用必须通过 `ChannelContentArtifactRef` 指向已审核的精确 ArtifactVersion。
- `spec_version` 引用 #12 发布的渠道能力/规格快照；#8 不维护 OAuth 或账号权限。
- ChannelContent 不绑定具体账号；目标账号只在 PublishPackageItem 中作为 #12 的外键引用，不代表 #8 获得读取凭据或调用厂商 API 的权限。

`ChannelContentArtifactRef`：`id, store_id, channel_content_id, artifact_version_id, role(image), position`。它是图片版本的关系表，包含 store_id 复合外键；不存储图片二进制。
- status 仅表达内容快照状态（如 ready/stale/blocked）；异步生成中状态读取 #9 Job，不复制 Job 的 queued/running/retry_wait 等状态。

### 3.4 QualityReport

`QualityReport`：`id, store_id, task_id, channel_content_id, rule_version, input_fingerprint, result(pass|fail|needs_human), issues_json, created_at`。

- 质检报告按渠道内容快照生成；每条报告绑定规则版本和精确输入指纹，结果只追加。
- Hard fail：事实错误、未审核版本、素材无权使用、越权渠道/账号、必要字段缺失等，不可人工绕过。
- needs_human：软性风险或规则无法自动判断；原始 QualityReport 保持不可变，人工结论单独写入 QualityResolution。
- pass 只代表指定规则版本下的检查通过，不代表法律合规保证或官方渠道已接受。
- 输入或规则版本变化后旧报告标记 stale，不得用于冻结新包。

`QualityResolution`：`id, store_id, quality_report_id, quality_report_fingerprint, decision(accepted|rejected), reviewer_user_id, reason, created_at, idempotency_record_id`。
- 仅允许对 `result=needs_human` 的报告追加 QualityResolution；decision=accepted 才允许该报告参与冻结，rejected 继续阻断。
- 复核权限必须经 #5 AuthorizedStoreContext 的 capability check；具体 capability key 由 #5 联合评审确定，#8 不自行按 role 字符串授权。
- `result=fail` 是 hard fail，不允许通过 QualityResolution 覆盖；必须修正输入并生成新报告。
- QualityResolution 是追加式记录；不得回写 QualityReport 的 result、reviewer 或 resolution_reason。

### 3.5 PublishPackage / PublishPackageItem / PublishConfirmation

Demo 的最终确认页面一次汇总多个目标渠道，因此发布包必须支持多渠道聚合，而不是把一个 `channel_content_id` 塞进单个包后丢失其他渠道。

- `PublishPackage` 是一次营销任务交付的不可变聚合快照：`id, store_id, task_id, package_version, package_fingerprint, frozen_at, frozen_by`。事实快照通过 `PublishPackageFactRef` 子表引用，API 可投影为 fact_snapshot_ids[]。
- `PublishPackageFactRef`：`id, store_id, publish_package_id, business_fact_snapshot_id, position`；通过复合 FK 引用 #7 的任务级 BusinessFactSnapshot；其 source revision 必须追溯至 #6 已确认的 StoreRecordRevision。
- `PublishPackageItem` 每个渠道一条：`id, store_id, publish_package_id, channel_key, channel_content_id, quality_report_id, channel_account_id, delivery_mode(official_api|manual_handoff), planned_publish_at, item_fingerprint`。文案/图片版本通过不可变 ChannelContent 间接绑定，避免在 PackageItem 重复存储版本数组。
- `PublishConfirmation`：`id, store_id, publish_package_id, package_fingerprint, confirmed_by_user_id, confirmed_at, confirmation_note`。
- 一个 PublishPackage 至少包含一个 PackageItem 和一个已确认 BusinessFactSnapshot 引用；同一 package 的 channel_key 唯一。无可引用的已确认事实时不得进入最终发布确认。
- PublishConfirmation 是不可变确认记录；首期不提供撤销接口。若未来允许撤销，必须新增独立追加式撤销记录，不得更新原确认行。PackageItem 精确绑定 ChannelContent、QualityReport 和可选 ChannelAccount；Copy/Image 版本由 ChannelContent 的直接/子表引用间接冻结。
- `delivery_mode=official_api` 时必须引用 #12 已授权且支持该渠道动作的 ChannelAccount；`manual_handoff` 不得伪造账号或显示已发布。
- 冻结包和 PackageItem 冻结后不可 UPDATE；任何上游内容变化创建新 package_version 和新 fingerprint。
- 最终确认绑定整个 package fingerprint；任一渠道 item 变化都必须重新冻结并重新确认。
- #8 不创建 PublishOperation，不存平台密钥，不声称外部发布成功。#12 持有 PublishOperation 和平台证据；#9 负责异步 Job/Outbox。

## 4. 状态与版本不变量

1. 产物版本不可变；修改只创建新版本。
2. 审核永远针对指定版本；旧版本审核不会自动继承。
3. 文案审核与图片审核相互独立。文案版本变化只使真实依赖它的图片/渠道内容/质检/发布包 stale；图片版本变化不重置文案审核。
4. ChannelContent 是渠道适配快照；输入指纹变化必须创建新快照，旧快照保留为历史。
5. QualityReport 绑定 ChannelContent + rule_version + input_fingerprint；报告过期时必须重新质检。
6. PublishPackage 是多渠道原子冻结快照；PackageItem 的集合、顺序规范化后参与 package fingerprint。
7. PublishConfirmation 绑定 package_id + package_fingerprint；旧确认不能授权新包。
8. 账号授权/能力在真正提交发布命令前由 #12 重新校验；账号 token、OAuth refresh token 不进入 #8 数据库/事件/日志。
9. #9 Job succeeded 不等于发布成功；只有 #12 PublishOperation 有平台侧成功证据时，业务层才可记录已发布。
10. 未连接账号的 manual_handoff 项只能标记待人工发布/交付，不得进入“已发布”或产生虚构效果数据。

## 5. Fingerprint 规则

所有 fingerprint 使用稳定 canonical JSON（字段排序、统一 UTC 时间、明确 null/数组顺序）并计算 SHA-256；禁止直接 hash 非稳定 JSON 字符串。

- ArtifactVersion.input_fingerprint：task_id、RequirementSnapshot/StrategySnapshot ID、BusinessFactSnapshot IDs、源 MediaAsset IDs + content_hash、前序依赖版本、prompt_version_id、provider/model 版本、生成指令。
- ChannelContent.input_fingerprint：channel_key、copy_version_id、image_version_ids、Store/Task 事实快照 IDs、channel spec_version、适配规则版本。
- QualityReport.input_fingerprint：channel_content_id + content fingerprint、rule_version、相关事实快照和必要素材哈希。
- PublishPackage.package_fingerprint：task snapshot IDs、全部 PackageItem 按 channel_key 排序后的 item_fingerprint、所有 QualityReport IDs/fingerprints、fact_snapshot_ids、planned_publish_at 和 delivery_mode。
- Fingerprint 不包含 secret/token；ChannelAccount 只记录 ID 与能力快照版本，不记录凭据。

## 6. API 契约细化

所有门店请求都消费 #5 的 request-scoped `AuthorizedStoreContext.request_store_id`；客户端不得提交可信 store_id/actor_id。所有写请求必须有 Idempotency-Key；更新提交 expected_version/If-Match。

| API | 关键输入 | 成功结果 | 关键拒绝条件 |
|---|---|---|---|
| POST /marketing-tasks/{task_id}/artifacts | artifact_type、source_type、初始内容/源引用 | Artifact + ArtifactVersion | task 不属于当前门店、来源资产不属于门店 |
| POST /artifacts/{artifact_id}/versions | expected_version、source_type、instruction、content/source_refs | 新 ArtifactVersion | 版本冲突、事实未确认、素材无权使用 |
| POST /artifact-versions/{version_id}/reviews | review_type、decision、comment、target、expected_version | ReviewRecord | review_type 不匹配、旧版本/重复提交 |
| POST /channel-content | channel_key、copy_version_id、image_version_ids、spec_version | ChannelContent + Job 引用 | 版本未审核、渠道不支持、指纹过期 |
| POST /quality-reports/run | channel_content_id、rule_version、expected_fingerprint | QualityReport + Job 引用 | ChannelContent 不属于当前门店或已 stale |
| POST /quality-reports/{id}/resolutions | decision、reason、expected_fingerprint | QualityResolution | 非 needs_human、无权复核、fingerprint 已变化 |
| POST /publish-packages/freeze | task_version、items[]、fact_snapshot_ids、expected_fingerprint | 不可变 PublishPackage + PackageItems | 任一 item 审核/质检不通过、指纹不匹配、版本跨店 |
| POST /publish-packages/{id}/confirm | package_fingerprint、confirmation_note | PublishConfirmation | 包非当前版本、指纹不符、操作者无权确认 |
| POST /publish-packages/{id}/publish | package_fingerprint、Idempotency-Key | #12 发布命令引用 + #9 Job 引用 | 未确认、账号未授权、账号能力不支持、重复命令 |

发布 API 只创建受控发布命令。#8 应通过应用服务向 #12 提交每个 official_api PackageItem；#12 校验账号/权限并创建 PublishOperation，#9 负责异步执行。未知结果进入 needs_human 并查询平台状态，不盲目重发。

标准错误码复用跨域契约：400 STORE_CONTEXT_REQUIRED、404 资源不存在/跨店、403 capability denied、409 VERSION_CONFLICT / IDEMPOTENCY_CONFLICT / PACKAGE_STALE、422 REVIEW_REQUIRED / QUALITY_BLOCKED / PACKAGE_NOT_CONFIRMED、429 RATE_LIMITED、503 dependency unavailable。

## 7. 事件契约

建议使用版本化 Outbox 事件，payload 仅包含资源 ID、版本、指纹、状态和摘要：
- `content.artifact_version_created`
- `content.review_recorded`
- `content.channel_content_created`
- `content.quality_report_completed`
- `content.quality_resolution_recorded`
- `content.publish_package_frozen`
- `content.publish_confirmed`
- `content.publish_command_requested`（每个 official_api PackageItem 一条）

每个事件使用标准 Envelope：event_id、event_type、schema_version、store_id、aggregate_type/id、aggregate_version、correlation_id、causation_id、occurred_at。消费者按 event_id 幂等并校验 fingerprint。不得在事件中放原始敏感 Prompt、媒体二进制、Cookie、Token 或平台密钥。

## 8. 事务、并发与幂等

- 创建 ArtifactVersion：锁定 Artifact 或使用 version CAS；分配 version_no 并更新 current_version_id 的事务原子提交。
- 审核：锁定目标 ArtifactVersion；校验它仍可审核；追加 ReviewRecord；不能以“最新版本”模糊指针审核。
- 异步产物写回：Worker 提交 job_id/lease_token；业务服务重新校验 task/version/input_fingerprint，过期结果只能归档，不能成为 current_version。
- ChannelContent/QualityReport：创建时保存输入快照和 fingerprint；不得更新旧记录以覆盖结果。
- Freeze：单事务校验所有 PackageItem 的版本归属、审核、质检、事实快照、渠道规格和 package fingerprint；写入 Package + Items；禁止部分冻结。
- Confirm：锁定 package，比较 package_fingerprint，追加 PublishConfirmation；同一确认请求幂等。
- Publish：再次校验包确认、门店状态、当前操作者授权、#12 账号状态和能力；同一 package/item/action 使用稳定幂等键。
- QualityResolution 与 PublishConfirmation 的操作者权限均由 #5 授权上下文决定；#8 不缓存/重定义角色能力。
- 应用层幂等范围沿用 #7：store_id + actor_id + operation + idempotency_key；Job 幂等键映射与重试规则由 #9 管理。

## 9. 数据库约束候选

- 所有内容表均有 store_id；跨域复合外键包含 store_id。
- UNIQUE(store_id, artifact_id, version_no)。
- ReviewRecord 必须 FK 到 (store_id, artifact_id, artifact_version_id)；唯一幂等记录避免重复审核动作。
- ChannelContent 对 (store_id, channel_key, input_fingerprint) 建议唯一，另提供 (store_id, id, channel_key) 复合唯一键；copy_version_id 使用 store_id 复合 FK。
- QualityReport FK 到确切 ChannelContent；提供 (store_id, channel_content_id, id) 复合唯一键，同一 channel_content_id + rule_version + input_fingerprint 幂等唯一。
- QualityResolution 复合 FK 到同店 QualityReport；仅允许 needs_human 报告；必须保存被决议报告的 fingerprint；UNIQUE(store_id, quality_report_id, quality_report_fingerprint)，并按幂等记录去重。
- UNIQUE(store_id, task_id, package_version)。
- UNIQUE(store_id, publish_package_id, channel_key)。
- ChannelContentArtifactRef 复合 FK 到 ChannelContent 和 ArtifactVersion；UNIQUE(store_id, channel_content_id, position)。
- PublishPackageItem 复合 FK 到 (store_id, channel_content_id, channel_key) 和 (store_id, channel_content_id, quality_report_id)，确保渠道和质检报告对应同一 ChannelContent；#12 ChannelAccount 引用也包含 store_id，manual_handoff 时 channel_account_id 可空。
- PublishConfirmation FK 到 package_id + package_fingerprint；UNIQUE(store_id, publish_package_id, package_fingerprint) 保证同一冻结包只有一条确认记录。
- 冻结后禁止修改 Package/PackageItem 核心字段；通过数据库权限或触发器保护不可变性。

## 10. 测试矩阵（设计准备，全部待执行）

| ID | 场景 | 预期 |
|---|---|---|
| CNT-01 | A 店访问 B 店 Artifact/Version/Review/Package ID | 统一 404 |
| CNT-02 | 同 Artifact 并发创建版本 | version_no 唯一，无覆盖 |
| CNT-03 | 对 v1 审核通过后创建 v2 | v2 重新 waiting_for_review，v1 历史保留 |
| CNT-04 | 用旧版本审核请求覆盖新版本 | 409 VERSION_CONFLICT |
| CNT-05 | 文案 revision_requested 后整改 | 新 ArtifactVersion，旧版本/审核不可变 |
| CNT-06 | 商家上传文案/图片 | source_type=merchant_upload，仍需审核 |
| CNT-07 | 图片审核通过，文案变化 | 文案重新审核；依赖旧文案的图片/下游变 stale |
| CNT-08 | 图片版本变化 | 不重置文案审核 |
| CNT-09 | Worker 迟到提交旧 input_fingerprint | 拒绝成为 current_version |
| CNT-10 | 渠道适配使用未审核文案/图片 | 422 REVIEW_REQUIRED |
| CNT-11 | channel spec_version 变化 | 旧 ChannelContent stale，必须重新适配 |
| CNT-12 | QualityReport 规则版本变化 | 旧报告 stale，不能冻结 |
| CNT-13 | Hard fail 试图人工覆盖 | 拒绝 |
| CNT-14 | needs_human 未创建 QualityResolution 或缺少操作者/理由 | Freeze 阻断并审计；accepted 决议允许，rejected 决议继续阻断 |
| CNT-27 | 对 QualityReport hard fail 创建 QualityResolution 试图覆盖 | 拒绝；必须修复输入并重新质检 |
| CNT-15 | 多渠道包缺少一个目标渠道质量报告 | Freeze 原子失败，不产生半包 |
| CNT-16 | 同一 package 重复包含 channel_key | 409/422，唯一约束阻断 |
| CNT-17 | PackageItem 跨店引用 ChannelContent/QualityReport，或图片引用跨店 ArtifactVersion | DB 复合 FK 拒绝 |
| CNT-18 | 冻结后更新 PackageItem 内容 | DB 拒绝 |
| CNT-19 | package fingerprint 变化后复用旧确认 | 409 PACKAGE_STALE / PACKAGE_NOT_CONFIRMED |
| CNT-20 | 账号撤权后发起 publish | #12 再校验并拒绝；不得触发外部副作用 |
| CNT-21 | 发布超时且平台结果未知 | Job needs_human，查询平台后才能恢复 |
| CNT-22 | 同 package/item/action 重复发布命令 | 返回同一命令/Job，不重复外部副作用 |
| CNT-23 | manual_handoff item | 不创建 PublishOperation，不显示已发布 |
| CNT-24 | #9 Job succeeded 但 #12 无平台成功证据 | 不得将任务标记已发布 |
| CNT-25 | Package/事件/日志中扫描 Secret、Cookie、原始 Prompt | 不含敏感值 |
| CNT-26 | 浏览器按 Demo 的 copy→image→channel→quality→publish 操作 | 页面层级和阻断行为一致，刷新/回退不丢失版本与审核状态 |

## 11. 联合评审待决项

1. 多渠道发布包采用本稿的 `PublishPackage + PublishPackageItem` 聚合方案，还是每渠道独立包；本稿推荐前者，以匹配 Demo 一次确认多个渠道的交互。
2. #12 提供的 ChannelCapability/Spec Snapshot 字段、版本发布和失效事件。
3. needs_human 的人工复核权限、QualityResolution 记录字段与审计；Hard fail 不允许覆盖。
4. manual_handoff 首期仅展示待人工发布，还是需要可下载交付包；未获产品确认前不新增导出/外部协作功能。
5. 图片 OCR/文字安全、素材恶意文件扫描由 #6/#10/#4 哪个服务提供；#8 只消费扫描/识别结果。
6. 计划发布时间是否由 #8 仅保存意图，还是由 #12 负责调度；首期不引入独立调度系统。
7. 首期 PublishConfirmation 不提供撤销；未来若产品要求撤销，必须通过独立追加式撤销记录实现，并定义已提交发布命令的取消/对账边界。

## 12. 实施门禁

- 先完成 #5/#6/#7/#9/#12 的跨域联合评审，并冻结 PackageItem 方案、ChannelSpec 引用、人工复核与 manual_handoff 决策。
- Issue #4 工程底座验收前不创建生产 ORM、迁移或 API 实现。
- 实现时必须先生成 Pydantic/OpenAPI/JSON Schema、SQLAlchemy/Alembic 约束和契约测试，再接 UI。
- Demo 浏览器验收矩阵中的 FLOW-05/FLOW-06/FLOW-07、STATE-03/STATE-04、SIM-03/SIM-04/SIM-06 必须逐项回归。
- 本文为设计准备；所有 CNT 测试待执行，不得标记为通过。
