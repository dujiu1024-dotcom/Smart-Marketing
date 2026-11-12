import { useCallback, useEffect, useState, type FormEvent } from "react";
import { createMetricObservation, getEffectsOverview, getMetricDefinitions, getMetricObservations, importMetricCsv,
  type EffectsOverview, type MetricDefinitionRecord, type MetricObservationRecord } from "./api";

const tierLabels = { content_performance: "内容表现", intent: "互动意向", business_outcome: "经营结果" } as const;
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请稍后重试。";

export default function EffectsWorkspace({ storeId }: { storeId: string }) {
  const [overview, setOverview] = useState<EffectsOverview | null>(null);
  const [definitions, setDefinitions] = useState<MetricDefinitionRecord[]>([]);
  const [observations, setObservations] = useState<MetricObservationRecord[]>([]);
  const [tier, setTier] = useState<"all" | keyof typeof tierLabels>("all");
  const [metricKey, setMetricKey] = useState("");
  const [value, setValue] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [sourceId, setSourceId] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [csvText, setCsvText] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [summary, dictionary, history] = await Promise.all([
        getEffectsOverview(storeId), getMetricDefinitions(), getMetricObservations(storeId),
      ]);
      setOverview(summary); setDefinitions(dictionary.items); setObservations(history.items);
      setMetricKey(current => current || dictionary.items[0]?.metric_key || "");
    } catch (reason) { setError(errorText(reason)); }
    finally { setLoading(false); }
  }, [storeId]);
  useEffect(() => { void load(); }, [load]);

  function toIso(value: string): string | null {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
  }
  async function saveObservation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError(""); setNotice("");
    try {
      await createMetricObservation(storeId, {
        metric_key: metricKey, value_numeric: value.trim() || null,
        period_start: toIso(periodStart), period_end: toIso(periodEnd), period_timezone: timezone,
        source_record_id: sourceId.trim() || null, source_evidence_ref: evidenceRef.trim() || null,
      });
      setNotice("已保存为商家手工报告。该数据不会自动成为已核验经营结果或 ROI 依据。");
      setValue(""); setSourceId(""); setEvidenceRef(""); await load();
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function importCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError(""); setNotice("");
    try {
      const result = await importMetricCsv(storeId, csvText);
      setNotice(`导入完成：新增 ${result.created} 条，重复跳过 ${result.duplicates_skipped} 条。全部标记为商家报告。`);
      setCsvText(""); await load();
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  const filtered = observations.filter(item => tier === "all" || item.metric_tier === tier);

  return <section className="effects-workspace">
    <div className="page-heading"><div><p className="eyebrow">BUSINESS PERFORMANCE</p><h1>经营效果</h1><p className="muted">独立观察内容表现、互动意向与真实经营结果。所有数据均保留来源、统计周期、时区和可信状态。</p></div><button className="secondary" onClick={() => void load()} disabled={loading}>刷新数据</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    {loading && !overview ? <div className="loading-card"><span className="spinner" />正在读取经营数据…</div> : <>
      <div className="effects-status"><strong>{overview?.data_status === "available" ? "部分指标已有可核验数据" : "暂无可核验的经营数据"}</strong><span>未连接或未核验的数据源会明确显示暂无数据，不以 0 代替。</span></div>
      <div className="effects-grid">
        {(["content_performance", "intent", "business_outcome"] as const).map(group => <article className="form-card" key={group}>
          <p className="eyebrow">{group.toUpperCase()}</p><h2>{tierLabels[group]}</h2>
          <div className="effects-metric-list">{(overview?.items ?? []).filter(item => item.metric_tier === group).map(item => <div className="effects-metric" key={item.metric_key}><span>{item.display_name}</span><strong>{item.value ?? "暂无数据"}</strong><small>{item.status === "available" ? `来源：${item.source_system} · ${item.period_timezone}` : item.reason}</small></div>)}
          {!overview?.items.some(item => item.metric_tier === group) && <p className="muted">当前没有可展示的指标观测。</p>}</div>
        </article>)}
      </div>
      <article className="form-card">
        <div className="section-title"><div><h2>经营结论门禁</h2><p>经营结果需要真实证据，内容热度不能推导销售或到店增长。</p></div></div>
        <div className="effects-outcomes"><div><span>ROI</span><strong>暂无数据</strong></div><div><span>销售增长</span><strong>暂无数据</strong></div><div><span>到店增长</span><strong>暂无数据</strong></div></div>
        <p className="footnote">{overview?.business_outcomes.reason ?? "缺少真实经营结果与成本证据时，不计算 ROI 或增长结论。"}</p>
      </article>
      <article className="form-card">
        <div className="section-title"><div><h2>指标记录</h2><p>手工录入与导入的数据均标记为商家报告，等待独立核验。</p></div>
          <label className="field"><span>指标分类</span><select value={tier} onChange={event => setTier(event.target.value as typeof tier)}><option value="all">全部</option><option value="content_performance">内容表现</option><option value="intent">互动意向</option><option value="business_outcome">经营结果</option></select></label>
        </div>
        <div className="catalog-list">{filtered.map(item => <div className="catalog-item" key={item.id}><div className="catalog-item-main"><div><h3>{item.display_name}</h3><p>{item.metric_key} · {item.source_system}</p></div><span className="status-chip">{item.authenticity_status === "merchant_reported" ? "商家报告" : item.authenticity_status}</span></div><div className="catalog-meta"><span>数值：{item.value_numeric ?? "未知"}</span><span>周期：{item.period_start ?? "未提供"} 至 {item.period_end ?? "未提供"}</span><span>时区：{item.period_timezone}</span><span>采集：{new Date(item.collected_at).toLocaleString()}</span></div>{item.source_evidence_ref && <p className="catalog-description">证据：{item.source_evidence_ref}</p>}</div>)}
          {!filtered.length && <p className="muted">暂无记录。可以手工录入或导入 CSV。</p>}</div>
      </article>
      <div className="effects-grid">
        <article className="form-card"><h2>手工录入指标</h2><form className="profile-form" onSubmit={saveObservation}>
          <label className="field"><span>指标</span><select value={metricKey} onChange={event => setMetricKey(event.target.value)}>{definitions.map(def => <option key={def.id} value={def.metric_key}>{def.display_name}（{tierLabels[def.metric_tier]}）</option>)}</select></label>
          <label className="field"><span>数值（未知可留空）</span><input inputMode="decimal" value={value} onChange={event => setValue(event.target.value)} /></label>
          <label className="field"><span>统计开始时间</span><input type="datetime-local" value={periodStart} onChange={event => setPeriodStart(event.target.value)} /></label>
          <label className="field"><span>统计结束时间</span><input type="datetime-local" value={periodEnd} onChange={event => setPeriodEnd(event.target.value)} /></label>
          <label className="field"><span>IANA 时区</span><input value={timezone} onChange={event => setTimezone(event.target.value)} required /></label>
          <label className="field"><span>来源记录 ID</span><input value={sourceId} onChange={event => setSourceId(event.target.value)} /></label>
          <label className="field"><span>证据引用（链接或说明）</span><input value={evidenceRef} onChange={event => setEvidenceRef(event.target.value)} /></label>
          <button className="primary" disabled={saving || !metricKey || !timezone.trim()}>保存为手工报告</button>
        </form></article>
        <article className="form-card"><h2>CSV / Excel 数据导入</h2><p className="muted">当前接口接受 CSV 文本。Excel 文件可先另存为 CSV。必需列：metric_key、value_numeric、period_timezone；可选列：period_start、period_end、source_record_id、source_evidence_ref。时间必须带时区偏移。</p>
          <form className="profile-form" onSubmit={importCsv}><label className="field"><span>CSV 内容</span><textarea rows={12} value={csvText} onChange={event => setCsvText(event.target.value)} placeholder={"metric_key,value_numeric,period_timezone,period_start,period_end,source_record_id\nviews,1200,Asia/Shanghai,2026-11-01T00:00:00+08:00,2026-11-02T00:00:00+08:00,post-001"} /></label><button className="primary" disabled={saving || !csvText.trim()}>导入 CSV</button></form>
        </article>
      </div>
    </>}
  </section>;
}
