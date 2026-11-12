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

export interface Product {
  id: string;
  store_id: string;
  name: string;
  category: string | null;
  sku: string | null;
  specification: string | null;
  unit: string | null;
  price_amount: string | null;
  currency: string | null;
  availability_status: "available" | "unavailable" | "seasonal" | "limited" | "unknown";
  inventory_quantity: string | null;
  key_selling_points_json: string[] | null;
  description: string | null;
  ingredients_or_materials: string | null;
  allergens_and_restrictions_json: string[] | null;
  service_process: string | null;
  delivery_method: string | null;
  fact_status: string;
  current_version: number;
}

export interface ProductInput {
  name: string;
  category: string | null;
  sku: string | null;
  specification: string | null;
  unit: string | null;
  price_amount: string | null;
  currency: string | null;
  availability_status: Product["availability_status"];
  inventory_quantity: string | null;
  key_selling_points_json: string[];
  description: string | null;
  ingredients_or_materials: string | null;
  allergens_and_restrictions_json: string[];
  service_process: string | null;
  delivery_method: string | null;
}

export interface Offer {
  id: string;
  store_id: string;
  title: string;
  offer_type: string;
  terms_json: Record<string, unknown>;
  eligibility_rules_json: Record<string, unknown>;
  starts_at: string | null;
  ends_at: string | null;
  stacking_policy: string | null;
  usage_limit: number | null;
  status: "draft" | "active" | "paused" | "expired" | "archived";
  fact_status: string;
  current_version: number;
}

export interface OfferInput {
  title: string;
  offer_type: string;
  terms_json: Record<string, unknown>;
  eligibility_rules_json: Record<string, unknown>;
  starts_at: string | null;
  ends_at: string | null;
  stacking_policy: string | null;
  usage_limit: number | null;
  status: Offer["status"];
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

export async function refreshCsrfToken(): Promise<void> {
  const response = await request<{ csrf_token: string }>("/auth/csrf", {
    method: "POST",
  });
  sessionStorage.setItem(CSRF_KEY, response.csrf_token);
}

export async function logout(): Promise<void> {
  await request<void>("/auth/logout", { method: "POST" });
  sessionStorage.removeItem(CSRF_KEY);
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

export async function confirmStoreProfileFacts(
  storeId: string,
  profile: StoreProfile,
): Promise<StoreProfile> {
  return request(
    `/store/profile/${profile.id}/confirm-facts`,
    {
      method: "POST",
      headers: { "If-Match": String(profile.current_version) },
      body: JSON.stringify({
        source_type: "merchant_ui_confirmation",
        source_ref: "store-profile-page",
        confirmation_note: "由当前门店成员核对后确认",
      }),
    },
    storeId,
  );
}

export function clearCsrfToken(): void {
  sessionStorage.removeItem(CSRF_KEY);
}

export async function getProducts(storeId: string): Promise<{ items: Product[]; total: number }> {
  return request("/store/products?limit=200&offset=0", {}, storeId);
}

export async function createProduct(storeId: string, input: ProductInput): Promise<Product> {
  return request("/store/products", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(input),
  }, storeId);
}

export async function updateProduct(storeId: string, product: Product, input: ProductInput): Promise<Product> {
  return request(`/store/products/${product.id}`, {
    method: "PATCH",
    headers: { "If-Match": String(product.current_version) },
    body: JSON.stringify(input),
  }, storeId);
}

export async function confirmProductFacts(storeId: string, product: Product): Promise<Product> {
  return request(`/store/products/${product.id}/confirm-facts`, {
    method: "POST",
    headers: { "If-Match": String(product.current_version) },
    body: JSON.stringify({
      source_type: "merchant_ui_confirmation",
      source_ref: "store-products-page",
      confirmation_note: "由当前门店成员核对商品事实后确认",
    }),
  }, storeId);
}

export async function getOffers(storeId: string): Promise<{ items: Offer[]; total: number }> {
  return request("/store/offers?limit=200&offset=0", {}, storeId);
}

export async function createOffer(storeId: string, input: OfferInput): Promise<Offer> {
  return request("/store/offers", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(input),
  }, storeId);
}

export async function updateOffer(storeId: string, offer: Offer, input: OfferInput): Promise<Offer> {
  return request(`/store/offers/${offer.id}`, {
    method: "PATCH",
    headers: { "If-Match": String(offer.current_version) },
    body: JSON.stringify(input),
  }, storeId);
}

export async function confirmOfferFacts(storeId: string, offer: Offer): Promise<Offer> {
  return request(`/store/offers/${offer.id}/confirm-facts`, {
    method: "POST",
    headers: { "If-Match": String(offer.current_version) },
    body: JSON.stringify({
      source_type: "merchant_ui_confirmation",
      source_ref: "store-offers-page",
      confirmation_note: "由当前门店成员核对活动规则和有效期后确认",
    }),
  }, storeId);
}
