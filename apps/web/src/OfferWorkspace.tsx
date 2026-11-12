import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  confirmOfferFacts, createOffer, getOffer, getProducts, listOffers, updateOffer,
  type Offer, type OfferInput, type Product,
} from "./api";

type OfferType = "discount_percent" | "discount_amount" | "fixed_price" | "buy_x_get_y" | "gift" | "threshold_discount";
interface OfferForm {
  title: string;
  offer_type: OfferType;
  percent: string;
  amount: string;
  currency: string;
  buy_quantity: string;
  get_quantity: string;
  gift_description: string;
  minimum_spend: string;
  discount_type: "amount" | "percent";
  discount_value: string;
  eligible_product_ids: string[];
  eligibility_rules_json: string;
  starts_at: string;
  ends_at: string;
  stacking_policy: string;
  usage_limit: string;
  status: Offer["status"];
}
const emptyForm: OfferForm = {
  title: "", offer_type: "discount_percent", percent: "", amount: "", currency: "",
  buy_quantity: "1", get_quantity: "1", gift_description: "", minimum_spend: "",
  discount_type: "amount", discount_value: "", eligible_product_ids: [],
  eligibility_rules_json: "{}", starts_at: "", ends_at: "", stacking_policy: "not_stackable",
  usage_limit: "", status: "draft",
};
const readRoute = () => window.location.hash.match(/^#store-editor:offer:(.+)$/)?.[1] ?? "";
const message = (reason: unknown) => reason instanceof Error ? reason.message : "请求失败，请稍后重试";
const asText = (value: unknown) => value === null || value === undefined ? "" : String(value);

function fromOffer(offer: Offer): OfferForm {
  const terms = offer.terms_json;
  const ids = terms.eligible_product_ids;
  return {
    ...emptyForm,
    title: offer.title,
    offer_type: offer.offer_type as OfferType,
    percent: asText(terms.percent),
    amount: asText(terms.amount),
    currency: asText(terms.currency),
    buy_quantity: asText(terms.buy_quantity || 1),
    get_quantity: asText(terms.get_quantity || 1),
    gift_description: asText(terms.gift_description),
    minimum_spend: asText(terms.minimum_spend),
    discount_type: terms.discount_type === "percent" ? "percent" : "amount",
    discount_value: asText(terms.discount_value),
    eligible_product_ids: Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [],
    eligibility_rules_json: JSON.stringify(offer.eligibility_rules_json ?? {}, null, 2),
    starts_at: offer.starts_at ?? "",
    ends_at: offer.ends_at ?? "",
    stacking_policy: offer.stacking_policy ?? "not_stackable",
    usage_limit: offer.usage_limit === null ? "" : String(offer.usage_limit),
    status: offer.status,
  };
}

function zonedTimestamp(value: string, label: string): string | null {
  const normalized = value.trim();
  if (!normalized) return null;
  if (!/(Z|[+-]\d{2}:\d{2})$/i.test(normalized)) {
    throw new Error(`${label} 必须包含时区，例如 2026-12-01T09:00:00+08:00。`);
  }
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) throw new Error(`${label} 不是有效的 ISO 8601 时间。`);
  return parsed.toISOString();
}

function toOfferInput(form: OfferForm): OfferInput {
  let eligibility: unknown;
  try { eligibility = JSON.parse(form.eligibility_rules_json.trim() || "{}"); }
  catch { throw new Error("适用条件必须是有效 JSON 对象。"); }
  if (!eligibility || typeof eligibility !== "object" || Array.isArray(eligibility)) {
    throw new Error("适用条件必须是 JSON 对象。");
  }
  let terms: Record<string, unknown>;
  if (form.offer_type === "discount_percent") {
    const percent = Number(form.percent);
    if (!Number.isFinite(percent) || percent <= 0 || percent > 100) throw new Error("折扣比例必须大于 0 且不超过 100。");
    terms = { percent };
  } else if (form.offer_type === "discount_amount" || form.offer_type === "fixed_price") {
    const amount = Number(form.amount);
    if (!Number.isFinite(amount) || amount <= 0 || !/^[A-Z]{3}$/.test(form.currency.trim().toUpperCase())) {
      throw new Error("金额必须为非负数，并填写三位币种代码。");
    }
    terms = { amount: form.amount.trim(), currency: form.currency.trim().toUpperCase() };
  } else if (form.offer_type === "buy_x_get_y") {
    const buy = Number(form.buy_quantity), get = Number(form.get_quantity);
    if (!Number.isInteger(buy) || buy < 1 || !Number.isInteger(get) || get < 1) throw new Error("买入数量和赠送数量必须为正整数。");
    if (!form.eligible_product_ids.length) throw new Error("买赠活动至少选择一项适用商品。");
    terms = { buy_quantity: buy, get_quantity: get, eligible_product_ids: form.eligible_product_ids };
  } else if (form.offer_type === "gift") {
    if (!form.gift_description.trim() || !form.eligible_product_ids.length) throw new Error("赠品说明和适用商品均为必填。");
    terms = { gift_description: form.gift_description.trim(), eligible_product_ids: form.eligible_product_ids };
  } else {
    const minimum = Number(form.minimum_spend), value = Number(form.discount_value);
    if (!Number.isFinite(minimum) || minimum <= 0 || !Number.isFinite(value) || value <= 0) throw new Error("满减门槛和优惠值必须大于 0。");
    if (!/^[A-Z]{3}$/.test(form.currency.trim().toUpperCase())) throw new Error("请填写三位币种代码。");
    if (form.discount_type === "percent" && value > 100) throw new Error("折扣比例不能超过 100。");
    terms = { minimum_spend: form.minimum_spend.trim(), currency: form.currency.trim().toUpperCase(), discount_type: form.discount_type, discount_value: form.discount_value.trim() };
  }
  const start = zonedTimestamp(form.starts_at, "开始时间");
  const end = zonedTimestamp(form.ends_at, "结束时间");
  if (start && end && Date.parse(end) <= Date.parse(start)) throw new Error("结束时间必须晚于开始时间。");
  const usage = form.usage_limit.trim();
  if (usage && (!Number.isInteger(Number(usage)) || Number(usage) < 1)) throw new Error("使用次数上限必须为正整数。");
  return {
    title: form.title.trim(),
    offer_type: form.offer_type,
    terms_json: terms,
    eligibility_rules_json: eligibility as Record<string, unknown>,
    starts_at: start,
    ends_at: end,
    stacking_policy: form.stacking_policy.trim() || null,
    usage_limit: usage ? Number(usage) : null,
    status: form.status,
  };
}

function Field({ label, value, onChange, type = "text", placeholder }: {
  label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string;
}) {
  return <label className="field"><span>{label}</span><input type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

export default function OfferWorkspace({ storeId }: { storeId: string }) {
  const [route, setRoute] = useState(readRoute);
  const [items, setItems] = useState<Offer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [form, setForm] = useState<OfferForm>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const createKey = useRef("");

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const result = await listOffers(storeId);
      setItems(result.items);
    } catch (reason) { setError(message(reason)); }
    finally { setLoading(false); }
  }, [storeId]);

  useEffect(() => {
    const sync = () => setRoute(readRoute());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    if (!route) {
      sessionStorage.removeItem(`store-operator.offer-create.${storeId}`);
      void refresh();
      return;
    }
    if (route === "new") {
      setLoading(false); setOffer(null); setForm(emptyForm); setDirty(false); setError(""); setNotice("");
      const key = `store-operator.offer-create.${storeId}`;
      createKey.current = sessionStorage.getItem(key) ?? crypto.randomUUID();
      sessionStorage.setItem(key, createKey.current);
      void getProducts(storeId).then((result) => setProducts(result.items)).catch((reason) => setError(message(reason)));
      return;
    }
    let active = true;
    setLoading(true); setError(""); setOffer(null); setForm(emptyForm); setDirty(false);
    void Promise.all([getOffer(storeId, route), getProducts(storeId)]).then(([value, productResult]) => {
      if (!active) return;
      setOffer(value); setForm(fromOffer(value)); setProducts(productResult.items);
    }).catch((reason: unknown) => {
      if (active) setError(message(reason));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [route, storeId, refresh]);

  const open = (id: string) => { window.location.hash = `#store-editor:offer:${id}`; };
  const back = () => { window.location.hash = "#store:offers"; };
  const change = <K extends keyof OfferForm>(key: K, value: OfferForm[K]) => {
    setForm((current) => ({ ...current, [key]: value })); setDirty(true); setNotice("");
  };
  const toggleProduct = (id: string, checked: boolean) => {
    setForm((current) => ({ ...current, eligible_product_ids: checked ? [...current.eligible_product_ids, id] : current.eligible_product_ids.filter((value) => value !== id) }));
    setDirty(true);
  };

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.title.trim()) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const input = toOfferInput(form);
      const saved = offer ? await updateOffer(storeId, offer, input) : await createOffer(storeId, input, createKey.current || crypto.randomUUID());
      setOffer(saved); setForm(fromOffer(saved)); setDirty(false);
      if (!offer) {
        sessionStorage.removeItem(`store-operator.offer-create.${storeId}`);
        window.location.hash = `#store-editor:offer:${saved.id}`;
      }
      setNotice(`活动优惠已保存为 V${saved.current_version}，请核对规则并确认事实。`);
    } catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }

  async function confirmFacts() {
    if (!offer || dirty || saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const confirmed = await confirmOfferFacts(storeId, offer);
      setOffer(confirmed); setForm(fromOffer(confirmed));
      setNotice(`活动优惠 V${confirmed.current_version} 已确认。`);
    } catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }


  if (!route) return <>
    <div className="page-heading"><div><p className="eyebrow">OFFERS & PROMOTIONS</p><h1>活动与优惠</h1><p className="muted">维护真实优惠机制、适用商品、限制和有效期；未知条件不自动补全。</p></div><button className="primary" type="button" onClick={() => open("new")}>新增活动</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {loading ? <div className="loading-card"><span className="spinner" />正在读取活动优惠…</div> : items.length === 0 ?
      <section className="empty-card"><h2>还没有活动或优惠</h2><p>添加真实活动规则和适用范围，保存后由门店成员核对并确认。</p><button className="primary" type="button" onClick={() => open("new")}>创建第一项活动</button></section> :
      <section className="form-card"><div className="section-title"><div><h2>活动与优惠清单</h2><p>共 {items.length} 项</p></div></div><div className="product-list">
        {items.map((item) => <button className="product-row" type="button" key={item.id} onClick={() => open(item.id)}>
          <span className="product-main"><strong>{item.title}</strong><small>{item.offer_type} · {item.starts_at ? item.starts_at : "未设开始时间"} – {item.ends_at ? item.ends_at : "未设结束时间"}</small></span>
          <span className="product-meta">{({draft:"草稿",active:"生效中",paused:"已暂停",expired:"已过期",archived:"已归档"})[item.status]}</span>
          <span className={item.fact_status === "confirmed" ? "fact-status confirmed" : "fact-status pending"}>{item.fact_status === "confirmed" ? "已确认" : "待确认"}</span><span>›</span>
        </button>)}
      </div></section>}
  </>;

  if (loading) return <div className="loading-card"><span className="spinner" />正在读取活动优惠…</div>;
  if (route !== "new" && !offer) return <section className="empty-card"><h2>无法读取该活动</h2><p>{error || "活动可能已删除，或当前门店无权访问。"}</p><button className="secondary" type="button" onClick={back}>返回活动清单</button></section>;

  return <>
    <div className="page-heading"><div><p className="eyebrow">OFFER EDITOR</p><h1>{route === "new" ? "新增活动与优惠" : "编辑活动与优惠"}</h1><p className="muted">规则以结构化字段保存；时间必须带明确时区偏移，避免跨地区误解有效期。</p></div>{offer && <div className="version-chip">V{offer.current_version} · {offer.fact_status === "confirmed" ? "已确认" : "待确认"}</div>}</div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    <form className="profile-form" onSubmit={save}>
      <section className="form-card"><div className="section-title"><div><h2>活动基本信息</h2><p>活动名称、优惠类型和当前状态。</p></div></div><div className="form-grid">
        <Field label="活动名称 *" value={form.title} onChange={(v) => change("title", v)} />
        <label className="field"><span>优惠类型</span><select value={form.offer_type} onChange={(e) => change("offer_type", e.target.value as OfferType)}><option value="discount_percent">折扣比例</option><option value="discount_amount">立减金额</option><option value="fixed_price">优惠固定价</option><option value="buy_x_get_y">买 X 赠 Y</option><option value="gift">赠品活动</option><option value="threshold_discount">满额优惠</option></select></label>
        <label className="field"><span>活动状态</span><select value={form.status} onChange={(e) => change("status", e.target.value as Offer["status"])}><option value="draft">草稿</option><option value="active">生效中</option><option value="paused">已暂停</option><option value="expired">已过期</option><option value="archived">已归档</option></select></label>
        <label className="field"><span>叠加政策</span><select value={form.stacking_policy} onChange={(e) => change("stacking_policy", e.target.value)}><option value="not_stackable">不可叠加</option><option value="stackable">允许叠加</option><option value="conditional">按规则叠加</option></select></label>
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>优惠规则</h2><p>根据优惠类型填写对应规则，不使用自由文本替代关键数值。</p></div></div><div className="form-grid">
        {form.offer_type === "discount_percent" && <Field label="折扣比例（百分比）" type="number" value={form.percent} onChange={(v) => change("percent", v)} placeholder="例如 80 表示八折" />}
        {(form.offer_type === "discount_amount" || form.offer_type === "fixed_price") && <><Field label={form.offer_type === "fixed_price" ? "优惠固定价" : "立减金额"} type="number" value={form.amount} onChange={(v) => change("amount", v)} /><Field label="币种代码" value={form.currency} onChange={(v) => change("currency", v)} placeholder="CNY" /></>}
        {form.offer_type === "buy_x_get_y" && <><Field label="买入数量" type="number" value={form.buy_quantity} onChange={(v) => change("buy_quantity", v)} /><Field label="赠送数量" type="number" value={form.get_quantity} onChange={(v) => change("get_quantity", v)} /></>}
        {form.offer_type === "gift" && <Field label="赠品说明" value={form.gift_description} onChange={(v) => change("gift_description", v)} />}
        {form.offer_type === "threshold_discount" && <><Field label="最低消费金额" type="number" value={form.minimum_spend} onChange={(v) => change("minimum_spend", v)} /><Field label="币种代码" value={form.currency} onChange={(v) => change("currency", v)} placeholder="CNY" /><label className="field"><span>优惠方式</span><select value={form.discount_type} onChange={(e) => change("discount_type", e.target.value as OfferForm["discount_type"])}><option value="amount">减免金额</option><option value="percent">折扣比例</option></select></label><Field label="优惠值" type="number" value={form.discount_value} onChange={(v) => change("discount_value", v)} /></>}
      </div>
      {(form.offer_type === "buy_x_get_y" || form.offer_type === "gift") && <div className="field product-check-list"><span>适用商品</span>{products.length ? products.map((p) => <label key={p.id} className="product-check"><input type="checkbox" checked={form.eligible_product_ids.includes(p.id)} onChange={(e) => toggleProduct(p.id, e.target.checked)} /><span>{p.name}</span></label>) : <small>当前门店尚无商品资料，请先维护商品与服务。</small>}</div>}
      </section>
      <section className="form-card"><div className="section-title"><div><h2>适用条件与有效期</h2><p>有效时间使用 ISO 8601 并显式带时区，例如 +08:00。</p></div></div><div className="form-grid">
        <Field label="开始时间（含时区）" value={form.starts_at} onChange={(v) => change("starts_at", v)} placeholder="2026-12-01T09:00:00+08:00" />
        <Field label="结束时间（含时区）" value={form.ends_at} onChange={(v) => change("ends_at", v)} placeholder="2026-12-31T23:59:59+08:00" />
        <Field label="使用次数上限" type="number" value={form.usage_limit} onChange={(v) => change("usage_limit", v)} placeholder="不限制可留空" />
        <label className="field span-2"><span>其他适用条件（JSON 对象）</span><textarea rows={3} value={form.eligibility_rules_json} onChange={(e) => change("eligibility_rules_json", e.target.value)} placeholder='例如 {"new_customer":true}' /></label>
      </div></section>
      <div className="form-footer"><p>保存后生成新版本并重置事实确认状态。</p><div className="form-actions">
        <button className="secondary" type="button" onClick={back}>返回清单</button>
        {offer && offer.fact_status !== "confirmed" && <button className="secondary" type="button" onClick={() => void confirmFacts()} disabled={saving || dirty} title={dirty ? "请先保存修改，再确认活动事实" : undefined}>确认事实</button>}
        <button className="primary" type="submit" disabled={saving || !form.title.trim()}>{saving ? "处理中…" : offer ? "保存修改" : "创建活动"}</button>
      </div></div>
    </form>
  </>;
}
