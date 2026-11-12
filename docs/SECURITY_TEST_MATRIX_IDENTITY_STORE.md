# Identity & Store Security Test Matrix（Issue #5）

> 状态：完整安全场景设计矩阵。PR #141 已补充并执行部分跨店 API/Worker 测试；具体通过证据与未覆盖缺口以本文“当前实现与覆盖盘点”和 PR CI 为准，不将未执行场景标记为通过。
> 工具：pytest + HTTPX + PostgreSQL integration + Playwright；不得用 SQLite 冒充生产数据库行为。

## 测试夹具

- Store A：Alice（owner）、Bob（member）。
- Store B：Carol（owner）。
- 无门店用户 Dave；可选独立 PlatformAdmin。
- A/B 各有任务、商品、活动、文案/图片资产、发布包、Job、效果记录。
- 使用真实 PostgreSQL migration 和真实认证中间件路径。

对跨门店访问，预期与随机不存在 ID 相同的 404；不得产生写入、Job、文件签名或 Provider 副作用。拒绝事件需写脱敏审计。

## A. 认证与 Session

| ID | 场景 | 操作 | 预期 |
|---|---|---|---|
| AUTH-01 | 匿名访问 | 无 Cookie 调用受保护 API | 401，无业务副作用 |
| AUTH-02 | 无效 token | 随机/篡改 Cookie | 401，不泄露 Session 是否存在 |
| AUTH-03 | Session 过期 | idle/absolute expiry 已过 | 401，清 Cookie |
| AUTH-04 | Session 撤销 | 撤销后重放旧 Cookie | 401 |
| AUTH-05 | User 禁用 | 禁用后重放有效 Session | 401 |
| AUTH-06 | 全设备失效 | logout-all 后重放旧 Session | 401 |
| AUTH-07 | Token 轮换 | 登录/改密/权限提升后重放旧 token | 旧 token 401，新 token 正常 |
| AUTH-08 | Token 不落库 | 检查 DB 与日志 | 仅 verifier；日志无 token/Cookie |
| AUTH-09 | Cookie 属性 | 检查 Set-Cookie | Secure、HttpOnly、SameSite=Lax、Path=/、无 Domain |
| AUTH-10 | 登录枚举 | 不存在邮箱与错误密码 | 相同状态码与通用文案 |
| AUTH-11 | 暴力尝试 | 超过限流阈值登录 | 429 |
| AUTH-12 | CSRF 缺失 | 无 CSRF header 执行写请求 | 403，数据不变 |
| AUTH-13 | CSRF/Origin 错误 | 错 token 或非法 Origin | 403，数据不变 |
| AUTH-14 | CORS 凭据 | 非白名单 Origin | 不返回允许凭据的 CORS 响应 |

## B. 门店上下文与成员关系

| ID | 场景 | 操作 | 预期 |
|---|---|---|---|
| STORE-01 | 无当前门店 | 已登录但缺少 X-Store-ID 访问业务 API | 400 STORE_CONTEXT_REQUIRED |
| STORE-02 | 合法切换 | A 用户切换到其另一 active membership 门店 | 200，更新 UI 默认选择并审计 |
| STORE-11 | 请求门店伪造 | A 用户发送 B 的 X-Store-ID | 404；不能仅凭 header 访问 B |
| STORE-12 | 多标签页独立上下文 | 同一 Session 的 Tab 1 使用 A、Tab 2 使用 B（若用户均为成员） | 每个请求按各自 X-Store-ID 授权；切换默认门店不改变另一标签页上下文 |
| STORE-13 | 请求缺少门店选择器 | 用户不发送 X-Store-ID（即使 Session.active_store_id 有值） | 400 STORE_CONTEXT_REQUIRED |
| STORE-14 | 默认选择非授权 | Session.active_store_id 指向已撤销 membership 的门店 | X-Store-ID 仍须重新验证 membership 并拒绝；active_store_id 不构成授权 |
| STORE-03 | 非成员切换 | A 用户切换到 B | 404，原上下文不变 |
| STORE-04 | 已撤销成员切换 | membership removed 后切换该店 | 404 |
| STORE-05 | 即时撤销 | 移除当前门店成员后继续请求 | 后续请求拒绝，无长缓存窗口 |
| STORE-06 | 门店停用 | suspended Store 成员访问业务 API | 不返回数据，统一不可访问策略 |
| STORE-07 | 伪造角色 | 请求传 role=owner | 不影响服务端角色；越权操作 403 |
| STORE-08 | 伪造用户 | 请求传其他 user_id | 不改变 AuthContext |
| STORE-09 | 注入租户字段 | 请求传 tenant_id/org_id | 不形成授权 |
| STORE-10 | 最后 owner 保护 | 移除/降级最后 active owner | 409，事务回滚 |

## C. IDOR 与跨门店资源（A→B、B→A）

| ID | 资源/操作 | 攻击方式 | 预期 |
|---|---|---|---|
| IDOR-01 | 任务列表 | 修改 query store_id | 只返回当前门店数据 |
| IDOR-02 | 任务详情 | task_id 替换为 B 资源 | 404，不泄露存在性 |
| IDOR-03 | 任务更新/删除 | 替换路径 ID/body resource ID | 404，B 数据不变 |
| IDOR-04 | 商品/活动 | 列表、详情、编辑、删除换 ID | 跨店 404，无副作用 |
| IDOR-05 | 文案/图片版本 | 猜测 artifact/version ID | 404，不返回内容/元数据 |
| IDOR-06 | 发布包/发布动作 | 替换 package/operation ID | 404，不触发发布 |
| IDOR-07 | 渠道账号 | 替换 channel_account_id | 404，不泄露授权状态 |
| IDOR-08 | 效果/作品 | 替换 report/work ID | 404，不返回指标 |
| IDOR-09 | 文件下载 | 替换 asset_id/object_key | 不签发 URL，拒绝下载 |
| IDOR-10 | 上传完成回调 | 替换 upload/asset ID | 归属失败，不关联对象 |
| IDOR-11 | 搜索/导出 | 注入 store_id/resource ID | 结果严格限定当前门店 |
| IDOR-12 | 批量操作 | 混入 A+B 资源 ID | 整批失败，所有数据不变 |

## D. Job / Worker

| ID | 场景 | 攻击方式 | 预期 |
|---|---|---|---|
| JOB-01 | Job 创建门店注入 | 客户端提交 B store_id | 服务端从 AuthContext 写 A |
| JOB-02 | Job 详情 | A 用户读取 B job_id | 404 |
| JOB-03 | Worker 归属不一致 | Job.store=A，关联资源.store=B | 拒绝执行，不调用 Provider |
| JOB-04 | 重放任务 | 重复 idempotency_key | 不产生重复副作用 |
| JOB-05 | 成员撤销后执行 | Job 创建后撤销成员 | 执行前重新校验策略 |
| JOB-06 | 伪造 actor | payload actor_user_id 替换 | 以持久化可信 actor 为准 |

## E. 文件、缓存、审计、并发

| ID | 场景 | 操作 | 预期 |
|---|---|---|---|
| SEC-01 | 缓存串店 | A/B 同 URL 或短 ID | Cache key 含服务端 store scope |
| SEC-02 | 并发切店 | 同 Session 不同标签页分别发送不同 X-Store-ID，并发读资源 | 每个请求只使用自身 request-scoped AuthContext，无跨请求上下文污染 |
| SEC-11 | 切换默认门店竞争 | 并发调用 active-store 与业务 API | 业务授权由本次 X-Store-ID 决定，不受默认值写入时序影响 |
| SEC-03 | TOCTOU | 授权后并发撤销再更新 | 事务/条件更新阻止越权写入 |
| SEC-04 | RLS 上下文泄漏 | 若启用，连接池复用不同 store | SET LOCAL 不跨事务 |
| SEC-05 | 审计完整性 | 登录、切换、撤销、越权 | 记录 actor/store/action/result/request_id，不含 secret |
| SEC-06 | 审计不可篡改 | 普通 DB role 修改/删除审计 | 拒绝 |
| SEC-07 | 错误侧信道 | 对比不存在 ID 与跨店 ID | 状态码/响应结构一致 |
| SEC-08 | 授权依赖故障 | DB 不可用 | 503，fail closed |
| SEC-09 | 直接对象访问 | 访问公开 bucket/object URL | bucket 私有，未签名不可读 |
| SEC-10 | 日志脱敏 | 注入测试 token/password/Cookie | log/trace/error report 无原值 |

## CI 门禁

- 每次 PR：认证/授权单元测试、API contract tests、PostgreSQL 集成测试、lint/type check。
- 每次 PR 最低覆盖：AUTH-01/03/04/09/12/13；STORE-03/05/06/07；IDOR-01 至 IDOR-12；JOB-01/03；SEC-01/07/08。
- Playwright smoke：登录 → 门店列表 → 合法切换 → 数据刷新 → 非成员切换失败 → 登出 → 旧 Cookie 失效。
- 夜间/发布前：完整 IDOR、并发撤销、文件授权、RLS（若启用）、审计权限测试。
- 每个跨店拒绝用例断言 HTTP 结果、数据库无变更、无 Job/Provider/签名 URL 副作用。
- 使用隔离 fixture；禁止在生产数据上执行破坏性测试。

**注意：** A–G 是目标安全覆盖清单，不代表每个场景都已自动化。PR #141 的实际覆盖只以已提交测试和通过的 CI 结果为准；表格中仍列出的缺口继续保持待补状态。


## F. 平台管理员与成员管理边界

| ID | 场景 | 操作 | 预期 |
|---|---|---|---|
| ADMIN-01 | 合法成员管理 | 有 platform.store_members.manage 的管理员查看门店成员最小字段 | 允许并写审计 |
| ADMIN-02 | 门店 owner 越权管理成员 | owner 调用邀请/移除/角色变更 API | 403，无数据变化 |
| ADMIN-03 | 普通 member 越权管理成员 | member 调用成员管理 API | 403，无数据变化 |
| ADMIN-04 | 平台管理员读取门店内容 | 管理员尝试读取任务正文、文案、图片或经营资料 | 默认拒绝，不因成员管理能力扩权 |
| ADMIN-05 | 平台管理员跨域操作 | 管理员调用门店营销业务 API 且无 StoreMembership | 404，不因平台管理员身份绕过门店授权 |
| ADMIN-06 | 最后 owner 保护 | 管理员移除/降级最后 active owner | 409，事务回滚 |
| ADMIN-07 | 管理字段最小化 | 检查成员管理响应 | 不返回营销内容、素材内容、价格/经营数据或凭据 |


## G. Platform Admin 授权边界

| ID | 场景 | 操作 | 预期 |
|---|---|---|---|
| ADMIN-08 | 无平台授权 | 普通 User 调用 /admin/stores/{id}/members | 403 |
| ADMIN-09 | 平台授权撤销 | 撤销 PlatformAdminGrant 后重放 Session | 403，无成员数据返回 |
| ADMIN-10 | 平台成员管理范围 | 管理员读取成员关系最小字段 | 允许；响应不含业务资料/营销内容 |
| ADMIN-11 | 平台身份不能访问门店业务 | 管理员无 StoreMembership，调用门店任务/素材 API | 404 |
| ADMIN-12 | 邀请流程未冻结 | 调用尚未启用的邀请端点 | 不得返回成功；明确功能未启用 |


## 当前实现与覆盖盘点（2026-11-12，Issue #135 审计）

以下是代码存在性盘点，不代表每个场景已在当前 PR 的 CI 中通过，也不代表完整矩阵覆盖。

| 领域 | 主干已有自动化证据 | 尚未证明完整的缺口 |
|---|---|---|
| 认证 / Session | `test_identity.py` 覆盖登录 Cookie/CSRF、登录限流、Session 过期/撤销、登出全部设备、密码轮换、双标签页请求门店上下文、成员撤销即时生效、审计追加写 | 匿名与无效 Cookie 全矩阵、禁用用户、token 轮换边界、CORS 凭据、所有 Origin/CSRF 组合仍需逐项核验 |
| 门店上下文 / 成员 | `test_identity.py` 覆盖请求级门店选择器、非成员门店拒绝、双标签页隔离、成员撤销后拒绝 | PR #141 增加门店 suspended 后下一请求立即拒绝并写审计的测试；成员角色变更、最后 owner、并发撤销与 TOCTOU 的完整组合仍需补证 |
| 门店资料 / 商品 / 活动 / 素材 | `test_store_knowledge_api.py` 覆盖资料跨店读取/更新、商品跨店读取/更新/删除、活动/知识/客群跨店读取/更新/删除、素材列表/上传完成/下载跨店拒绝及无权限对象不泄露；覆盖方向以测试断言为准 | 其余资源批量路径、完整 A→B 与 B→A 对称矩阵、上传回调的无副作用断言仍需补齐 |
| 营销任务 | `test_marketing_task_api.py` 覆盖任务列表/详情门店隔离、跨店取消/归档拒绝、创建幂等、确认快照、恢复/取消/归档 | PR #141 增加跨店取消/归档拒绝；路径 ID 与 body ID 混用、创建后成员撤销、并发操作及所有状态转换的资源级 IDOR 仍需补齐 |
| 内容版本 / 审核 | `test_content_delivery_api.py`、`test_content_delivery_models.py` 覆盖版本绑定、审核版本绑定和同店约束；PR #141 覆盖 Artifact 列表、版本创建和审核写入的跨店 404/无写入，并新增 Artifact ID + Version ID 交叉替换攻击测试（外部门店任务/Artifact + 他店 Version）及无版本/审核/Outbox 写入断言 | 当前没有单独的 Artifact 或 Version 按 ID GET 详情端点；版本内容通过门店隔离后的 Artifact 列表返回。恢复/批量路径和完整双向资源组合仍需按实际新增 API 扩展 |
| 质检 / 发布包 | `test_content_quality_api.py`、`test_publish_package_api.py` 覆盖文案审核门禁、幂等、质检阻断、已确认事实和发布包约束；PR #141 覆盖发布包列表/冻结/确认跨店拒绝，并新增冻结请求中的 BusinessFactSnapshot、ChannelContent、QualityReport、ChannelAccount 跨店 ID 替换拒绝及无发布包/确认写入断言；同时覆盖已存在 PublishOperation 的跨店读取 404 与本店读取 200 | PublishOperation 创建流程中 package-item ID 的独立替换组合、完整双向关联矩阵和真实渠道账号撤销后读写仍需结合实际 API/真机验收持续补充 |
| 渠道账号 / Provider | `test_channel_spec_api.py`、`test_channel_delivery_security.py`、抖音 Adapter/Webhook 测试覆盖渠道规格授权、密钥存储、OAuth state、发布确认和回读核验；PR #141 增加 ChannelAccount 列表过滤、capability 跨店 404/凭据不泄露及 refresh 跨店拒绝测试 | 账号列表/capability/refresh 的跨店拒绝已有测试；授权撤销后的访问矩阵、OAuth 回调归属和真实渠道权限仍需真机验收 |
| Job / AI Invocation | `test_job_runtime_api.py`、`test_ai_invocation_service.py` 覆盖 Job 和 AI Invocation 门店范围、跨店取消/重试/人工恢复拒绝；`test_job_runtime_service.py` 覆盖幂等、租约 fencing、超时恢复、重复投递相关服务规则和未知副作用 | Job 创建后成员撤销、资源归属不一致、Worker 执行前权限重验及所有操作的完整 API 越权矩阵仍需补齐 |
| 日志 / Trace | `test_observability.py`、`test_tracing.py`、`test_health.py` 覆盖递归敏感字段脱敏、Trace 导出、请求 ID 和错误响应 | PR #141 增加 Worker JSON 日志、job correlation_id、递归敏感字段脱敏和告警 webhook 单元测试；Cookie/Token/个人数据在所有 Trace、Provider 错误和端到端 Worker 路径的脱敏仍需补证 |
| 经营指标 | 当前 API 代码树未发现门店经营指标/效果数据资源端点；现有 Demo 效果数据为本地模拟 | 目前无后端经营指标资源可执行 IDOR 测试；未来新增 API 必须以 StoreMembership 和 store_id 做服务端授权，不得依赖前端过滤 |
| 文件 / 缓存 / 并发 | `test_object_storage_download.py` 与素材 API 测试覆盖部分下载和素材授权边界 | 缓存串店、对象直链、连接池上下文泄漏、并发切店、授权后撤销再写入等场景仍需自动化验证 |

### Issue #135 本轮 E2E 状态

- 原有 `apps/web/e2e/smoke.py` 只验证生产 Web 登录入口，不是完整营销业务 E2E。
- 原有 `apps/e2e/demo_smoke.py` 主要验证 Demo 路由、Tab、编辑页和浏览器历史，不覆盖完整业务提交流程。
- PR #141 在 `apps/e2e/demo_smoke.py` 增加需求/策略门禁、文案整改及审核、图片整改/依赖失效及重新审核、渠道预览、质检、最终确认、同版本重复冻结幂等、刷新恢复、移动视口和键盘 Tab 导航。该测试使用本地 Demo 模拟能力，不代表生产 React/API、真实 LLM、生图服务或官方平台发布已完成；以 PR CI 实际结果为准。

### 生产运维质量门禁状态

- 主干已有 JSON 结构化日志、请求 ID、OpenTelemetry Trace、递归脱敏及健康检查。
- Issue #135 分支新增 PostgreSQL custom-format 备份与显式确认恢复脚本，并在 CI Infrastructure Job 中加入备份/变更/恢复/校验演练、目录/文件权限和未确认恢复拒绝测试。
- Worker 已增加 provider.failure、channel.delivery.failure、job.timeout、worker.unexpected_failure、worker.expired_leases_recovered、outbox.dead_letter 等结构化告警事件；可通过 OPS_ALERT_WEBHOOK_URL 向外部接收器发送脱敏 JSON。部署/备份/恢复步骤见 `docs/PRODUCTION_OPERATIONS_RUNBOOK.md`。
- 生产告警接收器、路由/升级策略和通知送达仍依赖部署环境配置；本仓库没有真实生产 webhook 凭据，也未执行生产 Provider/渠道/消息队列故障演练。
