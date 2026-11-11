# API 工程约定（v1）

状态：工程基线。具体业务端点仍以各领域契约评审和 FastAPI OpenAPI 为准。

## 1. 路径与数据格式

- 所有业务 API 使用 `/api/v1` 前缀；健康检查保留在 `/health/*`。
- JSON 字段使用 `snake_case`。
- 时间戳使用带时区的 ISO 8601，服务端统一存储 UTC。
- API 路由层只负责 HTTP 输入/输出、鉴权上下文和错误映射；业务规则放在应用服务/领域模块中。
- 路由层不得直接编写业务 SQL。基础设施健康检查可直接探测 PostgreSQL/Redis。

## 2. 请求 ID 与错误结构

- 客户端可通过 `X-Request-ID` 传入请求关联 ID；缺失时由服务端生成 UUID。
- 每个响应均返回 `X-Request-ID`，日志和 Trace 使用同一 ID。
- 错误响应统一为：

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Resource not found"
  },
  "request_id": "..."
}
```

- 错误码稳定、可机器识别；message 仅提供安全的通用说明。
- 不向客户端回显请求体、校验输入原值、SQL、异常堆栈、密钥或第三方响应。
- 请求校验错误使用 HTTP 422 / `VALIDATION_ERROR`；未知服务端错误使用 HTTP 500 / `INTERNAL_ERROR`。
- HTTP 404 对不存在与无权访问的门店资源保持统一外部表现，具体授权语义由身份/门店安全契约约束。

## 3. 列表分页

适用于可能增长的集合端点；有明确上限的小型集合（例如当前用户的门店列表）可不分页，但必须在端点契约中声明上限。

请求参数：

| 参数 | 规则 |
|---|---|
| `limit` | 默认 20，允许 1–100；超出范围返回 400 |
| `cursor` | 不透明游标；首屏省略，后续请求原样传回 |

响应结构：

```json
{
  "items": [],
  "page": {
    "limit": 20,
    "next_cursor": null,
    "has_more": false
  }
}
```

规则：

- 默认采用基于唯一、稳定排序键的游标分页；禁止在大集合上默认使用无界 offset 分页。
- 排序必须确定且包含唯一 tie-breaker，例如 `created_at DESC, id DESC`。
- 游标必须完整性保护，并绑定资源范围、门店上下文、过滤条件、排序条件及契约版本；过期或与当前查询不匹配时返回 400 / `INVALID_CURSOR`。
- 游标不是授权凭据。每次请求仍须重新验证当前用户和门店权限，SQL 仍必须带服务端授权得到的 `store_id`。
- 默认不返回昂贵的 `total_count`；若产品确实需要总数，必须在具体端点契约中说明计算成本和一致性语义。
- 不允许客户端通过修改 cursor 内容切换门店、扩大过滤范围或改变排序。

## 4. 门店上下文与模块边界

- 门店业务端点从已验证的 request-scoped AuthContext 取得 `store_id`；请求头中的 `X-Store-ID` 仅是不可信 selector。
- 详情查询同时约束资源 ID 与已授权 `store_id`；创建时由服务端注入 `store_id`。
- 模块间只通过公开应用服务/API 契约交互，不导入其他模块的 repository、ORM model 或内部实现。
- OpenAPI 是机器可读契约事实源；契约变更需同步生成客户端类型并在 CI 检查漂移。

## 5. 当前实现状态

工程骨架已实现 API 版本前缀、请求 ID、统一 HTTP/校验/服务端错误 envelope、健康检查和 OpenTelemetry Trace 关联。分页规则是后续集合 API 的统一约定；在具体业务列表端点及其契约冻结前，不宣称已有生产分页实现。
