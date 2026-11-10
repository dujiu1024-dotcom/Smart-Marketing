# Identity & Store 身份与门店安全设计

> 对应 Issue：#5  
> 产品基线：PRODUCT_DESIGN.md v1.8  
> 技术基线：TECH_STACK_SELECTION.md（应用内 Identity + 服务端 Session）  
> 状态：设计基线提案，待安全评审冻结；不是生产实现声明  
> 日期：2026-11-11

## 1. 设计边界

首期只建立 User、Store、StoreUser、Session 和平台管理员身份边界。不建立租户层级、可配置 RBAC 管理后台、组织架构、工单或独立角色管理模块。平台管理员与门店用户是不同授权主体；平台管理员身份不自动授予读取门店经营内容的权限。

核心原则：
- 身份认证回答“是谁”；门店成员关系回答“是否属于该门店”；能力授权回答“能否执行该动作”。
- store_id、user_id、role、permission 均不得由客户端请求体或 URL 参数直接作为授权事实。
- 所有门店资源在读取和写入时都要校验资源归属，不能只在列表或 UI 层过滤。
- Session 可撤销；成员移除、门店停用和权限变更对后续请求即时生效。
- 所有身份/授权敏感操作写入追加式审计记录。

## 2. 权威数据模型

所有 ID 使用 UUID。时间使用 UTC timestamptz。密码仅存 Argon2id 哈希；Session 仅存随机 Token 的 verifier/hash。

### User
- id UUID PK
- email_normalized citext UNIQUE NOT NULL
- password_hash TEXT NOT NULL
- display_name TEXT NOT NULL
- status ENUM(active, disabled, pending_verification) NOT NULL
- email_verified_at timestamptz NULL
- password_changed_at timestamptz NULL
- created_at / updated_at timestamptz NOT NULL

### Store
- id UUID PK
- name TEXT NOT NULL
- status ENUM(active, suspended, archived) NOT NULL
- created_at / updated_at timestamptz NOT NULL

Store 的经营资料字段由 #6 Store Knowledge 管理；Identity 域只持有身份与门店生命周期最小字段，不复制 StoreProfile。

### StoreUser
- id UUID PK
- store_id UUID NOT NULL FK Store(id)
- user_id UUID NOT NULL FK User(id)
- role ENUM(owner, member) NOT NULL
- status ENUM(invited, active, suspended, removed) NOT NULL
- invited_by UUID NULL FK User(id)
- joined_at timestamptz NULL
- removed_at timestamptz NULL
- created_at / updated_at timestamptz NOT NULL
- UNIQUE(store_id, user_id)
- INDEX(user_id, status), INDEX(store_id, status)

首期只使用固定 owner/member 两种门店角色，不提供角色配置 UI。角色到能力的映射由服务端代码集中定义；若产品后续需要更细粒度权限，必须走产品决策与 ADR，不在本 Issue 暗中扩张。

### Session
- id UUID PK
- user_id UUID NOT NULL FK User(id)
- token_hash BYTEA UNIQUE NOT NULL
- status ENUM(active, revoked, expired) NOT NULL
- created_at / last_seen_at / expires_at timestamptz NOT NULL
- rotated_from_session_id UUID NULL FK Session(id)
- revoked_at timestamptz NULL
- revoke_reason TEXT NULL
- ip_hash TEXT NULL
- user_agent_summary TEXT NULL
- INDEX(user_id, status), INDEX(expires_at)

Session 原始 Token 只在创建/轮换时返回一次，以 Secure + HttpOnly + SameSite=Lax Cookie 传递；生产必须 HTTPS。不得将 Token 放入 localStorage、URL、日志或分析事件。

### PlatformAdmin
平台管理员不作为 StoreUser 的 role 值。首期可用独立平台管理员授权表或受控配置映射到 User；具体实现必须明确审计，且不能默认授予门店业务内容读取权限。此处不新增平台角色管理 UI。

### AuditEvent
- id UUID PK
- actor_user_id UUID NULL
- actor_type ENUM(user, platform_admin, system)
- store_id UUID NULL
- action TEXT NOT NULL
- target_type TEXT NOT NULL
- target_id UUID NULL
- outcome ENUM(success, denied, failure) NOT NULL
- reason_code TEXT NULL
- request_id TEXT NULL
- metadata JSONB NOT NULL DEFAULT '{}'
- occurred_at timestamptz NOT NULL
审计 metadata 禁止包含密码、Cookie、Token、API Key 或原始敏感认证材料。

## 3. AuthorizedStoreContext

认证中间件从 Session 得到 User；授权服务依据 StoreUser 和 Store 状态构造只读上下文：

- actor_user_id
- store_id
- store_user_id
- store_role
- capabilities（服务端枚举）
- authorization_version（用于缓存失效/变更检测）
- request_id

业务模块只能接收此上下文，不自行从请求体解析身份或门店权限。当前门店通过 `X-Store-Id` 请求头表达选择；每个门店作用域请求都必须重新验证 active membership 和 active Store。门店切换 API 只负责验证并返回可用上下文，前端保存的门店选择仅是 UI 状态，不是授权凭据；Session 不保存可绕过成员关系校验的 current_store_id。不得接受客户端声明 role/capabilities。所有门店作用域 API 均要求该请求头，缺失返回 400 STORE_CONTEXT_REQUIRED，非法/非成员门店返回统一 404。

## 4. 首期能力矩阵

| 能力 | owner | member | platform admin |
|---|---:|---:|---:|
| 查看/编辑门店经营资料 | 是 | 是 | 否（不属于平台管理职责） |
| 创建/编辑营销任务 | 是 | 是 | 否 |
| 审核文案/图片 | 是 | 是 | 否 |
| 最终确认/发布 | 是 | 是 | 否 |
| 查看门店任务与效果 | 是 | 是 | 否 |
| 邀请/移除门店成员 | 首期由平台管理端管理成员；owner 不额外获得管理 UI | 否 | 按管理权限执行 |
| 管理平台模型目录/平台提示词 | 否 | 否 | 是 |
| 查看平台运行监控/用量 | 否 | 否 | 是 |
| 读取门店营销正文/素材 | 否（除非明确的受审计支持流程） | 否 | 默认否 |

说明：owner/member 在首期业务动作上保持相同能力，owner 是门店归属/生命周期标识，不借此引入权限管理产品。平台管理员管理门店用户关系时，只能访问管理所需字段，不因此获得门店业务资料权限。若后续需限制“谁能最终发布”等动作，应先由产品负责人明确角色差异再扩展。

## 5. Session 生命周期与安全控制

- 登录：验证用户状态与密码；成功后生成高熵随机不透明 Token，数据库只存 SHA-256/HMAC verifier；设置 HttpOnly、Secure、SameSite=Lax、Path=/ Cookie。
- 写请求：Cookie Session + CSRF Token/双重提交或严格 Origin 校验；所有跨站状态变更请求必须通过 CSRF 校验。
- 轮换：登录、权限提升、敏感认证事件后轮换 Session；旧 Session 原子撤销。
- 续期：仅在活跃且未超过绝对生命周期时滑动续期；设置 idle timeout 与 absolute timeout，具体时长由安全评审给出默认值。
- 登出：撤销当前 Session；提供撤销该用户全部 Session 的服务端能力。
- 密码变更/重置、用户禁用：撤销该用户全部 Session。
- 成员移除或门店停用：每个请求重新校验 membership/store 状态；不依赖长效 JWT 中缓存的角色声明。
- 频率限制：登录、密码重置、邀请/成员变更和敏感操作限流；响应避免账号枚举。
- Cookie/Token/密码/密钥不得写日志；审计仅记录主体、动作、结果、时间、请求 ID 和必要目标引用。

## 6. API 契约草案

所有路径均为建议的 v1 契约，最终以 FastAPI OpenAPI 为事实源。统一 JSON 错误结构：`{code, message, request_id, details?}`；不得回显敏感认证信息。

| 方法 | 路径 | 作用 | 关键约束 |
|---|---|---|---|
| POST | /api/v1/auth/login | 登录并创建 Session | 限流、统一失败语义、CSRF 初始化 |
| POST | /api/v1/auth/logout | 撤销当前 Session | 幂等 |
| GET | /api/v1/auth/me | 当前用户和可访问门店摘要 | 不返回 Session Token |
| POST | /api/v1/auth/session/rotate | 轮换 Session | 原子撤销旧 Session |
| POST | /api/v1/auth/password/change | 修改密码 | 验证当前凭据并撤销其他 Session |
| GET | /api/v1/stores | 当前用户可访问门店列表 | 仅 active membership + active Store |
| POST | /api/v1/stores/{store_id}/switch | 切换当前门店 | 服务端验证成员关系 |
| GET | /api/v1/stores/{store_id}/context | 获取当前门店上下文摘要 | 仅当前授权门店 |
| GET | /api/v1/admin/stores/{store_id}/members | 管理端查看成员 | 平台管理员专属能力、字段最小化 |
| POST | /api/v1/admin/stores/{store_id}/members | 邀请/添加成员 | 幂等、审计 |
| PATCH | /api/v1/admin/stores/{store_id}/members/{membership_id} | 更新成员状态/固定角色 | 不允许客户端任意写 capabilities |
| DELETE | /api/v1/admin/stores/{store_id}/members/{membership_id} | 移除成员 | 撤销/失效后续授权、审计 |

## 7. 错误语义

- 401 AUTH_REQUIRED / SESSION_EXPIRED：未认证或 Session 无效。
- 403 ACTION_FORBIDDEN：已认证但无该动作能力。
- 404 RESOURCE_NOT_FOUND：资源不存在或不属于当前门店，避免 IDOR 枚举。
- 409 MEMBERSHIP_INACTIVE / STORE_INACTIVE / SESSION_VERSION_CONFLICT：成员、门店或授权状态冲突。
- 422 VALIDATION_ERROR：字段格式或业务输入无效。
- 429 RATE_LIMITED：触发认证/敏感操作限流。

跨门店访问统一采用 404，不向请求者透露资源是否属于其他门店。

## 8. 强制安全测试矩阵

- 匿名访问所有门店 API。
- 同门店 owner/member 正常访问。
- 篡改 store_id、user_id、role、membership_id。
- 通过 task/artifact/version/file/job ID 跨门店访问。
- 门店列表隐藏但详情 API 直接访问。
- 移除成员后使用既有 Session 发请求。
- 停用门店后切换、读写、上传/下载和发布。
- 登出后重放旧 Cookie。
- Session 轮换并发重放旧 Token。
- CSRF 缺失/错误 Origin 的写请求。
- 平台管理员访问门店经营内容、素材和任务。
- 数据库连接池复用时验证门店上下文清理，不发生跨请求串店。

所有测试必须使用真实 PostgreSQL；SQLite 不能替代 RLS/复合外键/事务语义验证。

## 9. 与其他领域的接口约束

- #6 Store Knowledge 的所有写入/读取服务接收 AuthorizedStoreContext；StoreProfile 等经营字段不写入 Identity Store 表。
- #7/#8 的 task、artifact、review、package 都必须带 store_id，且由服务端上下文注入；子资源复合外键包含 store_id。
- #9 Worker 执行时使用 Job 绑定的 store_id 和 actor 引用进行受托执行；不得继承用户 Session，也不得扩大跨店权限。外部副作用前重新验证门店状态、授权和业务门禁。
- #10 AI Provider 只能由服务端 AI Gateway 调用，不能从浏览器直连；模型 Secret 以 secret reference 存储。
- 成员/门店状态变更发出版本化 Identity 事件，供 Job Runtime 对未开始或外部副作用任务执行取消/阻断策略。

## 10. 待评审事项（冻结前必须决议）

1. 平台管理员主体的存储方式和初始化/恢复流程。
2. Session idle/absolute timeout 的明确时长；安全评审前建议 idle 30 分钟、absolute 12 小时，敏感认证事件立即轮换/撤销。
3. CSRF 采用 synchronizer token 还是严格 Origin + double-submit 组合。
4. owner/member 两种固定角色是否足够覆盖首期真实门店流程。
5. 门店切换是写入 Session current_store_id，还是每个请求显式带上下文 header；无论哪种均由服务端校验。
6. 用户邀请/注册/密码重置的产品交互与邮件交付机制（不擅自接入第三方邮件供应商）。

以上待决项未评审前，文档为设计提案。任何待决项不得通过实现时临时假设解决。
