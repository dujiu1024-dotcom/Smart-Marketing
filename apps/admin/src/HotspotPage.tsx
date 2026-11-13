import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type {
  AdminJob,
  MatchRow,
  OpportunitySource,
  OpportunitySourceInput,
  OpportunitySourcePreset,
} from "./api";
import {
  EmptyState,
  ErrorBanner,
  NoticeBanner,
  PageHeader,
  StatusPill,
  dash,
  formatHeat,
  formatScore,
  formatTime,
  useAsyncData,
} from "./ui";

interface MatchReason {
  categories: string;
  words: string[];
  audience: string;
  region: string;
  brand: string;
  score: string | null;
  reviewNotes: string[];
}

function parseMatchReason(value: string | null | undefined): MatchReason {
  const text = value ?? "";
  const section = (label: string) => {
    const match = text.match(new RegExp(`${label}：([^；。]*)`));
    return match?.[1]?.trim() ?? "";
  };
  const categories = section("命中品类")
    .replace(/（[^）]*）/g, "")
    .trim();
  const words = section("命中内容词")
    .split("、")
    .map((item) => item.trim())
    .filter((item) => item && item !== "无");
  const audienceRaw = section("命中客群/场景词");
  const regionRaw = section("地域");
  const scoreMatch = text.match(/加权得分\s*([\d.]+)/);
  const reviewRaw = text.match(/未达可采纳原因：([^。]*)/)?.[1] ?? "";
  let region = "无地域证据";
  if (regionRaw.includes("一致")) {
    const city = regionRaw.match(/「([^」]+)」/)?.[1];
    region = city ? `一致（${city}）` : "一致";
  } else if (regionRaw.includes("不一致")) {
    region = "不匹配";
  } else if (regionRaw.includes("未登记")) {
    region = "门店未登记";
  }
  return {
    categories: categories || "无",
    words,
    audience: audienceRaw === "无" ? "" : audienceRaw,
    region,
    brand: text.includes("品牌禁用词") ? "风险" : "安全",
    score: scoreMatch?.[1] ?? null,
    reviewNotes: reviewRaw
      .split("；")
      .map((item) => item.trim())
      .filter((item) => item && !item.startsWith("加权得分低于")),
  };
}

const REVIEW_NOTE_LABELS: Record<string, string> = {
  "仅命中父品类，未命中门店细分品类": "仅父品类",
  未命中门店品类: "未命中品类",
  地域明确不匹配: "地域不匹配",
  命中品牌禁用词: "品牌风险",
  "门店行业标签未能从业态/商品推断，交由 AI 创意重算判断": "行业待确认",
};

function shortReviewNote(note: string): string {
  return REVIEW_NOTE_LABELS[note] ?? note;
}

function MatchReasonCell({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  const reason = parseMatchReason(value);
  const conclusion = `命中 ${reason.categories}，地域${reason.region} | ${
    reason.words.length ? `${reason.words.length} 个内容词` : "无内容词"
  }`;
  const labels = [
    `品类 ${reason.categories}`,
    `客群 ${reason.audience || "无"}`,
    `地域 ${reason.region}`,
    `品牌 ${reason.brand}`,
    ...reason.reviewNotes.map((note) => `需复核 ${shortReviewNote(note)}`),
  ].join(" · ");
  return (
    <div className="reason-cell">
      <div className="reason-conclusion" title={conclusion}>
        {conclusion}
      </div>
      <div className="reason-labels" title={labels}>
        {labels}
      </div>
      <details className="reason-details">
        <summary>查看计算依据</summary>
        <div className="reason-full">
          {reason.score ? <div>加权得分 {reason.score}</div> : null}
          {reason.words.length ? <div>命中内容词：{reason.words.join("、")}</div> : null}
          <div>{value}</div>
        </div>
      </details>
    </div>
  );
}

function AiCreativeCell({ item }: { item: MatchRow }) {
  const ai = item.ai_creative;
  if (!ai) return <MatchReasonCell value={item.reason_summary} />;
  const offer = ai.offer;
  const confidence = item.ai_confidence
    ? Number(item.ai_confidence).toFixed(2)
    : null;
  const labels = [
    ai.target_audience ? `客群 ${ai.target_audience}` : null,
    offer?.discount_rule ? `机制 ${offer.discount_rule}` : null,
    confidence ? `置信度 ${confidence}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const offerText = [
    offer?.audience_condition,
    offer?.mechanic,
    offer?.discount_rule,
  ]
    .filter(Boolean)
    .join("，");
  return (
    <div className="reason-cell">
      <div className="reason-conclusion" title={ai.theme ?? undefined}>
        {dash(ai.theme)}
      </div>
      <div className="reason-labels" title={labels}>
        {labels}
      </div>
      <details className="reason-details">
        <summary>查看创意依据</summary>
        <div className="reason-full">
          {ai.play ? <div>玩法：{ai.play}</div> : null}
          {offerText ? <div>优惠机制：{offerText}</div> : null}
          {ai.borrow_logic ? <div>借势逻辑：{ai.borrow_logic}</div> : null}
          {ai.channels?.length ? <div>建议渠道：{ai.channels.join("、")}</div> : null}
          {ai.risk_notes?.length ? (
            <div>风险提示：{ai.risk_notes.join("；")}</div>
          ) : null}
          {item.ai_prompt_version ? (
            <div>Prompt 版本：{item.ai_prompt_version}</div>
          ) : null}
        </div>
      </details>
    </div>
  );
}

function hostOf(value: string): string | null {
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" ? url.hostname.toLowerCase() : null;
  } catch {
    return null;
  }
}

export default function HotspotPage() {
  const [tab, setTab] = useState<"matches" | "topics">("matches");
  const [storeFilter, setStoreFilter] = useState("");
  const [eligibility, setEligibility] = useState("");
  const [matchSource, setMatchSource] = useState("");
  const [search, setSearch] = useState("");
  const [topicPage, setTopicPage] = useState(1);
  const [collectOpen, setCollectOpen] = useState(false);
  const [sourceDialog, setSourceDialog] = useState<
    { mode: "create" } | { mode: "edit"; source: OpportunitySource } | null
  >(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [collectionJobs, setCollectionJobs] = useState<
    { jobId: string; storeName: string; job: AdminJob | null; error?: string }[]
  >([]);
  const [showHistory, setShowHistory] = useState(false);
  const finalized = useRef(false);

  const stores = useAsyncData(() => api.stores({ limit: 200 }), []);
  const sources = useAsyncData(() => api.opportunitySources(), []);
  const presets = useAsyncData(() => api.opportunitySourcePresets(), []);
  const matches = useAsyncData(
    () =>
      api.matches({
        store_id: storeFilter || undefined,
        eligibility: eligibility || undefined,
        match_source: matchSource || undefined,
        limit: 200,
      }),
    [storeFilter, eligibility, matchSource],
  );
  const topics = useAsyncData(
    () =>
      api.hotTopics({
        query: search || undefined,
        limit: 20,
        offset: (topicPage - 1) * 20,
      }),
    [search, topicPage],
  );

  useEffect(() => {
    if (collectionJobs.length === 0) return;
    const terminal = new Set(["succeeded", "failed", "cancelled", "needs_human"]);
    const allDone = collectionJobs.every(
      (item) => item.job && terminal.has(item.job.status),
    );
    if (allDone) {
      if (!finalized.current) {
        finalized.current = true;
        const inserted = collectionJobs.reduce(
          (sum, item) => sum + (item.job?.topics_inserted ?? 0),
          0,
        );
        const created = collectionJobs.reduce(
          (sum, item) => sum + (item.job?.opportunities_created ?? 0),
          0,
        );
        const failed = collectionJobs.filter(
          (item) => item.job?.status === "failed",
        ).length;
        setNotice(
          `采集完成：新增热点 ${inserted} 条，生成机会 ${created} 条` +
            (failed ? `，${failed} 个门店作业失败，请查看原因。` : "。"),
        );
        topics.reload();
        matches.reload();
      }
      return;
    }
    const timer = window.setTimeout(async () => {
      const next = await Promise.all(
        collectionJobs.map(async (item) => {
          if (item.job && terminal.has(item.job.status)) return item;
          try {
            return { ...item, job: await api.job(item.jobId), error: undefined };
          } catch (reason) {
            return {
              ...item,
              error: reason instanceof ApiError ? reason.message : "状态读取失败",
            };
          }
        }),
      );
      setCollectionJobs(next);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [collectionJobs]);

  async function enableSource(sourceId: string, displayName: string) {
    setBusy(sourceId);
    setError("");
    try {
      await api.enableOpportunitySource(sourceId);
      setNotice(`热点来源「${displayName}」已启用。`);
      sources.reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "启用失败");
    } finally {
      setBusy("");
    }
  }

  async function disableSource(sourceId: string, displayName: string) {
    setBusy(sourceId);
    setError("");
    try {
      await api.disableOpportunitySource(sourceId);
      setNotice(`热点来源「${displayName}」已停用。`);
      sources.reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "停用失败");
    } finally {
      setBusy("");
    }
  }

  const matchItems = matches.data?.items ?? [];
  const storeIds = new Set(matchItems.map((item) => item.store.id));
  const singleStore = storeIds.size === 1 ? matchItems[0].store : null;
  const visibleMatches = matchItems.filter((item) => showHistory || !item.stale_at);

  return (
    <section>
      <PageHeader
        title="热点采集与门店画像匹配"
        description="维护热点来源、触发采集，并查看热点与门店画像的匹配下发结果。"
        actions={
          <button className="button primary" type="button" onClick={() => setCollectOpen(true)}>
            立即采集
          </button>
        }
      />
      {error ? <ErrorBanner message={error} /> : null}
      {notice ? <NoticeBanner message={notice} /> : null}

      {collectionJobs.length > 0 ? (
        <div className="panel">
          <div className="panel-head">
            <h2>本次采集进度</h2>
            <div className="toolbar">
              <span className="muted">每 2 秒刷新，作业结束后自动停止。</span>
              <button
                className="button ghost"
                type="button"
                onClick={() => setCollectionJobs([])}
              >
                收起
              </button>
            </div>
          </div>
          <div className="table-scroll">
            <table className="table compact cards">
              <thead>
                <tr>
                  <th>门店</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>创建时间</th>
                  <th>来源结果</th>
                </tr>
              </thead>
              <tbody>
                {collectionJobs.map((item) => {
                  const job = item.job;
                  const progress = job?.progress_total
                    ? `${job.progress_current ?? 0}/${job.progress_total}`
                    : "—";
                  return (
                    <tr key={item.jobId}>
                      <td data-label="门店">{job?.store_name || item.storeName || item.jobId}</td>
                      <td data-label="状态">
                        <StatusPill status={job?.status ?? "queued"} />
                        {job?.error_code ? (
                          <div className="muted">
                            {job.error_code}：{job.error_summary}
                          </div>
                        ) : null}
                        {item.error ? <div className="muted">{item.error}</div> : null}
                      </td>
                      <td data-label="进度" className="cell-num">{progress}</td>
                      <td data-label="创建时间" className="cell-time">{formatTime(job?.created_at)}</td>
                      <td data-label="来源结果">
                        {(job?.source_results?.length ?? 0) +
                          (job?.source_failures?.length ?? 0) >
                        0 ? (
                          <div className="collect-sources">
                            {job?.source_results?.map((source) => (
                              <span
                                key={`ok-${source.source_key}`}
                                className="pill pill-succeeded"
                              >
                                {source.source_key} 抓取 {source.entries ?? 0} 条 / 新增{" "}
                                {source.inserted ?? 0}
                              </span>
                            ))}
                            {job?.source_failures?.map((failure) => (
                              <span
                                key={`fail-${failure.source_key ?? failure.error_code}`}
                                className="pill pill-failed"
                                title={failure.summary}
                              >
                                {failure.source_key ?? "来源"} {failure.error_code}
                              </span>
                            ))}
                          </div>
                        ) : job?.status === "queued" ? (
                          <span className="muted">等待开始</span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                        {job?.source_failures?.length ? (
                          <div className="muted">
                            {job.source_failures
                              .map(
                                (failure) =>
                                  `${failure.source_key ?? "来源"}：${failure.error_code} ${failure.summary}`,
                              )
                              .join("；")}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <div className="panel-head">
          <h2>采集来源</h2>
          <div className="toolbar">
            <span className="muted">来源默认禁用，完成条款登记并经管理员确认后才能启用。</span>
            <button
              className="button"
              type="button"
              onClick={() => setSourceDialog({ mode: "create" })}
            >
              新增来源
            </button>
          </div>
        </div>
        {sources.error ? <ErrorBanner message={sources.error} /> : null}
        {sources.loading && !sources.data ? <div className="loading">读取来源…</div> : null}
        {sources.data && sources.data.items.length === 0 ? (
          <EmptyState>
            尚未登记热点来源。点击「新增来源」登记公开 RSS 或公开热榜来源，完成条款审查后再启用。
          </EmptyState>
        ) : null}
        {sources.data && sources.data.items.length > 0 ? (
          <div className="table-scroll">
            <table className="table compact cards">
            <thead>
              <tr>
                <th>来源</th>
                <th>类型</th>
                <th>健康状态</th>
                <th>状态</th>
                <th>最近成功</th>
                <th className="right">操作</th>
              </tr>
            </thead>
            <tbody>
              {sources.data.items.map((source) => (
                <tr key={source.id}>
                  <td data-label="来源">
                    <strong>{source.display_name}</strong>
                    <div className="muted mono">{source.source_key}</div>
                  </td>
                  <td data-label="类型" className="muted">
                    {source.source_type === "rss"
                      ? "RSS 订阅"
                      : source.source_type === "public_feed"
                        ? "公开热榜"
                        : "其他来源"}
                  </td>
                  <td data-label="健康状态">
                    <StatusPill status={source.health_status} />
                    {source.last_error_code ? (
                      <div className="muted mono" title={source.last_error_summary ?? undefined}>
                        {source.last_error_code}
                      </div>
                    ) : null}
                  </td>
                  <td data-label="状态">
                    <StatusPill status={source.enabled ? "active" : "suspended"} />
                  </td>
                  <td data-label="最近成功" className="cell-time muted">
                    {formatTime(source.last_success_at)}
                  </td>
                  <td data-label="操作" className="right">
                    <button
                      className="link-button"
                      type="button"
                      disabled={source.enabled}
                      title={source.enabled ? "请先停用后再编辑" : undefined}
                      onClick={() => setSourceDialog({ mode: "edit", source })}
                    >
                      编辑
                    </button>
                    <button
                      className="link-button"
                      type="button"
                      disabled={busy === source.id}
                      onClick={() =>
                        source.enabled
                          ? void disableSource(source.id, source.display_name)
                          : void enableSource(source.id, source.display_name)
                      }
                    >
                      {source.enabled ? "停用" : "启用"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div className="subtabs">
        <button
          className={tab === "matches" ? "subtab active" : "subtab"}
          type="button"
          onClick={() => setTab("matches")}
        >
          门店匹配结果
        </button>
        <button
          className={tab === "topics" ? "subtab active" : "subtab"}
          type="button"
          onClick={() => setTab("topics")}
        >
          热点池
        </button>
      </div>

      {tab === "matches" ? (
        <>
          <div className="toolbar">
            <select
              className="select"
              value={storeFilter}
              onChange={(event) => setStoreFilter(event.target.value)}
            >
              <option value="">全部门店</option>
              {(stores.data?.items ?? []).map((store) => (
                <option key={store.id} value={store.id}>
                  {store.name}
                </option>
              ))}
            </select>
            <select
              className="select"
              value={eligibility}
              onChange={(event) => setEligibility(event.target.value)}
            >
              <option value="">全部匹配状态</option>
              <option value="eligible">可执行</option>
              <option value="review_required">需复核</option>
              <option value="ineligible">不适用</option>
              <option value="unassessed">未评估</option>
            </select>
            <select
              className="select"
              value={matchSource}
              onChange={(event) => setMatchSource(event.target.value)}
            >
              <option value="">全部来源</option>
              <option value="rules">规则命中</option>
              <option value="ai_creative">AI 创意</option>
            </select>
            <span className="toolbar-meta">
              共 {visibleMatches.length} 条匹配 · 规则命中{" "}
              {matches.data?.source_counts?.rules ?? 0} 条 · AI 创意{" "}
              {matches.data?.source_counts?.ai_creative ?? 0} 条
              {showHistory && matchItems.length !== visibleMatches.length
                ? `（历史 ${matchItems.length - visibleMatches.length} 条）`
                : ""}
            </span>
            <label className="toolbar-check">
              <input
                type="checkbox"
                checked={showHistory}
                onChange={(event) => setShowHistory(event.target.checked)}
              />
              显示历史版本
            </label>
            {singleStore ? (
              <span className="toolbar-meta">当前门店：{singleStore.name}</span>
            ) : null}
          </div>
          {matches.error ? <ErrorBanner message={matches.error} /> : null}
          {matches.loading && !matches.data ? <div className="loading">读取匹配结果…</div> : null}
          {matches.data && visibleMatches.length === 0 ? (
            <EmptyState>
              暂无匹配结果。确认热点来源已启用并完成采集后，匹配结果会按门店下发并记录在这里。
            </EmptyState>
          ) : null}
          {matches.data && visibleMatches.length > 0 ? (
            <div className="panel table-panel">
              <table className="table cards matches-table">
                <thead>
                  <tr>
                    {singleStore ? null : <th>门店</th>}
                    <th>热点</th>
                    <th className="cell-num">相关度</th>
                    <th>匹配状态</th>
                    <th>匹配说明</th>
                    <th className="cell-time">匹配时间</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleMatches.map((item) => (
                    <tr key={item.id} className={item.stale_at ? "row-stale" : undefined}>
                      {singleStore ? null : (
                        <td data-label="门店" className="cell-store">
                          <strong>{item.store.name}</strong>
                          {item.store.status !== "active" ? (
                            <div>
                              <StatusPill status={item.store.status} />
                            </div>
                          ) : null}
                        </td>
                      )}
                      <td data-label="热点" className="cell-title">
                        <a
                          href={item.canonical_url}
                          target="_blank"
                          rel="noreferrer"
                          title={item.title}
                        >
                          {item.title}
                        </a>
                        <div className="muted">{dash(item.suggested_scenario)}</div>
                      </td>
                      <td data-label="相关度" className="cell-num">
                        {formatScore(item.relevance_score)}
                      </td>
                      <td data-label="匹配状态" className="cell-nowrap">
                        <StatusPill status={item.eligibility_status} />
                        {item.stale_at ? <span className="pill">历史</span> : null}
                        <div className="muted">
                          算法 v{item.matching_algorithm_version}
                          {item.match_source === "ai_creative" ? " · AI 创意" : ""}
                        </div>
                      </td>
                      <td data-label="匹配说明">
                        {item.match_source === "ai_creative" ? (
                          <AiCreativeCell item={item} />
                        ) : (
                          <MatchReasonCell value={item.reason_summary} />
                        )}
                      </td>
                      <td data-label="匹配时间" className="cell-time muted">
                        {formatTime(item.matched_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : (
        <>
          <div className="toolbar">
            <input
              className="input"
              placeholder="搜索热点标题"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setTopicPage(1);
              }}
            />
            <span className="toolbar-meta">
              共 {topics.data?.total ?? 0} 条热点 · 第 {topicPage} /{" "}
              {Math.max(1, topics.data?.total_pages ?? 0)} 页
            </span>
            <button
              className="button ghost"
              type="button"
              disabled={topicPage <= 1 || topics.loading}
              onClick={() => setTopicPage((page) => Math.max(1, page - 1))}
            >
              上一页
            </button>
            <button
              className="button ghost"
              type="button"
              disabled={
                topics.loading ||
                topicPage >= Math.max(1, topics.data?.total_pages ?? 0)
              }
              onClick={() => setTopicPage((page) => page + 1)}
            >
              下一页
            </button>
          </div>
          {topics.error ? <ErrorBanner message={topics.error} /> : null}
          {topics.loading && !topics.data ? <div className="loading">读取热点…</div> : null}
          {topics.data && topics.data.items.length === 0 ? (
            <EmptyState>热点池为空。启用来源后点击“立即采集”。</EmptyState>
          ) : null}
          {topics.data && topics.data.items.length > 0 ? (
            <div className="panel table-panel">
              <table className="table cards topics-table">
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>来源</th>
                    <th className="cell-num">热度</th>
                    <th>核验状态</th>
                    <th className="cell-time">发现时间</th>
                    <th className="cell-time">过期时间</th>
                  </tr>
                </thead>
                <tbody>
                  {topics.data.items.map((topic) => (
                    <tr key={topic.id}>
                      <td data-label="标题" className="cell-title">
                        <a
                          href={topic.canonical_url}
                          target="_blank"
                          rel="noreferrer"
                          title={topic.title}
                        >
                          {topic.title}
                        </a>
                        <div className="muted">{dash(topic.region)}</div>
                      </td>
                      <td data-label="来源" className="cell-nowrap muted">
                        {topic.source.display_name}
                      </td>
                      <td data-label="热度" className="cell-num">
                        {formatHeat(topic.heat_value, topic.heat_unit)}
                      </td>
                      <td data-label="核验状态" className="cell-nowrap">
                        <StatusPill status={topic.evidence_status} />
                      </td>
                      <td data-label="发现时间" className="cell-time muted">
                        {formatTime(topic.discovered_at)}
                      </td>
                      <td data-label="过期时间" className="cell-time muted">
                        {formatTime(topic.expires_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}

      {sourceDialog ? (
        <SourceDialog
          mode={sourceDialog.mode}
          source={sourceDialog.mode === "edit" ? sourceDialog.source : null}
          presets={presets.data?.items ?? []}
          allowedHosts={presets.data?.allowed_hosts ?? []}
          onClose={() => setSourceDialog(null)}
          onSaved={(message) => {
            setSourceDialog(null);
            setNotice(message);
            sources.reload();
          }}
        />
      ) : null}

      {collectOpen ? (
        <CollectDialog
          stores={(stores.data?.items ?? []).filter((store) => store.status === "active")}
          onClose={() => setCollectOpen(false)}
          onSubmit={async (storeIds) => {
            const result = await api.collect(storeIds, crypto.randomUUID());
            if (result.message) {
              setNotice(result.message);
              setCollectOpen(false);
              return;
            }
            finalized.current = false;
            setNotice("");
            setCollectionJobs(
              result.items.map((item) => ({
                jobId: item.job_id,
                storeName: item.store_name,
                job: null,
              })),
            );
            setCollectOpen(false);
          }}
        />
      ) : null}
    </section>
  );
}

function SourceDialog({
  mode,
  source,
  presets,
  allowedHosts,
  onClose,
  onSaved,
}: {
  mode: "create" | "edit";
  source: OpportunitySource | null;
  presets: OpportunitySourcePreset[];
  allowedHosts: string[];
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [sourceKey, setSourceKey] = useState(source?.source_key ?? "");
  const [displayName, setDisplayName] = useState(source?.display_name ?? "");
  const [sourceType, setSourceType] = useState<"rss" | "public_feed">(
    source?.source_type === "public_feed" ? "public_feed" : "rss",
  );
  const [sourceUrl, setSourceUrl] = useState(source?.source_url ?? "");
  const [fallbackUrl, setFallbackUrl] = useState(source?.fallback_url ?? "");
  const [termsUrl, setTermsUrl] = useState(source?.terms_url ?? "");
  const [permittedUse, setPermittedUse] = useState(source?.permitted_use ?? "");
  const [attribution, setAttribution] = useState(source?.attribution_template ?? "");
  const [enabled, setEnabled] = useState(source?.enabled ?? false);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  function applyPreset(key: string) {
    const preset = presets.find((item) => item.key === key);
    if (!preset) {
      return;
    }
    setSourceType("public_feed");
    setSourceKey(`60s-${preset.key}`);
    setDisplayName(preset.display_name);
    setSourceUrl(preset.source_url);
    setFallbackUrl(preset.fallback_url ?? "");
  }

  function validate(): string {
    if (!sourceKey.trim()) {
      return "请填写来源标识，建议使用英文、数字或短横线。";
    }
    if (!displayName.trim()) {
      return "请填写来源名称。";
    }
    const feedHost = hostOf(sourceUrl);
    if (!feedHost) {
      return "来源地址必须是完整的 HTTPS 地址，例如 https://example.com/feed.json。";
    }
    if (allowedHosts.length > 0 && !allowedHosts.includes(feedHost)) {
      return `来源地址域名 ${feedHost} 不在允许白名单内，当前允许：${allowedHosts.join("、")}。请先让平台在服务端白名单中加入该域名。`;
    }
    if (fallbackUrl.trim()) {
      const fallbackHost = hostOf(fallbackUrl);
      if (!fallbackHost) {
        return "备用地址必须是完整的 HTTPS 地址，例如 https://example.com/feed.json。";
      }
      if (allowedHosts.length > 0 && !allowedHosts.includes(fallbackHost)) {
        return `备用地址域名 ${fallbackHost} 不在允许白名单内，当前允许：${allowedHosts.join("、")}。`;
      }
    }
    if (!termsUrl.trim()) {
      return "请填写使用条款 URL，未登记条款的来源不能启用，也不能参与采集。";
    }
    const termsHost = hostOf(termsUrl);
    if (!termsHost) {
      return "条款地址必须是完整的 HTTPS 地址。";
    }
    if (allowedHosts.length > 0 && !allowedHosts.includes(termsHost)) {
      return `条款地址域名 ${termsHost} 不在允许白名单内，当前允许：${allowedHosts.join("、")}。`;
    }
    if (permittedUse.trim().length < 10) {
      return "请用不少于 10 个字写明允许用途，例如使用范围、署名要求和禁止事项。";
    }
    return "";
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        className="modal"
        onSubmit={(event) => {
          event.preventDefault();
          const validation = validate();
          if (validation) {
            setError(validation);
            return;
          }
          setSubmitting(true);
          setError("");
          const payload: OpportunitySourceInput = {
            source_key: sourceKey.trim(),
            display_name: displayName.trim(),
            source_type: sourceType,
            source_url: sourceUrl.trim(),
            fallback_url: fallbackUrl.trim() || null,
            terms_url: termsUrl.trim(),
            permitted_use: permittedUse.trim(),
            attribution_template: attribution.trim() || null,
          };
          (async () => {
            let sourceId = source?.id ?? createdId;
            if (mode === "create" && !createdId) {
              const created = await api.createOpportunitySource(payload);
              sourceId = created.id;
              setCreatedId(created.id);
            } else if (mode === "edit" && sourceId) {
              if (source?.enabled && !enabled) {
                await api.disableOpportunitySource(sourceId);
              }
              await api.updateOpportunitySource(sourceId, {
                display_name: payload.display_name,
                source_url: payload.source_url,
                fallback_url: payload.fallback_url ?? "",
                terms_url: payload.terms_url,
                permitted_use: payload.permitted_use,
                attribution_template: payload.attribution_template,
              });
            }
            if (enabled && sourceId) {
              await api.enableOpportunitySource(sourceId);
            }
            onSaved(
              enabled
                ? "热点来源已保存并启用，可立即用于采集。"
                : "热点来源已保存，当前为停用状态。",
            );
          })()
            .catch((reason: unknown) => {
              setError(
                reason instanceof ApiError
                  ? reason.message
                  : "保存失败，请检查网络后重试。",
              );
            })
            .finally(() => setSubmitting(false));
        }}
      >
        <h2>{mode === "create" ? "新增热点来源" : "编辑热点来源"}</h2>
        <p className="muted">
          来源登记后默认禁用。仅公开、条款已登记且域名在白名单内的来源可启用；公开热榜预设复用
          Easel 的多源热榜端点（xxapi 主源、60s 备用）。
        </p>
        {mode === "create" ? (
          <label className="field">
            <span>公开热榜预设（可选）</span>
            <select className="select" defaultValue="" onChange={(event) => applyPreset(event.target.value)}>
              <option value="">不使用预设</option>
              {presets.map((preset) => (
                <option key={preset.key} value={preset.key}>
                  {preset.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="field">
          <span>来源标识</span>
          <input
            className="input"
            value={sourceKey}
            readOnly={mode === "edit"}
            required
            onChange={(event) => setSourceKey(event.target.value)}
          />
        </label>
        <label className="field">
          <span>显示名称</span>
          <input
            className="input"
            value={displayName}
            required
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label className="field">
          <span>来源类型</span>
          <select
            className="select"
            value={sourceType}
            disabled={mode === "edit"}
            onChange={(event) => setSourceType(event.target.value as "rss" | "public_feed")}
          >
            <option value="public_feed">公开热榜 JSON</option>
            <option value="rss">RSS / Atom 订阅</option>
          </select>
        </label>
        <label className="field">
          <span>来源地址</span>
          <input
            className="input"
            value={sourceUrl}
            placeholder="https://"
            required
            onChange={(event) => setSourceUrl(event.target.value)}
          />
        </label>
        <label className="field">
          <span>备用地址（可选，主地址失败时自动切换）</span>
          <input
            className="input"
            value={fallbackUrl}
            placeholder="https://"
            onChange={(event) => setFallbackUrl(event.target.value)}
          />
        </label>
        <label className="field">
          <span>使用条款地址</span>
          <input
            className="input"
            value={termsUrl}
            placeholder="https://"
            required
            onChange={(event) => setTermsUrl(event.target.value)}
          />
        </label>
        <label className="field">
          <span>允许用途（不少于 10 字）</span>
          <textarea
            className="input"
            rows={3}
            value={permittedUse}
            required
            onChange={(event) => setPermittedUse(event.target.value)}
          />
        </label>
        <label className="field">
          <span>署名模板（可选）</span>
          <input
            className="input"
            value={attribution}
            onChange={(event) => setAttribution(event.target.value)}
          />
        </label>
        <label className="field checkbox-field">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          <span>保存后立即启用（需条款已登记且域名在白名单内，启用后可直接参与采集）</span>
        </label>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="modal-actions">
          <button className="button ghost" type="button" onClick={onClose}>
            取消
          </button>
          <button className="button primary" type="submit" disabled={submitting}>
            {submitting ? "保存中…" : "保存"}
          </button>
        </div>
      </form>
    </div>
  );
}

function CollectDialog({
  stores,
  onClose,
  onSubmit,
}: {
  stores: { id: string; name: string }[];
  onClose: () => void;
  onSubmit: (storeIds: string[] | null) => Promise<void>;
}) {
  const [scope, setScope] = useState("all");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        className="modal"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitting(true);
          setError("");
          onSubmit(scope === "all" ? null : [scope])
            .catch((reason: unknown) => {
              setError(reason instanceof ApiError ? reason.message : "采集任务创建失败");
            })
            .finally(() => setSubmitting(false));
        }}
      >
        <h2>立即采集热点</h2>
        <p className="muted">
          使用已启用且完成条款登记的来源，为所选门店采集热点并按门店画像执行匹配。
        </p>
        <label className="field">
          <span>采集范围</span>
          <select className="select" value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="all">全部门店</option>
            {stores.map((store) => (
              <option key={store.id} value={store.id}>
                {store.name}
              </option>
            ))}
          </select>
        </label>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="modal-actions">
          <button className="button ghost" type="button" onClick={onClose}>
            取消
          </button>
          <button className="button primary" type="submit" disabled={submitting}>
            {submitting ? "创建中…" : "开始采集"}
          </button>
        </div>
      </form>
    </div>
  );
}
