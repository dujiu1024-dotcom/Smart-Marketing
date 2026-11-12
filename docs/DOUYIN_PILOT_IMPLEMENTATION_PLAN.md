# 抖音首个官方渠道试点实施记录（Issue #12）

> 选择：抖音网站应用（Web OAuth 2.0）  
> 记录日期：2026-11-11  
> 当前状态：Adapter 代码初版已通过 PR #68 合并至 main；真实应用审核、授权账号、Token 安全存储和真实平台联调仍阻塞。  
> 证据：仅引用抖音官方开放平台文档；MockTransport 测试不等于真实平台验收。

## 1. 项目决策与目标

项目负责人已确认抖音为首个官方渠道。首期使用抖音网站应用 Web OAuth，服务端持有 Client Secret 和用户 Token；不在浏览器保存凭证，不采用 Cookie 注入、私有接口或页面自动化。

首期授权 Scope 申请建议：
- `user_info`：读取授权账号公开信息，建立 open_id 与昵称/头像。
- `video.create.bind`：官方 Partner 文档标注的“代替用户发布内容到抖音”能力申请 Scope，用于上传视频与创建视频；需在开放平台能力实验室申请并用户授权。
- `video.list`：授权账号视频列表读回，需单独申请并用户授权，用于发布结果核验。
- 暂不申请非必要手机号、粉丝关系、评论或广告相关 Scope。

注意：不同版本官方文档对视频发布 Scope 存在 `video.create` 与 `video.create.bind` 的文档分支差异。当前上传/创建视频的 Partner API 文档明确要求 `video.create.bind`，而旧版 OpenAPI 文档使用 `video.create`。实现采用当前 Partner API 路径与 Scope；最终以应用控制台实际可申请权限为准，不将 Scope 名称写死为“已获批”。

## 2. 官方 API 能力映射

| 能力 | 官方端点 | Scope | 当前实现/状态 |
|---|---|---|---|
| Web OAuth 授权 URL | `GET /platform/oauth/connect/` | 应用 OAuth | Adapter 已实现 URL 构造 |
| 授权码换 Token | `POST /oauth/access_token/` | 应用 OAuth | Adapter 已实现 form POST |
| 刷新 Access Token | `POST /oauth/refresh_token/` | 应用 OAuth | Adapter 已实现 form POST |
| 获取账号资料 | `POST /oauth/userinfo/` | `user_info` | Adapter 已实现 |
| 上传视频 | `POST /api/douyin/v1/video/upload_video/` | `video.create.bind` | Adapter 已实现单次上传（<=300 MB） |
| 创建视频 | `POST /api/douyin/v1/video/create_video/` | `video.create.bind` | Adapter 已实现，要求显式商家确认 |
| 授权账号作品列表 | `GET /video/list/` | `video.list` | Adapter 已实现最多 4 页读回 |
| 草稿创建/读回 | 未找到官方公开草稿 API | — | **unsupported / 未证实** |
| 视频发布后审核状态 | 创建返回 item_id；列表提供 is_reviewed/video_status | `video.list` | 返回初始 processing；读回出现 item_id 后才有外部证据，不把创建响应等同公开发布成功 |

官方文档明确创建视频后会经历审核，审核期间仅自己可见；每次代用户创建内容必须让用户明确感知。产品必须在最终确认页清楚展示账号、视频、文案、可见性和发布动作，并由用户主动点击确认。创建视频不是“保存草稿”。

## 3. OAuth 流程与安全门禁

目标生产流程：
1. 已登录用户在当前门店「门店资料 → 渠道账号」发起连接；服务端从 AuthContext 取得 user_id/store_id。
2. 服务端生成 256-bit 随机 state，只持久化 state_hash、store_id、requested_by_user_id、channel_key、redirect_uri、expires_at、consumed_at；state 只返回给 OAuth URL。
3. 服务端生成授权 URL，scope 只取应用已审核并允许申请的 Scope；redirect_uri 必须是 HTTPS 且与开放平台控制台登记值完全一致。
4. callback 验证 state hash、TTL、未消费、redirect_uri、当前 Session user_id 等于发起人、StoreMembership 仍 active、Store 仍 active；无有效 Session 或校验不通过直接拒绝。
5. 服务端一次性用 code 调用 token endpoint；官方文档指出 code 10 分钟有效且只能使用一次。
6. 通过 access_token 读取 user_info，确认 open_id 与授权返回一致。
7. 将 access_token / refresh_token 写入经安全审查的 Secret Manager；数据库只保存 SecretRef、scope、expiry、token_version 和状态。Token 不得进入 API 响应、日志、异常、事件或普通数据库字段。
8. Token 刷新必须锁定账号记录或使用 CAS，原子轮换 SecretRef；refresh_token 过期、用户撤权或 invalid_grant 后进入 reauth_required。
9. 断开时调用平台撤权能力（若实际支持）；本地 SecretRef 必须禁用/删除并记录审计。

**当前阻塞：** 项目尚未选定/实现 Secret Manager 适配器。现有架构文档仅规定“Secret Manager 或等价服务”，没有具体云供应商/部署区域。当前 Adapter 只返回内存 TokenSet，不能直接挂到生产 API 或持久化。禁止临时把 Token 明文放 PostgreSQL 以赶进度。

## 4. 视频发布与核验流程

1. #8 提供冻结的 PublishPackage / PackageItem；发布前校验 package fingerprint、内容审核、质检、商家最终确认、账号授权与 capability snapshot。
2. Worker 从受控对象存储读取最终视频，检查 MP4/WebM、文件大小、时长、分辨率和使用权；视频上传到抖音官方 upload API。
3. 上传返回加密 video_id，作为后续创建视频参数；上传失败可以在确认无副作用后按 Job policy 重试。
4. 创建视频前再次校验确认 fingerprint 和确认时间；每次调用都必须让用户明确感知。创建 API 请求必须通过唯一 PublishOperation 幂等门禁。
5. 创建响应返回 item_id 时，状态仅为 processing / external accepted；不能写 published。
6. 使用 `video.list` 在授权账号视频列表中核验 item_id。只有真实读回命中后保存作品证据、分享链接、create_time、is_reviewed、video_status；如平台尚未返回，保持 processing 并安排后续 reconcile。
7. API 超时但无法确定平台是否创建成功时，先通过作品列表核验；不能确认时转 needs_human，不盲目重新 create。
8. 公开可见/审核通过的判定须基于官方字段语义；首期保留原始 is_reviewed 与 video_status，不自行猜测数值状态含义。

### 草稿能力决策

本轮检索未找到抖音官方草稿箱 API。官方创建视频接口执行的是创建/投稿，并有平台审核流程；这不是草稿保存。

**产品决策：已批准（2026-11-11）。** 项目负责人明确批准以下替代验收路径，作为抖音首期正式验收基线；不再以抖音原生草稿箱能力作为首期阻塞条件：
- 系统先完成本地冻结发布包（含文案、素材、渠道参数、版本指纹及校验结果）；本地冻结包是本系统草稿，不称为抖音草稿。冻结后内容不可原位修改，修改必须生成新版本并重新审核/质检。
- 商家在最终确认页核对账号、文案、视频、可见性和发布动作后主动点击“确认并发布”；确认记录必须绑定冻结包 fingerprint、门店、账号、操作者和时间。服务端再次校验确认与冻结版本一致后，才可上传并调用官方创建视频 API。
- 发布操作必须有唯一幂等标识及持久化 PublishOperation/Attempt；以 item_id 和 `video.list` 读回验证外部结果。未读回时保持 processing 并重试只读核验；发布请求结果未知时进入 needs_human，禁止盲目重复 create_video。
- UI 明确提示“提交后进入抖音审核，审核期间仅自己可见”；不承诺可在抖音草稿箱编辑。只有作品读回证据命中后才记录外部作品归属；读回结果与审核状态分别保存，不将 item_id 返回等同公开发布成功。

## 5. 代码初版范围

本 PR 新增 `apps/api/src/store_operator/channels/douyin.py`：
- OAuth URL 构造、code exchange、access token refresh。
- 账号公开信息读取。
- 作品列表分页读取。
- 单次视频上传（限制 <=300 MB；更大文件须实现官方分片上传流程）。
- 受商家确认门禁保护的 create_video。
- 按 item_id 读回核验。
- 平台错误脱敏；TokenSet 的 repr 不暴露 Token。
- Adapter 不负责持久化凭证，等待 Secret Manager 与领域模型集成。

新增 MockTransport 单元测试覆盖授权 URL、表单交换、刷新、账号读取、上传、确认门禁、创建响应、作品读回和错误脱敏。MockTransport 仅验证本地请求构造，不是抖音真实平台测试。

## 6. 尚未完成的生产接入

| 项目 | 状态 | 解除条件 |
|---|---|---|
| 抖音开发者账号/网站应用 | pending | 项目主体注册并完成平台应用审核 |
| ClientKey / ClientSecret | pending | 在 Secret Manager 配置；禁止提交仓库/聊天 |
| 授权回调域名 | pending | 部署域名 HTTPS、开放平台配置一致 |
| video.create.bind | pending | 能力实验室申请通过 |
| video.list | pending | 对应权限申请通过 |
| 测试账号 | pending | 获得可授权且可发布的测试抖音账号 |
| Secret Manager | blocked | 确认部署区域/供应商，完成实现与安全审查 |
| OAuth API 路由与 OAuthAuthorizationAttempt 持久化 | not implemented | #5 auth context、DB 模型、state 消费事务与安全测试 |
| ChannelAccount / CapabilitySnapshot 持久化 | not implemented | #12 migration/model/service |
| PublishOperation + #9 Job Handler | not implemented | #8 frozen package 集成、#9 handler 与幂等/对账 |
| Demo 门店资料渠道账号 UI 真实 API | not implemented | OpenAPI 契约后实现 |
| 真实 OAuth/上传/发布/读回 | not run | 需平台应用、权限和测试账号 |

## 7. 官方文档

- 网站应用 OAuth 2.0：https://open.douyin.com/platform/resource/docs/develop/permission/web/oauth2
- 获取 access_token：https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/account-permission/get-access-token
- 刷新 access_token：https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/basic-abilities/interface-request-credential/user-authorization/refresh-user-access-token
- 获取用户公开信息：https://open.douyin.com/platform/resource/docs/openapi/account-management/get-account-open-info
- 视频上传（当前 Partner API）：https://partner.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/upload-video
- 创建视频（当前 Partner API）：https://partner.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create
- 查询授权账号视频列表：https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/search-video/account-video-list
- 能力与权限申请说明：https://open.douyin.com/platform/resource/docs/accession-guide/type-and-permission

## 8. 验收记录

### 已批准的首期验收方案（2026-11-11）

项目负责人已明确批准“本地冻结草稿包 + 商家最终确认 + 官方发布 + 作品读回核验”替代抖音原生草稿箱验收。该批准只解除原生草稿箱 API 缺失这一产品决策阻塞，不代表 OAuth、Secret Manager、真实发布和作品读回已完成。首期 DoD 以本地冻结版本可追溯、确认绑定 fingerprint、官方发布受幂等门禁保护、作品读回有真实证据为准。


本 PR 的 CI 应执行：
- `cd apps/api && uv run pytest tests/test_douyin_adapter.py`
- `cd apps/api && uv run ruff check src/store_operator/channels tests/test_douyin_adapter.py`
- `cd apps/api && uv run mypy src/store_operator/channels/douyin.py`

以上命令尚未在本执行环境运行；以 PR CI 结果为准。真实平台调用、真实 OAuth、Secret Manager、数据库 migration、跨门店 IDOR、浏览器端到端均未执行。


## 7. Adapter 合并与 CI 证据（2026-11-11）

PR #68 已 squash merge 至 main，merge commit：`9a417f30e4da74496ad8e65d70588d130ac51139`。旧 PR #65 因基线落后关闭，由 PR #68 的基于最新 main 分支替代。

CI Run [42998696426](https://github.com/dujiu1024-dotcom/Smart-Marketing/actions/runs/42998696426) 对精确 PR head 6/6 jobs 通过：
- API：Ruff、MyPy、Alembic upgrade/downgrade/upgrade、129 pytest passed（1 条 Starlette/httpx deprecation warning）
- Worker、Web、Contracts、E2E、Infrastructure 全部通过
- E2E/Infrastructure 仅验证仓库应用与 Demo 路由/状态 smoke，不是抖音真实平台验收

仍未完成：OAuth state 持久化与回调 Session/store 校验、Secret Manager/SecretRef、ChannelAccount 账号授权管理、PublishOperation 幂等/重试/未知结果恢复、冻结包与账号能力关联、真实抖音应用审核与账号授权、真实上传/发布/作品读回。Issue #12 保持 Open。


## 8. 发布 API 调用审计（2026-11-12）

PR #93 已合并（merge commit：`b6ed0433c96148e6f6538cc04d2859cec649eb67`），新增 `PublishOperationAttempt` 持久化记录图片上传、图文发布提交和作品读回的调用尝试，保存请求指纹、适配器版本、抖音 `extra.logid`、归一化状态及错误码。发布提交遇到传输异常时按未知副作用处理，禁止自动重复发布。

合并后审查发现作品读回路径的 `httpx.HTTPError` 未结束 Attempt 记录，PR #96 补齐传输异常审计；读回仅验证已提交作品，不创建新作品，因此可重试。

以上仍是 API 尝试审计能力，不代表真实账号、OAuth 或作品发布验收完成。
