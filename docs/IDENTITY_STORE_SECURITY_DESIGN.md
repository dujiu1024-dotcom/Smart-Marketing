# 身份认证与门店安全设计（Issue #5）

> 状态：设计评审稿，不代表生产实现。日期：2026-11-11。
> 基线：产品 v1.8；React SPA + FastAPI 模块化单体 + PostgreSQL；技术选型见 TECH_STACK_SELECTION.md。
> 前置：Issue #4 工程骨架尚未完成验收。本分支只交付设计和测试准备，不接入认证实现。

## 1. 目标与非目标

建立可撤销的服务端身份会话，以及以 StoreMembership 为唯一授权事实来源的门店隔离。所有门店业务 API 必须认证用户、解析当前门店成员关系、验证资源归属。

非目标：独立租户层级、复杂可配置 RBAC 后台、组织/区域/品牌多级架构、SSO 管理 UI、跨门店共享、员工审批层级。OIDC 只预留标准接入边界。

## 2. 不可破坏的安全不变量

1. User 是全局身份；Store 是门店业务边界；StoreMembership 是用户访问门店的唯一授权事实。
2. 客户端传入的 user_id、store_id、role、permission、资源 owner 均不是授权证据。
3. Session 只证明登录主体，不自动授予门店访问权。
4. 每个门店请求都必须具有明确的 request-scoped store selector；服务端逐请求验证该门店属于已认证用户的 active membership。Session.active_store_id 仅作为 UI 默认选择和恢复提示，不是请求授权上下文。
5. 同一 Session 可在多个浏览器标签页同时操作不同门店；一个标签页切换门店不得改变其他标签页正在使用的门店请求上下文。
6. 所有门店业务资源必须有非空 store_id；列表、详情、写入、删除、导出、文件、任务均验证资源归属。
7. 跨门店资源统一按不存在处理（404），避免泄露资源是否存在；未认证统一 401。
8. 列表、详情、异步任务和对象存储访问必须执行同一授权规则。
9. 成员撤销、门店停用或 Session 撤销后，后续请求必须拒绝；首期不使用长 TTL 权限缓存。
10. 授权依赖不可用时 fail closed，不允许回退客户端状态或放行。
11. 平台管理员身份与门店成员身份分离；平台角色不自动授予门店经营数据访问权。

## 3. 领域模型

### User

- id：UUID 主键。
- email_normalized：非空、数据库唯一、大小写规范化。
- password_hash：Argon2id PHC 字符串；永不返回 API。
- status：active / locked / disabled。
- email_verified_at、password_changed_at、created_at、updated_at。
- auth_version：整数，默认 1；用于全设备会话失效。

密码重置 token 单独保存 verifier、到期时间和 consumed_at；不存明文 token。

### Store

- id：UUID 主键；name：非空。
- status：active / suspended / closed。
- created_at、updated_at。
- 首期不增加 Tenant / Organization 层级。

### StoreMembership

- id：UUID 主键；store_id、user_id 外键。
- role：首期仅 owner / member。
- status：invited / active / suspended / removed。
- invited_by_user_id、joined_at、revoked_at、created_at、updated_at。
- UNIQUE(store_id, user_id)；索引 (user_id, status)、(store_id, status)。
- owner / member 均可执行产品 v1.8 定义的门店营销业务；role 不用于增加营销审批层级。门店成员查看、邀请、移除和角色维护由平台管理员在平台管理端执行，符合 PRODUCT_DESIGN.md 的平台管理员职责。
- 移除/降级最后一个 active owner 必须事务失败。所有权转移是显式审计动作。

### Session

- id：UUID 主键；user_id 外键。
- token_hash：唯一 bytea，保存 Cookie 随机 token 的 HMAC-SHA-256 verifier，不存原 token。
- auth_version：创建时 User.auth_version 快照。
- active_store_id：可空 Store 外键；仅作为 UI 默认门店选择/恢复提示，不作为每个请求的授权上下文或授权凭据。
- created_at、last_seen_at、idle_expires_at、expires_at。
- rotated_from_session_id、revoked_at、revoke_reason。
- ip_fingerprint、user_agent（可选，最小化保存并设保留期）。

Cookie token 使用 256-bit CSPRNG；服务端 pepper 计算 verifier。Token、Cookie、CSRF secret 不得写日志、trace 或错误追踪。

### AuditEvent

记录 actor_user_id、store_id（如适用）、action、target_type、target_id、result、request_id、occurred_at、redacted metadata。覆盖登录成功/失败、登出、会话撤销、密码重置、门店切换、成员邀请/加入/角色变更/撤销、门店停用、敏感导出及授权拒绝。

审计事件追加写入；普通业务 API 不可修改/删除。metadata 禁止密码、token、cookie、密钥、完整请求体和敏感营销内容。

## 4. Session 生命周期与认证机制

### Cookie 与 CSRF

Cookie 名称 __Host-ai_store_session；属性 Secure、HttpOnly、SameSite=Lax、Path=/，不设置 Domain，生产必须 HTTPS。所有状态变更请求使用绑定 Session 的 synchronizer CSRF token，通过 X-CSRF-Token header 发送；同时校验 Origin/Referer。CORS 仅允许显式前端 Origin，禁止 credentials 与 wildcard origin 组合。

不得将认证 token 存入 localStorage/sessionStorage，不得通过 URL/query/fragment 传递。

### 建议生命周期参数（上线前安全评审）

- 暂定评估值：空闲超时 12 小时、绝对寿命 7 天；这两个值不是已批准的安全策略，须在安全评审中 accept/change/defer 后才可写入运行配置。
- 登录成功签发新 Session，不复用匿名 Session。
- 登录、密码重置、密码修改、权限提升后轮换 token，旧 token 原子撤销。
- 登出撤销当前 Session 并清 Cookie。
- 登出所有设备递增 User.auth_version 并撤销该用户全部活动 Session。
- 敏感操作要求近期重新认证；具体清单在实现 PR 确认。
- last_seen 更新节流；服务端每次请求仍执行过期判断。

### 请求认证顺序

1. 读取 Cookie 并计算 HMAC verifier。
2. 查询未撤销、未过期 Session 和 User。
3. 校验 User.status=active，且 Session.auth_version 等于 User.auth_version。
4. 状态变更请求校验 CSRF 与 Origin。
5. 门店请求必须读取 X-Store-ID 不可信 selector；逐请求校验 Store.status=active 和该 User 的 StoreMembership.status=active。不得使用 Session.active_store_id 替代请求 selector，也不得把它复制到请求授权上下文。
6. 建立不可由客户端覆盖的 AuthContext：user_id、session_id、request_store_id、membership_id、role、capabilities、authorization_version、request_id。Session.active_store_id 只用于 UI 默认门店选择。
7. 应用服务执行资源归属和操作权限检查。
8. 任一授权依赖失败均拒绝，不降级放行。

首期每个门店请求重新校验 membership，不做跨请求长 TTL 权限缓存。若 membership/store 状态读取失败，返回 503 并 fail closed。

## 5. 门店切换与服务端授权

### 切换流程

前端调用 GET /api/v1/me/stores 获取当前用户 active membership 门店；选择目标后调用 POST /api/v1/session/active-store。服务端事务内验证 User、Session、Store 有效且目标 StoreMembership 为 active，再更新 Session.active_store_id（仅 UI 默认选择）并写 AuditEvent。业务 API 每次请求另带 X-Store-ID，服务端独立校验 membership 并生成 request-scoped AuthContext；不能仅凭 Session.active_store_id 授权。失败不改变默认选择；目标不可访问统一返回 404。

切换成功后前端清空或按 store_id 分区所有门店范围 TanStack Query 缓存。多标签页可分别发送各自 X-Store-ID，不共享可变的服务端请求上下文。该动作仅防止 UX 串数据，不构成安全控制。

### 授权决策

- Store scope：必须有 request_store_id、active Store、active Membership；request_store_id 由服务端在每个请求中解析并验证。
- Role policy：owner/member 映射到固定 permission set；每个 endpoint 声明所需 permission。
- Resource policy：资源 store_id 必须等于 AuthContext.request_store_id。
- 更新/删除 SQL 必须同时约束资源 ID 与 store_id；不能先按 ID 读取再依赖前端校验。
- Job 创建时从 AuthContext 注入 store_id 和 actor_user_id；Worker 执行前再次核验 Job 与业务资源归属。
- 文件签名 URL 生成前验证 Asset.store_id；object key 本身不是授权凭据。
- 批量操作逐项验证归属，任一越权对象导致整批失败，不能静默跳过。

### 数据库纵深防御

所有门店业务表 store_id UUID NOT NULL 并建立索引。推荐 UNIQUE(store_id, id)，子资源使用复合外键 (store_id, parent_id) 引用父资源，阻止跨门店关联。

Repository 必须接受 AuthContext/store scope；详情、更新和删除 SQL 均含 store_id；列表在 SQL 层过滤，禁止取回后在 Python 内存中过滤。

PostgreSQL RLS 可作为纵深防御但不替代应用层授权。若启用，事务内 SET LOCAL app.current_store_id / app.current_user_id；应用 DB role 不得 BYPASSRLS；必须验证连接池上下文不会泄漏。未完成连接池复用测试前不得宣称 RLS 已保护数据。

## 6. 最小角色与错误策略

首期门店角色仅 owner / member，不增加 RBAC 管理 UI。两者均可执行产品 v1.8 定义的门店营销流程，不新增审批层级。成员管理由平台管理员在平台管理端完成；平台管理员可访问管理所需的成员最小字段，但不因此获得门店营销正文、素材、经营资料或任务的读取权限。此职责以 PRODUCT_DESIGN.md 2.2 为准。

| 场景 | HTTP | code |
|---|---:|---|
| 无 Session / 过期 / 撤销 | 401 | UNAUTHENTICATED |
| CSRF 缺失或错误 | 403 | CSRF_INVALID |
| 已认证但无当前门店 | 400 | STORE_CONTEXT_REQUIRED |
| 门店不存在/非成员/已停用 | 404 | STORE_NOT_FOUND |
| 资源不存在/属于其他门店 | 404 | RESOURCE_NOT_FOUND |
| 成员缺少操作权限 | 403 | FORBIDDEN |
| 最后 owner 将被移除 | 409 | LAST_OWNER_REQUIRED |
| 授权依赖不可用 | 503 | AUTHORIZATION_UNAVAILABLE |

错误统一包含 request_id，不返回 SQL、实际所属门店、邮箱、token 或堆栈信息。

## 7. 实施门禁

Issue #4 合并并验收工程骨架、CI、PostgreSQL 测试服务、迁移入口、统一 API 错误和 OpenAPI 生成后，才开始接入：
1. ORM 模型与 Alembic migration。
2. 认证应用服务、Session repository、Cookie/CSRF 中间件。
3. StoreMembership、AuthContext 和门店切换服务。
4. 所有门店 API/Repository 的 store scope。
5. 审计事件、文件和 Job 授权钩子。
6. 安全矩阵、PostgreSQL 集成和 Playwright 回归。
7. 安全专项审查通过后才可关闭 Issue #5。

## 8. 未决项

用户注册/邀请与邮箱验证供应商、密码重置邮件供应商依部署区域与开户流程确认；是否启用 RLS 在应用层授权完成后评估；12h/7d Session 参数上线前由安全评审确认；平台管理员的独立授权记录、初始化和紧急恢复流程必须在实施前定案。本设计不擅自选定云厂商或 OIDC 供应商。


## 9. 产品权限基线校正（2026-11-11）

依据 PRODUCT_DESIGN.md v1.8 第 2.2 节，平台管理员负责在门店详情中管理门店用户。因此：
- 成员列表、邀请、移除、状态变更和角色维护属于平台管理端能力，不归门店 owner/member。
- owner/member 不因此获得额外成员管理、角色配置或审批能力；两者的营销业务能力按现行产品流程执行。
- 平台管理员可以读取管理成员关系所需的最小字段，不得由此访问门店任务正文、文案、图片、素材或经营资料。
- 本节是对本设计原先权限表述的纠偏，API 和安全测试矩阵必须同步遵守。

## 10. 门店上下文一致性补充

- X-Store-ID 是每个门店业务请求的唯一请求级 selector；服务端将其与已认证 User 的 active StoreMembership 逐请求核验。
- Session.active_store_id 只作为 UI 默认门店选择和恢复提示。切换该字段不得改变其他标签页的请求授权。
- AuthContext 只暴露 request_store_id，不提供可被业务代码误用的 active_store_id 授权字段。
- 请求 selector 缺失时返回 400 STORE_CONTEXT_REQUIRED；selector 指向非成员/停用门店时统一 404 STORE_NOT_FOUND。
