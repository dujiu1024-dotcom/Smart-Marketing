import { useCallback, useEffect, useState } from "react";
import { decideOpportunity, getOpportunity, getOpportunities, requestOpportunityCollection, type OpportunityItem } from "./api";

const labels: Record<string, string> = {
  eligible: "可采纳", review_required: "需要人工核对", ineligible: "不适合本店", unassessed: "尚未评估",
  adopt: "已采纳", ignore: "已忽略", snooze: "已暂缓",
};
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请稍后重试。";

export default function HotspotWorkspace({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<OpportunityItem[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [route, setRoute] = useState(window.location.hash || "#hotspots");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [adoptedOpportunityId, setAdoptedOpportunityId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await getOpportunities(storeId);
      setItems(result.items);
    } catch (reasonValue) { setError(errorText(reasonValue)); }
    finally { setLoading(false); }
  }, [storeId]);

  const loadDetail = useCallback(async (id: string) => {
    setLoading(true);
    setError("");
    try { setDetail(await getOpportunity(storeId, id)); }
    catch (reasonValue) { setDetail(null); setError(errorText(reasonValue)); }
    finally { setLoading(false); }
  }, [storeId]);

  useEffect(() => {
    const onRoute = () => setRoute(window.location.hash || "#hotspots");
    window.addEventListener("hashchange", onRoute);
    return () => window.removeEventListener("hashchange", onRoute);
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const match = route.match(/^#hotspot-detail:([0-9a-f-]+)$/i);
    if (match) void loadDetail(match[1]);
    else setDetail(null);
  }, [route, loadDetail]);

  async function collect() {
    setCollecting(true); setError(""); setNotice("");
    try {
      const result = await requestOpportunityCollection(storeId, crypto.randomUUID());
      setNotice(result.message ?? (result.job_id ? `已创建采集任务：${result.job_id}` : "当前没有可采集来源。"));
      if (result.job_id) await load();
    } catch (reasonValue) { setError(errorText(reasonValue)); }
    finally { setCollecting(false); }
  }

  async function decide(decision: "adopt" | "ignore" | "snooze") {
    const id = typeof detail?.id === "string" ? detail.id : "";
    if (!id) return;
    setSaving(true); setError(""); setNotice("");
    try {
      await decideOpportunity(storeId, id, decision, reason, crypto.randomUUID());
      setAdoptedOpportunityId(decision === "adopt" ? id : null);
      setNotice(decision === "adopt" ? "机会已采纳。你可以主动选择基于该机会制作营销内容；系统不会自动创建任务。" : `已记录：${labels[decision]}。`);
      await load();
    } catch (reasonValue) { setError(errorText(reasonValue)); }
    finally { setSaving(false); }
  }

  const filtered = items.filter(item =>
    (status === "all" || item.eligibility_status === status) &&
    (!query.trim() || item.title.toLowerCase().includes(query.trim().toLowerCase()))
  );

  if (route.startsWith("#hotspot-detail:")) {
    const source = (detail?.source ?? {}) as Record<string, unknown>;
    const match = (detail?.match ?? {}) as Record<string, unknown>;
    const id = typeof detail?.id === "string" ? detail.id : "";
    return <section className="opportunity-workspace">
      <div className="page-heading"><div><p className="eyebrow">MARKETING OPPORTUNITY</p><h1>机会详情</h1><p className="muted">核对来源证据、门店匹配理由和风险后再做决定。</p></div><button className="secondary" onClick={() => { window.location.hash = "#hotspots"; setRoute("#hotspots"); }}>返回机会列表</button></div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {notice && <div className="alert success" role="status">{notice}</div>}
      {loading ? <div className="loading-card"><span className="spinner" />正在读取机会…</div> : detail ? <>
        <article className="form-card">
          <div className="section-title"><div><h2>{String(detail.title ?? "未命名机会")}</h2><p>{String(detail.summary ?? "暂无来源摘要")}</p></div><span className="status-chip">{labels[String(match.eligibility_status)] ?? "状态未知"}</span></div>
          <div className="catalog-meta"><span>来源证据：{source.evidence_status === "collected" ? "已采集" : source.evidence_status === "partial" ? "证据不完整" : "待核验"}</span><span>发布时间：{source.published_at ? new Date(String(source.published_at)).toLocaleString() : "未提供"}</span><span>采集时间：{source.discovered_at ? new Date(String(source.discovered_at)).toLocaleString() : "未知"}</span></div>
          {typeof source.url === "string" && <p className="opportunity-source"><a href={source.url} target="_blank" rel="noreferrer">查看原始来源</a></p>}
        </article>
        <article className="form-card">
          <h2>为什么匹配这家门店</h2>
          <p>{String(match.reason ?? "暂无可解释的匹配理由")}</p>
          <div className="catalog-meta"><span>匹配方式：{String(match.method ?? "未知")}</span><span>算法版本：{String(match.algorithm_version ?? "未知")}</span><span>相关性评分：{match.score == null ? "尚未计算" : String(match.score)}</span></div>
          <p>建议场景：{String(match.scenario ?? "暂无")}</p><p>内容角度：{String(match.content_angle ?? "暂无")}</p>
          <p>关联商品：{Array.isArray(match.products) && match.products.length ? match.products.join("、") : "暂无"}</p>
          <p>风险提示：{Array.isArray(match.risk_flags) && match.risk_flags.length ? match.risk_flags.join("、") : "暂无已登记风险"}</p>
          <label className="field"><span>决策备注（可选）</span><textarea rows={2} value={reason} onChange={event => setReason(event.target.value)} placeholder="说明采纳、忽略或暂缓的原因" /></label>
          <div className="form-actions">
            <button className="secondary" disabled={saving} onClick={() => void decide("ignore")}>忽略</button>
            <button className="secondary" disabled={saving} onClick={() => void decide("snooze")}>暂缓</button>
            <button className="primary" disabled={saving || match.eligibility_status !== "eligible"} onClick={() => void decide("adopt")}>采纳机会</button>
          </div>
          {match.eligibility_status !== "eligible" && <p className="footnote">当前机会未达到可采纳条件；系统不会绕过来源、有效期或人工核对门槛。</p>}
          {adoptedOpportunityId === id && <button className="primary" onClick={() => {
            sessionStorage.setItem(`store-operator.opportunity-handoff.${storeId}`, JSON.stringify({
              opportunity_id: id, title: detail.title, summary: detail.summary,
              suggested_scenario: match.scenario, content_angle: match.content_angle,
            }));
            window.location.hash = "#create";
          }}>基于此机会制作内容</button>}
        </article>
      </> : <div className="empty-card"><h2>机会不可用</h2><p>该机会不存在、已失效或不属于当前门店。</p></div>}
    </section>;
  }

  return <section className="opportunity-workspace">
    <div className="page-heading"><div><p className="eyebrow">HOT TOPICS & OPPORTUNITIES</p><h1>发现营销机会</h1><p className="muted">从有来源证据的经营机会中发现方向；也可以跳过热点，直接按需制作。</p></div><div className="form-actions"><button className="secondary" onClick={() => void load()} disabled={loading}>刷新列表</button><button className="primary" onClick={() => void collect()} disabled={collecting}> {collecting ? "提交中…" : "采集并匹配"} </button></div></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    <div className="task-filter-row">
      <label className="field"><span>搜索机会</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="输入关键词" /></label>
      <label className="field"><span>匹配状态</span><select value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option><option value="eligible">可采纳</option><option value="review_required">需要人工核对</option><option value="ineligible">不适合本店</option><option value="unassessed">尚未评估</option></select></label>
    </div>
    {loading ? <div className="loading-card"><span className="spinner" />正在读取机会…</div> : filtered.length ? <div className="catalog-list">
      {filtered.map(item => <article className="catalog-item" key={item.id}>
        <div className="catalog-item-main"><div><h2>{item.title}</h2><p>{item.summary ?? "暂无摘要"}</p></div><span className="status-chip">{labels[item.eligibility_status] ?? item.eligibility_status}</span></div>
        <div className="catalog-meta"><span>来源：{item.evidence_status === "collected" ? "已采集" : "证据不完整"}</span><span>匹配：{item.relevance_score ?? "未计算"}</span><span>算法 v{item.matching_algorithm_version}</span><span>地区：{item.region ?? "未标注"}</span><span>更新时间：{new Date(item.discovered_at).toLocaleString()}</span></div>
        {item.reason_summary && <p className="catalog-description">{item.reason_summary}</p>}
        <div className="catalog-actions"><button className="secondary" onClick={() => { const nextRoute = `#hotspot-detail:${item.id}`; window.location.hash = nextRoute; setRoute(nextRoute); }}>查看详情</button></div>
      </article>)}
    </div> : <div className="empty-card"><h2>暂无可用营销机会</h2><p>当前没有已核验来源生成的有效机会。不会用演示数据冒充实时热点，也不会随机生成匹配分数。</p><div className="form-actions"><a className="primary opportunity-link" href="#create">直接按需制作</a></div></div>}
  </section>;
}
