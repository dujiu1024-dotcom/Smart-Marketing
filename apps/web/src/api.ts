const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const API_PREFIX = "/api/v1";
const CSRF_KEY = "store-operator.csrf";

export interface User {
  id: string;
  email: string;
}

export interface StoreSummary {
  id: string;
  name: string;
}

export interface StoreMembership extends StoreSummary {
  role: "owner" | "member";
}

export interface StoreProfile {
  id: string;
  store_id: string;
  display_name: string;
  business_type: string | null;
  industry_category: string | null;
  brand_name: string | null;
  introduction: string | null;
  country_code: string | null;
  region: string | null;
  province: string | null;
  city: string | null;
  district: string | null;
  address: string | null;
  phone: string | null;
  opening_hours_json: Record<string, unknown> | null;
  temporary_closures_json: Array<Record<string, unknown>> | null;
  service_radius: string | null;
  service_capabilities_json: string[] | null;
  fact_status: string;
  current_version: number;
}

export interface ProfileInput {
  display_name: string;
  business_type: string;
  industry_category: string;
  brand_name: string;
  introduction: string;
  country_code: string;
  region: string;
  province: string;
  city: string;
  district: string;
  address: string;
  phone: string;
  opening_hours_json: Record<string, unknown>;
  temporary_closures_json: Array<Record<string, unknown>>;
  service_radius: string;
  service_capabilities_json: string[];
}

interface ApiErrorBody {
  error?: { code?: string; message?: string };
  detail?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function endpoint(path: string): string {
  return `${API_BASE}${API_PREFIX}${path}`;
}

function csrfToken(): string {
  return sessionStorage.getItem(CSRF_KEY) ?? "";
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  storeId?: string,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (storeId) headers.set("X-Store-ID", storeId);
  if (["POST", "PATCH", "PUT", "DELETE"].includes((init.method ?? "GET").toUpperCase())) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  const response = await fetch(endpoint(path), {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      body.error?.message ?? body.detail ?? "请求失败，请稍后重试",
      response.status,
      body.error?.code ?? "REQUEST_FAILED",
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await request<{
    user: User;
    csrf_token: string;
  }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  sessionStorage.setItem(CSRF_KEY, response.csrf_token);
  return response.user;
}

export async function getCurrentUser(): Promise<User> {
  const response = await request<{ user: User }>("/auth/me");
  return response.user;
}

export async function getStores(): Promise<{
  items: StoreMembership[];
  active_store_id: string | null;
}> {
  return request("/me/stores");
}

export async function setActiveStore(storeId: string): Promise<void> {
  await request("/session/active-store", {
    method: "POST",
    body: JSON.stringify({ store_id: storeId }),
  });
}

export async function getStoreProfile(storeId: string): Promise<StoreProfile> {
  return request("/store/profile", {}, storeId);
}

export async function createStoreProfile(
  storeId: string,
  input: ProfileInput,
): Promise<StoreProfile> {
  return request(
    "/store/profile",
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(input),
    },
    storeId,
  );
}

export async function updateStoreProfile(
  storeId: string,
  profile: StoreProfile,
  input: ProfileInput,
): Promise<StoreProfile> {
  return request(
    "/store/profile",
    {
      method: "PATCH",
      headers: { "If-Match": String(profile.current_version) },
      body: JSON.stringify(input),
    },
    storeId,
  );
}

export function clearCsrfToken(): void {
  sessionStorage.removeItem(CSRF_KEY);
}
