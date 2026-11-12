import { useCallback, useEffect, useState, type FormEvent } from "react";
import { createMetricObservation, getEffectsOverview, getMetricDefinitions, getMetricObservations, getPublishedWorks, getBusinessOutcomes, getAttributions, getDataSourceCapabilities, getPublishReadbacks, registerPublishedWorkFromReadback, createBusinessOutcome, importMetricCsv,
  type EffectsOverview, type MetricDefinitionRecord, type MetricObservationRecord, type PublishedWorkRecord,
  type BusinessOutcomeEvidenceRecord, type AttributionEvidenceRecord, type DataSourceCapabilitySnapshotRecord, type PublishReadbackCandidate } from "./api";

const tierLabels = { content_performance: "内容表现", intent: "互动意向", business_outcome: "经营结果" } as const;
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请稍后重试。";

export default function EffectsWorkspace({ storeId }: { storeId: string }) {
  const [overview, setOverview] = useState<EffectsOverview | null>(null);
  const [definitions, setDefinitions] = useState<MetricDefinitionRecord[]>([]);
  const [observations, setObservations] = useState<MetricObservationRecord[]>([]);
  const [publishedWorks, setPublishedWorks] = useState<PublishedWorkRecord[]>([]);
  const [businessOutcomes, setBusinessOutcomes] = useState<BusinessOutcomeEvidenceRecord[]>([]);
  const [attributions, setAttributions] = useState<AttributionEvidenceRecord[]>([]);
  const [capabilities, setCapabilities] = useState<DataSourceCapabilitySnapshotRecord[]>([]);
  const [publishReadbacks, setPublishReadbacks] = useState<PublishReadbackCandidate[]>([]);
  const [tier, setTier] = useState<"all" | keyof typeof tierLabels>("all");
  const [metricKey, setMetricKey] = useState("");
  const [value, setValue] = useState("");
  const [currency, setCurrency] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [sourceId, setSourceId] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [csvText, setCsvText] = useState("");
  const [outcomeType, setOutcomeType] = useState("orders");
  const [outcomeValue, setOutcomeValue] = useState("");
  const [outcomeCurrency, setOutcomeCurrency] = useState("CNY");
  const [outcomeSourceId, setOutcomeSourceId] = useState("");
  const [outcomeEvidence, setOutcomeEvidence] = useState("");
  const [outcomeOccurredAt, setOutcomeOccurredAt] = useState(() => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [summary, dictionary, history, works, outcomes, attributionHistory, capabilityHistory, readbacks] = await Promise.all([
        getEffectsOverview(storeId), getMetricDefinitions(), getMetricObservations(storeId),
        getPublishedWorks(storeId), getBusinessOutcomes(storeId), getAttributions(storeId),
        getDataSourceCapabilities(storeId), getPublishReadbacks(storeId),
      ]);
      setOverview(summary); setDefinitions(dictionary.items); setObservations(history.items);
      setPublishedWorks(works.items); setBusinessOutcomes(outcomes.items); setAttributions(attributionHistory.items);
      setCapabilities(capabilityHistory.items); setPublishReadbacks(readbacks.items);
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
        metric_key: metricKey, value_numeric: value.trim() || null, currency: currency.trim().toUpperCase() || null,
        period_start: toIso(periodStart), period_end: toIso(periodEnd), period_timezone: timezone,
        source_record_id: sourceId.trim() || null, source_evidence_ref: evidenceRef.trim() || null,
      });
      setNotice("已保存为商家手工报告。该数据不会自动成为已核验经营结果或 ROI 依据。");
      setValue(""); setCurrency(""); setSourceId(""); setEvidenceRef(""); await load();
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function saveBusinessOutcome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError(""); setNotice("");
    try {
      const occurredAt = toIso(outcomeOccurredAt);
      if (!occurredAt) throw new Error("请选择有效的经营结果发生时间");
      const result = await createBusinessOutcome(storeId, {
        outcome_type: outcomeType,
        value_numeric: outcomeValue,
        currency: outcomeType === "revenue" ? outcomeCurrency.trim().toUpperCase() : null,
        source_record_id: outcomeSourceId.trim() || null,
        source_evidence_ref: outcomeEvidence.trim(),
        occurred_at: occurredAt,
      });
      setNotice(result.message ?? "已保存为商家报告；尚未核验，不进入正式归因或 ROI。");
      setOutcomeValue(""); setOutcomeSourceId(""); setOutcomeEvidence("");
      await load();
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  async function importCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError(""); setNotice("");
    try {
      const result = await importMetricCsv(storeId, csvText);
      setNotice(`导入完成：新增 ${result.created} 条，重复跳过 ${result.duplicates_skipped} 条。批次 ${result.import_batch_id}；SHA-256 ${result.content_sha256}。全部标记为商家报告。`);
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
        <div className="section-title"><div><h2>指标趋势与周期对比</h2><p>仅对完整、当前且已核验的数据进行聚合；周期长度不一致或样本不足时不计算环比。</p></div></div>
        {(overview?.trends ?? []).length ? <div className="catalog-list">
          {overview?.trends.map(trend => <div className="catalog-item" key={trend.metric_key}>
            <div className="catalog-item-main"><div><h3>{trend.display_name}</h3><p>{trend.metric_key}</p></div>
              <span className="status-chip">{trend.comparison.status === "available" ? `环比 ${trend.comparison.change_percent}%` : "样本不足"}</span></div>
            <div className="catalog-meta">{trend.points.map(point => <span key={point.period_end}>{new Date(point.period_start).toLocaleDateString()} – {new Date(point.period_end).toLocaleDateString()}：{point.value}（n={point.sample_count}）</span>)}</div>
          </div>)}
        </div> : <p className="muted">{overview?.data_quality?.reason ?? "暂无可用于趋势分析的已核验周期数据。"}</p>}
        {(overview?.content_performance ?? []).length > 0 && <div className="catalog-list">
          <h3>按作品查看内容表现</h3>
          {overview?.content_performance.map(work => <div className="catalog-item" key={work.published_work_id + work.metric_key}>
            <div className="catalog-item-main"><div><strong>{work.display_name}</strong><p>{work.channel_key} · {work.external_work_id}</p></div>
              <span className="status-chip">{work.comparison.status === "available" ? `环比 ${work.comparison.change_percent}%` : "样本不足"}</span></div>
            <p className="catalog-description">关联任务：{work.marketing_task_id ?? "未关联"} · {work.points.map(point => `${new Date(point.period_start).toLocaleDateString()}–${new Date(point.period_end).toLocaleDateString()}：${point.value}`).join("；")}</p>
          </div>)}
        </div>}
        <p className="footnote">数据质量：观测 {overview?.data_quality.total_observations ?? 0} 条 · 已核验 {overview?.data_quality.verified_observations ?? 0} 条 · 延迟 {overview?.data_quality.delayed_observations ?? 0} 条 · 不完整/异常 {overview?.data_quality.incomplete_or_anomalous_observations ?? 0} 条</p>
      </article>
      <article className="form-card">
        <div className="section-title"><div><h2>作品归属与经营结果归因</h2><p>仅系统发布读回或官方作品核验可以确立作品归属；正式归因还要求已核验经营结果。</p></div></div>
        <div className="effects-grid">
          <div><strong>已核验作品：{publishedWorks.filter(item => ["verified_system_publish", "verified_platform_api"].includes(item.ownership_status) && item.verified_at).length}</strong><p className="muted">待核验或商家自行申报的作品不会进入归因。</p></div>
          <div><strong>经营结果证据：{businessOutcomes.length}</strong><p className="muted">商家报告与已核验结果分开记录。</p></div>
          <div><strong>有效归因：{attributions.length}</strong><p className="muted">归因保存证据快照和分摊比例。</p></div>
        </div>
        <div className="catalog-list">
          {publishReadbacks.map(item => <div className="catalog-item" key={item.publish_operation_id}>
            <div className="catalog-item-main"><div><h3>{item.channel_key} · {item.external_work_id}</h3><p>营销任务：{item.marketing_task_id}</p></div><span className="status-chip">已读回待登记</span></div>
            <p className="catalog-description">读回时间：{new Date(item.readback_at).toLocaleString()}</p>
            <button className="secondary" onClick={async () => {
              try {
                await registerPublishedWorkFromReadback(storeId, item.publish_operation_id);
                setNotice("已根据官方发布读回登记作品归属。");
                await load();
              } catch (error) {
                setNotice(error instanceof Error ? error.message : "作品登记失败");
              }
            }}>登记已核验作品</button>
          </div>)}
          {!publishReadbacks.length && <p className="muted">暂无待登记的官方发布读回记录。</p>}
        </div>
        <div className="catalog-list">
          {capabilities.map(item => <div className="catalog-item" key={item.id}>
            <div className="catalog-item-main"><div><h3>{item.channel_key} · {item.capability_key}</h3><p>能力快照 v{item.snapshot_version}</p></div><span className="status-chip">{item.status}</span></div>
            <p className="catalog-description">检查时间：{new Date(item.checked_at).toLocaleString()} · 已授权范围：{item.granted_scopes.join(", ") || "无"}</p>
          </div>)}
          {!capabilities.length && <p className="muted">暂无渠道数据读取能力快照；发布授权不代表已获得数据读取权限。</p>}
        </div>
        <div className="catalog-list">
          {publishedWorks.map(work => <div className="catalog-item" key={work.id}>
            <div className="catalog-item-main"><div><h3>{work.title ?? work.external_work_id}</h3><p>{work.channel_key} · {work.external_work_id}</p></div><span className="status-chip">{work.ownership_status}</span></div>
            <p className="catalog-description">{work.verified_at ? `核验时间：${new Date(work.verified_at).toLocaleString()}` : "尚未核验作品归属"}{work.task_id ? ` · 营销任务：${work.task_id}` : ""}</p>
          </div>)}
          {!publishedWorks.length && <p className="muted">暂无已读回或已登记的作品。</p>}
        </div>
        <form className="form-card" onSubmit={saveBusinessOutcome}>
          <h3>登记经营结果证据</h3>
          <p className="muted">手工登记只作为商家报告留痕，不能直接成为已核验经营结果或归因依据。</p>
          <div className="form-grid">
            <label>结果类型<select value={outcomeType} onChange={event => setOutcomeType(event.target.value)}>
              <option value="orders">订单数</option><option value="revenue">营业额</option>
              <option value="redemptions">优惠核销</option><option value="store_visits">到店人数</option><option value="leads">咨询线索</option>
            </select></label>
            <label>结果数值<input type="number" min="0" step="0.01" value={outcomeValue} onChange={event => setOutcomeValue(event.target.value)} required /></label>
            {outcomeType === "revenue" && <label>币种<input value={outcomeCurrency} onChange={event => setOutcomeCurrency(event.target.value)} maxLength={3} required /></label>}
            <label>发生时间<input type="datetime-local" value={outcomeOccurredAt} onChange={event => setOutcomeOccurredAt(event.target.value)} required /></label>
            <label>来源记录 ID（可选）<input value={outcomeSourceId} onChange={event => setOutcomeSourceId(event.target.value)} /></label>
            <label className="form-field-wide">证据说明或凭证链接<input value={outcomeEvidence} onChange={event => setOutcomeEvidence(event.target.value)} required /></label>
          </div>
          <button className="primary" type="submit" disabled={saving || !outcomeValue || !outcomeEvidence.trim()}>保存商家报告</button>
        </form>
        <div className="catalog-list">
          {businessOutcomes.map(outcome => <div className="catalog-item" key={outcome.id}>
            <div className="catalog-item-main"><div><h3>{outcome.outcome_type} · {outcome.value_numeric}{outcome.currency ? ` ${outcome.currency}` : ""}</h3><p>{outcome.source_system} · {new Date(outcome.occurred_at).toLocaleString()}</p></div><span className="status-chip">{outcome.authenticity_status} / {outcome.integrity_status}</span></div>
          </div>)}
          {!businessOutcomes.length && <p className="muted">暂无经营结果证据；没有真实证据时不计算 ROI。</p>}
        </div>
        {attributions.length > 0 && <div className="catalog-list">{attributions.map(item => <div className="catalog-item" key={item.id}>
          <p>营销任务 {item.marketing_task_id} · 作品 {item.published_work_id} · 经营结果 {item.outcome_evidence_id}</p>
          <p className="catalog-description">{item.attribution_method} · {item.evidence_strength} · 分摊 {item.allocation_percent}%</p>
        </div>)}</div>}
      </article>
      <article className="form-card">
        <div className="section-title"><div><h2>经营结论门禁</h2><p>经营结果需要真实证据，内容热度不能推导销售或到店增长。</p></div></div>
        <div className="effects-outcomes"><div><span>ROI</span><strong>暂无数据</strong></div><div><span>销售增长</span><strong>暂无数据</strong></div><div><span>到店增长</span><strong>暂无数据</strong></div></div>
        <p className="footnote">{overview?.business_outcomes?.reason ?? "缺少真实经营结果与成本证据时，不计算 ROI 或增长结论。"}</p>
      </article>
      <article className="form-card">
        <div className="section-title"><div><h2>指标记录</h2><p>手工录入与导入的数据均标记为商家报告，等待独立核验。</p></div>
          <label className="field"><span>指标分类</span><select value={tier} onChange={event => setTier(event.target.value as typeof tier)}><option value="all">全部</option><option value="content_performance">内容表现</option><option value="intent">互动意向</option><option value="business_outcome">经营结果</option></select></label>
        </div>
        <div className="catalog-list">{filtered.map(item => <div className="catalog-item" key={item.id}><div className="catalog-item-main"><div><h3>{item.display_name}</h3><p>{item.metric_key} · {item.source_system}</p></div><span className="status-chip">{item.authenticity_status === "merchant_reported" ? "商家报告" : item.authenticity_status}</span></div><div className="catalog-meta"><span>数值：{item.value_numeric ?? "未知"}</span><span>周期：{item.period_start ?? "未提供"} 至 {item.period_end ?? "未提供"}</span><span>时区：{item.period_timezone}</span><span>采集：{new Date(item.collected_at).toLocaleString()}</span></div>{item.source_evidence_ref && <p className="catalog-description">证据：{item.source_evidence_ref}</p>}{item.supersedes_observation_id && <p className="catalog-description">更正自：{item.supersedes_observation_id}</p>}{item.import_batch_id && <p className="catalog-description">导入批次：{item.import_batch_id}</p>}{item.published_work_id && <p className="catalog-description">已核验作品：{item.published_work_id}</p>}{item.marketing_task_id && <p className="catalog-description">关联营销任务：{item.marketing_task_id}</p>}</div>)}
          {!filtered.length && <p className="muted">暂无记录。可以手工录入或导入 CSV。</p>}</div>
      </article>
      <div className="effects-grid">
        <article className="form-card"><h2>手工录入指标</h2><form className="profile-form" onSubmit={saveObservation}>
          <label className="field"><span>指标</span><select value={metricKey} onChange={event => setMetricKey(event.target.value)}>{definitions.map(def => <option key={def.id} value={def.metric_key}>{def.display_name}（{tierLabels[def.metric_tier]}）</option>)}</select></label>
          <label className="field"><span>数值（未知可留空）</span><input inputMode="decimal" value={value} onChange={event => setValue(event.target.value)} /></label>
          <label className="field"><span>币种（销售额必填，ISO 4217）</span><input value={currency} onChange={event => setCurrency(event.target.value)} placeholder="CNY / JPY / USD" maxLength={3} /></label>
          <label className="field"><span>统计开始时间</span><input type="datetime-local" value={periodStart} onChange={event => setPeriodStart(event.target.value)} /></label>
          <label className="field"><span>统计结束时间</span><input type="datetime-local" value={periodEnd} onChange={event => setPeriodEnd(event.target.value)} /></label>
          <label className="field"><span>IANA 时区</span><input value={timezone} onChange={event => setTimezone(event.target.value)} required /></label>
          <label className="field"><span>来源记录 ID</span><input value={sourceId} onChange={event => setSourceId(event.target.value)} /></label>
          <label className="field"><span>证据引用（链接或说明）</span><input value={evidenceRef} onChange={event => setEvidenceRef(event.target.value)} /></label>
          <button className="primary" disabled={saving || !metricKey || !timezone.trim()}>保存为手工报告</button>
        </form></article>
        <article className="form-card"><h2>CSV / Excel 数据导入</h2><p className="muted">当前接口接受 CSV 文本。Excel 文件可先另存为 CSV。必需列：metric_key、value_numeric、period_timezone；可选列：period_start、period_end、currency、source_record_id、source_evidence_ref、published_work_id、marketing_task_id。作品关联仅接受已核验的系统发布读回作品。销售额必须提供 ISO 4217 币种；时间必须带时区偏移。</p>
          <form className="profile-form" onSubmit={importCsv}><label className="field"><span>CSV 内容</span><textarea rows={12} value={csvText} onChange={event => setCsvText(event.target.value)} placeholder={"metric_key,value_numeric,period_timezone,period_start,period_end,source_record_id\nviews,1200,Asia/Shanghai,2026-11-01T00:00:00+08:00,2026-11-02T00:00:00+08:00,post-001"} /></label><button className="primary" disabled={saving || !csvText.trim()}>导入 CSV</button></form>
        </article>
      </div>
    </>}
  </section>;
}
