# AI 门店运营官 — Demo 验收追踪矩阵

> 文档版本：v1.8  
> 对应唯一产品基线：[PRODUCT_DESIGN.md v1.8](PRODUCT_DESIGN.md)  
> 对应 UI/UX 基线：[UX_AUDIT_AND_REDESIGN.md v1.8](UX_AUDIT_AND_REDESIGN.md)  
> 更新日期：2026-11-11  
> 当前总状态：**部分代码实现与静态检查完成；真实浏览器 E2E 未完成；不得宣称正式验收通过。**

本矩阵取代此前 v1.5 及历史轮次中的旧状态表。历史缺陷描述仅保留为追溯依据，不作为当前缺陷状态。状态以当前 main 分支代码及本矩阵记录的验证证据为准。

## 1. 状态定义

| 状态 | 含义 |
|---|---|
| 代码已实现 | 已找到对应实现路径；尚不代表交互正确 |
| 静态逻辑已检查 | 已检查代码条件/调用路径，或通过 mock 测试；不代表真实浏览器行为 |
| 已修复，待浏览器确认 | 历史缺陷已在代码层修复，但尚未完成真实浏览器端到端验证 |
| 浏览器实测通过 | 已在真实浏览器执行完整步骤并记录环境、步骤和结果 |
| 未实现/未接入 | 当前 Demo 或生产服务没有该能力 |
| 不适用/已移除 | 不属于 v1.8 产品范围 |

## 2. 核心营销流程（P0）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| FLOW-01 | 流程与页面一致 | 部分实现 | 待验收 | 七个任务页签存在；热点机会仍为独立工作台，跳过原因记录和统一状态机尚需完善 |
| FLOW-02 | 需求理解 | 代码已实现 | 待验收 | 可编辑目标、类型、商品、客群、动作和日期；真实 AI 自动理解未接入 |
| FLOW-03 | 热点机会 | 部分实现 | 待验收 | 可在热点工作台查看、采纳、忽略、暂缓；任务流程内跳过状态和原因尚未统一 |
| FLOW-04 | 策略确认 | 代码已实现 | 待验收 | 本地策略编辑/确认；真实模型生成未接入 |
| FLOW-05 | 文案独立审核 | 代码已实现 | 待验收 | 多渠道文案编辑、审核、整改和版本记录；整改为本地模拟 |
| FLOW-06 | 图片独立审核 | 代码已实现 | 待验收 | 信息图、原图改造、自有图片上传与审核路径；图像生成服务未接入 |
| FLOW-07 | 发布门槛 | **已修复，静态逻辑已检查** | **待浏览器确认** | 当前代码检查需求确认和策略确认状态；发布页还检查策略快照、文案审核、图片审核、质检和最终确认。旧版“未校验 briefConfirmed / strategyStatus、可绕过发布”的失败结论已过时并撤销 |
| FLOW-08 | 效果复盘独立 | 代码已实现 | 待验收 | 经营效果为独立模块，不作为任务发布后的即时结论 |
| FLOW-09 | 页签与路由一致 | 代码已实现 | 待验收 | 七个页签可导航，需浏览器验证 URL、刷新、前进后退和内容一致性 |
| FLOW-10 | 无效任务与空状态 | 代码已实现 | 待验收 | 无任务时有返回入口；需真实浏览器验证异常路径 |

### FLOW-07 当前代码证据

- `renderTaskStage()`：非需求页签在 `briefConfirmed` 未确认时返回需求阻断说明。
- `renderTaskStage()`：文案、图片、渠道、质检和发布步骤在 `strategyStatus !== "confirmed"` 时返回策略阻断说明。
- `renderPublish()`：核对需求/策略确认、策略快照、文案审核、图片审核、质检新鲜度和发布确认条件。
- 以上属于代码逻辑检查，不等于浏览器 E2E 或服务端安全校验。

## 3. 账号运营监测与经营效果（P0）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| ACCOUNT-01 | 账号运营监测入口 | 代码已实现 | 待验收 | 门店端独立入口 |
| ACCOUNT-02 | 账号授权/可用状态 | 代码已实现 | 待真机验收 | 抖音 OAuth、账号状态、Scope 与刷新流程已实现；真实应用/账号授权另计 |
| ACCOUNT-03 | 发布作品登记 | 代码已实现 | 待验收 | 官方发布读回成功后 Worker 自动登记作品；Effects 工作区保留历史读回记录的人工对账入口 |
| ACCOUNT-04 | 作品归属核验 | 代码已实现 | 待验收 | 系统发布读回与平台 API 证据可核验；商家手工认领始终不计入正式归因 |
| EFFECT-01 | 经营效果独立页面 | 代码已实现 | 待验收 | 独立工作区，不在任务完成时自动生成经营结论 |
| EFFECT-02 | 作品与任务关联 | 代码已实现 | 待验收 | 已核验作品、营销任务、指标观察通过稳定 ID 关联，并执行门店隔离 |
| EFFECT-03 | 指标真实性 | 代码已实现 | 待验收 | 仅完整、当前且已核验观测进入统计；手工录入/CSV 保留为商家报告 |
| EFFECT-04 | 经营结果归因 | 代码已实现（证据门禁） | 待验收 | 只有已核验作品和已核验经营结果可正式归因；无真实交易证据不输出 ROI/增长 |
| EFFECT-05 | 指标聚合、环比与转化率 | 代码已实现 | 待验收 | 按来源/渠道/统计周期聚合；转化率要求同来源、同渠道、同周期分子分母，零分母不计算 |
| EFFECT-06 | 单作品表现对比 | 代码已实现 | 待验收 | 已核验作品维度展示趋势和相邻等长周期变化；样本不足明确标注 |
| EFFECT-07 | 数据读取能力边界 | 代码已实现 | 待验收 | 区分作品读回、内容指标读取和经营结果读取；video.list 不冒充指标读取权限 |
| EFFECT-08 | 归因修订与撤销 | 代码已实现 | 待验收 | 原始归因快照保留，撤销原因/操作人/时间审计；可撤销后重新建立归因 |
| HOT-03 | 匹配算法解释与版本 | 代码已实现 | 待验收 | 行业/门店资料、服务区域、品牌规范参与评分；算法版本写入机会并进入上下文指纹 |

**职责边界**
- 账号运营监测：账号授权健康、作品登记、归属核验、数据同步状态。
- 经营效果：已核验作品表现、经营指标、数据口径与可信度。
- 同一作品记录可以被两处引用，但不重复定义指标。

## 4. 首页与信息架构（P1）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| IA-01 | AI 推荐营销主入口 | 代码已实现 | 待验收 | 直达热点机会工作台 |
| IA-02 | 按需制作入口 | 代码已实现 | 待验收 | 自然语言目标输入 |
| IA-03 | 主次入口关系 | 代码已实现 | 待验收 | AI 推荐营销为发现机会主入口；按需制作是明确目标时的次入口 |
| IA-04 | 任务列表不重复新建 | 代码已实现 | 待验收 | 新建从 AI 营销/热点采纳进入 |
| IA-05 | 管理端职责边界 | 代码已实现 | 待验收 | 不展示最近门店营销任务，不维护门店经营资料 |

## 5. 任务状态机与交互（P1）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| STATE-01 | 单一状态来源 | 代码已实现 | 待验收 | 任务状态与渲染规则已抽离至 task-renderers.js；热点决策并入策略步骤 |
| STATE-02 | 可跳过节点 | 部分实现 | 待验收 | 热点可选择不使用并填写原因；其他节点跳过机制尚未扩展，审核/发布不可跳过 |
| STATE-03 | 修改后的下游失效 | 代码已实现 | 待验收 | 需求/策略变化应使依赖内容、审核和质检失效 |
| STATE-04 | 发布包快照 | 代码已实现 | 待验收 | 冻结内容、策略、质检和商家确认信息 |

## 6. AI 模拟标识与能力边界（P0）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| SIM-01 | 需求理解模拟标识 | 已实现 | 待验收 | 页面已提示未调用真实大模型 |
| SIM-02 | 策略产出模拟标识 | 已实现 | 待验收 | 策略结果区域有明确本地模拟说明 |
| SIM-03 | 文案生成/整改模拟标识 | 已实现 | 待验收 | 文案工作室有明确本地模拟说明 |
| SIM-04 | 图片产出模拟标识 | 已实现 | 待验收 | 明确 SVG/占位预览，不是真实 AI 生图 |
| SIM-05 | 热点非实时标识 | 代码已实现 | 待验收 | 演示样例不得呈现为实时热点 |
| SIM-06 | 渠道本地预览标识 | 代码已实现 | 待验收 | 非官方规格校验、非真实发布 |

## 7. 多门店与数据隔离（P0）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| STORE-01 | 当前门店上下文 | 部分实现 | 待验收 | 当前 Demo 只有默认门店完整资料；未提供门店端完整切换，不得假设已完成 |
| STORE-02 | 门店数据隔离 | Demo 模拟实现 | 待验收 | localStorage 命名空间不等于生产服务端访问控制 |
| STORE-03 | 空门店状态 | 部分实现 | 待验收 | 任务列表严格按 storeId 过滤；其他经营资料仍为默认门店样例 |

## 8. 工程与可访问性（P2）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| ENG-01 | 页面渲染模块化 | 部分完成 | 不适用 | 任务、经营效果、门店资料页面已拆至独立 renderer 模块；AI 首页、热点、账号监测和管理端仍在 app.js/admin.js |
| ENG-02 | 重复代码清理 | 部分完成 | 不适用 | titleFor 的重复 store:channels 键已清理；仍需逐页清理重复事件监听和模板逻辑 |
| A11Y-01 | Tab 语义与键盘操作 | 代码已实现 | 待验收 | 任务与门店资料 Tab 增加 tabpanel 关联、方向键/Home/End；屏幕阅读器待验收 |
| A11Y-02 | 表单标签与错误提示 | 部分实现 | 待验收 | 通用 field/textarea/select helper 已关联 label/id；手写表单尚未全量审查 |
| A11Y-03 | 动态状态播报 | 部分实现 | 待验收 | toast 有 aria-live；步骤阻断和局部更新的播报仍需检查 |

## 9. 当前静态检查与未完成验收

### 已有证据
- 最近一次代码审查记录：四个 JavaScript 文件语法检查通过。
- 七个任务页签曾通过 mock DOM 烟雾测试，能渲染并触发导航/阻断说明。
- 账号运营监测页面曾通过 mock DOM 渲染检查。
- 本地存储曾通过命名空间持久化模拟测试。
- 当前代码中可见需求/策略门控和发布页校验条件。

以上是静态、mock 或代码路径证据，不得升级表述为真实浏览器测试。

### 尚未完成
- 全量业务交互的真实浏览器验收（路由/页面壳冒烟已接入 CI；完整业务流程仍未完成）。
- 七个任务页签逐一切换、刷新、前进/后退和状态恢复。
- 从需求创建到发布包冻结的完整端到端流程及各类阻断分支。
- 文案整改、图片上传/预览、版本恢复和渠道预览的真实浏览器操作。
- 门店切换后所有页面的数据隔离。
- 经营效果筛选、作品登记和账号运营页面交互。
- 桌面/移动端截图回归、键盘与屏幕阅读器基础测试。
- localStorage 配额失败、迁移和异常恢复的浏览器验证。
- OAuth、官方平台 API、真实模型、真实图片服务和真实发布联调。

**当前验收结论：Demo 具备部分代码实现与静态检查证据，但未完成真实浏览器 E2E，不通过正式验收。**

## 10. 生产服务接入缺口

- 真实 LLM 文案/策略生成和整改服务。
- 真实图像生成与编辑服务。
- 热点实时采集、来源追踪、去重和动态匹配。
- 平台 OAuth、作品 ID 核验、指标同步和真实发布。
- 经营数据接入及有证据的转化归因。
- 服务端认证、门店级授权、密钥托管、文件存储和审计保护。

不得以 Demo 模拟能力替代以上生产服务。


## 11. 本轮 P1/P2 实施追踪（2026-11-10）

| ID | 本轮实现 | 当前状态 | 仍需验证 |
|---|---|---|---|
| IA-03 | 首页将 AI 推荐营销设为第一入口；按需制作作为第二入口 | 代码已实现 | 浏览器视觉层级与移动端布局 |
| IA-06 | 快速开始改为目标模板预填，不再绕过商家确认直接创建任务 | 代码已实现 | 模板预填与表单值保持 |
| STATE-01 | 任务工作区渲染和状态规则拆至 task-renderers 模块；热点决策并入策略步骤状态 | 代码已实现 | 完整流程浏览器回归 |
| STATE-02 | 策略确认前必须选择“使用已关联热点”或“不使用热点”；跳过需记录原因 | 代码已实现 | 刷新恢复、修改决策后下游失效 |
| STORE-04 | schema v10 为历史任务补充默认门店归属，当前门店列表严格按 storeId 过滤 | 部分实现 | 完整门店资料切换与服务端隔离未实现 |
| ENG-01 | 任务工作区渲染/校验拆至 task-renderers.js，经营效果页面拆至 effect-renderers.js，门店资料页面拆至 store-renderers.js | 部分完成 | 后续按门店资料/经营效果继续拆分 |
| A11Y-01 | 任务 Tab 增加 tabpanel 关联、方向键/Home/End 键盘切换 | 代码已实现 | 屏幕阅读器与真实浏览器验证 |
| A11Y-02 | 通用 field/textarea/select helper 增加 label-for/id 关联 | 部分实现 | 手写字段逐页检查 |

本轮仍未执行真实浏览器 E2E。上述“代码已实现”不代表浏览器验收通过。


## 12. 本轮 UI/UX 收敛（2026-11-10）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| IA-07 | 首页 AI 推荐营销入口高度 | 代码已实现 | 待验收 | 压缩卡片内边距、标题字号和辅助说明，标题最大宽度控制在约两行；需桌面/移动端实测 |
| IA-08 | 提示词编辑独立二级页面 | 代码已实现 | 待验收 | 能力配置页保留业态分类和模板列表；编辑/新增进入独立编辑页，支持返回列表；保存创建新版本 |


## 13. UI/UX v2 整改追踪（2026-11-10）

| ID | 验收项 | 当前代码状态 | 浏览器验收状态 | 说明/缺口 |
|---|---|---|---|---|
| IA-09 | 首页主次入口与表单分离 | 代码已实现 | 待验收 | 首页只保留 AI 推荐营销主入口、任务摘要和按需制作入口；目标表单独立页面 |
| FLOW-11 | 任务步骤导航唯一 | 代码已实现 | 待验收 | 移除重复 stepper，统一在七步 Tab 中展示状态 |
| HOT-01 | 热点列表/详情分层 | 代码已实现 | 待验收 | 列表仅摘要，完整匹配分析与风险进入详情页 |
| STORE-05 | 门店资料字段职责去重 | 代码已实现 | 待验收 | 经营画像不再在档案页重复维护；品牌与客群字段各有维护位置 |
| DATA-01 | 门店任务/作品/报告查询范围 | 代码已实现 | 待验收 | 任务、作品、效果报告按当前门店任务 ID 过滤；非服务端权限隔离 |

| ACCOUNT-05 | 作品登记独立页面 | 代码已实现 | 待验收 | 账号监测列表不再内嵌长登记表单；登记页独立显示关联任务、平台账号、作品链接与发布时间 |
| STORE-06 | 商品/活动复杂编辑二级页面 | 代码已实现 | 待验收 | 商品与活动编辑独立于列表；支持保存返回、取消返回和刷新后按路由恢复编辑对象 |
| HOT-02 | 热点机会与当前门店商品匹配 | 代码已实现 | 待验收 | 热点列表仅展示匹配当前门店商品的机会，避免跨业态样例混入 |


## 14. PR #16 工程基础路由映射与浏览器冒烟（2026-11-11）

| ID | 验收项 | 当前状态 | 证据/边界 |
|---|---|---|---|
| ENG-DEMO-01 | Demo 页面、hash 路由、页面内 Tab 与二级编辑页映射 | 已形成文档 | 见 [DEMO_ROUTE_STATE_MAP.md](DEMO_ROUTE_STATE_MAP.md)，映射来自 `demo/app.js`、`demo/store-renderers.js`、`demo/admin.js` |
| ENG-DEMO-02 | 冻结 Demo 路由与页面壳 Chromium 冒烟 | **路由级冒烟已通过** | `apps/e2e/demo_smoke.py`；最新完整 CI Run [42938223781](https://github.com/dujiu1024-dotcom/Smart-Marketing/actions/runs/42938223781) 6/6 Job 通过；覆盖门店端一级路由、8 个门店资料 Tab、7 个任务步骤、平台管理一级/二级页面、商品/活动编辑和浏览器历史 |
| ENG-DEMO-03 | 完整业务流程与字段级浏览器验收 | 未完成 | 冒烟不验证完整表单提交、状态机正反路径、异常恢复、所有字段、移动端、可访问性或真实生产服务 |
| ENG-DEMO-04 | 冻结 Demo 正式验收 | 未通过 | 必须完成本矩阵 P0/P1/P2 适用项和真实浏览器证据；不得因路由冒烟通过而关闭 Issue #4 |

说明：本轮只补齐工程 PR 的 Demo 路由/页面状态对照和可重复的路由级浏览器门禁。生产 React 应用仍为工程壳；本 PR 不声称已将完整 Demo 迁移为生产 Web，也不声称 Demo 正式验收通过。


## 15. 最新浏览器路由冒烟结果（2026-11-11）

- CI Run [42937743402](https://github.com/dujiu1024-dotcom/Smart-Marketing/actions/runs/42937743402)，提交 `cf130673a216367025d840a66d87055f2f9cbe86`：Contracts、Web、API、Worker、Infrastructure 通过；E2E 失败。
- 失败步骤：`Run frozen Demo route and page-state browser smoke`。日志定位到 `apps/e2e/demo_smoke.py` 的平台管理一级页面循环，在 `#admin:capabilities` 路由等待页面标题超时。
- 根因：Demo 的管理端导航标签是“AI 能力配置”，但该页面真实 H1 是“AI 能力与提示词配置”；测试错误地将导航标签当作页面标题。不是页面路由无法打开，也不是商品/活动编辑器入口失败。
- 修复：E2E 标题断言改为页面实际 H1；`DEMO_ROUTE_STATE_MAP.md` 明确区分导航标签与页面标题。
- 新提交的 CI 结果尚待执行；修复未通过新一轮 CI 前不得标记 ENG-DEMO-02 通过。
- ENG-DEMO-03 完整业务流程/字段级浏览器验收仍未完成；ENG-DEMO-04 Demo 正式验收仍未通过。


## 16. 最新完整 CI 与 Demo 路由冒烟结果（2026-11-11）

- PR CI Run [42938223781](https://github.com/dujiu1024-dotcom/Smart-Marketing/actions/runs/42938223781)，head `eedbebca7968d12f2d2e20d1194bb7c1a9873e13`：6/6 Job 全部成功（Web、API、Worker、Contracts、Infrastructure、E2E）。
- Demo E2E 输出：`Frozen Demo Playwright smoke passed: 9 store routes, 8 store tabs, 7 task stages, 7 admin pages, admin detail pages, editors and browser history.`
- Infrastructure 完成完整 Compose 启动、API readiness、Web HTTP 和 PostgreSQL volume restart persistence 检查。
- 因此 ENG-DEMO-02 的“路由/页面壳冒烟”子项可标记通过；这不改变 ENG-DEMO-03 和 ENG-DEMO-04 的未完成状态。
- 完整业务流程、字段级交互、异常恢复、移动端/响应式、可访问性和冻结 Demo 正式验收仍未完成；Issue #4 不关闭。


## 17. #8 内容质检服务接入进度（2026-11-11）

| 能力 | 生产 API/Worker 状态 | Demo/浏览器状态 |
|---|---|---|
| 渠道内容快照 | PR #61 已合并；按已审核文案/图片版本创建快照 | 页面完整接入未完成 |
| 异步质检请求 | PR #62 开发中；使用 #9 Job + Outbox，要求 expected fingerprint | 页面入口、进度和错误反馈未接入 |
| 结构规则检查 | `content-structure-v1`：占位/空内容 hard fail；经营事实表达 needs_human | 规则说明和报告展示未接入 |
| 人工复核 | QualityResolution API 开发中；仅 needs_human 可追加决议，hard fail 不可覆盖 | 复核页面和角色权限验收未完成 |
| 质检报告新鲜度 | Worker 执行前校验 ChannelContent 指纹、当前文案/图片版本和独立审核 | 上游修改后 UI stale 状态未验收 |

说明：PR #62 的确定性规则不是 LLM 语义质检、图片 OCR/视觉检查或渠道官方规范校验；也不构成经营事实验证。PR CI 通过只证明本轮 API/Worker/构建/基础设施检查，不代表 Demo 的完整质量检查流程通过。发布包冻结、商家最终确认、真实浏览器业务流程仍未完成。


## 18. #8 发布包冻结与最终确认服务进度（2026-11-11）

| 能力 | 生产 API/DB 状态 | Demo/浏览器状态 |
|---|---|---|
| 多渠道发布包冻结 | PR #64 已合并至 main（57bfff114f6d5c3b043e81bd20ba6640489f33b4）；事务创建 Package/Items/FactRefs，覆盖任务/内容/质检/事实指纹 | 发布包页面完整接入未完成 |
| 事实门禁 | 要求已确认 BusinessFactSnapshot，追溯到最新有效 StoreRecordRevision | 事实引用与过期提示未接入 |
| 质检门禁 | hard fail 阻断；needs_human 必须有 accepted QualityResolution | 报告及复核交互未接入 |
| 商家最终确认 | fingerprint-bound PublishConfirmation，不可变、幂等 | 确认摘要/二次确认 UI 未接入 |
| 人工交付 | 仅 manual_handoff；确认不等于发布成功 | 下载/交付界面尚未实现 |
| 官方 API | 暂不支持；等待 #12 ChannelAccount/OAuth/Adapter 实际能力 | 不显示已连接或已发布状态 |

本阶段后端接口不会模拟官方发布，也不会因 Job 成功或商家确认显示“已发布”。PR #64 CI 已通过（API 119 tests、Worker、Web、Contracts、E2E、Infrastructure 全部成功），证明当前服务端冻结/确认门禁；不代表 Demo 完整流程或真实渠道发布验收通过。


## 2026-11-11 素材授权/归档后端门禁（PR #66 已合并至 main（commit `d2f0b5e839ba04676ae9f51e9f51a456d3540bfd`））

| 能力 | 后端状态 | Demo/浏览器状态 |
|---|---|---|
| 使用权确认 | 增加 hash + version 绑定、CSRF/门店授权/幂等；仅扫描通过资产可确认 | 商家授权说明与状态展示未接入 |
| 使用权限制 | `restricted` 记录后继续禁止下载 | UI 状态反馈未接入 |
| 资产归档 | 增加 If-Match + 幂等；品牌 Logo 引用中阻断；不物理删除对象 | 归档入口和引用提示未接入 |
| 恶意文件扫描 | 未实现；当前上传完成仅验证对象大小/MIME/SHA-256 并保持 quarantine/scanning | 不得展示为“已安全”或“可用” |
| 资产列表/预览 | 后端列表和 ready+rights 下载门禁已存在 | 素材库完整交互/缩略图未验收 |



## 19. #12 抖音首期替代验收基线（2026-11-11）

| 验收项 | 首期规则 | 当前状态 |
|---|---|---|
| 本地冻结包 | 系统内保存不可变发布包，包含文案、素材、渠道参数、版本指纹与校验结果；修改必须生成新版本并重新审核/质检 | #8 已合并；#12 冻结时绑定同门店抖音账号，账号 ID 进入 fingerprint；图文素材门禁已接入 |
| 商家最终确认 | 确认绑定门店、账号、操作者、时间与冻结包 fingerprint；未经确认不得发布 | #8 PublishConfirmation + #12 发布 API 精确校验已合并；React/Demo 真实 UI 流程待接入 |
| 官方发布 | 仅调用官方 OAuth/API；每次图文发布必须经过商家明确确认和 PublishOperation 幂等门禁 | OAuth/Secret Manager/ChannelAccount + 图文 API/Worker 已合并；仅图文 Worker 已实现，真实平台联调未执行 |
| 作品读回核验 | 用 item_id 和官方作品列表核验；发布接口响应不等于公开发布成功，读回未命中保持 processing | item_id 持久化与 video.list 读回 Worker 已合并；读回命中仍标 processing，等待平台审核结果；真实平台读回未执行 |
| 未知结果保护 | 超时/结果不确定时进入 needs_human；有 item_id 后重试只读核验，禁止盲目重复 create | Worker 已实现 submitting 门禁、未知结果人工处理及 readback-only 重试；自动化测试通过 |
| 账号与能力状态 | 门店渠道账号、授权范围、连接状态、能力状态、重新授权/断开 | 账号列表、OAuth、Token refresh 已实现；能力快照、断开/revoke 和 UI 未实现 |
| 抖音原生草稿箱 | 不作为首期阻塞条件；本地冻结包不得命名为抖音草稿 | 产品负责人已批准替代验收方案 |

本批准仅解除“抖音原生草稿箱 API 不可用”这一产品决策阻塞，不等于真实 OAuth、密钥托管、官方发布、作品读回或完整浏览器流程已经验收。MockTransport 测试不替代真实平台验收。


### PR #68 合并状态（2026-11-11）

抖音官方 OAuth/视频 API Adapter 已合并至 main（`9a417f30e4da74496ad8e65d70588d130ac51139`）。CI Run [42998696426](https://github.com/dujiu1024-dotcom/Smart-Marketing/actions/runs/42998696426) 6/6 jobs 通过，API 129 pytest passed。当前仅为可测试的服务端 Adapter；没有 OAuth state/Secret Manager/ChannelAccount/PublishOperation 的完整生产集成，也未完成真实应用审核、真实账号授权、视频上传/发布和作品读回。Issue #12 继续保持 Open。


## 2026-11-11 #9 门店级 Job 并发门禁（PR #69）

| 能力 | 后端状态 | Demo/运维状态 |
|---|---|---|
| 门店 running Job 配额 | Worker claim 阶段锁门店行并统计 running Job；默认每店 3 个，可配置 | 尚未提供门店级配置页面 |
| 容量满时退避 | 保持 queued、不消耗 attempt；同事务创建延迟 Outbox 事件重新投递 | 任务列表暂不展示“等待并发槽位”状态 |
| Provider/模型并发 | 未实现；ProviderDescriptor.max_concurrency 仍只是声明 | 未接入 |

该能力只完成首期门店级限流；不代表全局/队列/Provider 多维配额、成本预算、公平调度和完整故障注入验收已完成。


## 2026-11-12 #9 Worker 崩溃租约恢复（PR #74）

| 验收项 | 状态 |
|---|---|
| 过期 Worker lease fencing | 已有；迟到 heartbeat/complete 被拒绝 |
| Sweeper 将过期 Job 转为 needs_human | 已有；抽取为可独立测试的 domain service |
| Attempt lease_expired 与审计事件 | 已有；记录原 lease token，便于追踪 |
| 重复 Sweeper 不重复写恢复事件 | 新增集成测试覆盖 |
| 自动重试未知外部副作用 | 明确禁止；需人工对账确认后恢复 |

当前 PR CI 结果以 PR 检查为准；本地未执行。


## 2026-11-12 抖音发布调用审计

| 验收项 | 状态 |
|---|---|
| 图片上传 API Attempt 持久化 | 已实现 |
| 图文发布提交 Attempt 持久化 | 已实现；传输结果未知时不自动重发 |
| 发布作品读回 Attempt 持久化 | 已实现；HTTP transport failure 也会结束 Attempt |
| 抖音外部请求 ID（logid） | API 返回时持久化 |
| 真实账号授权、发布及读回 | 未执行；等待平台应用审核与授权账号 |

PR #93 已合并；PR #96 补齐读回传输异常的审计闭环。Mock/单元测试不能替代真实抖音平台验收。


## 2026-11-12 #6 门店档案生产 Web 首个页面（PR #98）

| 能力 | 当前状态 | 边界 |
|---|---|---|
| 登录 / Session | 接入 `/auth/login`、`/auth/me`、`/auth/csrf`、`/auth/logout` | Session Cookie HttpOnly；CSRF token 仅保存在当前 Tab 的 sessionStorage |
| 门店选择 | 接入 `/me/stores` 与 `/session/active-store` | 服务端再次校验 membership，所有资料请求携带 X-Store-ID |
| 门店档案读取 | 接入 `GET /store/profile` | 不存在时呈现真实创建态，不注入 Demo seed |
| 门店档案创建/编辑 | 接入 POST/PATCH、Idempotency-Key、If-Match 版本控制 | 保存后事实状态回到 pending_confirmation |
| 事实确认 | 接入 `POST /store/profile/{id}/confirm-facts` | 由当前登录门店成员显式确认并生成新版本 |
| 其他七个门店资料模块 | 未接入，页面明确标记待接入 | 不使用 localStorage 演示数据冒充服务端记录 |
| Demo 全量页面与导航 | 未完成 | 本 PR 仅接入门店档案，不代表完整 Demo 已生产化 |

该 PR 同时为 Vite 开发服务与 Compose Nginx 增加同源 `/api` 代理。CI 验收必须覆盖前端测试、构建、E2E 与 Infrastructure；本地测试未执行。


## 2026-11-12 #6 第二个生产 Web 页面：商品与服务

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 商品列表 | 接入门店隔离的 `GET /api/v1/store/products` | 按当前 X-Store-ID 读取，不使用 Demo seed |
| 商品新增 | 接入 `POST /api/v1/store/products` | Idempotency-Key；未知价格和币种均为 NULL |
| 商品编辑 | 接入 `PATCH /api/v1/store/products/{id}` | If-Match 乐观锁；编辑后生成新版本并重置为待确认 |
| 事实确认 | 接入 `POST /api/v1/store/products/{id}/confirm-facts` | 独立显式确认，确认版本可追溯 |
| 商品字段 | 名称、分类、SKU、规格、单位、价格/币种、供应状态、库存/产能、卖点、介绍、原料/材质、过敏原/限制、服务流程、交付方式 | 未知字段不填造值；价格金额与币种成对提交 |
| 页面路由 | `#store:products`；`#store-editor:product:new`；`#store-editor:product:<id>` | 对照 Demo 商品列表和独立二级编辑页 |
| 未完成 | 删除/归档的完整 UX、商品与活动关联、完整浏览器视觉/移动端验收 | 不据此关闭 Issue #6 |

本页通过真实 API 读写商品资料；事实状态和版本由服务端返回。CI 验收覆盖 Web、API、Worker、Contracts、E2E、Infrastructure；实际运行结果以该 PR 对应最新 CI 为准。


## 2026-11-12 #6 第三个生产 Web 页面：活动与优惠

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 活动列表 | 接入门店隔离的 `GET /api/v1/store/offers` | 只显示当前门店真实记录 |
| 活动新增 | 接入 `POST /api/v1/store/offers` | Idempotency-Key；规则/适用条件为结构化 JSON 对象 |
| 活动编辑 | 接入 `PATCH /api/v1/store/offers/{id}` | If-Match 乐观锁；新版本重置事实状态 |
| 事实确认 | 接入 `POST /api/v1/store/offers/{id}/confirm-facts` | 商家独立确认，确认动作写入版本与审计 |
| 优惠规则 | offer_type、terms_json、eligibility_rules_json、stacking_policy、usage_limit | 规则结构化保存，不把自然语言描述当作规则引擎执行结果 |
| 有效期 | ISO 8601 且必须显式带时区偏移；客户端归一化为 UTC | 列表明确显示 UTC；当前 UI 尚未读取 Store.timezone 并转换为门店本地时间 |
| 活动状态 | draft/active/paused/expired/archived | 可通过编辑归档；不提供物理删除入口 |
| 页面路由 | `#store:offers`；`#store-editor:offer:new`；`#store-editor:offer:<id>` | 对照 Demo 活动列表与独立二级编辑页 |
| 未完成 | 门店时区本地化展示、完整浏览器视觉/移动端验收 | 不据此关闭 Issue #6 |

该页已接入真实 Offer API；CI 验收覆盖六组工作流。门店本地时区展示仍是明确缺口，不将 UTC 展示伪称为本地时间。


### PR #105 代码审查补充

- 优惠类型已按 `discount_percent`、`discount_amount`、`fixed_price`、`buy_x_get_y`、`gift`、`threshold_discount` 提供结构化字段，并校验对应必填数值。
- 买赠与赠品规则通过当前门店真实商品清单选择 Product ID；不要求商家手工输入 UUID。
- 创建幂等键在同一编辑草稿的重试期间保持稳定；未保存修改时禁止确认旧版本事实。
- 活动使用 `archived` 状态归档，不提供物理删除入口。


## 2026-11-12 #6 品牌规范生产 Web 接入

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 品牌规范读取/创建 | GET/POST /api/v1/store/brand-guideline | 当前门店范围；首次 404 进入真实创建态 |
| 品牌规范编辑 | PATCH /api/v1/store/brand-guideline | If-Match 乐观锁，保存生成新版本 |
| 品牌事实确认 | POST /api/v1/store/brand-guideline/{id}/confirm-facts | 独立商家确认；未保存修改时禁止确认 |
| 品牌字段 | 故事、定位、差异化、价值观、语气、常用/禁用表达、CTA、视觉风格、字体、色彩、Logo 资产引用 | 色彩为 JSON 对象数组；Logo 仅保存 asset ID，不伪造上传/选择能力 |
| 创建重试 | sessionStorage 保存本次创建 Idempotency-Key | 请求不确定时重试复用同一 key |
| 未完成 | Logo 资产选择器、门店本地时区、客群/知识/素材/渠道模块、完整浏览器与移动端验收 | 不据此关闭 Issue #6 |

## 2026-11-12 #6 客群与经营生产 Web（PR 待验收）
| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 客群列表/读取 | GET /api/v1/store/audiences | 当前门店隔离；不使用 Demo seed |
| 客群创建 | POST /api/v1/store/audiences | Idempotency-Key |
| 客群编辑/删除 | PATCH/DELETE /api/v1/store/audiences/{id} | If-Match 绑定 current_version |
| 事实确认 | POST /api/v1/store/audiences/{id}/confirm-facts | 独立显式确认；未保存编辑时禁止确认 |
| 经营画像字段 | 客群类型、描述、消费场景/时段、购买动机、常见异议、来源、样本量、采样时间、置信等级 | 未知样本量/置信度保持空白 |
| 页面路由 | #store:audience；#store-editor:audience:new；#store-editor:audience:<id> | 与 Demo 门店资料客群 Tab 和二级编辑页对应 |
| 未完成 | 客群与商品/优惠关联、真实 POS/CRM 数据源准入、完整浏览器与移动端/可访问性验收 | 不据此关闭 Issue #6 |


### 客群页面代码审查补充

- 客群创建使用 sessionStorage 保持本次编辑草稿的 Idempotency-Key，网络结果不确定时重试复用相同 key。
- `sampled_at` 必须显式提供 ISO 8601 时区偏移并归一化 UTC，不假设浏览器时区等于门店时区。
- 客群事实确认在编辑器存在未保存修改时禁用；不存在或不属于当前门店的记录不会退化为创建表单。


## 2026-11-12 #6 门店知识库生产 Web 接入（PR 待验收）

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 知识列表 | GET /api/v1/store/knowledge | 当前门店上下文；空态与错误态明确 |
| 知识创建 | POST /api/v1/store/knowledge | 稳定 Idempotency-Key；内容文本或内容引用至少填写一项 |
| 知识编辑/删除 | PATCH/DELETE /api/v1/store/knowledge/{id} | If-Match 绑定 current_version；删除为显式操作 |
| 事实确认 | POST /api/v1/store/knowledge/{id}/confirm-facts | 独立确认；未保存修改时禁止确认 |
| 知识字段 | 标题、分类、文本/引用、SHA-256、来源、有效期 | 时间必须带显式时区偏移并归一化 UTC；失效时间晚于生效时间 |
| 页面路由 | #store:knowledge；#store-editor:knowledge:new；#store-editor:knowledge:<id> | 与 Demo 门店资料知识库列表和独立二级编辑页对应 |
| 未完成 | 原始文件/素材资产上传与引用选择、知识检索消费接入、门店本地时区展示、完整浏览器/移动端/可访问性验收 | 不据此关闭 Issue #6 |

该实现接入现有 Store Knowledge API，不引入本地 Demo 数据；知识事实只有在商家显式确认后才可作为已确认经营上下文。

## 2026-11-12 #6 素材资产库生产 Web 接入

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 素材列表 | GET /api/v1/store/assets | 当前门店隔离，按服务端记录读取 |
| 上传 | SHA-256 本地计算 → upload-intent → 私有对象存储预签名 PUT → complete | 仅 JPEG/PNG/WebP，单张不超过 25 MB；稳定幂等键和 intent ID 保存在 sessionStorage 以恢复中断上传 |
| 服务端校验 | HEAD 元数据 + 完整对象 SHA-256 对照；Worker 重新下载并复核大小/SHA-256 | 对象存储不可用时不写入 ready |
| 使用权确认 | POST /api/v1/store/assets/{id}/confirm-usage-rights | 必须扫描 ready，绑定 version + SHA-256 + 商家来源说明；允许/限制均明确记录 |
| 原图下载 | GET /api/v1/store/assets/{id}/download-url | 仅 ready + confirmed_allowed，使用短期签名 URL；页面不持久化 URL |
| 归档 | POST /api/v1/store/assets/{id}/archive | If-Match + Idempotency-Key；不物理删除，品牌 Logo 当前引用会阻止归档 |
| 存储端点 | 内部 S3 endpoint 与浏览器可访问 presign endpoint 分离 | Compose API 使用 seaweedfs:8333；浏览器签名 URL 使用 localhost:8333；SeaweedFS 仅允许本地 Web origin CORS |
| 未完成 | 缩略图/完整图像解码、过期 UploadIntent sweeper、素材与商品/任务/Logo 关联选择器、真实对象存储浏览器联调 | 哈希/MIME 校验不是恶意文件扫描；扫描服务必须 fail-closed |

CI 将覆盖 Web/API/Worker/Contracts/E2E/Infrastructure；本次 GitHub 操作环境未执行本地命令，最终以 PR CI 为准。真实对象存储浏览器 PUT、CORS 和预签名 URL 仍需环境级验收。


## 2026-11-12 #7 营销任务生产工作区（PR 待验收）

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| AI 营销入口 | `#ai`；按需制作可用，营销机会入口明确标记数据源接入中 | 不展示虚构热点或模拟推荐 |
| 任务列表 | `#tasks`；当前门店列表、状态筛选、任务版本和阻塞数 | 所有读取由服务端门店上下文隔离 |
| 新建任务 | `#create`；完整营销、仅文案、仅图片、图片优化、商家已有素材 | 类型与内容范围校验；创建幂等；渠道选择和外部交付范围明确 |
| 任务详情 | `#task`；服务端固定 10 步状态、阻塞原因、版本与输出引用 | 当前任务 ID 仅保存在当前浏览器 session 的导航状态，不作为业务数据 |
| 需求确认 | 编辑结构化需求；选择门店已确认且未过期的档案、商品、活动、品牌、客群、知识事实 | 事实版本号显式提交；服务端冻结不可变快照 |
| 策略确认 | 等待异步 Worker 生成；仅在 waiting_for_user 状态提供编辑与确认 | 不在前端伪造策略；AI Provider/真实生成仍由 Issue #10 验收 |
| 步骤决策 | 可选步骤跳过、失败/过期/等待步骤恢复；任务取消/归档 | 所有操作带 expected_version、Idempotency-Key 和服务端原因校验 |
| 未完成 | 文案/图片产物生产与审核、质检、渠道适配、发布包和真实发布 UI、热点机会入口 | 由 Issue #8/#10/#11/#12 继续实现；Issue #7 不关闭 |


## 2026-11-12 #6 素材隔离扫描 Worker（当前主干重基线 PR）

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 隔离素材调度 | Celery Beat 每 15 秒调度 `media.scan_quarantined_assets` | Worker 周期重试；PostgreSQL 行锁和事务保证并发安全 |
| 对象完整性 | 重新下载私有对象，校验实际大小和 SHA-256 | 对象存储不可用时事务回滚，不写入 ready |
| 文件类型/尺寸 | PNG/JPEG/WebP 文件头检查；单边不超过 8000px、总像素不超过 4000 万 | 不等同完整图像解码或缩略图生成 |
| 恶意文件扫描 | ClamAV INSTREAM；明确 OK 才进入 ready，FOUND 进入 rejected | 服务不可用、超时或未知响应均 fail-closed，保持隔离等待重试 |
| 部署 | Compose 增加内网 ClamAV 和持久化签名卷；Worker/Scheduler 指向 clamd；不发布宿主机扫描端口 | StreamMaxLength=30M 覆盖 25 MiB 上传上限；生产需等价私有扫描服务和签名更新 |
| 过期 UploadIntent 清理 | PR #132 已合并；Worker 每 5 分钟清理过期意向和私有隔离对象，存储失败可重试 | 不等同完整解码/缩略图或真实浏览器上传 E2E |\n| 未完成 | 完整解码/缩略图、真实对象存储与 ClamAV 浏览器端到端联调 | Issue #6 继续 Open |


## 2026-11-12 #12 抖音门店账号 Web 接入（PR #129 已合并；真实 OAuth 待验收）

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 门店渠道入口 | `#store:channels` 接入门店资料导航 | 不新增渠道管理中心 |
| 官方 OAuth | Web 调用 `POST /api/v1/channels/douyin/oauth/authorize`，展示服务端返回授权链接 | 只使用官方 OAuth；应用凭据/Secret Manager 未配置时明确显示服务端错误，不创建模拟账号 |
| 账号列表 | 读取当前门店 Douyin ChannelAccount，显示外部账号 ID、授权范围、状态和到期时间 | Token 不返回前端；后端按当前门店隔离 |
| 授权刷新 | 账号 active 时可请求服务端重新验证/刷新 Token | 不显示已发布；真实 OAuth、scope 和发布读回仍需账号验收 |
| 未完成 | 断开/撤销 UI、能力快照、ChannelSpecVersion 管理/发现、内容适配、真实授权/发布 E2E | Issue #12 继续 Open |


## 2026-11-12 #8 文案/图片产物与版本审核 Web 接入（PR #130 已合并；完整内容闭环待验收）

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 文案产物 | 营销任务详情可手动编辑并创建 copy Artifact/ArtifactVersion | 明确标记商家手动编辑，不伪装为 AI 生成 |
| 图片产物 | 从当前门店素材中选择 ready 且 confirmed_allowed 的素材创建 image ArtifactVersion | 来源 MediaAsset 不被覆盖；图片二进制仍由私有对象存储管理 |
| 版本管理 | 修改已存在产物时创建不可变新版本；展示当前版本与版本历史 | 审核必须绑定当前精确版本；旧版本审核不继承 |
| 双审核 | 文案/图片分别提供通过、要求修改、拒绝；要求修改必须填写意见 | API 服务端校验 review_type、expected_version 和 revision comment |
| 未完成 | AI Provider 生成/图片编辑、渠道规格选择与 ChannelContent 适配、质检报告/人工复核、发布包冻结/最终确认/人工交付 UI | 由 #10/#12 及后续 #8 PR 完成；Issue #8 不关闭 |

Web 单元测试覆盖手动文案产物创建和精确版本审核请求；真实 AI 生成与完整发布浏览器链路未在本 PR 中实现。


## 2026-11-12 #12 ChannelSpec/ChannelSpecVersion/CapabilitySnapshot 数据层（PR #131 已合并；真实能力核验待完成）

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| ChannelSpec | 平台级 channel_key 唯一目录，current_version_id 复合外键确保指向同一 Spec 的版本 | 不含 store_id；规格更新不可覆盖历史 |
| ChannelSpecVersion | 不可变版本，保存文本/媒体/标签/链接/排期约束、草稿/发布能力、来源引用和 verification_status | 初始 Douyin v1 明确 pending_verification，能力 false、来源为空，不声称官方规则已核验 |
| ChannelCapabilitySnapshot | 门店账号级能力历史快照，复合外键约束同店账号和精确 SpecVersion | 当前仅完成数据模型/迁移，探测 Worker/API 尚未接入 |
| ChannelContent | channel_spec_version_id 增加外键，旧记录迁移时保留原 UUID 并创建 pending legacy spec/version；创建适配快照时强制校验同渠道且 verification_status=verified | pending/deprecated 规格返回明确阻断，不允许生成渠道适配内容 |
| API/UI | 门店渠道页面展示当前规格版本、来源与核验状态；新增门店认证后的规格目录/版本只读 API | 只读；规格维护和真实能力探测仍未完成 |


## 2026-11-12 #8 渠道适配、质检和最终确认 Web 闭环（PR #134 已合并）

| 能力 | 当前实现 | 验收边界 |
|---|---|---|
| 渠道适配 | 任务详情展示 ChannelSpec 核验状态；基于已审核当前文案/图片版本创建 ChannelContent | pending/unverified 规格在 UI 和服务端均阻断 |
| 质检 | 提交异步结构质检，展示最新报告；needs_human 可提交带理由的 accepted 决议 | 不冒充 AI 语义/视觉质检，硬失败不可接受 |
| 发布包 | 选择最新已确认经营事实快照，冻结渠道内容、质检报告和交付模式 | 当前 UI 仅开放 manual_handoff；official_api 需真实账号和权限前置 |
| 最终确认 | 展示不可变包指纹并确认精确版本，记录确认备注 | 确认不等于外部平台发布成功；执行仍由 #12 负责 |
| 未完成 | 真实 AI 生成/图片编辑/视觉质检、官方规则核验、真实账号浏览器验收 | Issue #8 继续 Open |


## 范围排除：视频生产与发布（2026-11-12）

Demo 与生产验收只覆盖视频脚本文本生成、图片生成/编辑和图片图文发布。不得出现可操作的视频生成、剪辑、合成、渲染、上传、草稿或发布控件；不得以静态示意页面表现这些能力。视频脚本应以文本编辑/审核交付，不作为媒体文件。抖音首期验收对象仅为图片图文发布。
