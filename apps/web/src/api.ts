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


export interface KnowledgeItem {
  id: string;
  store_id: string;
  title: string;
  category: string;
  content_text: string | null;
  content_ref: string | null;
  content_hash: string | null;
  source_type: string | null;
  source_ref: string | null;
  effective_at: string | null;
  expires_at: string | null;
  fact_status: string;
  current_version: number;
}
export type KnowledgeItemInput = Omit<KnowledgeItem, "id" | "store_id" | "fact_status" | "current_version">;
export async function getKnowledgeItems(storeId: string): Promise<{ items: KnowledgeItem[]; total: number }> {
  return request("/store/knowledge?limit=200&offset=0", {}, storeId);
}
export async function createKnowledgeItem(storeId: string, input: KnowledgeItemInput, idempotencyKey: string = crypto.randomUUID()): Promise<KnowledgeItem> {
  return request("/store/knowledge", { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(input) }, storeId);
}
export async function updateKnowledgeItem(storeId: string, current: KnowledgeItem, input: KnowledgeItemInput): Promise<KnowledgeItem> {
  return request(`/store/knowledge/${encodeURIComponent(current.id)}`, { method: "PATCH", headers: { "If-Match": String(current.current_version) }, body: JSON.stringify(input) }, storeId);
}
export async function deleteKnowledgeItem(storeId: string, current: KnowledgeItem): Promise<void> {
  return request(`/store/knowledge/${encodeURIComponent(current.id)}`, { method: "DELETE", headers: { "If-Match": String(current.current_version) } }, storeId);
}
export async function confirmKnowledgeFacts(storeId: string, current: KnowledgeItem): Promise<KnowledgeItem> {
  return request(`/store/knowledge/${encodeURIComponent(current.id)}/confirm-facts`, {
    method: "POST",
    headers: { "If-Match": String(current.current_version) },
    body: JSON.stringify({ source_type: "merchant_ui_confirmation", source_ref: "store-knowledge-page", confirmation_note: "由当前门店成员核对知识内容与来源后确认" }),
  }, storeId);
}

export interface MediaAsset {
  id: string;
  store_id: string;
  asset_type: string;
  mime_type: string;
  byte_size: number;
  sha256: string;
  original_filename_sanitized: string | null;
  usage_rights_status: "unknown" | "confirmed_allowed" | "restricted";
  status: "uploading" | "quarantined" | "scanning" | "ready" | "rejected" | "archived";
  parent_asset_id: string | null;
  version_no: number;
  created_at: string;
}
export interface AssetUploadIntent {
  id: string;
  upload_url: string;
  method: "PUT";
  required_headers: Record<string, string>;
  expires_at: string;
}
export interface AssetUploadInput {
  expected_mime_type: "image/jpeg" | "image/png" | "image/webp";
  expected_byte_size: number;
  expected_sha256: string;
  original_filename: string;
}
export async function getMediaAssets(storeId: string): Promise<{ items: MediaAsset[]; total: number }> {
  return request("/store/assets?limit=100&offset=0", {}, storeId);
}
export async function createAssetUploadIntent(storeId: string, input: AssetUploadInput, idempotencyKey: string): Promise<AssetUploadIntent> {
  return request("/store/assets/upload-intents", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(input),
  }, storeId);
}
export async function putAssetFile(upload: AssetUploadIntent, file: File): Promise<void> {
  const response = await fetch(upload.upload_url, {
    method: upload.method,
    headers: upload.required_headers,
    body: file,
    credentials: "omit",
    redirect: "error",
  });
  if (!response.ok) throw new ApiError("文件上传到私有对象存储失败，请重试。", response.status, "OBJECT_UPLOAD_FAILED");
}
export async function completeAssetUpload(storeId: string, intentId: string): Promise<{ asset: MediaAsset; status: string }> {
  return request("/store/assets/upload-intents/" + intentId + "/complete", { method: "POST" }, storeId);
}
export async function confirmMediaAssetUsageRights(
  storeId: string,
  asset: MediaAsset,
  usageRightsStatus: "confirmed_allowed" | "restricted",
  licenseNote: string,
  idempotencyKey: string,
): Promise<MediaAsset> {
  return request("/store/assets/" + asset.id + "/confirm-usage-rights", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      expected_version: asset.version_no,
      expected_sha256: asset.sha256,
      usage_rights_status: usageRightsStatus,
      license_note: licenseNote,
    }),
  }, storeId);
}
export async function archiveMediaAsset(storeId: string, asset: MediaAsset, idempotencyKey: string): Promise<MediaAsset> {
  return request("/store/assets/" + asset.id + "/archive", {
    method: "POST",
    headers: { "If-Match": String(asset.version_no), "Idempotency-Key": idempotencyKey },
  }, storeId);
}
export async function getMediaAssetDownloadUrl(storeId: string, assetId: string): Promise<string> {
  const response = await request<{ url: string }>("/store/assets/" + assetId + "/download-url", {}, storeId);
  return response.url;
}


export type MarketingTaskType = "full_marketing" | "copy_only" | "image_only" | "image_optimization" | "merchant_content";
export type MarketingTaskStatus = "draft" | "active" | "waiting_for_user" | "blocked" | "failed" | "completed" | "cancelled" | "archived";
export type TaskStepStatus = "pending" | "running" | "waiting_for_user" | "succeeded" | "failed" | "skipped" | "stale";
export type StepApplicability = "required" | "optional" | "not_applicable";
export type TaskStepKey =
  | "requirement_understanding" | "context_snapshot" | "opportunity_decision"
  | "strategy_confirmation" | "copy_production_review" | "image_production_review"
  | "channel_adaptation" | "quality_check" | "final_confirmation" | "delivery";
export interface MarketingTaskOptions {
  includes_copy: boolean | null;
  includes_image: boolean | null;
  opportunity_applicable: boolean | null;
  opportunity_snapshot?: Record<string, unknown> | null;
  selected_channel_keys: string[];
  requires_external_delivery: boolean;
}
export interface TaskStep {
  id: string;
  step_key: TaskStepKey;
  status: TaskStepStatus;
  applicability: StepApplicability;
  version: number;
  skip_reason: string | null;
  input_fingerprint: string | null;
  output_refs: Array<Record<string, unknown>>;
  blocked_by: Array<Record<string, unknown>>;
  block_code: string | null;
  block_detail: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
}
export interface MarketingTaskSummary {
  id: string;
  store_id: string;
  task_type: MarketingTaskType;
  lifecycle_status: MarketingTaskStatus;
  title: string;
  version: number;
  current_requirement_snapshot_id: string | null;
  current_strategy_snapshot_id: string | null;
  created_at: string;
  updated_at: string;
  pending_steps_count: number;
  blocked_steps_count: number;
}
export interface MarketingTask extends MarketingTaskSummary {
  requirement_draft: Record<string, unknown>;
  strategy_draft: Record<string, unknown>;
  task_options: MarketingTaskOptions;
  steps: TaskStep[];
}
export interface MarketingTaskCreateInput {
  task_type: MarketingTaskType;
  title: string;
  opportunity_id?: string | null;
  requirement_draft: Record<string, unknown>;
  task_options: MarketingTaskOptions;
}
export interface BusinessFactReference {
  fact_key: string;
  record_type: "store_profile" | "product" | "offer" | "audience_profile" | "brand_guideline" | "knowledge_item";
  record_id: string;
  expected_version_no: number;
}
export async function listMarketingTasks(storeId: string, filters: { lifecycle_status?: MarketingTaskStatus; task_type?: MarketingTaskType } = {}): Promise<{ items: MarketingTaskSummary[]; total: number }> {
  const params = new URLSearchParams({ limit: "100", offset: "0" });
  if (filters.lifecycle_status) params.set("lifecycle_status", filters.lifecycle_status);
  if (filters.task_type) params.set("task_type", filters.task_type);
  return request(`/marketing-tasks?${params.toString()}`, {}, storeId);
}
export async function getMarketingTask(storeId: string, taskId: string): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(taskId)}`, {}, storeId);
}
export async function createMarketingTask(storeId: string, input: MarketingTaskCreateInput, idempotencyKey: string = crypto.randomUUID()): Promise<MarketingTask> {
  return request("/marketing-tasks", { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(input) }, storeId);
}
export async function updateMarketingTaskRequirement(storeId: string, task: MarketingTask, requirementDraft: Record<string, unknown>): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/requirement`, {
    method: "PATCH", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version, requirement_draft: requirementDraft }),
  }, storeId);
}
export async function confirmMarketingTaskRequirement(storeId: string, task: MarketingTask, businessFacts: BusinessFactReference[]): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/requirement/confirm`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version, business_facts: businessFacts }),
  }, storeId);
}
export async function updateMarketingTaskStrategy(storeId: string, task: MarketingTask, strategy: Record<string, unknown>): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/strategy`, {
    method: "PATCH", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version, strategy }),
  }, storeId);
}
export async function confirmMarketingTaskStrategy(storeId: string, task: MarketingTask): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/strategy/confirm`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version }),
  }, storeId);
}
export async function skipMarketingTaskStep(storeId: string, task: MarketingTask, stepKey: TaskStepKey, reason: string): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/steps/${encodeURIComponent(stepKey)}/skip`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version, reason }),
  }, storeId);
}
export async function recoverMarketingTaskStep(storeId: string, task: MarketingTask, stepKey: TaskStepKey, reason: string): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/recover`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version, step_key: stepKey, reason }),
  }, storeId);
}
export async function cancelMarketingTask(storeId: string, task: MarketingTask, reason: string): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/cancel`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version, reason }),
  }, storeId);
}
export async function archiveMarketingTask(storeId: string, task: MarketingTask, reason: string): Promise<MarketingTask> {
  return request(`/marketing-tasks/${encodeURIComponent(task.id)}/archive`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ expected_version: task.version, reason }),
  }, storeId);
}


export interface DouyinAccount {
  id: string;
  provider: "douyin";
  external_account_id: string;
  display_name: string | null;
  avatar_url: string | null;
  granted_scopes: string[];
  access_token_expires_at: string;
  refresh_token_expires_at: string | null;
  status: "active" | "reauth_required" | "revoked" | "error";
  connected_at: string;
  last_verified_at: string | null;
}
export async function listDouyinAccounts(storeId: string): Promise<DouyinAccount[]> {
  return request("/channels/douyin/accounts", {}, storeId);
}
export async function startDouyinAuthorization(storeId: string): Promise<{ authorization_url: string; expires_in: string }> {
  return request("/channels/douyin/oauth/authorize", { method: "POST" }, storeId);
}
export async function refreshDouyinAccount(storeId: string, accountId: string): Promise<DouyinAccount> {
  return request(`/channels/douyin/accounts/${encodeURIComponent(accountId)}/refresh`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
  }, storeId);
}


export interface ArtifactVersionRecord {
  id: string;
  artifact_id: string;
  version_no: number;
  source_type: "ai_generated" | "merchant_upload" | "manual_edit";
  source_refs: Array<Record<string, unknown>>;
  instruction: string | null;
  content_json: Record<string, unknown> | null;
  content_hash: string;
  provider_id: string | null;
  model_id: string | null;
  prompt_version_id: string | null;
  input_fingerprint: string;
  created_at: string;
  reviews: Array<{
    id: string;
    review_type: "copy" | "image";
    decision: "approved" | "revision_requested" | "rejected";
    comment: string | null;
    target: Record<string, unknown> | null;
    created_at: string;
  }>;
}
export interface ContentArtifact {
  id: string;
  task_id: string;
  artifact_type: "copy" | "image";
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
  versions: ArtifactVersionRecord[];
}
export interface ContentArtifactVersionInput {
  source_type: "ai_generated" | "merchant_upload" | "manual_edit";
  source_refs?: Array<Record<string, unknown>>;
  instruction?: string | null;
  content_json?: Record<string, unknown> | null;
  media_asset_id?: string | null;
  provider_id?: string | null;
  model_id?: string | null;
  prompt_version_id?: string | null;
}
export interface ContentReviewInput {
  expected_version: number;
  review_type: "copy" | "image";
  decision: "approved" | "revision_requested" | "rejected";
  comment?: string | null;
  target?: Record<string, unknown> | null;
}
export async function listTaskArtifacts(storeId: string, taskId: string): Promise<ContentArtifact[]> {
  return request(`/marketing-tasks/${encodeURIComponent(taskId)}/artifacts`, {}, storeId);
}
export async function createTaskArtifact(
  storeId: string, taskId: string, artifactType: "copy" | "image",
  version: ContentArtifactVersionInput, idempotencyKey: string = crypto.randomUUID(),
): Promise<ContentArtifact> {
  return request(`/marketing-tasks/${encodeURIComponent(taskId)}/artifacts`, {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ artifact_type: artifactType, version }),
  }, storeId);
}
export async function createTaskArtifactVersion(
  storeId: string, taskId: string, artifact: ContentArtifact,
  version: ContentArtifactVersionInput, idempotencyKey: string = crypto.randomUUID(),
): Promise<ArtifactVersionRecord> {
  const currentVersion = artifact.versions.find(item => item.id === artifact.current_version_id);
  if (!currentVersion) throw new ApiError("当前产物版本不存在，请刷新后重试。", 409, "ARTIFACT_VERSION_MISSING");
  return request(`/marketing-tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifact.id)}/versions`, {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ ...version, expected_version: currentVersion.version_no }),
  }, storeId);
}
export async function createTaskArtifactReview(
  storeId: string, taskId: string, artifact: ContentArtifact, version: ArtifactVersionRecord,
  input: ContentReviewInput, idempotencyKey: string = crypto.randomUUID(),
): Promise<Record<string, unknown>> {
  return request(
    `/marketing-tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifact.id)}/versions/${encodeURIComponent(version.id)}/reviews`,
    { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(input) },
    storeId,
  );
}


export interface ChannelSpecVersionRecord {
  id: string;
  channel_spec_id: string;
  spec_version: number;
  text_constraints: Record<string, unknown>;
  media_constraints: Record<string, unknown>;
  hashtag_constraints: Record<string, unknown>;
  link_constraints: Record<string, unknown>;
  schedule_constraints: Record<string, unknown>;
  draft_supported: boolean;
  publish_supported: boolean;
  verification_status: "pending_verification" | "verified" | "deprecated";
  source_document_ref: string | null;
  published_at: string | null;
  created_at: string;
}
export interface ChannelSpecRecord {
  id: string;
  channel_key: string;
  status: "active" | "archived";
  current_version: ChannelSpecVersionRecord | null;
}
export async function listChannelSpecs(storeId: string): Promise<ChannelSpecRecord[]> {
  return request("/channels/specs", {}, storeId);
}
export async function listChannelSpecVersions(storeId: string, channelKey: string): Promise<ChannelSpecVersionRecord[]> {
  return request(`/channels/specs/${encodeURIComponent(channelKey)}/versions`, {}, storeId);
}




export interface TaskBusinessFactSnapshot {
  id: string;
  fact_key: string;
  version_no: number;
  value: Record<string, unknown>;
  content_fingerprint: string;
  confirmation_status: "pending" | "confirmed" | "rejected" | "needs_review";
  confirmed_at: string | null;
}
export async function listTaskBusinessFacts(storeId: string, taskId: string): Promise<TaskBusinessFactSnapshot[]> {
  return request("/marketing-tasks/" + encodeURIComponent(taskId) + "/business-facts", {}, storeId);
}
export interface ChannelContentQualityReport {
  id: string;
  rule_version: string;
  input_fingerprint: string;
  result: "pass" | "fail" | "needs_human";
  issues: Array<Record<string, unknown>>;
  resolutions: Array<{ id: string; decision: "accepted" | "rejected"; reason: string; created_at: string }>;
  created_at: string;
}
export interface ChannelContentRecord {
  id: string;
  task_id: string;
  channel_key: string;
  copy_version_id: string;
  channel_spec_version_id: string;
  payload: Record<string, unknown>;
  input_fingerprint: string;
  status: "ready" | "stale" | "blocked";
  image_version_ids: string[];
  quality_reports: ChannelContentQualityReport[];
  created_at: string;
  updated_at: string;
}
export interface PublishPackageRecord {
  id: string;
  task_id: string;
  package_version: number;
  package_fingerprint: string;
  frozen_at: string;
  frozen_by_user_id: string | null;
  items: Array<{
    id: string;
    channel_key: string;
    channel_content_id: string;
    quality_report_id: string;
    delivery_mode: "official_api" | "manual_handoff";
    channel_account_id: string | null;
    planned_publish_at: string | null;
    item_fingerprint: string;
  }>;
  fact_snapshot_ids: string[];
  confirmation: {
    id: string;
    package_fingerprint: string;
    confirmed_by_user_id: string;
    confirmed_at: string;
    confirmation_note: string | null;
  } | null;
}
export interface PublishPackageFreezeInput {
  expected_task_version: number;
  fact_snapshot_ids: string[];
  items: Array<{
    channel_content_id: string;
    quality_report_id: string;
    delivery_mode: "official_api" | "manual_handoff";
    channel_account_id?: string | null;
    planned_publish_at?: string | null;
  }>;
}
export async function createChannelContent(
  storeId: string, taskId: string, input: {
    channel_key: string;
    copy_version_id: string;
    channel_spec_version_id: string;
    payload: Record<string, unknown>;
    image_version_ids: string[];
  }, idempotencyKey: string = crypto.randomUUID(),
): Promise<ChannelContentRecord> {
  return request("/marketing-tasks/" + encodeURIComponent(taskId) + "/channel-contents", {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(input),
  }, storeId);
}
export async function listChannelContents(storeId: string, taskId: string): Promise<ChannelContentRecord[]> {
  return request("/marketing-tasks/" + encodeURIComponent(taskId) + "/channel-contents", {}, storeId);
}
export async function runChannelContentQuality(
  storeId: string, taskId: string, content: ChannelContentRecord,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<{ job_id: string; job_status: string; channel_content_id: string; expected_fingerprint: string; rule_version: string }> {
  return request(
    "/marketing-tasks/" + encodeURIComponent(taskId) + "/channel-contents/" + encodeURIComponent(content.id) + "/quality-reports/run",
    {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ rule_version: "content-structure-v1", expected_fingerprint: content.input_fingerprint }),
    }, storeId,
  );
}

export async function createQualityResolution(
  storeId: string, reportId: string, expectedFingerprint: string, reason: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<{ id: string; quality_report_id: string; decision: "accepted" | "rejected"; reason: string }> {
  return request(
    "/marketing-tasks/quality-reports/" + encodeURIComponent(reportId) + "/resolutions",
    {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ decision: "accepted", reason, expected_fingerprint: expectedFingerprint }),
    }, storeId,
  );
}
export async function freezePublishPackage(
  storeId: string, taskId: string, input: PublishPackageFreezeInput,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<PublishPackageRecord> {
  return request(
    "/marketing-tasks/" + encodeURIComponent(taskId) + "/publish-packages/freeze",
    { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(input) },
    storeId,
  );
}
export async function confirmPublishPackage(
  storeId: string, packageId: string, packageFingerprint: string, confirmationNote: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<PublishPackageRecord["confirmation"]> {
  return request(
    "/marketing-tasks/publish-packages/" + encodeURIComponent(packageId) + "/confirm",
    {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ package_fingerprint: packageFingerprint, confirmation_note: confirmationNote || null }),
    }, storeId,
  );
}
export async function listPublishPackages(storeId: string, taskId: string): Promise<PublishPackageRecord[]> {
  return request("/marketing-tasks/" + encodeURIComponent(taskId) + "/publish-packages", {}, storeId);
}

export interface ChannelCapabilitySnapshotRecord {
  id: string;
  channel_account_id: string;
  channel_spec_version_id: string;
  capability_key: string;
  support_status: "supported" | "unsupported" | "pending_verification";
  evidence_ref: string | null;
  reason: string | null;
  checked_at: string;
  expires_at: string | null;
}
export async function listDouyinAccountCapabilities(storeId: string, accountId: string): Promise<ChannelCapabilitySnapshotRecord[]> {
  return request(`/channels/douyin/accounts/${encodeURIComponent(accountId)}/capabilities`, {}, storeId);
}


export interface OpportunityItem {
  id: string;
  title: string;
  summary: string | null;
  source_url: string;
  published_at: string | null;
  discovered_at: string;
  expires_at: string | null;
  region: string | null;
  heat_value: string | null;
  heat_unit: string | null;
  evidence_status: string;
  relevance_score: string | null;
  match_method: string;
  matching_algorithm_version: number;
  reason_summary: string | null;
  suggested_scenario: string | null;
  content_angle: string | null;
  risk_flags: string[];
  eligibility_status: string;
  decision: string | null;
}
export interface OpportunityList {
  items: OpportunityItem[];
  total: number;
  source_status: "available" | "unavailable";
  empty_reason: string | null;
}
export interface MetricDefinitionRecord {
  id: string;
  source_system: string;
  metric_key: string;
  metric_tier: "content_performance" | "intent" | "business_outcome";
  display_name: string;
  unit: string | null;
  definition: string;
  definition_version: number;
}
export interface MetricObservationRecord {
  id: string;
  metric_key: string;
  metric_tier: "content_performance" | "intent" | "business_outcome";
  display_name: string;
  value_numeric: string | null;
  unit: string | null;
  currency: string | null;
  source_system: string;
  source_record_id: string | null;
  source_evidence_ref: string | null;
  period_start: string | null;
  period_end: string | null;
  period_timezone: string;
  collected_at: string;
  definition_version: number;
  integrity_status: string;
  authenticity_status: string;
  sync_status: string;
  supersedes_observation_id: string | null;
  import_batch_id: string | null;
  published_work_id: string | null;
  marketing_task_id: string | null;
}
export interface DataSourceCapabilitySnapshotRecord {
  id: string; channel_key: string; capability_key: string; status: string;
  required_scopes: string[]; granted_scopes: string[]; evidence_ref: string | null;
  snapshot_version: number; checked_at: string; reason: string | null;
}
export interface PublishReadbackCandidate {
  publish_operation_id: string; marketing_task_id: string; channel_key: string;
  channel_account_id: string; channel_provider: string; external_work_id: string;
  published_at: string | null; readback_at: string;
}
export interface PublishedWorkRecord {
  id: string; task_id: string | null; publish_operation_id: string | null;
  channel_account_id: string | null; channel_key: string; external_work_id: string;
  title: string | null; permalink: string | null; published_at: string | null;
  ownership_status: string; verified_at: string | null; source_snapshot: Record<string, unknown>;
}
export interface BusinessOutcomeEvidenceRecord {
  id: string; outcome_type: string; value_numeric: string; currency: string | null;
  source_system: string; source_record_id: string | null; source_evidence_ref: string | null;
  occurred_at: string; authenticity_status: string; integrity_status: string;
}
export interface AttributionEvidenceRecord {
  id: string; marketing_task_id: string; published_work_id: string; outcome_evidence_id: string;
  attribution_method: string; evidence_strength: string; allocation_percent: string;
  status: string; snapshot: Record<string, unknown>; reversal_reason: string | null; reversed_at: string | null;
}
export interface EffectsOverview {
  items: Array<{
    metric_key: string; display_name: string; metric_tier: string; value: string | null;
    status: "available" | "unavailable"; reason: string | null; source_system: string;
    period_end: string | null; period_timezone: string; collected_at: string;
    authenticity_status: string; integrity_status: string;
  }>;
  trends: Array<{
    metric_key: string; display_name: string; source_system: string; channel_key: string | null;
    points: Array<{
      period_start: string; period_end: string; value: string; sample_count: number;
      timezone: string; aggregation_rule: string; display_name: string;
    }>;
    comparison: { status: string; change_percent: string | null };
  }>;
  conversion_rates: Array<{
    metric_key: string; display_name: string; numerator_key: string; denominator_key: string;
    source_system: string; channel_key: string | null;
    period_start: string; period_end: string; timezone: string;
    numerator_value: string; denominator_value: string;
    value_percent: string | null; status: string;
  }>;
  content_performance: Array<{
    published_work_id: string; marketing_task_id: string | null; channel_key: string;
    external_work_id: string; metric_key: string; source_system: string; display_name: string;
    points: Array<{ period_start: string; period_end: string; value: string; sample_count: number; timezone: string }>;
    comparison: { status: string; change_percent: string | null };
  }>;
  data_quality: {
    total_observations: number; verified_observations: number; delayed_observations: number;
    incomplete_or_anomalous_observations: number; status: string; reason: string | null;
  };
  data_status: "available" | "unavailable";
  business_outcomes: { roi: number | null; sales_growth: number | null; store_visit_growth: number | null; reason: string };
}
export function getOpportunities(storeId: string): Promise<OpportunityList> {
  return request<OpportunityList>("/opportunities", {}, storeId);
}
export function getOpportunity(storeId: string, opportunityId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/opportunities/${encodeURIComponent(opportunityId)}`, {}, storeId);
}
export function decideOpportunity(storeId: string, opportunityId: string, decision: "adopt" | "ignore" | "snooze", reason: string, idempotencyKey: string): Promise<{ id: string; decision: string; replayed: boolean }> {
  return request("/opportunities/" + encodeURIComponent(opportunityId) + "/decisions", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ decision, reason: reason || null }),
  }, storeId);
}
export function getEffectsOverview(storeId: string): Promise<EffectsOverview> {
  return request<EffectsOverview>("/effects/overview", {}, storeId);
}
export function getMetricDefinitions(): Promise<{ items: MetricDefinitionRecord[] }> {
  return request<{ items: MetricDefinitionRecord[] }>("/effects/definitions");
}
export function getMetricObservations(storeId: string): Promise<{ items: MetricObservationRecord[] }> {
  return request<{ items: MetricObservationRecord[] }>("/effects/observations", {}, storeId);
}
export function createMetricObservation(storeId: string, payload: {
  metric_key: string; value_numeric: string | null; currency: string | null; period_start: string | null;
  period_end: string | null; period_timezone: string; source_record_id: string | null;
  source_evidence_ref: string | null;
  published_work_id?: string | null;
  marketing_task_id?: string | null;
}): Promise<{ item: MetricObservationRecord; message: string }> {
  return request("/effects/observations", { method: "POST", body: JSON.stringify(payload) }, storeId);
}
export function importMetricCsv(storeId: string, csvText: string): Promise<{
  created: number; duplicates_skipped: number; import_batch_id: string;
  content_sha256: string; authenticity_status: string; message: string;
}> {
  return request("/effects/import", { method: "POST", body: JSON.stringify({ csv_text: csvText }) }, storeId);
}

export function getDataSourceCapabilities(storeId: string): Promise<{ items: DataSourceCapabilitySnapshotRecord[]; total: number }> {
  return request("/effects/data-source-capabilities", {}, storeId);
}
export function checkDataSourceCapabilities(storeId: string): Promise<{ items: DataSourceCapabilitySnapshotRecord[]; total: number }> {
  return request("/effects/data-source-capabilities/check", { method: "POST" }, storeId);
}
export function getPublishReadbacks(storeId: string): Promise<{ items: PublishReadbackCandidate[]; total: number }> {
  return request("/effects/publish-readbacks", {}, storeId);
}
export function getPublishedWorks(storeId: string): Promise<{ items: PublishedWorkRecord[]; total: number; verified_count: number }> {
  return request("/effects/published-works", {}, storeId);
}
export function getBusinessOutcomes(storeId: string): Promise<{ items: BusinessOutcomeEvidenceRecord[]; total: number }> {
  return request("/effects/business-outcomes", {}, storeId);
}
export function createBusinessOutcome(storeId: string, payload: {
  outcome_type: string; value_numeric: string; currency?: string | null;
  source_record_id?: string | null; source_evidence_ref: string; occurred_at: string;
}): Promise<{ item: BusinessOutcomeEvidenceRecord; replayed: boolean; message?: string }> {
  return request("/effects/business-outcomes", { method: "POST", body: JSON.stringify(payload) }, storeId);
}
export function getAttributions(storeId: string): Promise<{ items: AttributionEvidenceRecord[]; total: number }> {
  return request("/effects/attributions", {}, storeId);
}
export function reverseAttribution(storeId: string, attributionId: string, reason: string): Promise<{ item: AttributionEvidenceRecord; message: string }> {
  return request(
    `/effects/attributions/${encodeURIComponent(attributionId)}/reversal`,
    { method: "POST", body: JSON.stringify({ reason }) },
    storeId,
  );
}
export function registerPublishedWorkFromReadback(storeId: string, operationId: string): Promise<{ item: PublishedWorkRecord; replayed: boolean }> {
  return request(
    `/effects/published-works/from-publish-operation/${encodeURIComponent(operationId)}`,
    { method: "POST" },
    storeId,
  );
}
export function requestOpportunityCollection(storeId: string, idempotencyKey: string): Promise<{
  status: string; job_id: string | null; source_count?: number; message?: string;
}> {
  return request("/opportunities/collect", {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey },
  }, storeId);
}
