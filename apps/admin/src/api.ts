export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

let csrfToken = "";

// The API enforces its own request deadline and answers with a 504; this client
// timeout only covers traffic that never reaches it.
const REQUEST_TIMEOUT_MS = 40_000;

const ERROR_MESSAGES_ZH: Record<string, string> = {
  LAST_OWNER_REQUIRED: "门店至少需要保留一名启用中的所有者",
  STORE_USER_ALREADY_BOUND: "该账号已绑定其他门店，一个门店用户只能属于一家门店",
  EMAIL_ALREADY_EXISTS: "该邮箱已被使用，请更换邮箱或直接管理已有账号",
  RATE_LIMITED: "登录尝试过于频繁，请稍后再试",
  INVALID_CREDENTIALS: "邮箱或密码不正确",
  PLATFORM_ADMIN_REQUIRED: "该账号不是平台管理员，无法登录后台",
  CSRF_INVALID: "页面安全令牌已失效，请刷新页面后重试",
  UNAUTHENTICATED: "登录状态已失效，请重新登录",
  FORBIDDEN: "没有权限执行该操作",
  STORE_NOT_FOUND: "门店不存在或已被删除",
  STORE_NOT_ACTIVE: "门店当前未启用，无法执行该操作",
  RESOURCE_NOT_FOUND: "数据不存在或已被删除",
  VALIDATION_ERROR: "提交内容不合法，请检查后重试",
  INVALID_TIMEZONE: "请输入有效的 IANA 时区，例如 Asia/Shanghai",
  MEMBERSHIP_REINVITE_REQUIRED: "该成员需要重新邀请后才能启用",
  IDEMPOTENCY_KEY_REUSED: "重复提交已被拦截，请刷新后重试",
  AUTHORIZATION_UNAVAILABLE: "服务暂时不可用，请稍后重试",
  CHANNEL_NOT_CONFIGURED: "抖音渠道尚未配置，请联系平台管理员完成应用授权配置",
  CHANNEL_SPEC_NOT_FOUND: "渠道规格不存在或未启用",
  CHANNEL_SPEC_SOURCE_REQUIRED: "请提供该渠道官方 HTTPS 来源后再发布规格",
  STALE_CHANNEL_SPEC_VERSION: "渠道规格已更新，请刷新后重试",
  SOURCE_HOST_NOT_ALLOWED:
    "端点地址或条款地址的域名不在允许白名单内，或不是 HTTPS 地址；请先确认该域名已被平台加入白名单",
  SOURCE_TERMS_REQUIRED: "启用前必须填写允许用途并登记条款 URL",
  SOURCE_TERMS_MISSING: "来源缺少条款 URL 或允许用途，无法用于采集",
  SOURCE_ENABLED_LOCKED: "来源处于启用状态，请先停用后再修改地址或条款",
  SOURCE_KEY_EXISTS: "来源标识已存在，请更换来源标识",
  SOURCE_FEED_INVALID: "热榜端点返回的内容无法识别，请确认选择的是公开热榜 JSON 地址",
  SOURCE_FETCH_FAILED: "采集时无法访问来源端点，请检查地址是否可访问后重试",
  REQUEST_FAILED: "请求失败，请稍后重试",
};

function localizeErrorMessage(code: string, message: string): string {
  if (ERROR_MESSAGES_ZH[code]) return ERROR_MESSAGES_ZH[code];
  if (/[\u4e00-\u9fff]/.test(message)) return message;
  if (!/[A-Za-z]{3,}/.test(message)) return message;
  return `请求失败，请稍后重试（错误码：${code}）`;
}

export function setCsrfToken(token: string) {
  csrfToken = token;
}

export function clearCsrfToken() {
  csrfToken = "";
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  allowCsrfRetry = true,
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {
    ...((options.headers as Record<string, string> | undefined) ?? {}),
  };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (method !== "GET" && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      method,
      headers,
      credentials: "include",
      signal: controller.signal,
    });
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") {
      throw new ApiError(
        0,
        "REQUEST_TIMEOUT",
        `请求超时（${Math.round(REQUEST_TIMEOUT_MS / 1000)} 秒内没有响应），请检查网络后重试。`,
      );
    }
    throw new ApiError(0, "NETWORK_ERROR", "网络连接失败，请检查网络后重试。");
  } finally {
    clearTimeout(timeout);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const payload = (await response.json().catch(() => null)) as
    | { error?: { code?: string; message?: string } }
    | null;
  if (!response.ok) {
    if (
      allowCsrfRetry &&
      method !== "GET" &&
      response.status === 403 &&
      payload?.error?.code === "CSRF_INVALID" &&
      path !== "/admin/auth/csrf"
    ) {
      const refreshed = await request<{ csrf_token: string }>(
        "/admin/auth/csrf",
        { method: "POST" },
        false,
      );
      setCsrfToken(refreshed.csrf_token);
      return request<T>(path, options, false);
    }
    throw new ApiError(
      response.status,
      payload?.error?.code ?? "REQUEST_FAILED",
      localizeErrorMessage(
        payload?.error?.code ?? "REQUEST_FAILED",
        payload?.error?.message ?? "请求失败，请稍后重试",
      ),
    );
  }
  return payload as T;
}

export interface AdminIdentity {
  user: { id: string; email: string };
  capabilities: string[];
}

export interface Overview {
  stores: { total: number; by_status: Record<string, number> };
  store_users: { active: number };
  marketing_tasks: { by_status: Record<string, number> };
  jobs: { running: number; queued: number; failed_or_needs_human_24h: number };
  hot_topics: { collected: number; matches_24h: number };
  dispatches: { by_status: Record<string, number> };
}

export interface StoreRow {
  id: string;
  name: string;
  timezone: string;
  status: "active" | "suspended" | "closed";
  created_at: string | null;
  updated_at: string | null;
  member_count: number;
  owners: string[];
}

export interface StoreUserRow {
  membership_id: string;
  user_id: string;
  email: string;
  role: "owner" | "member";
  status: "invited" | "active" | "suspended" | "removed";
  created_at: string | null;
  joined_at: string | null;
  store: { id: string; name: string; status: string };
}

export interface OpportunitySource {
  id: string;
  source_key: string;
  display_name: string;
  source_type: string;
  source_url: string;
  fallback_url?: string | null;
  terms_url: string | null;
  permitted_use?: string | null;
  attribution_template?: string | null;
  enabled: boolean;
  health_status: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error_code?: string | null;
  last_error_summary?: string | null;
}

export interface OpportunitySourcePreset {
  key: string;
  display_name: string;
  source_url: string;
  fallback_url: string | null;
}

export interface OpportunitySourceInput {
  source_key: string;
  display_name: string;
  source_type: "rss" | "public_feed";
  source_url: string;
  fallback_url?: string | null;
  terms_url: string;
  permitted_use: string;
  attribution_template?: string | null;
}

export interface HotTopicRow {
  id: string;
  title: string;
  summary: string | null;
  canonical_url: string;
  region: string | null;
  industry_tags: string[];
  topic_tags: string[];
  heat_value: string | null;
  heat_unit: string | null;
  evidence_status: string;
  published_at: string | null;
  discovered_at: string | null;
  expires_at: string | null;
  source: { id: string; source_key: string; display_name: string; enabled: boolean };
}

export interface AiCreative {
  excluded?: boolean;
  exclude_reason?: string | null;
  theme?: string;
  play?: string;
  offer?: {
    audience_condition?: string;
    mechanic?: string;
    discount_rule?: string;
  };
  target_audience?: string;
  borrow_logic?: string;
  risk_notes?: string[];
  channels?: string[];
  confidence?: number;
}

export interface MatchRow {
  id: string;
  store: { id: string; name: string; status: string };
  title: string;
  canonical_url: string;
  relevance_score: string | null;
  match_method: string;
  matching_algorithm_version: number;
  match_source: "rules" | "ai_creative";
  ai_creative: AiCreative | null;
  ai_confidence: string | null;
  ai_prompt_version: string | null;
  eligibility_status: string;
  reason_summary: string | null;
  suggested_scenario: string | null;
  content_angle: string | null;
  risk_flags: string[];
  matched_at: string | null;
  expires_at: string | null;
  stale_at: string | null;
  hot_topic: { id: string; evidence_status: string; published_at: string | null };
}

export interface AdminJob {
  id: string;
  job_type: string;
  status: string;
  store_id: string | null;
  store_name: string | null;
  attempt_count: number;
  max_attempts: number;
  progress_current: number | null;
  progress_total: number | null;
  error_code: string | null;
  error_summary: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  topics_inserted: number | null;
  opportunities_created: number | null;
  source_results: {
    source_key: string;
    entries?: number;
    inserted?: number;
    fallback_used?: boolean;
    attempts?: { url: string; error_code: string; summary: string }[];
  }[];
  source_failures: { source_key?: string; error_code: string; summary: string }[];
  match?: {
    opportunities_created?: number;
    rule_opportunities_created?: number;
    ai_opportunities_created?: number;
    ai_creative?: {
      candidates?: number;
      model_calls?: number;
      cache_hits?: number;
      excluded?: number;
      errors?: { error_code: string; summary: string }[];
    };
  };
}

export interface DispatchRow {
  id: string;
  store: { id: string; name: string };
  channel_key: string | null;
  status: string;
  attempt_count: number;
  platform_item_id: string | null;
  last_error_code: string | null;
  last_error_summary: string | null;
  created_at: string | null;
  updated_at: string | null;
  submitted_at: string | null;
  published_at: string | null;
  last_readback_at: string | null;
}

interface ListResponse<T> {
  items: T[];
  total: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ user: { id: string; email: string }; csrf_token: string }>(
      "/admin/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      },
    ),
  logout: () => request<void>("/admin/auth/logout", { method: "POST" }),
  refreshCsrf: () => request<{ csrf_token: string }>("/admin/auth/csrf", { method: "POST" }),
  me: () => request<AdminIdentity>("/admin/me"),
  overview: () => request<Overview>("/admin/overview"),
  stores: (params: { query?: string; status?: string; limit?: number; offset?: number }) =>
    request<ListResponse<StoreRow>>(`/admin/stores${toQuery(params)}`),
  createStore: (payload: { name: string; timezone: string; status?: string }) =>
    request<StoreRow>("/admin/stores", { method: "POST", body: JSON.stringify(payload) }),
  updateStore: (
    storeId: string,
    payload: { name?: string; timezone?: string; status?: string },
  ) =>
    request<StoreRow>(`/admin/stores/${storeId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  storeUsers: (params: {
    store_id?: string;
    query?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => request<ListResponse<StoreUserRow>>(`/admin/store-users${toQuery(params)}`),
  createStoreUser: (payload: {
    store_id: string;
    email: string;
    password: string;
    role: string;
  }) =>
    request<StoreUserRow>("/admin/store-users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateMembership: (
    storeId: string,
    membershipId: string,
    payload: { role?: string; status?: string },
  ) =>
    request<{ membership_id: string; role: string; status: string }>(
      `/admin/stores/${storeId}/members/${membershipId}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  resetPassword: (storeId: string, membershipId: string, password: string) =>
    request<void>(
      `/admin/stores/${storeId}/members/${membershipId}/reset-password`,
      { method: "POST", body: JSON.stringify({ password }) },
    ),
  opportunitySources: () =>
    request<{ items: OpportunitySource[] }>("/admin/opportunity-sources"),
  opportunitySourcePresets: () =>
    request<{ items: OpportunitySourcePreset[]; allowed_hosts: string[] }>(
      "/admin/opportunity-sources/presets",
    ),
  createOpportunitySource: (payload: OpportunitySourceInput) =>
    request<{ id: string; source_key: string; enabled: boolean; message?: string }>(
      "/admin/opportunity-sources",
      { method: "POST", body: JSON.stringify(payload) },
    ),
  updateOpportunitySource: (
    sourceId: string,
    payload: Partial<Omit<OpportunitySourceInput, "source_key" | "source_type">>,
  ) =>
    request<OpportunitySource>(`/admin/opportunity-sources/${sourceId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  enableOpportunitySource: (sourceId: string) =>
    request<{ id: string; enabled: boolean }>(
      `/admin/opportunity-sources/${sourceId}/enable`,
      { method: "POST" },
    ),
  disableOpportunitySource: (sourceId: string) =>
    request<{ id: string; enabled: boolean }>(
      `/admin/opportunity-sources/${sourceId}/disable`,
      { method: "POST" },
    ),
  hotTopics: (params: { query?: string; status?: string; limit?: number; offset?: number }) =>
    request<ListResponse<HotTopicRow>>(`/admin/hot-topics${toQuery(params)}`),
  matches: (params: {
    store_id?: string;
    query?: string;
    eligibility?: string;
    match_source?: string;
    limit?: number;
    offset?: number;
  }) =>
    request<
      ListResponse<MatchRow> & { source_counts?: { rules: number; ai_creative: number } }
    >(`/admin/opportunities${toQuery(params)}`),
  collect: (storeIds: string[] | null, idempotencyKey: string) =>
    request<{ status: string; items: { store_name: string; job_id: string }[]; message?: string }>(
      "/admin/opportunities/collect",
      {
        method: "POST",
        body: JSON.stringify(storeIds ? { store_ids: storeIds } : {}),
        headers: { "Idempotency-Key": idempotencyKey },
      },
    ),
  job: (jobId: string) => request<AdminJob>(`/admin/jobs/${jobId}`),
  dispatches: (params: {
    store_id?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => request<ListResponse<DispatchRow>>(`/admin/dispatches${toQuery(params)}`),
};

function toQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
