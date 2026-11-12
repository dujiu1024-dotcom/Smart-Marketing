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

export interface BrandGuideline {
  id: string;
  store_id: string;
  brand_story: string | null;
  positioning: string | null;
  differentiators: string | null;
  core_values_json: string[] | null;
  tone_of_voice: string | null;
  common_phrases_json: string[] | null;
  prohibited_phrases_json: string[] | null;
  cta_preferences_json: string[] | null;
  logo_asset_id: string | null;
  color_palette_json: Array<Record<string, unknown>> | null;
  font_preferences_json: string[] | null;
  visual_style: string | null;
  fact_status: string;
  current_version: number;
}

export interface BrandGuidelineInput {
  brand_story: string | null;
  positioning: string | null;
  differentiators: string | null;
  core_values_json: string[];
  tone_of_voice: string | null;
  common_phrases_json: string[];
  prohibited_phrases_json: string[];
  cta_preferences_json: string[];
  logo_asset_id: string | null;
  color_palette_json: Array<Record<string, unknown>>;
  font_preferences_json: string[];
  visual_style: string | null;
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


export async function listOffers(storeId: string): Promise<{ items: Offer[]; total: number }> {
  return request("/store/offers?limit=200&offset=0", {}, storeId);
}

export async function getOffer(storeId: string, offerId: string): Promise<Offer> {
  return request(`/store/offers/${encodeURIComponent(offerId)}`, {}, storeId);
}

export async function createOffer(storeId: string, input: OfferInput, idempotencyKey: string): Promise<Offer> {
  return request("/store/offers", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(input),
  }, storeId);
}

export async function updateOffer(storeId: string, offer: Offer, input: OfferInput): Promise<Offer> {
  return request(`/store/offers/${encodeURIComponent(offer.id)}`, {
    method: "PATCH",
    headers: { "If-Match": String(offer.current_version) },
    body: JSON.stringify(input),
  }, storeId);
}

export async function deleteOffer(storeId: string, offer: Offer): Promise<void> {
  return request(`/store/offers/${encodeURIComponent(offer.id)}`, {
    method: "DELETE",
    headers: { "If-Match": String(offer.current_version) },
  }, storeId);
}

export async function confirmOfferFacts(storeId: string, offer: Offer): Promise<Offer> {
  return request(`/store/offers/${encodeURIComponent(offer.id)}/confirm-facts`, {
    method: "POST",
    headers: { "If-Match": String(offer.current_version) },
    body: JSON.stringify({
      source_type: "merchant_ui_confirmation",
      source_ref: "store-offers-page",
      confirmation_note: "由当前门店成员核对活动规则与有效期后确认",
    }),
  }, storeId);
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

export async function getBrandGuideline(storeId: string): Promise<BrandGuideline> {
  return request("/store/brand-guideline", {}, storeId);
}

export async function createBrandGuideline(storeId: string, input: BrandGuidelineInput, idempotencyKey: string = crypto.randomUUID()): Promise<BrandGuideline> {
  return request("/store/brand-guideline", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(input),
  }, storeId);
}

export async function updateBrandGuideline(storeId: string, guideline: BrandGuideline, input: BrandGuidelineInput): Promise<BrandGuideline> {
  return request("/store/brand-guideline", {
    method: "PATCH",
    headers: { "If-Match": String(guideline.current_version) },
    body: JSON.stringify(input),
  }, storeId);
}

export async function confirmBrandGuidelineFacts(storeId: string, guideline: BrandGuideline): Promise<BrandGuideline> {
  return request(`/store/brand-guideline/${guideline.id}/confirm-facts`, {
    method: "POST",
    headers: { "If-Match": String(guideline.current_version) },
    body: JSON.stringify({
      source_type: "merchant_ui_confirmation",
      source_ref: "store-brand-guideline-page",
      confirmation_note: "由当前门店成员核对品牌定位、表达和视觉规范后确认",
    }),
  }, storeId);
}

export interface AudienceProfile {
  id: string; store_id: string; name: string; segment_type: "core" | "secondary" | "seasonal" | "scenario";
  audience_description: string | null; consumption_scenarios_json: string[] | null; consumption_periods_json: string[] | null;
  purchase_motivations_json: string[] | null; common_objections_json: string[] | null; source_type: string | null;
  source_ref: string | null; sample_size: number | null; sampled_at: string | null; confidence_level: string | null;
  fact_status: string; current_version: number;
}
export type AudienceProfileInput = Omit<AudienceProfile, "id" | "store_id" | "fact_status" | "current_version">;
export async function getAudienceProfiles(storeId: string): Promise<{ items: AudienceProfile[]; total: number }> {
  return request("/store/audiences?limit=200&offset=0", {}, storeId);
}
export async function createAudienceProfile(storeId: string, input: AudienceProfileInput, idempotencyKey: string = crypto.randomUUID()): Promise<AudienceProfile> {
  return request("/store/audiences", { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(input) }, storeId);
}
export async function updateAudienceProfile(storeId: string, current: AudienceProfile, input: AudienceProfileInput): Promise<AudienceProfile> {
  return request(`/store/audiences/${current.id}`, { method: "PATCH", headers: { "If-Match": String(current.current_version) }, body: JSON.stringify(input) }, storeId);
}
export async function deleteAudienceProfile(storeId: string, current: AudienceProfile): Promise<void> {
  return request(`/store/audiences/${current.id}`, { method: "DELETE", headers: { "If-Match": String(current.current_version) } }, storeId);
}
export async function confirmAudienceFacts(storeId: string, current: AudienceProfile): Promise<AudienceProfile> {
  return request(`/store/audiences/${current.id}/confirm-facts`, {
    method: "POST", headers: { "If-Match": String(current.current_version) },
    body: JSON.stringify({ source_type: "merchant_ui_confirmation", source_ref: "store-audience-page", confirmation_note: "由当前门店成员核对客群描述与样本来源后确认" }),
  }, storeId);
}
