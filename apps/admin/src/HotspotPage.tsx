import { useState } from "react";
import { api, ApiError } from "./api";
import type {
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
  formatTime,
  useAsyncData,
} from "./ui";

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
  const [search, setSearch] = useState("");
  const [collectOpen, setCollectOpen] = useState(false);
  const [sourceDialog, setSourceDialog] = useState<
    { mode: "create" } | { mode: "edit"; source: OpportunitySource } | null
  >(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const stores = useAsyncData(() => api.stores({ limit: 200 }), []);
  const sources = useAsyncData(() => api.opportunitySources(), []);
  const presets = useAsyncData(() => api.opportunitySourcePresets(), []);
  const matches = useAsyncData(
    () =>
      api.matches({
        store_id: storeFilter || undefined,
        eligibility: eligibility || undefined,
        limit: 200,
      }),
    [storeFilter, eligibility],
  );
  const topics = useAsyncData(
    () => api.hotTopics({ query: search || undefined, limit: 200 }),
    [search],
  );

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
          <table className="table compact">
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
                  <td>
                    <strong>{source.display_name}</strong>
                    <div className="muted mono">{source.source_key}</div>
                  </td>
                  <td className="muted">
                    {source.source_type === "rss"
                      ? "RSS 订阅"
                      : source.source_type === "public_feed"
                        ? "公开热榜"
                        : "其他来源"}
                  </td>
                  <td>
                    <StatusPill status={source.health_status} />
                  </td>
                  <td>
                    <StatusPill status={source.enabled ? "active" : "suspended"} />
                  </td>
                  <td className="muted">{formatTime(source.last_success_at)}</td>
                  <td className="right">
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
            <span className="toolbar-meta">共 {matches.data?.total ?? 0} 条匹配</span>
          </div>
          {matches.error ? <ErrorBanner message={matches.error} /> : null}
          {matches.loading && !matches.data ? <div className="loading">读取匹配结果…</div> : null}
          {matches.data && matches.data.items.length === 0 ? (
            <EmptyState>
              暂无匹配结果。确认热点来源已启用并完成采集后，匹配结果会按门店下发并记录在这里。
            </EmptyState>
          ) : null}
          {matches.data && matches.data.items.length > 0 ? (
            <div className="panel table-panel">
              <table className="table">
                <thead>
                  <tr>
                    <th>门店</th>
                    <th>热点</th>
                    <th>相关度</th>
                    <th>匹配状态</th>
                    <th>匹配说明</th>
                    <th>匹配时间</th>
                  </tr>
                </thead>
                <tbody>
                  {matches.data.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.store.name}</strong>
                        <div>
                          <StatusPill status={item.store.status} />
                        </div>
                      </td>
                      <td>
                        <a href={item.canonical_url} target="_blank" rel="noreferrer">
                          {item.title}
                        </a>
                        <div className="muted">{item.suggested_scenario ?? "—"}</div>
                      </td>
                      <td>{item.relevance_score ?? "—"}</td>
                      <td>
                        <StatusPill status={item.eligibility_status} />
                        <div className="muted">算法 v{item.matching_algorithm_version}</div>
                      </td>
                      <td className="wrap muted">{item.reason_summary ?? "—"}</td>
                      <td className="muted">{formatTime(item.matched_at)}</td>
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
              onChange={(event) => setSearch(event.target.value)}
            />
            <span className="toolbar-meta">共 {topics.data?.total ?? 0} 条热点</span>
          </div>
          {topics.error ? <ErrorBanner message={topics.error} /> : null}
          {topics.loading && !topics.data ? <div className="loading">读取热点…</div> : null}
          {topics.data && topics.data.items.length === 0 ? (
            <EmptyState>热点池为空。启用来源后点击“立即采集”。</EmptyState>
          ) : null}
          {topics.data && topics.data.items.length > 0 ? (
            <div className="panel table-panel">
              <table className="table">
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>来源</th>
                    <th>热度</th>
                    <th>核验状态</th>
                    <th>发现时间</th>
                    <th>过期时间</th>
                  </tr>
                </thead>
                <tbody>
                  {topics.data.items.map((topic) => (
                    <tr key={topic.id}>
                      <td>
                        <a href={topic.canonical_url} target="_blank" rel="noreferrer">
                          {topic.title}
                        </a>
                        <div className="muted">{topic.region ?? "—"}</div>
                      </td>
                      <td className="muted">{topic.source.display_name}</td>
                      <td>
                        {topic.heat_value ?? "—"} {topic.heat_unit ?? ""}
                      </td>
                      <td>
                        <StatusPill status={topic.evidence_status} />
                      </td>
                      <td className="muted">{formatTime(topic.discovered_at)}</td>
                      <td className="muted">{formatTime(topic.expires_at)}</td>
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
            } else {
              setNotice(
                `已为 ${result.items.length} 家门店创建采集作业，可在门店匹配结果中查看本次下发。`,
              );
            }
            setCollectOpen(false);
            matches.reload();
            topics.reload();
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
          Easel 的 60s 热榜端点清单。
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
