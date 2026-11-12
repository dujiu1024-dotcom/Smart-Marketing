import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  archiveMarketingTask, cancelMarketingTask, confirmMarketingTaskRequirement,
  confirmMarketingTaskStrategy, createMarketingTask, getAudienceProfiles, getMediaAssets,
  getBrandGuideline, getKnowledgeItems, getMarketingTask, listOffers, listTaskArtifacts,
  createTaskArtifact, createTaskArtifactVersion, createTaskArtifactReview,
  getProducts, getStoreProfile, listMarketingTasks, recoverMarketingTaskStep,
  skipMarketingTaskStep, updateMarketingTaskRequirement, updateMarketingTaskStrategy,
  type BusinessFactReference, type ContentArtifact, type ArtifactVersionRecord,
  type MediaAsset, type MarketingTask, type MarketingTaskCreateInput,
  type MarketingTaskSummary, type MarketingTaskType, type TaskStep, type TaskStepKey,
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
const statusLabels: Record<string, string> = {
  draft: "草稿", active: "执行中", waiting_for_user: "待商家处理", blocked: "已阻塞",
  failed: "执行失败", completed: "已完成", cancelled: "已取消", archived: "已归档",
  pending: "待处理", running: "执行中", succeeded: "已完成", skipped: "已跳过", stale: "需重新检查",
  required: "必需", optional: "可选", not_applicable: "不适用",
};
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请稍后重试。";
const selectedTaskKey = (storeId: string) => `store-operator.current-task-id.${storeId}`;
const createTaskKey = (storeId: string) => `store-operator.task-create.${storeId}`;
const readText = (record: Record<string, unknown>, key: string) => typeof record[key] === "string" ? String(record[key]) : "";
function safeJson(value: Record<string, unknown>): string { return JSON.stringify(value, null, 2); }
interface FactOption extends BusinessFactReference { label: string; }
interface DraftForm { goal: string; target_audience: string; core_message: string; constraints: string; }

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

export default function MarketingTaskWorkspace({ storeId }: { storeId: string }) {
  const [route, setRoute] = useState(window.location.hash || "#ai");
  const [items, setItems] = useState<MarketingTaskSummary[]>([]);
  const [task, setTask] = useState<MarketingTask | null>(null);
  const [facts, setFacts] = useState<FactOption[]>([]);
  const [selectedFacts, setSelectedFacts] = useState<string[]>([]);
  const [artifacts, setArtifacts] = useState<ContentArtifact[]>([]);
  const [mediaAssets, setMediaAssets] = useState<MediaAsset[]>([]);
  const [copyTitle, setCopyTitle] = useState("");
  const [copyBody, setCopyBody] = useState("");
  const [copyHashtags, setCopyHashtags] = useState("");
  const [selectedImageAssetId, setSelectedImageAssetId] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [loading, setLoading] = useState(false);
  const [factsLoading, setFactsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("all");
  const [taskType, setTaskType] = useState<MarketingTaskType>("full_marketing");
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [coreMessage, setCoreMessage] = useState("");
  const [constraints, setConstraints] = useState("");
  const [includesCopy, setIncludesCopy] = useState(true);
  const [includesImage, setIncludesImage] = useState(true);
  const [channelSelected, setChannelSelected] = useState(true);
  const [externalDelivery, setExternalDelivery] = useState(false);
  const [draft, setDraft] = useState<DraftForm>({ goal: "", target_audience: "", core_message: "", constraints: "" });
  const [draftDirty, setDraftDirty] = useState(false);
  const [strategyText, setStrategyText] = useState("{}");
  const [strategyDirty, setStrategyDirty] = useState(false);
  const createKey = useRef("");
  const contentMutationKey = useRef("");
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

  const loadTask = useCallback(async () => {
    const id = sessionStorage.getItem(selectedTaskKey(storeId));
    if (!id) { window.location.hash = "#tasks"; return; }
    setLoading(true); setError("");
    try {
      const response = await getMarketingTask(storeId, id);
      setTask(response);
      setDraft(requirementForm(response.requirement_draft));
      setDraftDirty(false);
      setStrategyText(safeJson(response.strategy_draft));
      setStrategyDirty(false);
    } catch (reason) { setError(errorText(reason)); setTask(null); }
    finally { setLoading(false); }
  }, [storeId]);

  const loadContent = useCallback(async (taskId: string) => {
    try {
      const [contentItems, assetItems] = await Promise.all([
        listTaskArtifacts(storeId, taskId),
        getMediaAssets(storeId),
      ]);
      setArtifacts(contentItems);
      setMediaAssets(assetItems.items);
      setSelectedImageAssetId(current => current || assetItems.items.find(item =>
        item.status === "ready" && item.usage_rights_status === "confirmed_allowed" && item.mime_type.startsWith("image/")
      )?.id || "");
    } catch (reason) { setError(errorText(reason)); }
  }, [storeId]);

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
    if (route === "#tasks") void loadTasks();
    if (route === "#task") {
      void loadTask(); void loadFacts();
      const taskId = sessionStorage.getItem(selectedTaskKey(storeId));
      if (taskId) void loadContent(taskId);
    }
    if (route === "#create") {
      const key = createTaskKey(storeId);
      createKey.current = sessionStorage.getItem(key) ?? crypto.randomUUID();
      sessionStorage.setItem(key, createKey.current);
    }
  }, [route, storeId, loadTasks, loadTask, loadFacts, loadContent]);

  const filteredItems = useMemo(() => filter === "all" ? items : items.filter(item => item.lifecycle_status === filter), [items, filter]);
  const stepProgress = task ? task.steps.filter(step => step.status === "succeeded" || step.status === "skipped").length : 0;

  function openTask(id: string) {
    sessionStorage.setItem(selectedTaskKey(storeId), id);
    window.location.hash = "#task";
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
        requirement_draft: requirementPayload({ goal, target_audience: targetAudience, core_message: coreMessage, constraints }),
        task_options: {
          includes_copy: taskType === "merchant_content" ? includesCopy : scope.includes_copy,
          includes_image: taskType === "merchant_content" ? includesImage : scope.includes_image,
          opportunity_applicable: false,
          selected_channel_keys: channelSelected ? ["douyin"] : [],
          requires_external_delivery: externalDelivery && channelSelected,
        },
      };
      if (!input.requirement_draft.goal) throw new Error("请先填写营销目标。");
      const created = await createMarketingTask(storeId, input, createKey.current || crypto.randomUUID());
      sessionStorage.removeItem(createTaskKey(storeId));
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
      await loadContent(task.id);
      setNotice(existing ? "图片产物新版本已关联，旧版本保留。" : "图片产物已关联到门店已授权素材。");
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

  if (route === "#ai") return <section className="task-home">
    <div className="page-heading"><div><p className="eyebrow">AI MARKETING</p><h1>AI 营销</h1><p className="muted">告诉 AI 你希望实现的经营目标，按需制作营销内容并由你确认关键事实和最终交付。</p></div></div>
    <div className="task-home-grid">
      <article className="task-home-card primary-card"><p className="eyebrow">START A TASK</p><h2>按需制作</h2><p>选择营销目标和内容范围，进入固定的需求、事实、策略、内容审核与交付流程。</p><button className="primary" type="button" onClick={() => { window.location.hash = "#create"; }}>开始制作</button></article>
      <article className="task-home-card"><p className="eyebrow">OPPORTUNITY DISCOVERY</p><h2>发现营销机会</h2><p>热点来源和门店机会匹配仍在接入，当前不展示模拟热点或虚构推荐。</p><button className="secondary" type="button" disabled>数据源接入中</button></article>
    </div>
    <div className="task-home-footer"><span>任务由商家按需发起；热点不是必经步骤。</span><button className="text-button" type="button" onClick={() => { window.location.hash = "#tasks"; }}>查看营销任务</button></div>
  </section>;

  if (isCreate) return <>
    <div className="page-heading"><div><p className="eyebrow">NEW MARKETING TASK</p><h1>按需制作</h1><p className="muted">先明确目标和内容范围，创建后再确认需求与经营事实。</p></div><button className="secondary" type="button" onClick={() => { window.location.hash = "#ai"; }}>返回</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    <form className="profile-form" onSubmit={createTask}>
      <section className="form-card"><div className="section-title"><div><h2>营销需求</h2><p>不需要先选择热点；普通按需制作可直接开始。</p></div></div><div className="form-grid">
        <label className="field"><span>任务类型</span><select value={taskType} onChange={event => setTaskType(event.target.value as MarketingTaskType)}><option value="full_marketing">完整营销执行</option><option value="copy_only">仅制作文案</option><option value="image_only">仅制作图片</option><option value="image_optimization">图片优化</option><option value="merchant_content">商家已有素材制作</option></select></label>
        <Field label="任务名称 *" value={title} onChange={setTitle} placeholder="例如：周末新品推广" />
        <Field label="经营目标 *" value={goal} onChange={setGoal} rows={3} placeholder="例如：提高周末下午茶时段的到店转化。" />
        <Field label="目标客群" value={targetAudience} onChange={setTargetAudience} placeholder="例如：附近写字楼白领" />
        <Field label="核心信息" value={coreMessage} onChange={setCoreMessage} placeholder="希望顾客记住的产品或服务价值" />
        <Field label="限制条件" value={constraints} onChange={setConstraints} rows={3} placeholder="例如：不使用未经确认的价格，不承诺库存。" />
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>内容与交付范围</h2><p>渠道适配和对外交付按实际需求选择。</p></div></div>
        {taskType === "merchant_content" && <div className="task-checkboxes"><label><input type="checkbox" checked={includesCopy} onChange={event => setIncludesCopy(event.target.checked)} />包含文案</label><label><input type="checkbox" checked={includesImage} onChange={event => setIncludesImage(event.target.checked)} />包含图片</label></div>}
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
      <section className="task-panel"><div className="section-title"><div><h2>需求与经营事实</h2><p>确认后形成不可变需求快照；只允许选择当前门店已确认且仍有效的经营事实。</p></div><span className="status-chip">{task.current_requirement_snapshot_id ? "需求已确认" : "待确认"}</span></div>
        {task.current_requirement_snapshot_id ? <div className="task-readonly-grid">{Object.entries(task.requirement_draft).map(([key,value]) => <div key={key}><strong>{key}</strong><span>{typeof value === "string" ? value : JSON.stringify(value)}</span></div>)}</div> : <>
          <div className="form-grid"><Field label="经营目标" value={draft.goal} onChange={value => updateDraft("goal", value)} rows={2} /><Field label="目标客群" value={draft.target_audience} onChange={value => updateDraft("target_audience", value)} /><Field label="核心信息" value={draft.core_message} onChange={value => updateDraft("core_message", value)} /><Field label="限制条件" value={draft.constraints} onChange={value => updateDraft("constraints", value)} rows={2} /></div>
          <div className="task-facts"><div className="section-title"><div><h3>选择已确认的经营事实</h3><p>这些事实会冻结到本次任务快照，后续源资料变化不会静默改写历史。最多选择 50 项，当前已选 {selectedFacts.length} 项。</p></div><button className="text-button" type="button" onClick={() => void loadFacts()}>刷新资料</button></div>
            {factsLoading ? <p className="muted">正在读取门店已确认资料…</p> : facts.length === 0 ? <p className="alert error">当前门店没有可用的已确认事实。请先到门店资料中完善并确认档案、商品、活动、客群、品牌或知识。</p> : facts.map(fact => <label className="task-fact-option" key={fact.fact_key}><input type="checkbox" checked={selectedFacts.includes(fact.fact_key)} disabled={!selectedFacts.includes(fact.fact_key) && selectedFacts.length >= 50} onChange={event => setSelectedFacts(current => event.target.checked ? [...current, fact.fact_key] : current.filter(value => value !== fact.fact_key))} /><span>{fact.label}</span><small>V{fact.expected_version_no}</small></label>)}
          </div>
          <div className="form-footer"><p>{draftDirty ? "需求有未保存修改。" : "需求确认后将创建策略生成 Job。"}</p><div className="form-actions"><button className="secondary" type="button" disabled={saving || !draftDirty} onClick={() => void saveRequirement()}>保存需求</button><button className="primary" type="button" disabled={saving || draftDirty || factsLoading || selectedFacts.length === 0 || !draft.goal.trim()} onClick={() => void confirmRequirement()}>确认需求与事实</button></div></div>
        </>}
      </section>
      <section className="task-panel"><div className="section-title"><div><h2>营销策略</h2><p>策略由异步执行生成；只有进入待商家处理状态后才可编辑和确认。</p></div><span className="status-chip">{task.current_strategy_snapshot_id ? "策略已确认" : statusLabels[task.steps.find(step => step.step_key === "strategy_confirmation")?.status || "pending"]}</span></div>
        {task.current_strategy_snapshot_id ? <pre className="task-json">{safeJson(task.strategy_draft)}</pre>
        : task.steps.find(step => step.step_key === "strategy_confirmation")?.status === "waiting_for_user" ? <><label className="field"><span>策略草稿（JSON）</span><textarea rows={8} value={strategyText} onChange={event => { setStrategyText(event.target.value); setStrategyDirty(true); }} /></label><div className="form-footer"><p>修改后必须先保存，再确认策略。</p><div className="form-actions"><button className="secondary" type="button" disabled={saving || !strategyDirty} onClick={() => void saveStrategy()}>保存策略</button><button className="primary" type="button" disabled={saving || strategyDirty} onClick={() => void confirmStrategy()}>确认策略</button></div></div></>
        : <p className="muted">{task.current_requirement_snapshot_id ? "策略生成任务已提交，等待 Worker 返回可审核草稿。若执行失败，可在下方步骤中查看阻塞原因并恢复。" : "请先完成需求与经营事实确认。"}</p>}
      </section>
      <section className="task-panel">
        <div className="section-title"><div><h2>文案与图片产物</h2><p>当前为商家手动编辑/已有素材关联路径；不会把未接入的 AI 生成伪装成真实结果。每次修改都会创建不可变新版本。</p></div><button className="text-button" type="button" onClick={() => task && void loadContent(task.id)}>刷新产物</button></div>
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
        {artifacts.length === 0 ? <p className="muted">尚无文案或图片产物。保存文案或关联图片后，这里会显示版本与审核状态。</p> : <div className="task-content-artifacts">{artifacts.map(artifact => {
          const current = artifact.versions.find(version => version.id === artifact.current_version_id);
          const content = current?.content_json || {};
          const body = typeof content.body === "string" ? content.body : "";
          const titleText = typeof content.title === "string" ? content.title : "";
          const asset = current?.source_refs.find(ref => ref.type === "media_asset");
          const reviews = current?.reviews || [];
          const latestReview = reviews[reviews.length - 1];
          const reviewLabels: Record<string, string> = { approved: "审核通过", revision_requested: "需要修改", rejected: "已拒绝" };
          return <article className="task-content-artifact" key={artifact.id}>
            <div className="task-step-title"><strong>{artifact.artifact_type === "copy" ? "文案产物" : "图片产物"}</strong><span className="status-chip">{current ? `当前版本 V${current.version_no} · ${latestReview ? reviewLabels[latestReview.decision] : "待审核"}` : "无当前版本"}</span></div>
            {current && artifact.artifact_type === "copy" && <div className="task-readonly-grid"><div><strong>{titleText || "未填写标题"}</strong><span>{body}</span></div></div>}
            {current && artifact.artifact_type === "image" && <p className="muted">已关联素材引用：{asset && typeof asset.id === "string" ? asset.id : current.content_hash}</p>}
            <p className="muted">版本历史：{artifact.versions.map(version => `V${version.version_no}`).join(" · ")}</p>
            {latestReview && <p className="muted">最近审核：{reviewLabels[latestReview.decision]} · {new Date(latestReview.created_at).toLocaleString()}{latestReview.comment ? ` · ${latestReview.comment}` : ""}</p>}
            {current && !latestReview && <div className="task-step-actions">
              <button className="text-button" type="button" disabled={saving} onClick={() => void reviewArtifact(artifact, current, "approved")}>审核通过</button>
              <button className="text-button" type="button" disabled={saving || !reviewComment.trim()} onClick={() => void reviewArtifact(artifact, current, "revision_requested")}>要求修改</button>
              <button className="text-button" type="button" disabled={saving} onClick={() => void reviewArtifact(artifact, current, "rejected")}>拒绝当前版本</button>
            </div>}
          </article>;
        })}</div>}
        <label className="field"><span>审核修改意见（要求修改时必填）</span><textarea rows={2} value={reviewComment} onChange={event => setReviewComment(event.target.value)} placeholder="明确指出需要调整的内容、位置和原因" /></label>
      </section>
      <section className="task-panel"><div className="section-title"><div><h2>固定执行流程</h2><p>步骤状态由服务端状态机维护，必需审核节点不可跳过。</p></div><span className="status-chip">{stepProgress}/10 已完成</span></div>
        <div className="task-step-list">{task.steps.map((step, index) => <article className="task-step" key={step.id}><div className="task-step-index">{index + 1}</div><div className="task-step-body"><div className="task-step-title"><strong>{stepLabels[step.step_key]}</strong><span className={step.status === "failed" || step.block_code ? "status-chip danger" : "status-chip"}>{statusLabels[step.status]}</span><span className="task-applicability">{statusLabels[step.applicability]}</span></div>{step.block_code && <p className="task-block-reason">{step.block_code}{step.block_detail ? ` · ${JSON.stringify(step.block_detail)}` : ""}</p>}{step.skip_reason && <p className="muted">跳过原因：{step.skip_reason}</p>}{step.output_refs.length > 0 && <p className="muted">已关联 {step.output_refs.length} 项输出</p>}<div className="task-step-actions">{["active","waiting_for_user"].includes(task.lifecycle_status) && step.applicability === "optional" && step.status === "pending" && <button className="text-button" type="button" disabled={saving} onClick={() => void stepAction(step, "skip")}>记录跳过原因</button>}{["active","waiting_for_user","blocked","failed"].includes(task.lifecycle_status) && ["failed","stale","waiting_for_user"].includes(step.status) && step.applicability !== "not_applicable" && <button className="text-button" type="button" disabled={saving} onClick={() => void stepAction(step, "recover")}>恢复此步骤</button>}</div></div></article>)}</div>
      </section>
      <div className="task-danger-actions">{["draft","active","waiting_for_user","blocked","failed"].includes(task.lifecycle_status) && <button className="secondary" type="button" disabled={saving} onClick={() => void taskAction("cancel")}>取消任务</button>}{["completed","cancelled"].includes(task.lifecycle_status) && <button className="secondary" type="button" disabled={saving} onClick={() => void taskAction("archive")}>归档任务</button>}</div>
    </>}
  </>;

  return <>
    <div className="page-heading"><div><p className="eyebrow">MARKETING TASKS</p><h1>营销任务</h1><p className="muted">查看当前门店任务、执行状态和需要商家处理的步骤。</p></div><button className="primary" type="button" onClick={() => { window.location.hash = "#create"; }}>新建营销任务</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    <div className="task-filter-row"><label className="field"><span>任务状态</span><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部状态</option><option value="draft">草稿</option><option value="active">执行中</option><option value="waiting_for_user">待商家处理</option><option value="blocked">已阻塞</option><option value="failed">执行失败</option><option value="completed">已完成</option><option value="cancelled">已取消</option></select></label><button className="secondary" type="button" onClick={() => void loadTasks()}>刷新</button></div>
    {loading ? <div className="loading-card"><span className="spinner" />正在读取营销任务…</div> : filteredItems.length === 0 ? <section className="empty-card"><h2>暂无营销任务</h2><p>按需提出经营目标即可开始，不需要先选择热点。</p><button className="primary" type="button" onClick={() => { window.location.hash = "#create"; }}>创建第一个营销任务</button></section> : <section className="task-list">{filteredItems.map(item => <button className="task-list-item" type="button" key={item.id} onClick={() => openTask(item.id)}><span className="task-list-main"><strong>{item.title}</strong><small>{taskTypeLabels[item.task_type]} · V{item.version}</small></span><span className="task-list-meta"><strong>{statusLabels[item.lifecycle_status]}</strong><small>{item.pending_steps_count} 个待处理 · {item.blocked_steps_count} 个阻塞</small></span><span className="task-list-date">{new Date(item.updated_at).toLocaleDateString()}</span></button>)}</section>}
  </>;
}
