# Store Knowledge 门店经营资料领域设计

> 对应 Issue：#6
> 产品基线：PRODUCT_DESIGN.md v1.8
> 架构基线：模块化单体 + PostgreSQL + S3 API
> 状态：设计提案，待 #5 身份契约与 #4 工程底座评审后冻结；不是生产实现或数据库迁移
> 日期：2026-11-11

## 1. 目标与边界

将门店端现有资料能力转为服务端可信经营上下文，供营销策略、文案、图片与质检按需读取。资料服务只管理营销所需的经营事实、知识和来源素材，不扩展成 ERP、POS、CRM、库存系统或通用文档平台。

本领域负责：
- 门店档案、商品与服务、活动与优惠、品牌规范、客群与经营、知识条目、素材资产。
- 事实来源、版本、确认状态、生效/失效时间与历史追溯。
- 门店资料 API、上传意图、对象存储元数据和授权下载。
- 对下游发布版本化事实变化事件。

本领域不负责：
- User、Store 生命周期、Store.timezone、StoreMembership、Session 和授权上下文（#5 所有）。
- MarketingTask、RequirementSnapshot、StrategySnapshot、TaskStep 和依赖失效状态机（#7 所有）。
- Copy/Image Artifact、独立审核、质检、发布包和最终确认（#8 所有）。
- Job、Worker、Outbox Relay 和 AI Gateway 执行（#9 所有）。
- 渠道账号授权凭据和平台发布（#12 所有）。
- POS 库存、订单、会员、团购核销、支付和实时经营数据集成；如需接入须单独立项。

## 2. 与产品及 Demo 的页面职责

门店资料属于门店端，不放入平台管理员日常经营资料编辑后台。页面按现行 Demo/UX 维持独立职责：
- 门店档案：门店名称、业态、主营类目、品牌名称、地址、联系电话、营业时间、服务半径/配送范围、服务能力。
- 商品与服务：商品/服务信息、价格、规格、可售状态、卖点、成分/材质、禁忌/过敏原、服务流程和交付方式。
- 活动与优惠：活动机制、适用商品、有效期、门槛、名额/数量限制、叠加和限制条件。
- 品牌规范：品牌定位、差异化、价值、文案语气、禁用表达、CTA 偏好、Logo/颜色/字体/视觉要求。
- 客群与经营：核心/次级客群、消费场景/时段、购买动机/顾虑、经营目标、淡旺季和产能限制。
- 门店知识：FAQ、菜单、制度、服务说明、品牌故事、有效期和来源。
- 素材库：原图/文件、预览、格式、尺寸、授权信息、标签、关联商品/活动及衍生关系。

不得把品牌定位和差异化重复放进门店档案；不得把客群、消费场景和经营目标重复放进门店档案。复杂资料编辑按 UX 基线进入对应二级编辑页，不合并成单个大表单或万能弹窗。空状态须说明缺少资料对 AI 产出的影响和下一步动作。

## 3. 全局数据与授权约定

- 所有门店资料表包含 store_id UUID NOT NULL；所有读取、写入、搜索、聚合、导出和文件签名均受服务端门店上下文限制。
- 目标身份契约为 PR #26：每个门店请求携带不可信 X-Store-ID selector；#5 逐请求验证 active Store 与 active StoreMembership，构造 AuthorizedStoreContext.request_store_id。PR #26 尚未合并，此处为待对齐提案。
- 不信任请求体、查询参数或普通 Header 中的 user_id、role、capabilities、store_id。store_id 由可信上下文注入；若路径中出现 store_id，必须与 request_store_id 匹配。
- 跨门店资源与随机不存在资源统一 404；授权依赖不可用时 fail closed，返回 503。
- 子资源使用 (store_id, id) 复合唯一键和复合外键；详情/更新/删除 SQL 同时限定 id + store_id。
- 金额 NUMERIC(12,2) + CHAR(3) 币种；时间 UTC timestamptz；门店本地营业时间与日期边界使用 #5 Store.timezone。不得在 StoreProfile 或 Offer 再保存可冲突的 timezone。
- 未知值存 NULL；NULL 不代表 0、无库存或不适用。
- API 写请求使用 Idempotency-Key；更新使用 expected_version / If-Match；并发冲突返回 409。
- 经营事实快照和历史修订追加写；不得原地覆盖历史证据。

## 4. 事实状态与版本规则

### 4.1 事实状态

对会影响营销宣传的资料统一使用 fact_status：
- unverified：来源已记录，但尚未由商家确认。
- pending_confirmation：新建或重要字段修改后，等待商家确认。
- confirmed：商家明确确认当前版本；可按规则进入 AI 高风险上下文。
- needs_review：来源过期、互相矛盾、疑似变更或校验失败，需要再次确认。
- expired：已超过有效期或明确失效，不得用于当前营销宣传。

记录自身生命周期使用 active / archived 等状态，不与 fact_status 混为一个状态机。Offer 的有效性还必须检查 starts_at / ends_at；不能仅因 fact_status=confirmed 就视为当前可用。

### 4.2 确认规则

- 创建者、修改者、确认者均由 AuthorizedStoreContext 注入；客户端不得提交这些身份字段作为事实。
- 价格、优惠规则、营业时间、地址、可售状态、库存/产能限制、成分/过敏原、活动有效期、品牌声明和素材授权等关键字段变更，必须创建新版本并重置为 pending_confirmation。
- 仅标签、排序或展示备注等不改变事实含义的元数据修改，可不触发事实重新确认；必须由服务端字段策略白名单判断，不能由客户端传 skip_confirmation。
- 确认动作绑定精确 version + fingerprint；旧版本确认不能沿用到新版本。
- AI 推断、外部抓取和未核验导入只可作为 unverified / needs_review 候选，不得自动转为 confirmed。
- 事实来源至少记录 merchant_input、merchant_upload、verified_import、system_observation、ai_suggestion 等类型；来源类型本身不代表可信。
- 高风险文案/图片上下文只包含 confirmed 且当前有效的事实；未确认/过期事实以待补充或风险项呈现，不允许 AI 自行补全价格、优惠、成分、营业时间或库存。

### 4.3 历史版本

当前业务表保留可查询的规范化字段和 current_version；每次重要变更追加 StoreRecordRevision：
- id、store_id、record_type、record_id、version_no。
- snapshot_json、schema_version、content_fingerprint。
- fact_status、source_type、source_ref、valid_from、valid_until。
- created_by_user_id、created_at、change_reason。
- confirmed_by_user_id、confirmed_at。

唯一约束：(store_id, record_type, record_id, version_no)。Revision 追加写，不允许普通 API 更新或删除。由于 record_type/record_id 是多态引用，数据库无法用一个外键同时指向多种实体；应用服务必须在同一事务校验实体存在、store_id 一致及版本递增。若工程评审要求完全数据库级引用完整性，改用每实体独立版本表，不得静默放弃归属校验。

## 5. 核心实体逻辑 Schema

### 5.1 StoreProfile

一店一份，UNIQUE(store_id)：
- id、store_id、display_name、business_type、industry_category、brand_name。
- introduction、country_code、region、province、city、district、address、map_coordinates（可空）、phone、contact_name。
- opening_hours_json、temporary_closures_json、service_radius、delivery_range_json。
- service_description、service_capabilities_json、opening_date、store_size（按业态可空）。
- fact_status、current_version、created_by_user_id、updated_by_user_id、created_at、updated_at、archived_at。

边界：
- 不存 Store.status、Store.timezone；由 #5 唯一持有。
- 不存品牌定位/差异化（归 BrandGuideline）。
- 不存客群/经营目标（归 AudienceProfile）。
- 营业时间使用星期/节假日结构化数据；按 Store.timezone 解释，临时歇业单独表达，不用自由文本替代规则。

### 5.2 Product

- id、store_id、name、category、sku（可空）、specification、unit。
- price_amount NUMERIC(12,2) NULL、currency CHAR(3) NULL。
- availability_status：available / unavailable / seasonal / limited / unknown。
- inventory_quantity、capacity_value、capacity_unit、selling_periods_json（未知保持 NULL）。
- key_selling_points_json、description、ingredients_or_materials、applicable_audience、allergens_and_restrictions_json。
- service_process、delivery_method、recommendation_priority、is_featured、fact_status、current_version。
- created_by_user_id、updated_by_user_id、created_at、updated_at、archived_at。

约束：
- SKU 非空时 UNIQUE(store_id, sku)；不假设所有业态都有 SKU。
- 金额与币种同时为空或同时非空；金额不得使用浮点。
- 库存/产能不等于 POS 实时库存；仅表示商家维护的经营事实/限制。
- 商品主图、细节图、场景图通过 ProductMediaAsset 关系引用 MediaAsset，不复制 object_key。
- 成分、过敏原、禁忌和价格变更触发新版本与重新确认。

### 5.3 Offer

- id、store_id、title、offer_type、terms_json、eligibility_rules_json。
- starts_at、ends_at（UTC timestamptz）、target_audience_description、audience_profile_id（可空，引用本店客群画像）。
- stacking_policy、usage_limit、per_customer_limit、quota_value、quota_unit、status、fact_status、current_version。
- created_by_user_id、updated_by_user_id、created_at、updated_at、archived_at。

适用商品使用 OfferProduct 关联表，不把需要外键验证的 product IDs 只放 JSONB。有效状态由 status、fact_status、starts_at、ends_at 和适用条件共同决定；到期后不可用于新营销内容，即使异步到期任务尚未执行。

terms_json 必须使用 Pydantic discriminated union：
- discount_percent：percent。
- discount_amount：amount + currency。
- fixed_price：amount + currency。
- buy_x_get_y：buy_quantity + get_quantity + eligible_product_ids。
- gift：gift_description + eligible_product_ids。
- threshold_discount：minimum_spend + currency + discount_type + discount_value。

每种规则必须校验范围、币种、适用商品、使用门槛、名额/数量限制和叠加策略。不得只保存“打折/买赠”等自由文本。首期不建立券码、核销、订单、支付或团购平台同步模型。

### 5.4 BrandGuideline

一店一份，UNIQUE(store_id)：
- id、store_id、brand_story、positioning、differentiators、core_values。
- tone_of_voice、common_phrases_json、prohibited_phrases_json、cta_preferences_json。
- logo_asset_id、color_palette_json、font_preferences_json、visual_style、image_prohibitions_json。
- compliance_disclaimers_json、reference_content_json。
- fact_status、current_version、created_by_user_id、updated_by_user_id、created_at、updated_at。

Logo 和品牌文件只保存 MediaAsset 引用；视觉规则必须可被 AI/质检消费为结构化约束，不能只保留一段不可解析的长文本。

### 5.5 AudienceProfile

一店可有多个客群画像：
- id、store_id、name、segment_type（core / secondary / seasonal / scenario）。
- audience_description、consumption_scenarios_json、consumption_periods_json。
- purchase_motivations_json、common_objections_json、preferred_products_json。
- source_type、source_ref、sample_size（可空）、sampled_at、confidence_level。
- fact_status、current_version、created_by_user_id、updated_by_user_id、created_at、updated_at、archived_at。

只记录聚合客群和消费场景，不采集或推断个人敏感属性，不存顾客姓名、电话、身份证、精确轨迹或个体消费档案。客群样本数未知时保持 NULL，不推断统计置信度。

### 5.6 KnowledgeItem

- id、store_id、title、category（faq / menu / policy / service_description / brand_story / other）。
- content_text（短文本可直接存储）、content_ref（大文档/附件对象引用）、content_hash。
- source_type、source_ref、effective_at、expires_at。关联商品通过 KnowledgeItemProduct 关系表维护。
- fact_status、current_version、created_by_user_id、updated_by_user_id、created_at、updated_at、archived_at。

大文件存对象存储；DB 保存受控对象 key、哈希、MIME、大小和检索元数据。只有 confirmed 且当前有效的知识可作为高风险宣传事实；过期制度/菜单不能进入当前上下文。

### 5.7 MediaAsset 与 UploadIntent

MediaAsset：
- id、store_id、object_key、sha256、mime_type、byte_size、width、height、duration_ms。
- original_filename_sanitized、asset_type、source_type、source_ref、usage_rights_status、license_note。
- parent_asset_id、version_no、derivation_instruction、status、created_by_user_id、created_at、archived_at。

状态：uploading / quarantined / scanning / ready / rejected / archived。只有 ready 且 usage_rights_status=confirmed_allowed 的素材可进入对外营销内容生产；unknown/restricted 必须阻断或要求商家确认。

UploadIntent：
- id、store_id、created_by_user_id、object_key（服务端生成）、expected_mime_type、expected_byte_size、expected_sha256。
- status、expires_at、completed_at、rejection_reason、created_at。

上传规则：
- bucket 私有；客户端不能提交或覆盖 object_key。
- 先创建 upload intent，再获取限定对象 key、HTTP method、Content-Type、大小和有效期的短时签名上传 URL。
- 上传完成后服务端校验对象存在、大小、MIME、哈希和门店归属，进入隔离/扫描状态；扫描通过后才变为 ready。
- 签名下载 URL 前重新验证 AuthContext.request_store_id 与 asset.store_id；URL 建议 TTL 5 分钟，最终由安全评审确认。
- 原始素材 immutable；图片编辑结果作为新 MediaAsset 保存，parent_asset_id 指向来源；不覆盖原对象。
- 文件名净化；限制扩展名、MIME、大小、像素/时长；防止路径穿越、伪造 MIME、压缩炸弹和恶意文件。
- 删除采用 archive + 引用检查 + 延迟清理；仍被任务快照、产物或审计引用的对象不得物理删除。

### 5.8 关系表

- OfferProduct(store_id, offer_id, product_id)：复合外键确保 offer/product 属于同一门店。
- ProductMediaAsset(store_id, product_id, asset_id, role, sort_order)：主图/细节/场景/视频。
- KnowledgeItemProduct(store_id, knowledge_item_id, product_id)：知识条目与相关商品。
- AudienceProfileProduct(store_id, audience_profile_id, product_id)：客群偏好商品。
- BrandGuideline.logo_asset_id 通过同门店复合外键引用 MediaAsset。
- MediaAsset.parent_asset_id 使用 (store_id, parent_asset_id) 自引用，禁止跨门店派生关系。

## 6. API 契约草案

以下接口均要求 Cookie Session、CSRF（写请求）、X-Store-ID 和服务端 AuthorizedStoreContext。路径是逻辑建议，最终以 FastAPI OpenAPI 为准。

| 方法 | 路径 | 作用 | 关键约束 |
|---|---|---|---|
| GET/PATCH | /api/v1/store/profile | 查询/更新门店档案 | 一店一份；PATCH 带 expected_version |
| POST | /api/v1/store/profile/confirm | 确认门店档案事实 | 确认当前版本 + fingerprint |
| GET/POST | /api/v1/store/products | 商品列表/创建 | 列表按 store_id 过滤；创建注入 store_id |
| GET/PATCH/DELETE | /api/v1/store/products/{product_id} | 商品详情/更新/归档 | 复合归属校验；删除默认归档 |
| POST | /api/v1/store/products/{product_id}/confirm | 确认商品事实 | 确认当前版本 + fingerprint |
| GET/POST | /api/v1/store/offers | 活动列表/创建 | 结构化 Offer Schema |
| GET/PATCH/DELETE | /api/v1/store/offers/{offer_id} | 活动详情/更新/归档 | 有效期、商品关联、版本校验 |
| POST | /api/v1/store/offers/{offer_id}/confirm | 确认优惠事实 | 必须验证 terms/有效期/适用商品 |
| GET/PATCH | /api/v1/store/brand-guideline | 查询/更新品牌规范 | 一店一份；事实变化产生新版本 |
| POST | /api/v1/store/brand-guideline/confirm | 确认品牌规范 | 确认当前版本 |
| GET/POST | /api/v1/store/audience-profiles | 客群列表/创建 | 仅聚合客群，不存个人敏感信息 |
| GET/PATCH/DELETE | /api/v1/store/audience-profiles/{profile_id} | 客群详情/更新/归档 | source + sampled_at + fact status |
| POST | /api/v1/store/audience-profiles/{profile_id}/confirm | 确认客群资料 | 确认当前版本 |
| GET/POST | /api/v1/store/knowledge-items | 知识列表/创建 | 内容/附件引用、有效期 |
| GET/PATCH/DELETE | /api/v1/store/knowledge-items/{item_id} | 知识详情/更新/归档 | 版本、来源和确认状态 |
| POST | /api/v1/store/knowledge-items/{item_id}/confirm | 确认知识事实 | 确认当前版本 |
| POST | /api/v1/store/assets/upload-intents | 创建上传意图 | 限流、MIME/大小白名单 |
| POST | /api/v1/store/assets/upload-intents/{intent_id}/complete | 完成上传并校验 | 幂等；不可信客户端元数据必须复核 |
| GET | /api/v1/store/assets | 素材列表 | 仅 ready/允许状态按筛选展示 |
| GET | /api/v1/store/assets/{asset_id} | 素材详情 | 按 store_id 查询 |
| POST | /api/v1/store/assets/{asset_id}/download-url | 获取短时下载 URL | 每次重新授权 |
| POST | /api/v1/store/assets/{asset_id}/confirm-usage-rights | 确认素材使用权 | 绑定 asset_id + hash + 当前版本 |
| POST | /api/v1/store/assets/{asset_id}/archive | 归档素材 | 检查下游引用与保留规则 |
| GET | /api/v1/store/records/{record_type}/{record_id}/revisions | 历史版本 | 只读、门店范围内 |

所有有副作用 POST 必须 Idempotency-Key。更新必须 expected_version / If-Match；冲突返回 409 VERSION_CONFLICT。跨店资源返回统一 404。客户端不得传 store_id、created_by_user_id、confirmed_by_user_id 或 fact_status=confirmed 来直接建立可信事实。

## 7. 事件与下游集成

#6 拥有门店事实和素材源资产；下游只读消费，不跨模块写表。

建议版本化事件：
- store.fact.changed：通用事实变化事件，包含 entity_type、record_id、version、fingerprint、change_reason。
- store.fact.confirmed：通用事实确认事件，包含 entity_type、record_id、version、fingerprint、confirmed_by_user_id、confirmed_at。
- store.asset.created / store.asset.versioned / store.asset.ready / store.asset.archived：素材生命周期事件。
- store.offer.expired：活动到期事件；到期判定本身仍以查询时 starts_at/ends_at 为准，事件仅用于下游刷新。

事件 Envelope：event_id、event_type、schema_version、store_id、aggregate_type、aggregate_id、version、fingerprint、actor_type、actor_id、occurred_at、correlation_id。事件不携带密码、Session、Secret、签名 URL 或大段资料正文。

下游规则：
- #7 收到事实版本变化后，按实际引用关系更新 BusinessFactSnapshot/依赖指纹；不因任一资料修改而全量重置任务。
- #7 的任务快照必须保存当时事实内容或可还原的不可变 revision 引用，不能只读取当前资料行。
- #8 的 ImageArtifact 可引用 MediaAsset；不得覆盖来源资产。审核绑定 #8 ArtifactVersion，不改变 #6 资产确认状态。
- #9 负责耗时 OCR、缩略图、病毒扫描等异步执行能力（若启用）；Job 只携带 asset_id 和受控输入引用，#6 负责校验结果并推进资产状态。
- #10 AI Gateway 只能读取经授权的资料快照和可用素材引用，不直接查询跨门店对象。

## 8. 关键事务边界

1. 创建/更新资料：验证 AuthContext + expected_version；在同一事务更新当前行、追加 StoreRecordRevision、写审计/Outbox；重要事实变化将 fact_status 置为 pending_confirmation。
2. 确认事实：锁定/乐观校验当前版本和 fingerprint；追加确认事件；同一事务更新当前状态与审计/Outbox。
3. Offer 激活：校验 terms schema、币种、商品归属、有效期、数量/门槛、叠加规则和 fact_status=confirmed；不满足时不能 active。
4. 素材上传：创建 UploadIntent；对象上传完成后服务端 HEAD/校验；隔离扫描；通过后创建 MediaAsset ready 记录并写事件。不能先标 ready 再异步扫描。
5. 素材归档：检查任务/知识/商品/品牌规范的引用；归档不破坏历史快照，不物理删除仍被引用对象。
6. 所有资料 API 使用服务端门店范围查询；列表过滤不能替代详情/写入/文件签名授权。

## 9. 必需索引与数据库约束

- StoreProfile：UNIQUE(store_id)。
- BrandGuideline：UNIQUE(store_id)。
- Product：UNIQUE(store_id, id)；非空 SKU 的部分唯一索引 UNIQUE(store_id, sku) WHERE sku IS NOT NULL。
- Offer：UNIQUE(store_id, id)；按 (store_id, status, starts_at, ends_at) 查询。
- AudienceProfile：UNIQUE(store_id, id)；(store_id, status, segment_type)。
- KnowledgeItem：UNIQUE(store_id, id)；(store_id, fact_status, expires_at)。
- MediaAsset：UNIQUE(store_id, id)；(store_id, status, asset_type, created_at DESC)；(store_id, parent_asset_id, version_no) UNIQUE。
- UploadIntent：UNIQUE(store_id, id)；(status, expires_at) sweeper 索引；object_key 全局唯一。
- StoreRecordRevision：(store_id, record_type, record_id, version_no) UNIQUE；(store_id, record_type, record_id, created_at DESC)。
- 关系表所有外键均包含 store_id；OfferProduct/ProductMediaAsset 等禁止跨门店关联。
- JSONB 必须有 schema_version；需要筛选/关联/唯一约束的核心字段不得只放 JSONB。

## 10. 安全与测试矩阵

| ID | 场景 | 预期 |
|---|---|---|
| SK-01 | 匿名访问资料 API | 401，无数据返回 |
| SK-02 | 缺少 X-Store-ID | 400 STORE_CONTEXT_REQUIRED |
| SK-03 | A 店访问 B 店 Product/Offer/Asset/Knowledge ID | 与随机不存在 ID 一样 404 |
| SK-04 | 请求体伪造 store_id / created_by / fact_status=confirmed | 忽略或拒绝；以 AuthContext 注入 |
| SK-05 | 列表只过滤但详情未校验 | 测试必须发现并阻断跨店读取 |
| SK-06 | 更新时使用过期 expected_version | 409，不能覆盖新版本 |
| SK-07 | 价格/优惠/营业时间等重要字段修改 | 新版本 pending_confirmation；旧确认不沿用 |
| SK-08 | 未确认商品/优惠被营销上下文读取 | 不进入高风险事实上下文 |
| SK-09 | Offer 过期/暂停/未确认 | 不能用于新营销内容 |
| SK-10 | Offer 引用其他门店 Product | 复合外键/服务校验拒绝 |
| SK-11 | 客群资料含个人敏感信息 | 拒绝/脱敏，不存个体敏感属性 |
| SK-12 | 上传伪造 MIME、超限、恶意文件 | 隔离/拒绝，不进入 ready |
| SK-13 | 替换 object_key / asset_id 获取下载 URL | 不签发 URL，跨店统一 404 |
| SK-14 | 原图被 AI 编辑 | 原 asset 不变，衍生资产新 ID + parent_asset_id |
| SK-15 | 归档仍被任务快照引用的素材 | 仅归档，不物理删除历史对象 |
| SK-16 | 重复 upload complete / 重复创建 | 幂等返回原结果，不重复创建资产 |
| SK-17 | UploadIntent 过期 | 不允许完成上传，清理遵守引用检查 |
| SK-18 | 对象存储或授权依赖故障 | fail closed，不返回公开对象地址 |
| SK-19 | 事实变化事件重复投递 | 下游幂等，不重复建立 revision/事件 |
| SK-20 | 任务引用旧资料版本 | 历史任务可还原原版本，不被当前行覆盖 |

所有用例当前为待执行；实现时必须使用真实 PostgreSQL、对象存储和认证授权中间件，不以 SQLite、Mock 或静态页面代替。

## 11. 待联合评审与实施门禁

必须在设计评审记录 accept / change / defer：
- #5：PR #26 的 X-Store-ID / AuthorizedStoreContext、Store.timezone 权威字段、PlatformAdminGrant 边界；PR #26 尚未合并。
- #4：真实 PostgreSQL、Alembic、对象存储、CI 与 OpenAPI 门禁。
- #9：文件扫描、缩略图/OCR 是否使用 Job Runtime；Job payload 与资产状态回写契约。
- 产品：AudienceProfile 作为独立可维护客群记录；素材授权确认的交互与必填范围。
- 安全：允许的 MIME/文件大小/像素/时长、恶意文件扫描方式、签名 URL TTL、保留/删除周期。
- 数据：StoreRecordRevision 多态引用的数据库约束实现方式；若不接受应用层校验，改为实体专用版本表。
- 事实策略：不同资料的默认有效期/重新确认周期，以及过期事件的调度方式。

实现门禁：#4 工程基础和 #5 身份授权未验收前，不启动生产 CRUD、迁移或文件签名实现。可以先评审 Schema、OpenAPI 示例、Demo 页面字段映射和测试用例。


## 12. 确认粒度与 API 版本并发补充

事实确认绑定单条记录的完整 revision，而不是由客户端逐字段提交“已确认”标记。记录内未知字段保持 NULL；商家确认当前 revision 时，确认的是该版本所有已填写事实及其来源。重要字段任一变化都会创建新 revision 并将整条记录设为 pending_confirmation，避免同一商品出现“价格来自新版本、过敏原确认来自旧版本”的混合事实。若 UX 后续要求字段级确认，必须另增 StoreFactAssertion 实体并经 ADR 评审，不在首期隐式混用。

### 12.1 API 资源与版本并发补充

- StoreProfile、Product、Offer、BrandGuideline、AudienceProfile、KnowledgeItem 的更新均返回新 version 和 revision_id。
- 确认端点只允许确认服务端当前版本；请求必须携带 expected_version 或 If-Match。
- Offer 激活必须要求当前 revision confirmed、商品关联同店、规则 Schema 校验通过且有效期未结束。
- UploadIntent complete 的目标是 intent_id，不是 asset_id；Asset 只有通过对象校验和扫描后才创建为 ready。


## 2026-11-11 素材授权确认与归档 API 补充

PR #66 已合并至 main（commit `d2f0b5e839ba04676ae9f51e9f51a456d3540bfd`） 补齐两项此前仅存在于领域契约、尚未落地的素材生命周期操作：

- `POST /api/v1/store/assets/{asset_id}/confirm-usage-rights`：要求当前门店授权、CSRF、Idempotency-Key、expected_version、expected_sha256 和商家授权说明；仅允许扫描通过的 ready 资产记录 `confirmed_allowed` 或 `restricted`，授权记录绑定当前内容哈希，不能由客户端修改哈希或直接跳过扫描。
- `POST /api/v1/store/assets/{asset_id}/archive`：要求 If-Match + Idempotency-Key；仅归档 ready/rejected 资产，不删除对象；仍被当前 BrandGuideline.logo_asset_id 引用时返回 409 MEDIA_ASSET_IN_USE。

新增 API 测试覆盖授权确认幂等、版本冲突、下载门禁、品牌 Logo 引用阻断和归档状态。

边界更新（2026-11-12，PR 待 CI）：上传完成先进入 quarantined/scanning；Celery Worker 周期领取隔离素材，在事务行锁内校验对象大小/SHA-256、PNG/JPEG/WebP 文件头与尺寸上限，并通过 ClamAV INSTREAM 扫描。只有 ClamAV 明确返回 OK 且结构检查通过才写入 ready；FOUND 或文件结构/尺寸不合规写入 rejected。扫描服务不可用、超时或返回不确定结果时事务回滚，保持隔离等待重试，不允许 fail-open。完整解码、缩略图生成和过期 UploadIntent sweeper 仍未完成。


### PR #66 合并验证证据（2026-11-11）

CI Run [42997147535](https://github.com/dujiu1024-dotcom/Smart-Marketing/actions/runs/42997147535) 在合并前对精确 head `d7c57f776da1dd48b8e3e28a9dd47ff882623d66` 全部 6 个 Job 通过：
- API：Ruff、MyPy、Alembic upgrade/downgrade/upgrade、121 pytest passed（1 条依赖弃用警告）
- Worker、Web、Contracts：通过
- E2E：浏览器 smoke 和冻结 Demo 路由/状态 smoke 通过
- Infrastructure：完整 Compose 启动、API/Web readiness、PostgreSQL volume restart persistence 通过

Issue #6 仍 Open。恶意文件扫描、缩略图/尺寸元数据、Worker 扫描状态回写、UploadIntent 过期清理和素材库前端仍未实现。

## 2026-11-12 素材资产生产 Web 接入补充

- `#store:assets` 已接入真实素材列表与上传/归档/使用权交互；前端上传使用服务端 upload-intent 与预签名 PUT，完成接口在服务端重新校验对象大小、MIME 和 SHA-256。
- 私有对象存储配置拆分为内部 API/Worker endpoint 与浏览器 presigned URL endpoint，避免容器内 `localhost` 错误指向 API 容器，也避免向浏览器暴露不可解析的 Docker 服务主机名。
- 本地 SeaweedFS CORS 仅允许两个本地开发 origin；生产对象存储必须配置精确的 Web Origin、PUT/GET 方法和必要请求头。
- 文件上传完成先停留在隔离/扫描状态；新增 ClamAV Worker 只有在对象完整性、图片头部/尺寸和恶意文件扫描均通过后才写入 ready，异常时保持隔离。缩略图/完整解码和 UploadIntent 过期清理仍未完成；哈希与 MIME 校验本身不等于恶意文件扫描。
