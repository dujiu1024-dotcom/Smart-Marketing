import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  confirmOfferFacts, createOffer, deleteOffer, getOffers, updateOffer,
  type Offer, type OfferInput,
} from "./api";

interface OfferForm {
  title: string;
  offer_type: string;
  terms_json: string;
  eligibility_rules_json: string;
  starts_at: string;
  ends_at: string;
  stacking_policy: string;
  usage_limit: string;
  status: OfferInput["status"];
}
const emptyForm: OfferForm = {
  title: "", offer_type: "discount", terms_json: "{\n  \n}", eligibility_rules_json: "{\n  \n}",
  starts_at: "", ends_at: "", stacking_policy: "not_stackable", usage_limit: "", status: "draft",
};
function fromOffer(offer: Offer): OfferForm {
  const localDate = (value: string | null) => {
    if (!value) return "";
    const date = new Date(value);
    const pad = (part: number) => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  };
  return {
    title: offer.title, offer_type: offer.offer_type,
    terms_json: JSON.stringify(offer.terms_json, null, 2),
    eligibility_rules_json: JSON.stringify(offer.eligibility_rules_json, null, 2),
    starts_at: localDate(offer.starts_at), ends_at: localDate(offer.ends_at),
    stacking_policy: offer.stacking_policy ?? "", usage_limit: offer.usage_limit === null ? "" : String(offer.usage_limit),
    status: offer.status,
  };
}
function parseObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try { parsed = JSON.parse(value); } catch { throw new Error(`${label}必须是有效 JSON 对象`); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(`${label}必须是 JSON 对象`);
  return parsed as Record<string, unknown>;
}
function message(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败，请稍后重试。";
}
function inputValue(value: string): string | null { return value.trim() || null; }

export default function OfferWorkspace({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<Offer[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Offer | null>(null);
  const [form, setForm] = useState<OfferForm>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [route, setRoute] = useState(window.location.hash || "#store:offers");

  const reload = useCallback(async () => {
    if (!storeId) return;
    setLoading(true); setError("");
    try {
      const response = await getOffers(storeId);
      setItems(response.items); setTotal(response.total);
    } catch (reason) { setError(message(reason)); }
    finally { setLoading(false); }
  }, [storeId]);

  useEffect(() => {
    const updateRoute = () => setRoute(window.location.hash || "#store:offers");
    window.addEventListener("hashchange", updateRoute);
    void reload();
    return () => window.removeEventListener("hashchange", updateRoute);
  }, [reload]);

  useEffect(() => {
    if (!route.startsWith("#store-editor:offer:")) return;
    const id = route.slice("#store-editor:offer:".length);
    if (id === "new") { setSelected(null); setForm(emptyForm); return; }
    const offer = items.find((item) => item.id === id);
    if (offer) { setSelected(offer); setForm(fromOffer(offer)); }
  }, [route, items]);

  function change<K extends keyof OfferForm>(key: K, value: OfferForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setNotice("");
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setNotice("");
    try {
      const start = form.starts_at ? new Date(form.starts_at).toISOString() : null;
      const end = form.ends_at ? new Date(form.ends_at).toISOString() : null;
      if (start && end && new Date(end) <= new Date(start)) throw new Error("结束时间必须晚于开始时间");
      const usageLimit = form.usage_limit.trim() ? Number(form.usage_limit) : null;
      if (usageLimit !== null && (!Number.isInteger(usageLimit) || usageLimit < 1)) throw new Error("使用次数上限必须为正整数");
      const payload: OfferInput = {
        title: form.title.trim(), offer_type: form.offer_type,
        terms_json: parseObject(form.terms_json, "优惠规则"),
        eligibility_rules_json: parseObject(form.eligibility_rules_json, "适用条件"),
        starts_at: start, ends_at: end, stacking_policy: inputValue(form.stacking_policy),
        usage_limit: usageLimit, status: form.status,
      };
      const saved = selected ? await updateOffer(storeId, selected, payload) : await createOffer(storeId, payload);
      setItems((current) => selected ? current.map((item) => item.id === saved.id ? saved : item) : [saved, ...current]);
      setTotal((current) => selected ? current : current + 1);
      setSelected(saved); setForm(fromOffer(saved));
      setNotice(`活动优惠已保存为 V${saved.current_version}，请核对规则后确认。`);
      window.location.hash = "#store:offers";
    } catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }
  async function confirm(offer: Offer) {
    setSaving(true); setError(""); setNotice("");
    try {
      const confirmed = await confirmOfferFacts(storeId, offer);
      setItems((current) => current.map((item) => item.id === confirmed.id ? confirmed : item));
      setSelected((current) => current?.id === confirmed.id ? confirmed : current);
      setNotice(`${confirmed.title} 的事实版本 V${confirmed.current_version} 已确认。`);
    } catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }
  async function remove(offer: Offer) {
    if (!window.confirm(`确认删除活动「${offer.title}」？`)) return;
    setSaving(true); setError(""); setNotice("");
    try {
      await deleteOffer(storeId, offer);
      setItems((current) => current.filter((item) => item.id !== offer.id));
      setTotal((current) => Math.max(0, current - 1));
      setNotice("活动优惠已删除。");
    } catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }

  const editing = route.startsWith("#store-editor:offer:");
  return <>
    <div className="page-heading">
      <div><p className="eyebrow">STORE OFFERS</p><h1>活动与优惠</h1>
        <p className="muted">维护优惠规则、适用条件与有效期。未经确认的规则不得作为 AI 营销事实引用。</p></div>
      {!editing && <button className="primary" type="button" onClick={() => { window.location.hash = "#store-editor:offer:new"; }}>新增活动</button>}
      {editing && <button className="secondary" type="button" onClick={() => { window.location.hash = "#store:offers"; }}>返回列表</button>}
    </div>
    {error && <div className="alert error" role="alert">{error}{error.includes("VERSION_CONFLICT") || error.includes("changed") ? <button className="text-button" onClick={() => void reload()}>重新加载</button> : null}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    {editing ? (
      <form className="profile-form" onSubmit={save}>
        <section className="form-card">
          <div className="section-title"><div><h2>{selected ? "编辑活动优惠" : "新增活动优惠"}</h2><p>保存后生成新版本并重置为待确认；事实确认是独立操作。</p></div></div>
          <div className="form-grid">
            <label className="field"><span>活动名称 *</span><input required value={form.title} onChange={(e) => change("title", e.target.value)} /></label>
            <label className="field"><span>活动类型</span><select value={form.offer_type} onChange={(e) => change("offer_type", e.target.value)}>
              <option value="discount">折扣优惠</option><option value="bundle">组合优惠</option><option value="gift">赠品 / 买赠</option><option value="threshold">满额优惠</option><option value="other">其他</option>
            </select></label>
            <label className="field"><span>开始时间</span><input type="datetime-local" value={form.starts_at} onChange={(e) => change("starts_at", e.target.value)} /></label>
            <label className="field"><span>结束时间</span><input type="datetime-local" value={form.ends_at} onChange={(e) => change("ends_at", e.target.value)} /></label>
            <label className="field"><span>使用次数上限</span><input type="number" min="1" step="1" value={form.usage_limit} onChange={(e) => change("usage_limit", e.target.value)} placeholder="不限制请留空" /></label>
            <label className="field"><span>叠加策略</span><select value={form.stacking_policy} onChange={(e) => change("stacking_policy", e.target.value)}>
              <option value="not_stackable">不可叠加</option><option value="stackable">可叠加</option><option value="priority">按优先级</option>
            </select></label>
            <label className="field"><span>活动状态</span><select value={form.status} onChange={(e) => change("status", e.target.value as OfferInput["status"])}>
              <option value="draft">草稿</option><option value="active">生效中</option><option value="paused">已暂停</option><option value="expired">已过期</option><option value="archived">已归档</option>
            </select></label>
            <div className="field span-2"><span>优惠规则（JSON 对象）</span><textarea rows={4} value={form.terms_json} onChange={(e) => change("terms_json", e.target.value)} placeholder='例如：{"discount_percent": 50, "buy_quantity": 1, "gift_quantity": 1}' /></div>
            <div className="field span-2"><span>适用条件（JSON 对象）</span><textarea rows={4} value={form.eligibility_rules_json} onChange={(e) => change("eligibility_rules_json", e.target.value)} placeholder='例如：{"product_ids": [], "minimum_spend": 0, "member_only": false}' /></div>
          </div>
        </section>
        <div className="form-footer"><p>{selected ? `当前版本 V${selected.current_version} · ${selected.fact_status === "confirmed" ? "已确认" : "待确认"}` : "新增后需核对优惠规则、适用条件和有效期。"}</p>
          <div className="form-actions">
            {selected && selected.fact_status !== "confirmed" && <button className="secondary" type="button" disabled={saving} onClick={() => void confirm(selected)}>确认事实</button>}
            <button className="secondary" type="button" onClick={() => { window.location.hash = "#store:offers"; }}>取消</button>
            <button className="primary" type="submit" disabled={saving || !form.title.trim()}>{saving ? "保存中…" : "保存活动"}</button>
          </div>
        </div>
      </form>
    ) : loading ? <div className="loading-card"><span className="spinner" />正在读取活动优惠…</div>
    : items.length === 0 ? <section className="empty-card"><h2>还没有活动或优惠</h2><p>添加真实执行的促销活动，例如折扣、组合优惠或买赠。请明确适用商品、门槛、有效期和叠加规则。</p><button className="primary" onClick={() => { window.location.hash = "#store-editor:offer:new"; }}>添加第一项活动</button></section>
    : <section className="catalog-list">
      <div className="catalog-summary"><span>共 {total} 项活动</span><button className="text-button" onClick={() => void reload()}>刷新</button></div>
      {items.map((offer) => <article className="catalog-item" key={offer.id}>
        <div className="catalog-item-main"><div><h2>{offer.title}</h2><p>{({discount:"折扣优惠",bundle:"组合优惠",gift:"赠品 / 买赠",threshold:"满额优惠",other:"其他"} as Record<string,string>)[offer.offer_type] ?? offer.offer_type}</p></div>
          <span className={offer.fact_status === "confirmed" ? "status-chip confirmed" : "status-chip"}>{offer.fact_status === "confirmed" ? "事实已确认" : "待确认"}</span></div>
        <div className="catalog-meta"><span>{offer.starts_at ? new Date(offer.starts_at).toLocaleString() : "不限开始"}</span><span>{offer.ends_at ? new Date(offer.ends_at).toLocaleString() : "不限结束"}</span><span>{({draft:"草稿",active:"生效中",paused:"已暂停",expired:"已过期",archived:"已归档"} as Record<string,string>)[offer.status]}</span><span>V{offer.current_version}</span></div>
        <div className="catalog-actions"><button className="secondary" onClick={() => { window.location.hash = `#store-editor:offer:${offer.id}`; }}>编辑</button>
          {offer.fact_status !== "confirmed" && <button className="secondary" disabled={saving} onClick={() => void confirm(offer)}>确认事实</button>}
          <button className="secondary" disabled={saving} onClick={() => void remove(offer)}>删除</button></div>
      </article>)}
    </section>}
  </>;
}
