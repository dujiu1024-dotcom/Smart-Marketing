# Identity & Store Security Test Matrix（Issue #5）

> 状态：测试设计/准备，全部未执行。实际命令、结果和证据待工程骨架验收后补录。
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

**当前全部用例待执行。** 工程基础未验收前，不记录虚构命令、结果或安全通过结论。


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
