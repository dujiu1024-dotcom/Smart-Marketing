import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  archiveMarketingTask, cancelMarketingTask, confirmMarketingTaskRequirement,
  createChannelContent, runChannelContentQuality, createQualityResolution,
  freezePublishPackage, confirmPublishPackage, listChannelContents, listPublishPackages,
  listChannelSpecs, listTaskBusinessFacts,
  confirmMarketingTaskStrategy, createMarketingTask, getAudienceProfiles, getMediaAssets,
  getBrandGuideline, getArtifactVersionDownloadUrl, getKnowledgeItems, getMarketingTask, listOffers, listTaskArtifacts,
  createTaskArtifact, createTaskArtifactVersion, createTaskArtifactReview,
  getProducts, getStoreProfile, listMarketingTasks, recoverMarketingTaskStep,
  skipMarketingTaskStep, updateMarketingTaskRequirement, updateMarketingTaskStrategy,
  getOpportunities,
  type BusinessFactReference, type ContentArtifact, type ArtifactVersionRecord,
  type MediaAsset, type MarketingTask, type MarketingTaskCreateInput,
  type MarketingTaskSummary, type MarketingTaskType, type TaskStep, type TaskStepKey,
  type ChannelContentRecord, type ChannelSpecRecord, type PublishPackageRecord,
  type TaskBusinessFactSnapshot, type OpportunityItem,
} from "./api";

const taskTypeLabels: Record<MarketingTaskType, string> = {
  full_marketing: "完整营销执行",
  copy_only: "仅制作文案",
  image_only: "仅制作图片",
  image_optimization: "图片优化",
  merchant_content: "商家已有素材制作",
};
const stepLabels: Record<TaskStepKey, string> = {
  requirement_understanding: "需求理解",
  context_snapshot: "经营事实确认",
  opportunity_decision: "营销机会判断",
  strategy_confirmation: "策略确认",
  copy_production_review: "文案制作与审核",
  image_production_review: "图片制作与审核",
  channel_adaptation: "渠道内容适配",
  quality_check: "内容质检",
  final_confirmation: "最终发布确认",
  delivery: "发布与交付",
};
const taskTabs = [
  { key: "requirement", label: "需求与事实" },
  { key: "strategy", label: "营销策略" },
  { key: "content", label: "内容制作" },
  { key: "channel", label: "渠道与质检" },
  { key: "publish", label: "发布确认" },
  { key: "flow", label: "执行流程" },
] as const;
type TaskTabKey = (typeof taskTabs)[number]["key"];
const isTaskTab = (value: string | null): value is TaskTabKey => taskTabs.some(tab => tab.key === value);
const taskTabStorageKey = (taskId: string) => `store-operator.task-tab.${taskId}`;
function defaultTaskTab(task: MarketingTask): TaskTabKey {
  if (!task.current_requirement_snapshot_id) return "requirement";
  if (!task.current_strategy_snapshot_id) return "strategy";
  return "content";
}
const statusLabels: Record<string, string> = {
  draft: "草稿", active: "执行中", waiting_for_user: "待商家处理", blocked: "已阻塞",
  failed: "执行失败", completed: "已完成", cancelled: "已取消", archived: "已归档",
  pending: "待处理", running: "执行中", succeeded: "已完成", skipped: "已跳过", stale: "需重新检查",
  required: "必需", optional: "可选", not_applicable: "不适用",
};
const draftFieldLabels: Record<string, string> = {
  goal: "经营目标", target_audience: "目标客群", core_message: "核心信息", constraints: "约束条件",
};
const channelLabel = (key: string): string => key === "douyin" ? "抖音" : key;
const qualityResultLabels: Record<string, string> = {
  pass: "通过", needs_human: "待人工复核", fail: "未通过",
};
const qualityDecisionLabels: Record<string, string> = {
  accepted: "接受", rejected: "拒绝",
};
const severityLabels: Record<string, string> = {
  info: "提示", warning: "警告", error: "错误",
};
const sourceTypeLabels: Record<string, string> = {
  ai_generated: "AI 生成", merchant_upload: "商家上传", manual_edit: "手工编辑",
};
const reviewLabels: Record<string, string> = {
  approved: "审核通过", revision_requested: "需要修改", rejected: "已拒绝",
};
const latestReviewFor = (version: ArtifactVersionRecord) =>
  version.reviews && version.reviews.length > 0 ? version.reviews[version.reviews.length - 1] : undefined;
function formatBytes(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
const stepStatusLabel = (step: TaskStep): string =>
  step.status === "failed" && step.block_code ? "已阻塞" : statusLabels[step.status] ?? "状态未知";
const blockSummary = (step: TaskStep): string => {
  const summary = step.block_detail?.["summary"];
  return typeof summary === "string" ? summary : "";
};
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请稍后重试。";
const selectedTaskKey = (storeId: string) => `store-operator.current-task-id.${storeId}`;
const createTaskKey = (storeId: string) => `store-operator.task-create.${storeId}`;
const opportunityHandoffKey = (storeId: string) => `store-operator.opportunity-handoff.${storeId}`;
const readText = (record: Record<string, unknown>, key: string) => typeof record[key] === "string" ? String(record[key]) : "";
function safeJson(value: Record<string, unknown>): string { return JSON.stringify(value, null, 2); }
interface FactOption extends BusinessFactReference { label: string; }
interface DraftForm { goal: string; target_audience: string; core_message: string; constraints: string; }
interface AiArtifactEntry {
  taskId: string;
  taskTitle: string;
  artifact: ContentArtifact;
  version: ArtifactVersionRecord;
}

function requirementForm(value: Record<string, unknown>): DraftForm {
  return {
    goal: readText(value, "goal"),
    target_audience: readText(value, "target_audience"),
    core_message: readText(value, "core_message"),
    constraints: readText(value, "constraints"),
  };
}
function requirementPayload(form: DraftForm): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  if (form.goal.trim()) result.goal = form.goal.trim();
  if (form.target_audience.trim()) result.target_audience = form.target_audience.trim();
  if (form.core_message.trim()) result.core_message = form.core_message.trim();
  if (form.constraints.trim()) result.constraints = form.constraints.trim();
  return result;
}
function Field({ label, value, onChange, placeholder, rows = 1 }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; rows?: number }) {
  return <label className={rows > 1 ? "field span-2" : "field"}><span>{label}</span>{rows > 1 ? <textarea rows={rows} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} /> : <input value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} />}</label>;
}
function taskTypeOptions(type: MarketingTaskType) {
  if (type === "full_marketing") return { includes_copy: true, includes_image: true };
  if (type === "copy_only") return { includes_copy: true, includes_image: false };
  if (type === "image_only" || type === "image_optimization") return { includes_copy: false, includes_image: true };
  return { includes_copy: true, includes_image: true };
}

export default function MarketingTaskWorkspace({ storeId, storeName }: { storeId: string; storeName?: string }) {
  const [route, setRoute] = useState(window.location.hash || "#ai");
  const [items, setItems] = useState<MarketingTaskSummary[]>([]);
  const [aiOpportunities, setAiOpportunities] = useState<OpportunityItem[]>([]);
  const [aiOpportunitySource, setAiOpportunitySource] = useState<"available" | "unavailable">("available");
  const [aiArtifacts, setAiArtifacts] = useState<AiArtifactEntry[]>([]);
  const [aiImageUrls, setAiImageUrls] = useState<Record<string, string>>({});
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [task, setTask] = useState<MarketingTask | null>(null);
  const [facts, setFacts] = useState<FactOption[]>([]);
  const [selectedFacts, setSelectedFacts] = useState<string[]>([]);
  const [artifacts, setArtifacts] = useState<ContentArtifact[]>([]);
  const [mediaAssets, setMediaAssets] = useState<MediaAsset[]>([]);
  const [channelSpecs, setChannelSpecs] = useState<ChannelSpecRecord[]>([]);
  const [channelContents, setChannelContents] = useState<ChannelContentRecord[]>([]);
  const [publishPackages, setPublishPackages] = useState<PublishPackageRecord[]>([]);
  const [taskFactSnapshots, setTaskFactSnapshots] = useState<TaskBusinessFactSnapshot[]>([]);
  const [selectedPackageFacts, setSelectedPackageFacts] = useState<string[]>([]);
  const [qualityResolutionReason, setQualityResolutionReason] = useState("");
  const [confirmationNote, setConfirmationNote] = useState("");
  const [copyTitle, setCopyTitle] = useState("");
  const [copyBody, setCopyBody] = useState("");
  const [copyHashtags, setCopyHashtags] = useState("");
  const [selectedImageAssetId, setSelectedImageAssetId] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [selectedVersionIds, setSelectedVersionIds] = useState<Record<string, string>>({});
  const [imageFiles, setImageFiles] = useState<Record<string, { url?: string; filename?: string; loading?: boolean; error?: string }>>({});
  const [previewImage, setPreviewImage] = useState<{ url: string; filename: string; label: string } | null>(null);
  const [downloadingVersionId, setDownloadingVersionId] = useState("");
  const [imageNotice, setImageNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [factsLoading, setFactsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("all");
  const [taskType, setTaskType] = useState<MarketingTaskType>("full_marketing");
  const [opportunityId, setOpportunityId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [coreMessage, setCoreMessage] = useState("");
  const [constraints, setConstraints] = useState("");
  const [includesCopy, setIncludesCopy] = useState(true);
  const [includesImage, setIncludesImage] = useState(true);
  const [includesVideoScript, setIncludesVideoScript] = useState(false);
  const [channelSelected, setChannelSelected] = useState(true);
  const [externalDelivery, setExternalDelivery] = useState(false);
  const [draft, setDraft] = useState<DraftForm>({ goal: "", target_audience: "", core_message: "", constraints: "" });
  const [draftDirty, setDraftDirty] = useState(false);
  const [strategyText, setStrategyText] = useState("{}");
  const [strategyDirty, setStrategyDirty] = useState(false);
  const createKey = useRef("");
  const contentMutationKey = useRef("");
  const copyFormTaskId = useRef("");
  const imageRequests = useRef(new Set<string>());
  const imageRetries = useRef<Record<string, number>>({});
  const strategyStep = task?.steps.find(step => step.step_key === "strategy_confirmation");
  const [taskTab, setTaskTab] = useState<TaskTabKey>("requirement");
  const isCreate = route === "#create";
  const isDetail = route === "#task";

  const loadTasks = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await listMarketingTasks(storeId);
      setItems(response.items);
    } catch (reason) { setError(errorText(reason)); }
    finally { setLoading(false); }
  }, [storeId]);

  const loadAiHome = useCallback(async () => {
    setAiLoading(true); setAiError("");
    try {
      const [taskResponse, opportunityResponse] = await Promise.all([
        listMarketingTasks(storeId),
        getOpportunities(storeId).catch(() => null),
      ]);
      setItems(taskResponse.items);
      if (opportunityResponse) {
        setAiOpportunities(opportunityResponse.items);
        setAiOpportunitySource(opportunityResponse.source_status);
      } else {
        setAiOpportunitySource("unavailable");
      }
      const recentTasks = taskResponse.items.slice(0, 4);
      const artifactResults = await Promise.allSettled(recentTasks.map(item => listTaskArtifacts(storeId, item.id)));
      const entries: AiArtifactEntry[] = [];
      artifactResults.forEach((result, index) => {
        if (result.status !== "fulfilled") return;
        const taskItem = recentTasks[index];
        for (const artifact of result.value) {
          const version = artifact.versions.find(item => item.id === artifact.current_version_id) ?? artifact.versions[artifact.versions.length - 1];
          if (!version) continue;
          entries.push({ taskId: taskItem.id, taskTitle: taskItem.title, artifact, version });
        }
      });
      entries.sort((left, right) => new Date(right.version.created_at).getTime() - new Date(left.version.created_at).getTime());
      const topEntries = entries.slice(0, 6);
      setAiArtifacts(topEntries);
      const imageEntries = topEntries.filter(entry => entry.artifact.artifact_type === "image");
      const urlPairs = await Promise.all(imageEntries.map(async entry => {
        try {
          const info = await getArtifactVersionDownloadUrl(storeId, entry.taskId, entry.artifact.id, entry.version.id);
          return [entry.version.id, info.url] as const;
        } catch { return null; }
      }));
      setAiImageUrls(Object.fromEntries(urlPairs.filter((pair): pair is readonly [string, string] => Boolean(pair))));
    } catch (reason) { setAiError(errorText(reason)); }
    finally { setAiLoading(false); }
  }, [storeId]);

  const loadTask = useCallback(async () => {
    const id = sessionStorage.getItem(selectedTaskKey(storeId));
    if (!id) { window.location.hash = "#tasks"; return; }
    setLoading(true); setError("");
    try {
      const response = await getMarketingTask(storeId, id);
      const storedTab = sessionStorage.getItem(taskTabStorageKey(response.id));
      setTaskTab(isTaskTab(storedTab) ? storedTab : defaultTaskTab(response));
      setTask(response);
      setDraft(requirementForm(response.requirement_draft));
      setDraftDirty(false);
      setStrategyText(safeJson(response.strategy_draft));
      setStrategyDirty(false);
      setSelectedVersionIds({});
      setImageFiles({});
      setPreviewImage(null);
      setImageNotice("");
      imageRetries.current = {};
    } catch (reason) { setError(errorText(reason)); setTask(null); }
    finally { setLoading(false); }
  }, [storeId]);

  const loadContent = useCallback(async (taskId: string) => {
    try {
      const [contentItems, assetItems, channelItems, packageItems, specs, factItems] = await Promise.all([
        listTaskArtifacts(storeId, taskId),
        getMediaAssets(storeId),
        listChannelContents(storeId, taskId),
        listPublishPackages(storeId, taskId),
        listChannelSpecs(storeId),
        listTaskBusinessFacts(storeId, taskId),
      ]);
      setArtifacts(contentItems);
      setMediaAssets(assetItems.items);
      setChannelContents(channelItems);
      setPublishPackages(packageItems);
      setChannelSpecs(specs);
      setTaskFactSnapshots(factItems);
      if (copyFormTaskId.current !== taskId) {
        const copyArtifact = contentItems.find(item => item.artifact_type === "copy");
        const currentCopy = copyArtifact?.versions.find(item => item.id === copyArtifact.current_version_id);
        const copyContent = currentCopy?.content_json || {};
        setCopyTitle(typeof copyContent.title === "string" ? copyContent.title : "");
        setCopyBody(typeof copyContent.body === "string" ? copyContent.body : "");
        setCopyHashtags(Array.isArray(copyContent.hashtags) ? copyContent.hashtags.join(" ") : "");
        copyFormTaskId.current = taskId;
      }
      setSelectedPackageFacts(current => current.length ? current : factItems.filter(fact => fact.confirmation_status === "confirmed").map(fact => fact.id));
      setSelectedImageAssetId(current => current || assetItems.items.find(item =>
        item.status === "ready" && item.usage_rights_status === "confirmed_allowed" && item.mime_type.startsWith("image/")
      )?.id || "");
    } catch (reason) { setError(errorText(reason)); }
  }, [storeId]);

  const selectedVersionFor = (artifact: ContentArtifact): ArtifactVersionRecord | undefined =>
    artifact.versions.find(version => version.id === selectedVersionIds[artifact.id])
    ?? artifact.versions.find(version => version.id === artifact.current_version_id)
    ?? artifact.versions[artifact.versions.length - 1];

  const selectVersion = (artifact: ContentArtifact, version: ArtifactVersionRecord) => {
    setSelectedVersionIds(current => ({ ...current, [artifact.id]: version.id }));
    setImageNotice("");
    if (artifact.artifact_type === "image" && !imageFiles[version.id]) void ensureImageFile(artifact, version);
  };

  async function ensureImageFile(artifact: ContentArtifact, version: ArtifactVersionRecord, force = false) {
    if (!task || artifact.artifact_type !== "image") return;
    if (imageRequests.current.has(version.id)) return;
    if (force) setImageFiles(current => { const next = { ...current }; delete next[version.id]; return next; });
    else if (imageFiles[version.id]) return;
    imageRequests.current.add(version.id);
    setImageFiles(current => ({ ...current, [version.id]: { ...current[version.id], loading: true, error: undefined } }));
    try {
      const info = await getArtifactVersionDownloadUrl(storeId, task.id, artifact.id, version.id);
      setImageFiles(current => ({ ...current, [version.id]: { url: info.url, filename: info.filename } }));
    } catch (reason) {
      setImageFiles(current => ({ ...current, [version.id]: { error: errorText(reason) } }));
    } finally {
      imageRequests.current.delete(version.id);
    }
  }

  function retryImageFile(artifact: ContentArtifact, version: ArtifactVersionRecord) {
    const attempts = imageRetries.current[version.id] ?? 0;
    if (attempts >= 2) {
      setImageFiles(current => ({ ...current, [version.id]: { error: "图片加载失败，请点击「刷新产物」后重试。" } }));
      return;
    }
    imageRetries.current[version.id] = attempts + 1;
    void ensureImageFile(artifact, version, true);
  }

  async function saveSignedUrlAsFile(url: string, filename: string) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`文件读取失败（HTTP ${response.status}）`);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 15000);
  }

  async function downloadArtifactFile(artifact: ContentArtifact, version: ArtifactVersionRecord) {
    if (!task || downloadingVersionId) return;
    setDownloadingVersionId(version.id); setImageNotice(""); setError("");
    try {
      const info = await getArtifactVersionDownloadUrl(storeId, task.id, artifact.id, version.id);
      await saveSignedUrlAsFile(info.url, info.filename);
      setImageNotice(`已下载 ${info.filename}`);
    } catch (reason) {
      setError(`下载失败：${errorText(reason)}`);
    } finally {
      setDownloadingVersionId("");
    }
  }

  async function openImagePreview(artifact: ContentArtifact, version: ArtifactVersionRecord) {
    if (!task) return;
    setImageNotice(""); setError("");
    try {
      const info = await getArtifactVersionDownloadUrl(storeId, task.id, artifact.id, version.id);
      setPreviewImage({
        url: info.url,
        filename: info.filename,
        label: `V${version.version_no} · ${sourceTypeLabels[version.source_type] ?? version.source_type}`,
      });
    } catch (reason) { setError(errorText(reason)); }
  }

  useEffect(() => {
    if (!task) return;
    for (const artifact of artifacts) {
      if (artifact.artifact_type !== "image") continue;
      const version = selectedVersionFor(artifact);
      if (!version || imageFiles[version.id] || imageRequests.current.has(version.id)) continue;
      void ensureImageFile(artifact, version);
    }
  }, [artifacts, selectedVersionIds, imageFiles, task]);

  useEffect(() => {
    if (!previewImage) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setPreviewImage(null); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewImage]);

  const loadFacts = useCallback(async () => {
    setFactsLoading(true);
    const options: FactOption[] = [];
    const results = await Promise.allSettled([
      getStoreProfile(storeId), getProducts(storeId), listOffers(storeId),
      getBrandGuideline(storeId), getAudienceProfiles(storeId), getKnowledgeItems(storeId),
    ]);
    const [profile, products, offers, brand, audiences, knowledge] = results;
    if (profile.status === "fulfilled" && profile.value.fact_status === "confirmed") {
      options.push({ fact_key: "store_profile", record_type: "store_profile", record_id: profile.value.id, expected_version_no: profile.value.current_version, label: `门店档案 · ${profile.value.display_name}` });
    }
    if (products.status === "fulfilled") for (const item of products.value.items) if (item.fact_status === "confirmed") {
      options.push({ fact_key: `product:${item.id}`, record_type: "product", record_id: item.id, expected_version_no: item.current_version, label: `商品 · ${item.name}` });
    }
    if (offers.status === "fulfilled") for (const item of offers.value.items) if (item.fact_status === "confirmed") {
      options.push({ fact_key: `offer:${item.id}`, record_type: "offer", record_id: item.id, expected_version_no: item.current_version, label: `活动 · ${item.title}` });
    }
    if (brand.status === "fulfilled" && brand.value.fact_status === "confirmed") {
      options.push({ fact_key: "brand_guideline", record_type: "brand_guideline", record_id: brand.value.id, expected_version_no: brand.value.current_version, label: "品牌规范" });
    }
    if (audiences.status === "fulfilled") for (const item of audiences.value.items) if (item.fact_status === "confirmed") {
      options.push({ fact_key: `audience:${item.id}`, record_type: "audience_profile", record_id: item.id, expected_version_no: item.current_version, label: `客群 · ${item.name}` });
    }
    if (knowledge.status === "fulfilled") for (const item of knowledge.value.items) if (item.fact_status === "confirmed") {
      options.push({ fact_key: `knowledge:${item.id}`, record_type: "knowledge_item", record_id: item.id, expected_version_no: item.current_version, label: `知识 · ${item.title}` });
    }
    setFacts(options);
    setFactsLoading(false);
  }, [storeId]);

  useEffect(() => {
    const onRoute = () => setRoute(window.location.hash || "#ai");
    window.addEventListener("hashchange", onRoute);
    return () => window.removeEventListener("hashchange", onRoute);
  }, []);
  useEffect(() => {
    if (route === "#ai") void loadAiHome();
    if (route === "#tasks") void loadTasks();
    if (route === "#task") {
      void loadTask(); void loadFacts();
      const taskId = sessionStorage.getItem(selectedTaskKey(storeId));
      if (taskId) void loadContent(taskId);
    }
    if (route === "#create") {
      const handoffRaw = sessionStorage.getItem(opportunityHandoffKey(storeId));
      if (handoffRaw) {
        try {
          const handoff = JSON.parse(handoffRaw) as {
            opportunity_id?: string; title?: string; summary?: string;
            suggested_scenario?: string; content_angle?: string;
          };
          if (handoff.opportunity_id) {
            setOpportunityId(handoff.opportunity_id);
            setTitle(handoff.title ? `热点机会：${handoff.title}`.slice(0, 200) : "基于热点机会制作内容");
            setGoal(handoff.suggested_scenario || "结合已采纳的热点机会制作门店营销内容");
            setCoreMessage([handoff.summary, handoff.content_angle].filter(Boolean).join("\\n"));
          }
        } catch {
          sessionStorage.removeItem(opportunityHandoffKey(storeId));
          setOpportunityId(null);
        }
      } else {
        setOpportunityId(null);
      }
      const key = createTaskKey(storeId);
      createKey.current = sessionStorage.getItem(key) ?? crypto.randomUUID();
      sessionStorage.setItem(key, createKey.current);
    }
  }, [route, storeId, loadTasks, loadAiHome, loadTask, loadFacts, loadContent]);

  const filteredItems = useMemo(() => filter === "all" ? items : items.filter(item => item.lifecycle_status === filter), [items, filter]);
  const stepProgress = task ? task.steps.filter(step => step.status === "succeeded" || step.status === "skipped").length : 0;

  function openTask(id: string) {
    sessionStorage.setItem(selectedTaskKey(storeId), id);
    window.location.hash = "#task";
  }
  function openTaskContent(entry: AiArtifactEntry) {
    sessionStorage.setItem(taskTabStorageKey(entry.taskId), "content");
    openTask(entry.taskId);
  }
  async function openAiArtifactPreview(entry: AiArtifactEntry) {
    setAiError("");
    try {
      const info = await getArtifactVersionDownloadUrl(storeId, entry.taskId, entry.artifact.id, entry.version.id);
      setPreviewImage({
        url: info.url,
        filename: info.filename,
        label: `V${entry.version.version_no} · ${entry.taskTitle}`,
      });
    } catch (reason) { setAiError(`原图读取失败：${errorText(reason)}`); }
  }
  function selectTaskTab(key: TaskTabKey) {
    setTaskTab(key);
    if (task) sessionStorage.setItem(taskTabStorageKey(task.id), key);
  }
  function updateDraft<K extends keyof DraftForm>(key: K, value: DraftForm[K]) {
    setDraft(current => ({ ...current, [key]: value })); setDraftDirty(true);
  }
  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setNotice("");
    try {
      const scope = taskTypeOptions(taskType);
      const input: MarketingTaskCreateInput = {
        task_type: taskType,
        title: title.trim(),
        opportunity_id: opportunityId,
        requirement_draft: requirementPayload({ goal, target_audience: targetAudience, core_message: coreMessage, constraints }),
        task_options: {
          includes_copy: taskType === "merchant_content" ? includesCopy : scope.includes_copy,
          includes_image: taskType === "merchant_content" ? includesImage : scope.includes_image,
          includes_video_script: includesVideoScript,
          opportunity_applicable: Boolean(opportunityId),
          selected_channel_keys: channelSelected ? ["douyin"] : [],
          requires_external_delivery: externalDelivery && channelSelected,
        },
      };
      if (!input.requirement_draft.goal) throw new Error("请先填写营销目标。");
      const created = await createMarketingTask(storeId, input, createKey.current || crypto.randomUUID());
      sessionStorage.removeItem(createTaskKey(storeId));
      sessionStorage.removeItem(opportunityHandoffKey(storeId));
      setOpportunityId(null);
      openTask(created.id);
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function saveRequirement() {
    if (!task || !draftDirty) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const updated = await updateMarketingTaskRequirement(storeId, task, requirementPayload(draft));
      setTask(updated); setDraft(requirementForm(updated.requirement_draft)); setDraftDirty(false);
      setNotice(`需求草稿已保存（V${updated.version}）。`);
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function confirmRequirement() {
    if (!task || draftDirty || selectedFacts.length === 0) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const refs: BusinessFactReference[] = facts.filter(fact => selectedFacts.includes(fact.fact_key)).map(fact => ({
        fact_key: fact.fact_key, record_type: fact.record_type, record_id: fact.record_id,
        expected_version_no: fact.expected_version_no,
      }));
      const updated = await confirmMarketingTaskRequirement(storeId, task, refs);
      setTask(updated); setNotice("需求与经营事实已确认，策略生成任务已进入异步队列。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function saveStrategy() {
    if (!task || !strategyDirty) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const parsed: unknown = JSON.parse(strategyText);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || Object.keys(parsed).length === 0) throw new Error("策略必须是非空 JSON 对象。");
      const updated = await updateMarketingTaskStrategy(storeId, task, parsed as Record<string, unknown>);
      setTask(updated); setStrategyText(safeJson(updated.strategy_draft)); setStrategyDirty(false);
      setNotice("策略草稿已保存，请确认后继续。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function confirmStrategy() {
    if (!task || strategyDirty) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const updated = await confirmMarketingTaskStrategy(storeId, task);
      setTask(updated); setNotice("策略已确认，后续步骤将按固定流程推进。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function saveCopyArtifact() {
    if (!task || saving || !copyBody.trim()) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const existing = artifacts.find(item => item.artifact_type === "copy");
      const version = {
        source_type: "manual_edit" as const,
        instruction: "商家在营销任务工作区手动编辑文案",
        content_json: {
          title: copyTitle.trim(),
          body: copyBody.trim(),
          hashtags: copyHashtags.split(/[，,、\s]+/).map(item => item.trim().replace(/^#/, "")).filter(Boolean),
        },
      };
      const mutationKey = contentMutationKey.current || crypto.randomUUID();
      contentMutationKey.current = mutationKey;
      if (existing) await createTaskArtifactVersion(storeId, task.id, existing, version, mutationKey);
      else await createTaskArtifact(storeId, task.id, "copy", version, mutationKey);
      contentMutationKey.current = "";
      setSelectedVersionIds({});
      await loadContent(task.id);
      setNotice(existing ? "文案新版本已保存，旧版本保留。" : "文案产物已创建。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function saveImageArtifact() {
    if (!task || saving || !selectedImageAssetId) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const existing = artifacts.find(item => item.artifact_type === "image");
      const version = { source_type: "merchant_upload" as const, media_asset_id: selectedImageAssetId };
      const mutationKey = contentMutationKey.current || crypto.randomUUID();
      contentMutationKey.current = mutationKey;
      if (existing) await createTaskArtifactVersion(storeId, task.id, existing, version, mutationKey);
      else await createTaskArtifact(storeId, task.id, "image", version, mutationKey);
      contentMutationKey.current = "";
      setSelectedVersionIds({});
      await loadContent(task.id);
      setNotice(existing ? "图片产物新版本已关联，旧版本保留。" : "图片产物已关联到门店已授权素材。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function createChannelDraft() {
    if (!task || saving) return;
    const spec = channelSpecs.find(item => item.channel_key === "douyin")?.current_version;
    if (!spec || spec.verification_status !== "verified") {
      setError("当前渠道规格尚未完成官方核验，不能创建渠道适配内容。");
      return;
    }
    const copyArtifact = artifacts.find(item => item.artifact_type === "copy");
    const copyVersion = copyArtifact?.versions.find(version => version.id === copyArtifact.current_version_id);
    const copyReview = copyVersion?.reviews?.[copyVersion.reviews.length - 1];
    if (!copyArtifact || !copyVersion || copyReview?.decision !== "approved") {
      setError("请先完成文案当前版本审核，再进行渠道适配。");
      return;
    }
    const imageVersions = artifacts
      .filter(item => item.artifact_type === "image")
      .flatMap(item => item.versions.filter(version => version.id === item.current_version_id && version.reviews?.[version.reviews.length - 1]?.decision === "approved"));
    const content = copyVersion.content_json || {};
    setSaving(true); setError(""); setNotice("");
    try {
      await createChannelContent(storeId, task.id, {
        channel_key: "douyin",
        copy_version_id: copyVersion.id,
        channel_spec_version_id: spec.id,
        payload: {
          title: typeof content.title === "string" ? content.title : "",
          body: typeof content.body === "string" ? content.body : "",
          hashtags: typeof content.hashtags === "string" ? content.hashtags.split(/[、,，\s]+/).filter(Boolean) : [],
        },
        image_version_ids: imageVersions.map(version => version.id),
      });
      await loadContent(task.id);
      setNotice("渠道内容适配快照已创建。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function runQuality(content: ChannelContentRecord) {
    if (!task || saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const job = await runChannelContentQuality(storeId, task.id, content);
      setNotice("质检任务已提交（" + job.job_id + "）。完成后点击刷新产物查看报告。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function acceptQuality(report: ChannelContentRecord["quality_reports"][number]) {
    if (!task || saving || !qualityResolutionReason.trim()) return;
    setSaving(true); setError(""); setNotice("");
    try {
      await createQualityResolution(storeId, report.id, report.input_fingerprint, qualityResolutionReason.trim());
      setQualityResolutionReason("");
      await loadContent(task.id);
      setNotice("已记录当前质检报告的人工接受决议。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function freezePackage(content: ChannelContentRecord, report: ChannelContentRecord["quality_reports"][number]) {
    if (!task || saving) return;
    const confirmedFacts = taskFactSnapshots.filter(fact =>
      fact.confirmation_status === "confirmed" && selectedPackageFacts.includes(fact.id)
    );
    if (!confirmedFacts.length) {
      setError("发布包至少需要选择一项已确认的经营事实快照。");
      return;
    }
    setSaving(true); setError(""); setNotice("");
    try {
      await freezePublishPackage(storeId, task.id, {
        expected_task_version: task.version,
        fact_snapshot_ids: confirmedFacts.map(fact => fact.id),
        items: [{
          channel_content_id: content.id,
          quality_report_id: report.id,
          delivery_mode: "manual_handoff",
        }],
      });
      await loadContent(task.id);
      setNotice("发布包已冻结。冻结后内容不会被静默修改。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function confirmPackage(pkg: PublishPackageRecord) {
    if (!task || saving || pkg.confirmation) return;
    setSaving(true); setError(""); setNotice("");
    try {
      await confirmPublishPackage(storeId, pkg.id, pkg.package_fingerprint, confirmationNote.trim());
      setConfirmationNote("");
      await loadContent(task.id);
      setNotice("已确认该不可变发布包。实际发布状态仍需外部平台凭证确认。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function reviewArtifact(artifact: ContentArtifact, version: ArtifactVersionRecord, decision: "approved" | "revision_requested" | "rejected") {
    if (!task || saving) return;
    if (decision === "revision_requested" && !reviewComment.trim()) { setError("请填写具体的修改意见。"); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const mutationKey = contentMutationKey.current || crypto.randomUUID();
      contentMutationKey.current = mutationKey;
      await createTaskArtifactReview(storeId, task.id, artifact, version, {
        expected_version: version.version_no,
        review_type: artifact.artifact_type,
        decision,
        comment: reviewComment.trim() || null,
      }, mutationKey);
      contentMutationKey.current = "";
      setReviewComment("");
      await loadContent(task.id);
      if (decision === "approved") await loadTask();
      setNotice(decision === "approved" ? "当前产物版本已审核通过。" : decision === "revision_requested" ? "已记录修改意见，请创建新版本后重新审核。" : "当前产物版本已标记为拒绝。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function stepAction(step: TaskStep, action: "skip" | "recover") {
    if (!task || saving) return;
    const reason = window.prompt(action === "skip" ? "请说明跳过该可选步骤的原因（至少 8 个字）：" : "请说明恢复该步骤的原因（至少 8 个字）：");
    if (!reason) return;
    if (reason.trim().length < 8) { setError("原因至少需要 8 个字符。"); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const updated = action === "skip"
        ? await skipMarketingTaskStep(storeId, task, step.step_key, reason.trim())
        : await recoverMarketingTaskStep(storeId, task, step.step_key, reason.trim());
      setTask(updated); setNotice(action === "skip" ? "步骤已按商家决策跳过。" : "已提交步骤恢复请求。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function taskAction(action: "cancel" | "archive") {
    if (!task || saving) return;
    const reason = window.prompt(action === "cancel" ? "请说明取消该营销任务的原因：" : "请说明归档该营销任务的原因：");
    if (!reason) return;
    if (reason.trim().length < 8) { setError("原因至少需要 8 个字符。"); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const updated = action === "cancel"
        ? await cancelMarketingTask(storeId, task, reason.trim())
        : await archiveMarketingTask(storeId, task, reason.trim());
      setTask(updated); setNotice(action === "cancel" ? "任务已取消，关联异步任务已同步请求取消。" : "任务已归档。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  if (route === "#ai") {
    const activeTasks = items.filter(item => ["draft", "active", "waiting_for_user", "blocked", "failed"].includes(item.lifecycle_status));
    const waitingTasks = items.filter(item => item.lifecycle_status === "waiting_for_user");
    const blockedStepCount = activeTasks.reduce((sum, item) => sum + item.blocked_steps_count, 0);
    const eligibleOpportunities = aiOpportunities.filter(item => item.eligibility_status === "eligible" && !item.decision);
    const recentTasks = items
      .filter(item => item.lifecycle_status !== "archived")
      .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())
      .slice(0, 5);
    const opportunityPreview = aiOpportunities.slice(0, 4);
    const nextStep = blockedStepCount > 0
      ? { title: `${blockedStepCount} 个步骤待恢复`, text: "阻塞步骤不会自动跳过，确认原因后可继续推进。", label: "查看任务", href: "#tasks" }
      : waitingTasks.length > 0
        ? { title: `${waitingTasks.length} 个任务待你处理`, text: "策略或内容已生成，等待你的确认后再继续。", label: "去处理", href: "#tasks" }
        : activeTasks.length > 0
          ? { title: `${activeTasks.length} 个任务进行中`, text: `最近更新：${recentTasks[0]?.title ?? "当前门店"}`, label: "查看进度", href: "#tasks" }
          : { title: "从第一个营销任务开始", text: "描述目标后，按需求、事实、策略、内容与发布顺序推进。", label: "按需制作", href: "#create" };

    return <section className="ai-home">
      <div className="page-heading ai-page-head">
        <div>
          <p className="eyebrow">AI MARKETING WORKSPACE</p>
          <h1>AI 营销</h1>
          <p className="muted">从适合本店的机会开始，或直接描述经营目标按需制作。关键事实、内容与最终发布都由你确认。</p>
        </div>
        <div className="form-actions">
          <button className="secondary" type="button" onClick={() => { window.location.hash = "#tasks"; }}>查看营销任务</button>
          <button className="primary" type="button" onClick={() => { window.location.hash = "#create"; }}>新建营销任务</button>
        </div>
      </div>

      {aiError && <div className="alert error" role="alert">{aiError}</div>}

      <section className="ai-hero">
        <div className="ai-hero-main">
          <p className="eyebrow">START HERE</p>
          <h2>今天想为门店推进哪件事？</h2>
          <p>没有明确主题时，先看机会；已有目标时，直接按需制作。两种方式都会进入同一套确认流程，不会自动发布。</p>
          <div className="ai-hero-actions">
            <button className="btn-hero-primary" type="button" onClick={() => { window.location.hash = "#hotspots"; }}>发现营销机会 <span aria-hidden="true">↗</span></button>
            <button className="btn-hero-ghost" type="button" onClick={() => { window.location.hash = "#create"; }}>按需制作</button>
          </div>
          <div className="ai-hero-tags">新品推广 · 到店引流 · 活动促销 · 品牌内容 · 清库存</div>
        </div>
        <aside className="ai-hero-side">
          <span className="ai-hero-side-label">{storeName || "当前门店"} · 下一步</span>
          <strong>{nextStep.title}</strong>
          <p>{nextStep.text}</p>
          <button className="btn-hero-side" type="button" onClick={() => { window.location.hash = nextStep.href; }}>{nextStep.label}<span aria-hidden="true"> →</span></button>
        </aside>
      </section>

      <div className="ai-kpis">
        <article className="ai-kpi"><span className="label">进行中任务</span><strong>{activeTasks.length}</strong><small>当前门店未结束的任务</small></article>
        <article className="ai-kpi"><span className="label">待你处理</span><strong>{waitingTasks.length}</strong><small>等待商家确认或补充</small></article>
        <article className="ai-kpi"><span className="label">阻塞步骤</span><strong>{blockedStepCount}</strong><small>需要恢复或调整后继续</small></article>
        <article className="ai-kpi"><span className="label">可采纳机会</span><strong>{eligibleOpportunities.length}</strong><small>{aiOpportunitySource === "available" ? "已核验来源的机会" : "按需制作不受影响"}</small></article>
      </div>

      <div className="ai-columns">
        <section className="ai-panel">
          <div className="ai-panel-head">
            <div><h2>最近任务</h2><p>按更新时间排序，点开后继续当前步骤。</p></div>
            <button className="text-button" type="button" onClick={() => { window.location.hash = "#tasks"; }}>全部任务</button>
          </div>
          {aiLoading ? <div className="ai-empty"><p>正在读取任务…</p></div> : recentTasks.length === 0 ? <div className="ai-empty">
            <strong>还没有营销任务</strong>
            <p>描述本次想达成的经营目标，系统会生成可确认的需求与策略流程。</p>
            <button className="secondary" type="button" onClick={() => { window.location.hash = "#create"; }}>创建第一个任务</button>
          </div> : <div className="ai-task-list">
            {recentTasks.map(item => <button className="ai-task-row" type="button" key={item.id} onClick={() => openTask(item.id)}>
              <span className="ai-task-row-main"><strong>{item.title}</strong><small>{taskTypeLabels[item.task_type]} · 更新于 {new Date(item.updated_at).toLocaleDateString()}</small></span>
              <span className="ai-task-row-meta"><span className={item.lifecycle_status === "blocked" || item.lifecycle_status === "failed" ? "status-chip danger" : item.lifecycle_status === "waiting_for_user" ? "status-chip warn" : "status-chip"}>{statusLabels[item.lifecycle_status]}</span><small>{item.pending_steps_count} 个待处理</small></span>
            </button>)}
          </div>}
        </section>

        <section className="ai-panel">
          <div className="ai-panel-head">
            <div><h2>本期营销机会</h2><p>只展示已核验来源并能匹配本店的机会。</p></div>
            <button className="text-button" type="button" onClick={() => { window.location.hash = "#hotspots"; }}>机会列表</button>
          </div>
          {aiLoading ? <div className="ai-empty"><p>正在读取机会…</p></div> : opportunityPreview.length === 0 ? <div className="ai-empty">
            <strong>暂无可采纳的营销机会</strong>
            <p>{aiOpportunitySource === "available" ? "当前没有符合本店条件的机会。" : "当前没有已核验来源的有效机会。"}按需制作仍可直接开始。</p>
            <button className="secondary" type="button" onClick={() => { window.location.hash = "#create"; }}>按需制作</button>
          </div> : <div className="ai-task-list">
            {opportunityPreview.map(item => <button className="ai-task-row" type="button" key={item.id} onClick={() => { window.location.hash = `#hotspot-detail:${item.id}`; }}>
              <span className="ai-task-row-main"><strong>{item.title}</strong><small>{item.summary || item.reason_summary || "暂无来源摘要"}</small></span>
              <span className="ai-task-row-meta"><span className={item.eligibility_status === "eligible" ? "status-chip confirmed" : "status-chip"}>{item.eligibility_status === "eligible" ? "可采纳" : item.eligibility_status === "review_required" ? "需核对" : "不适合"}</span>{item.relevance_score && <small>匹配 {Number(item.relevance_score).toFixed(0)}</small>}</span>
            </button>)}
          </div>}
        </section>
      </div>

      <section className="ai-panel ai-artifacts-panel">
        <div className="ai-panel-head">
          <div><h2>最近产物</h2><p>来自最近更新的任务，展示当前版本的文案与图片；完整版本在任务「内容制作」中查看。</p></div>
          <button className="text-button" type="button" onClick={() => { window.location.hash = "#tasks"; }}>按任务查看</button>
        </div>
        {aiLoading ? <div className="ai-empty"><p>正在读取最近产物…</p></div> : aiArtifacts.length === 0 ? <div className="ai-empty">
          <strong>还没有内容产物</strong>
          <p>创建任务并完成内容制作后，最新生成的文案与图片会显示在这里。</p>
        </div> : <div className="ai-artifacts">
          {aiArtifacts.map(entry => {
            const content = entry.version.content_json || {};
            const titleText = typeof content.title === "string" ? content.title : "";
            const body = typeof content.body === "string" ? content.body : "";
            const isImage = entry.artifact.artifact_type === "image";
            const imageUrl = aiImageUrls[entry.version.id];
            return <article className="ai-artifact-card" key={`${entry.artifact.id}-${entry.version.id}`}>
              <div className="ai-artifact-top">
                <span className={isImage ? "status-chip chip-image" : "status-chip chip-copy"}>{isImage ? "图片" : "文案"}</span>
                <span className={`status-chip source-${entry.version.source_type}`}>{sourceTypeLabels[entry.version.source_type] ?? entry.version.source_type}</span>
                <span className="ai-artifact-version">V{entry.version.version_no}</span>
              </div>
              {isImage ? <button className="ai-artifact-thumb" type="button" onClick={() => void openAiArtifactPreview(entry)} aria-label={`查看 ${entry.taskTitle} 的 V${entry.version.version_no} 原图`}>
                {imageUrl ? <img src={imageUrl} alt={`${entry.taskTitle} V${entry.version.version_no} 产物`} /> : <span className="ai-artifact-thumb-placeholder">原图加载中</span>}
              </button> : <div className="ai-artifact-copy">
                <strong>{titleText || "未命名文案"}</strong>
                <p>{body || "该版本暂无正文内容"}</p>
              </div>}
              <div className="ai-artifact-foot"><span>{entry.version.model_id || "模型未记录"}</span><span>{new Date(entry.version.created_at).toLocaleDateString()}</span></div>
              <p className="ai-artifact-task">{entry.taskTitle}</p>
              <button className="text-button" type="button" onClick={() => openTaskContent(entry)}>打开内容制作 →</button>
            </article>;
          })}
        </div>}
      </section>

      {previewImage && <div className="artifact-preview-backdrop" role="dialog" aria-modal="true" aria-label="图片原图预览" onClick={() => setPreviewImage(null)}>
        <div className="artifact-preview-dialog" onClick={event => event.stopPropagation()}>
          <div className="artifact-preview-head">
            <strong>{previewImage.label}</strong>
            <div className="form-actions">
              <button className="secondary" type="button" onClick={() => { const target = previewImage; void saveSignedUrlAsFile(target.url, target.filename).then(() => setImageNotice(`已下载 ${target.filename}`)).catch(reason => setAiError(`下载失败：${errorText(reason)}`)); }}>下载原图</button>
              <button className="secondary" type="button" onClick={() => setPreviewImage(null)}>关闭</button>
            </div>
          </div>
          <img src={previewImage.url} alt={`${previewImage.label} 原图`} />
          <p className="muted">文件：{previewImage.filename}</p>
        </div>
      </div>}
    </section>;
  }

  if (isCreate) return <>
    <div className="page-heading"><div><p className="eyebrow">NEW MARKETING TASK</p><h1>按需制作</h1><p className="muted">先明确目标和内容范围，创建后再确认需求与经营事实。</p></div><button className="secondary" type="button" onClick={() => { window.location.hash = "#ai"; }}>返回</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    <form className="profile-form" onSubmit={createTask}>
      <section className="form-card"><div className="section-title"><div><h2>营销需求</h2><p>不需要先选择热点；普通按需制作可直接开始。</p></div></div><div className="form-grid">
        <label className="field"><span>任务类型</span><select value={taskType} onChange={event => { const nextType = event.target.value as MarketingTaskType; setTaskType(nextType); if (nextType === "image_only" || nextType === "image_optimization") setIncludesVideoScript(false); }}><option value="full_marketing">完整营销执行</option><option value="copy_only">仅制作文案</option><option value="image_only">仅制作图片</option><option value="image_optimization">图片优化</option><option value="merchant_content">商家已有素材制作</option></select></label>
        <Field label="任务名称 *" value={title} onChange={setTitle} placeholder="例如：周末新品推广" />
        <Field label="经营目标 *" value={goal} onChange={setGoal} rows={3} placeholder="例如：提高周末下午茶时段的到店转化。" />
        <Field label="目标客群" value={targetAudience} onChange={setTargetAudience} placeholder="例如：附近写字楼白领" />
        <Field label="核心信息" value={coreMessage} onChange={setCoreMessage} placeholder="希望顾客记住的产品或服务价值" />
        <Field label="限制条件" value={constraints} onChange={setConstraints} rows={3} placeholder="例如：不使用未经确认的价格，不承诺库存。" />
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>内容与交付范围</h2><p>渠道适配和对外交付按实际需求选择。</p></div></div>
        {taskType === "merchant_content" && <div className="task-checkboxes"><label><input type="checkbox" checked={includesCopy} onChange={event => { setIncludesCopy(event.target.checked); if (!event.target.checked) setIncludesVideoScript(false); }} />包含文案</label><label><input type="checkbox" checked={includesImage} onChange={event => setIncludesImage(event.target.checked)} />包含图片</label></div>}
        {(taskType !== "image_only" && taskType !== "image_optimization" && (taskType !== "merchant_content" || includesCopy)) && <div className="task-checkboxes"><label><input type="checkbox" checked={includesVideoScript} onChange={event => setIncludesVideoScript(event.target.checked)} />同时生成视频脚本文本（仅脚本，不生成视频）</label></div>}
        <div className="task-checkboxes"><label><input type="checkbox" checked={channelSelected} onChange={event => { setChannelSelected(event.target.checked); if (!event.target.checked) setExternalDelivery(false); }} />适配抖音</label><label><input type="checkbox" checked={externalDelivery} disabled={!channelSelected} onChange={event => setExternalDelivery(event.target.checked)} />需要对外发布/交付</label></div>
        {taskType === "merchant_content" && !includesCopy && !includesImage && <div className="alert error">商家已有素材任务至少需要选择文案或图片。</div>}
      </section>
      <div className="form-footer"><p>创建只会建立任务和固定步骤，不会伪造 AI 生成结果。</p><div className="form-actions"><button className="secondary" type="button" onClick={() => { window.location.hash = "#tasks"; }}>查看任务</button><button className="primary" type="submit" disabled={saving || !title.trim() || !goal.trim() || (taskType === "merchant_content" && !includesCopy && !includesImage)}>{saving ? "创建中…" : "创建营销任务"}</button></div></div>
    </form>
  </>;

  if (isDetail) return <>
    <div className="page-heading"><div><p className="eyebrow">MARKETING TASK</p><h1>{task?.title || "营销任务详情"}</h1><p className="muted">固定流程 · 版本控制 · 商家确认 · 异常可恢复</p></div><div className="form-actions"><button className="secondary" type="button" onClick={() => { window.location.hash = "#tasks"; }}>返回任务</button><button className="secondary" type="button" disabled={loading} onClick={() => void loadTask()}>刷新</button></div></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    {loading ? <div className="loading-card"><span className="spinner" />正在读取任务…</div> : !task ? <section className="empty-card"><h2>无法读取营销任务</h2><p>{error || "任务不存在，或当前门店无权访问。"}</p><button className="secondary" type="button" onClick={() => { window.location.hash = "#tasks"; }}>返回任务列表</button></section> : <>
      <section className="task-overview"><div><span className="eyebrow">{taskTypeLabels[task.task_type]}</span><h2>{task.title}</h2><p>任务版本 V{task.version} · 创建于 {new Date(task.created_at).toLocaleString()}</p></div><div className="task-overview-stats"><strong>{statusLabels[task.lifecycle_status]}</strong><span>{stepProgress}/10 步已完成</span><span>{task.blocked_steps_count} 个阻塞步骤</span></div></section>
      <div className="task-tabs" role="tablist" aria-label="营销任务内容分块">
        {taskTabs.map(tab => <button key={tab.key} type="button" role="tab" id={`task-tab-${tab.key}`} aria-controls={`task-tab-panel-${tab.key}`} aria-selected={taskTab === tab.key} className={taskTab === tab.key ? "active" : ""} onClick={() => selectTaskTab(tab.key)}>{tab.label}</button>)}
      </div>
      <div className="task-tab-panel" id={`task-tab-panel-${taskTab}`} role="tabpanel" aria-labelledby={`task-tab-${taskTab}`}>
      {taskTab === "requirement" && <section className="task-panel"><div className="section-title"><div><h2>需求与经营事实</h2><p>确认后形成不可变需求快照；只允许选择当前门店已确认且仍有效的经营事实。</p></div><span className="status-chip">{task.current_requirement_snapshot_id ? "需求已确认" : "待确认"}</span></div>
        {task.current_requirement_snapshot_id ? <div className="task-readonly-grid">{Object.entries(task.requirement_draft).map(([key,value]) => <div key={key}><strong>{draftFieldLabels[key] ?? key}</strong><span>{typeof value === "string" ? value : JSON.stringify(value)}</span></div>)}</div> : <>
          <div className="form-grid"><Field label="经营目标" value={draft.goal} onChange={value => updateDraft("goal", value)} rows={2} /><Field label="目标客群" value={draft.target_audience} onChange={value => updateDraft("target_audience", value)} /><Field label="核心信息" value={draft.core_message} onChange={value => updateDraft("core_message", value)} /><Field label="限制条件" value={draft.constraints} onChange={value => updateDraft("constraints", value)} rows={2} /></div>
          <div className="task-facts"><div className="section-title"><div><h3>选择已确认的经营事实</h3><p>这些事实会冻结到本次任务快照，后续源资料变化不会静默改写历史。最多选择 50 项，当前已选 {selectedFacts.length} 项。</p></div><button className="text-button" type="button" onClick={() => void loadFacts()}>刷新资料</button></div>
            {factsLoading ? <p className="muted">正在读取门店已确认资料…</p> : facts.length === 0 ? <p className="alert error">当前门店没有可用的已确认事实。请先到门店资料中完善并确认档案、商品、活动、客群、品牌或知识。</p> : facts.map(fact => <label className="task-fact-option" key={fact.fact_key}><input type="checkbox" checked={selectedFacts.includes(fact.fact_key)} disabled={!selectedFacts.includes(fact.fact_key) && selectedFacts.length >= 50} onChange={event => setSelectedFacts(current => event.target.checked ? [...current, fact.fact_key] : current.filter(value => value !== fact.fact_key))} /><span>{fact.label}</span><small>V{fact.expected_version_no}</small></label>)}
          </div>
          <div className="form-footer"><p>{draftDirty ? "需求有未保存修改。" : "需求确认后将创建策略生成 Job。"}</p><div className="form-actions"><button className="secondary" type="button" disabled={saving || !draftDirty} onClick={() => void saveRequirement()}>保存需求</button><button className="primary" type="button" disabled={saving || draftDirty || factsLoading || selectedFacts.length === 0 || !draft.goal.trim()} onClick={() => void confirmRequirement()}>确认需求与事实</button></div></div>
        </>}
      </section>}
      {taskTab === "strategy" && <section className="task-panel"><div className="section-title"><div><h2>营销策略</h2><p>策略由异步执行生成；只有进入待商家处理状态后才可编辑和确认。</p></div><span className="status-chip">{task.current_strategy_snapshot_id ? "策略已确认" : strategyStep ? stepStatusLabel(strategyStep) : "待处理"}</span></div>
        {task.current_strategy_snapshot_id ? <pre className="task-json">{safeJson(task.strategy_draft)}</pre>
        : strategyStep?.status === "waiting_for_user" ? <><label className="field"><span>策略草稿（JSON）</span><textarea rows={8} value={strategyText} onChange={event => { setStrategyText(event.target.value); setStrategyDirty(true); }} /></label><div className="form-footer"><p>修改后必须先保存，再确认策略。</p><div className="form-actions"><button className="secondary" type="button" disabled={saving || !strategyDirty} onClick={() => void saveStrategy()}>保存策略</button><button className="primary" type="button" disabled={saving || strategyDirty} onClick={() => void confirmStrategy()}>确认策略</button></div></div></>
        : <p className="muted">{task.current_requirement_snapshot_id ? "策略生成任务已提交，等待 Worker 返回可审核草稿。若执行失败，可在下方步骤中查看阻塞原因并恢复。" : "请先完成需求与经营事实确认。"}</p>}
      </section>}
      {taskTab === "content" && <section className="task-panel">
        <div className="section-title"><div><h2>文案与图片产物</h2><p>展示每个产物的全部版本；点版本号可查看该版本的完整文案或原图。历史版本只读，不会改动当前版本或审核状态。</p></div><button className="text-button" type="button" onClick={() => task && void loadContent(task.id)}>刷新产物</button></div>
        <div className="form-grid">
          <Field label="文案标题" value={copyTitle} onChange={setCopyTitle} placeholder="填写内容标题" />
          <Field label="话题标签（空格或逗号分隔）" value={copyHashtags} onChange={setCopyHashtags} placeholder="门店名称 周末活动" />
          <Field label="文案正文" value={copyBody} onChange={setCopyBody} rows={5} placeholder="编辑本次营销文案。请勿填写未经确认的价格、库存或效果承诺。" />
        </div>
        <div className="form-footer"><p>保存文案会创建新版本；审核记录始终绑定具体版本。</p><div className="form-actions"><button className="primary" type="button" disabled={saving || !copyBody.trim()} onClick={() => void saveCopyArtifact()}>保存文案版本</button></div></div>
        <div className="form-grid">
          <label className="field span-2"><span>选择已通过扫描且已确认使用权的图片素材</span><select value={selectedImageAssetId} onChange={event => setSelectedImageAssetId(event.target.value)}><option value="">请选择门店图片素材</option>{mediaAssets.filter(item => item.status === "ready" && item.usage_rights_status === "confirmed_allowed" && item.mime_type.startsWith("image/")).map(item => <option key={item.id} value={item.id}>{item.original_filename_sanitized || item.id} · {item.mime_type} · V{item.version_no}</option>)}</select></label>
        </div>
        <div className="form-footer"><p>图片产物只引用门店已授权素材，不复制或覆盖来源资产。</p><div className="form-actions"><button className="secondary" type="button" disabled={saving || !selectedImageAssetId} onClick={() => void saveImageArtifact()}>关联图片版本</button></div></div>
        {imageNotice && <div className="alert success" role="status">{imageNotice}</div>}
        {artifacts.length === 0 ? <p className="muted">尚无文案或图片产物。保存文案或关联图片后，这里会显示版本与审核状态。</p> : <div className="task-content-artifacts">{artifacts.map(artifact => {
          const current = artifact.versions.find(version => version.id === artifact.current_version_id);
          const selected = selectedVersionFor(artifact);
          const isCurrent = Boolean(selected && selected.id === artifact.current_version_id);
          const content = selected?.content_json || {};
          const body = typeof content.body === "string" ? content.body : "";
          const titleText = typeof content.title === "string" ? content.title : "";
          const hashtags = Array.isArray(content.hashtags) ? content.hashtags.map(item => String(item)).filter(Boolean) : [];
          const callToAction = typeof content.call_to_action === "string" ? content.call_to_action : typeof content.cta === "string" ? content.cta : "";
          const videoScript = content.video_script && typeof content.video_script === "object" && !Array.isArray(content.video_script) ? content.video_script as Record<string, unknown> : null;
          const storyboard = Array.isArray(videoScript?.storyboard) ? videoScript.storyboard : [];
          const reviews = selected?.reviews || [];
          const latestReview = reviews[reviews.length - 1];
          const fileState = selected ? imageFiles[selected.id] : undefined;
          const imagePrompt = typeof content.image_prompt === "string" ? content.image_prompt : "";
          const dimensions = typeof content.width === "number" && typeof content.height === "number" ? `${content.width}×${content.height}` : "";
          const byteSize = formatBytes(content.byte_size);
          const sha256 = typeof content.sha256 === "string" ? content.sha256 : selected?.content_hash || "";
          return <article className="task-content-artifact artifact-card" key={artifact.id}>
            <div className="task-step-title">
              <strong>{artifact.artifact_type === "copy" ? "文案产物" : "图片产物"}</strong>
              <span className="status-chip">{artifact.versions.length} 个版本</span>
              {current ? <span className="status-chip confirmed">当前 V{current.version_no} · {latestReviewFor(current) ? reviewLabels[latestReviewFor(current)!.decision] : "待审核"}</span> : <span className="status-chip danger">无当前版本</span>}
            </div>
            <div className="artifact-version-row" role="group" aria-label={`${artifact.artifact_type === "copy" ? "文案" : "图片"}版本历史`}>
              <span className="artifact-version-label">版本历史</span>
              {artifact.versions.length === 0 ? <span className="muted">暂无版本</span> : artifact.versions.map(version => <button
                key={version.id}
                type="button"
                className={`artifact-version-chip${selected?.id === version.id ? " active" : ""}`}
                aria-pressed={selected?.id === version.id}
                onClick={() => selectVersion(artifact, version)}
              >V{version.version_no}{version.id === artifact.current_version_id ? <span className="artifact-version-current">当前</span> : null}</button>)}
            </div>
            {selected && <div className="artifact-version-detail" aria-live="polite">
              <div className="artifact-version-meta">
                <span className={`status-chip source-${selected.source_type}`}>{sourceTypeLabels[selected.source_type] ?? selected.source_type}</span>
                <span>模型：{selected.model_id || "未记录"}</span>
                <span>生成时间：{new Date(selected.created_at).toLocaleString()}</span>
                {!isCurrent && <span className="artifact-readonly-note">历史版本 · 只读</span>}
              </div>
              {artifact.artifact_type === "copy" && <div className="artifact-copy">
                <strong>{titleText || "未填写标题"}</strong>
                <p className="artifact-copy-body">{body || "（无正文内容）"}</p>
                {hashtags.length > 0 && <p className="artifact-meta-line">话题标签：{hashtags.map(tag => `#${tag.replace(/^#/, "")}`).join(" ")}</p>}
                {callToAction && <p className="artifact-meta-line">CTA：{callToAction}</p>}
              </div>}
              {videoScript && <div className="task-readonly-grid video-script-preview"><div><strong>视频脚本（仅文本）</strong><span>主题：{String(videoScript.theme || "未填写")}</span><span>口播脚本：{String(videoScript.spoken_script || "未填写")}</span><span>分镜：</span>{storyboard.map((shot, index) => <span key={index}>{typeof shot === "string" ? shot : JSON.stringify(shot)}</span>)}<span>拍摄指导：{String(videoScript.shooting_guidance || "未填写")}</span></div></div>}
              {artifact.artifact_type === "image" && <div className="artifact-image">
                <button className="artifact-thumb" type="button" disabled={!fileState?.url} onClick={() => void openImagePreview(artifact, selected)} aria-label={`查看 V${selected.version_no} 原图`}>
                  {fileState?.url ? <img src={fileState.url} alt={`${artifact.artifact_type === "image" ? "图片" : "文案"} V${selected.version_no} 缩略图`} onError={() => retryImageFile(artifact, selected)} /> : <span className="artifact-thumb-placeholder">{fileState?.error ? "图片加载失败" : "正在加载图片…"}</span>}
                </button>
                <div className="artifact-image-side">
                  <div className="artifact-image-actions">
                    <button className="secondary" type="button" disabled={!fileState?.url} onClick={() => void openImagePreview(artifact, selected)}>查看原图</button>
                    <button className="secondary" type="button" disabled={downloadingVersionId === selected.id} onClick={() => void downloadArtifactFile(artifact, selected)}>{downloadingVersionId === selected.id ? "下载中…" : "下载原图"}</button>
                  </div>
                  {fileState?.error && <p className="alert error" role="alert">{fileState.error}</p>}
                  <p className="muted">{dimensions ? `尺寸 ${dimensions}` : "尺寸未记录"}{byteSize ? ` · ${byteSize}` : ""}</p>
                  {imagePrompt && <p className="artifact-prompt">生成提示词：{imagePrompt}</p>}
                  {sha256 && <p className="muted artifact-hash">SHA-256：{sha256.slice(0, 16)}…</p>}
                  <p className="muted">图片地址为短时签名链接，打开预览或下载时会重新获取。</p>
                </div>
              </div>}
              {latestReview && <p className="muted">该版本审核：{reviewLabels[latestReview.decision]} · {new Date(latestReview.created_at).toLocaleString()}{latestReview.comment ? ` · ${latestReview.comment}` : ""}</p>}
              {isCurrent && !latestReview && <div className="task-step-actions">
                <button className="text-button" type="button" disabled={saving} onClick={() => void reviewArtifact(artifact, selected, "approved")}>审核通过</button>
                <button className="text-button" type="button" disabled={saving || !reviewComment.trim()} onClick={() => void reviewArtifact(artifact, selected, "revision_requested")}>要求修改</button>
                <button className="text-button" type="button" disabled={saving} onClick={() => void reviewArtifact(artifact, selected, "rejected")}>拒绝当前版本</button>
              </div>}
            </div>}
          </article>;
        })}</div>}
        <label className="field"><span>审核修改意见（要求修改时必填）</span><textarea rows={2} value={reviewComment} onChange={event => setReviewComment(event.target.value)} placeholder="明确指出需要调整的内容、位置和原因" /></label>
      </section>}
      {taskTab === "channel" && <section className="task-panel">
        <div className="section-title"><div><h2>渠道适配与质检</h2><p>仅使用已审核的当前版本；渠道规格未核验时明确阻断，不展示虚假的官方校验结果。</p></div><button className="text-button" type="button" disabled={saving} onClick={() => task && void loadContent(task.id)}>刷新渠道内容</button></div>
        {channelSpecs.map(spec => <div className="task-step-title" key={spec.id}><strong>{channelLabel(spec.channel_key)}</strong><span className={spec.current_version?.verification_status === "verified" ? "status-chip" : "status-chip danger"}>{spec.current_version?.verification_status === "verified" ? "规格已核验" : "规格待核验"}</span><span className="muted">{spec.current_version ? "V" + spec.current_version.spec_version : "暂无版本"}</span></div>)}
        <p className="muted">渠道适配使用当前已审核文案和图片版本。官方规格仍待核验时，服务端会拒绝创建内容快照。</p>
        <div className="form-footer"><p>首期渠道适配目前支持抖音图文结构；AI 自动适配尚未接入。</p><div className="form-actions"><button className="primary" type="button" disabled={saving || !channelSpecs.some(spec => spec.channel_key === "douyin" && spec.current_version?.verification_status === "verified")} onClick={() => void createChannelDraft()}>创建抖音适配快照</button></div></div>
        {channelContents.length === 0 ? <p className="muted">尚无渠道内容快照。完成文案审核并核验渠道规格后，可创建适配内容。</p> : <div className="task-content-artifacts">{channelContents.map(content => {
          const report = content.quality_reports[content.quality_reports.length - 1];
          const resolution = report?.resolutions[report.resolutions.length - 1];
          return <article className="task-content-artifact" key={content.id}>
            <div className="task-step-title"><strong>{channelLabel(content.channel_key)} · 渠道内容</strong><span className={content.status === "ready" ? "status-chip" : "status-chip danger"}>{content.status === "ready" ? "可质检" : content.status === "stale" ? "内容已过期" : "内容阻断"}</span></div>
            <p className="muted">内容指纹：{content.input_fingerprint.slice(0, 16)}… · 图片 {content.image_version_ids.length} 张</p>
            <div className="form-footer"><p>{report ? "最新质检：" + (qualityResultLabels[report.result] ?? "结果未知") + (resolution ? " · 人工决议：" + (qualityDecisionLabels[resolution.decision] ?? "决议未知") : "") : "尚无质检报告"}</p><div className="form-actions"><button className="secondary" type="button" disabled={saving || content.status !== "ready"} onClick={() => void runQuality(content)}>运行结构质检</button></div></div>
            {report && <div className="muted"><p>规则版本：{report.rule_version} · {report.issues.length} 项问题</p>{report.issues.map((issue, index) => <p key={index}>{String(issue.code || "QUALITY_ISSUE")} · {severityLabels[String(issue.severity ?? "info")] ?? "提示"}</p>)}</div>}
            {report?.result === "needs_human" && !resolution && <><label className="field"><span>人工复核理由</span><textarea rows={2} value={qualityResolutionReason} onChange={event => setQualityResolutionReason(event.target.value)} placeholder="说明已核对哪些经营事实及为何接受该质检提示" /></label><button className="secondary" type="button" disabled={saving || qualityResolutionReason.trim().length < 8} onClick={() => void acceptQuality(report)}>接受人工复核结果</button></>}
            {report && (report.result === "pass" || (report.result === "needs_human" && resolution?.decision === "accepted")) && <button className="primary" type="button" disabled={saving || !taskFactSnapshots.some(fact => fact.confirmation_status === "confirmed")} onClick={() => void freezePackage(content, report)}>冻结为发布包（人工交付）</button>}
          </article>;
        })}</div>}
      </section>}
      {taskTab === "publish" && <section className="task-panel">
        <div className="section-title"><div><h2>最终发布确认</h2><p>发布包冻结后绑定完整内容与经营事实指纹；确认仅表示商家批准交付，不代表平台已发布。</p></div><button className="text-button" type="button" disabled={saving} onClick={() => task && void loadContent(task.id)}>刷新发布包</button></div>
        <div className="task-facts">{taskFactSnapshots.map(fact => <label className="task-fact-option" key={fact.id}><input type="checkbox" checked={selectedPackageFacts.includes(fact.id)} disabled={fact.confirmation_status !== "confirmed"} onChange={event => setSelectedPackageFacts(current => event.target.checked ? [...current, fact.id] : current.filter(id => id !== fact.id))} /><span>{fact.fact_key} · V{fact.version_no}</span><small>{fact.confirmation_status === "confirmed" ? "已确认" : "待确认"}</small></label>)}</div>
        <label className="field"><span>最终确认备注（可选）</span><textarea rows={2} value={confirmationNote} onChange={event => setConfirmationNote(event.target.value)} placeholder="补充本次交付确认说明" /></label>
        {publishPackages.length === 0 ? <p className="muted">尚无冻结发布包。完成渠道内容质检并选择已确认经营事实后，可生成发布包。</p> : <div className="task-content-artifacts">{publishPackages.map(pkg => <article className="task-content-artifact" key={pkg.id}>
          <div className="task-step-title"><strong>发布包 V{pkg.package_version}</strong><span className={pkg.confirmation ? "status-chip" : "status-chip danger"}>{pkg.confirmation ? "已确认" : "待最终确认"}</span></div>
          <p className="muted">指纹：{pkg.package_fingerprint} · 渠道数：{pkg.items.length} · 冻结时间：{new Date(pkg.frozen_at).toLocaleString()}</p>
          {pkg.items.map(item => <p className="muted" key={item.id}>{channelLabel(item.channel_key)} · {item.delivery_mode === "manual_handoff" ? "人工交付" : "官方 API"} · 内容 {item.channel_content_id.slice(0, 8)}…</p>)}
          {pkg.confirmation ? <p className="muted">确认时间：{new Date(pkg.confirmation.confirmed_at).toLocaleString()}</p> : <button className="primary" type="button" disabled={saving} onClick={() => void confirmPackage(pkg)}>确认该发布包</button>}
        </article>)}</div>}
      </section>}
      {taskTab === "flow" && <section className="task-panel"><div className="section-title"><div><h2>固定执行流程</h2><p>步骤状态由服务端状态机维护，必需审核节点不可跳过。</p></div><span className="status-chip">{stepProgress}/10 已完成</span></div>
        <div className="task-step-list">{task.steps.map((step, index) => <article className="task-step" key={step.id}><div className="task-step-index">{index + 1}</div><div className="task-step-body"><div className="task-step-title"><strong>{stepLabels[step.step_key]}</strong><span className={step.status === "failed" || step.block_code ? "status-chip danger" : "status-chip"}>{stepStatusLabel(step)}</span><span className="task-applicability">{statusLabels[step.applicability]}</span></div>{step.block_code && <p className="task-block-reason">{step.block_code}{blockSummary(step) ? ` · ${blockSummary(step)}` : ""}</p>}{step.skip_reason && <p className="muted">跳过原因：{step.skip_reason}</p>}{step.output_refs.length > 0 && <p className="muted">已关联 {step.output_refs.length} 项输出</p>}<div className="task-step-actions">{["active","waiting_for_user"].includes(task.lifecycle_status) && step.applicability === "optional" && step.status === "pending" && <button className="text-button" type="button" disabled={saving} onClick={() => void stepAction(step, "skip")}>记录跳过原因</button>}{["active","waiting_for_user","blocked","failed"].includes(task.lifecycle_status) && ["failed","stale","waiting_for_user"].includes(step.status) && step.applicability !== "not_applicable" && <button className="text-button" type="button" disabled={saving} onClick={() => void stepAction(step, "recover")}>恢复此步骤</button>}</div></div></article>)}</div>
      </section>}
      </div>
      <div className="task-danger-actions">{["draft","active","waiting_for_user","blocked","failed"].includes(task.lifecycle_status) && <button className="secondary" type="button" disabled={saving} onClick={() => void taskAction("cancel")}>取消任务</button>}{["completed","cancelled"].includes(task.lifecycle_status) && <button className="secondary" type="button" disabled={saving} onClick={() => void taskAction("archive")}>归档任务</button>}</div>
      {previewImage && <div className="artifact-preview-backdrop" role="dialog" aria-modal="true" aria-label="图片原图预览" onClick={() => setPreviewImage(null)}>
        <div className="artifact-preview-dialog" onClick={event => event.stopPropagation()}>
          <div className="artifact-preview-head">
            <strong>{previewImage.label}</strong>
            <div className="form-actions">
              <button className="secondary" type="button" onClick={() => { const target = previewImage; void saveSignedUrlAsFile(target.url, target.filename).then(() => setImageNotice(`已下载 ${target.filename}`)).catch(reason => setError(`下载失败：${errorText(reason)}`)); }}>下载原图</button>
              <button className="secondary" type="button" onClick={() => setPreviewImage(null)}>关闭</button>
            </div>
          </div>
          <img src={previewImage.url} alt={`${previewImage.label} 原图`} />
          <p className="muted">文件：{previewImage.filename}</p>
        </div>
      </div>}
    </>}
  </>;

  return <>
    <div className="page-heading"><div><p className="eyebrow">MARKETING TASKS</p><h1>营销任务</h1><p className="muted">查看当前门店任务、执行状态和需要商家处理的步骤。</p></div><button className="primary" type="button" onClick={() => { window.location.hash = "#create"; }}>新建营销任务</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    <div className="task-filter-row"><label className="field"><span>任务状态</span><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部状态</option><option value="draft">草稿</option><option value="active">执行中</option><option value="waiting_for_user">待商家处理</option><option value="blocked">已阻塞</option><option value="failed">执行失败</option><option value="completed">已完成</option><option value="cancelled">已取消</option></select></label><button className="secondary" type="button" onClick={() => void loadTasks()}>刷新</button></div>
    {loading ? <div className="loading-card"><span className="spinner" />正在读取营销任务…</div> : filteredItems.length === 0 ? <section className="empty-card"><h2>暂无营销任务</h2><p>按需提出经营目标即可开始，不需要先选择热点。</p><button className="primary" type="button" onClick={() => { window.location.hash = "#create"; }}>创建第一个营销任务</button></section> : <section className="task-list">{filteredItems.map(item => <button className="task-list-item" type="button" key={item.id} onClick={() => openTask(item.id)}><span className="task-list-main"><strong>{item.title}</strong><small>{taskTypeLabels[item.task_type]} · V{item.version}</small></span><span className="task-list-meta"><strong>{statusLabels[item.lifecycle_status]}</strong><small>{item.pending_steps_count} 个待处理 · {item.blocked_steps_count} 个阻塞</small></span><span className="task-list-date">{new Date(item.updated_at).toLocaleDateString()}</span></button>)}</section>}
  </>;
}
