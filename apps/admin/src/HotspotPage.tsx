import { useState } from "react";
import { api, ApiError } from "./api";
import {
  EmptyState,
  ErrorBanner,
  NoticeBanner,
  PageHeader,
  StatusPill,
  formatTime,
  useAsyncData,
} from "./ui";

export default function HotspotPage() {
  const [tab, setTab] = useState<"matches" | "topics">("matches");
  const [storeFilter, setStoreFilter] = useState("");
  const [eligibility, setEligibility] = useState("");
  const [search, setSearch] = useState("");
  const [collectOpen, setCollectOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const stores = useAsyncData(() => api.stores({ limit: 200 }), []);
  const sources = useAsyncData(() => api.opportunitySources(), []);
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
          <span className="muted">来源默认禁用，完成条款登记并经管理员确认后才能启用。</span>
        </div>
        {sources.error ? <ErrorBanner message={sources.error} /> : null}
        {sources.loading && !sources.data ? <div className="loading">读取来源…</div> : null}
        {sources.data && sources.data.items.length === 0 ? (
          <EmptyState>
            尚未登记热点来源。请先通过管理接口登记合规 RSS 来源，再在此启用并采集。
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
                  <td className="muted">{source.source_type === "rss" ? "RSS 订阅" : "其他来源"}</td>
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
                      disabled={source.enabled || busy === source.id}
                      onClick={() => void enableSource(source.id, source.display_name)}
                    >
                      {source.enabled ? "已启用" : "启用"}
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
