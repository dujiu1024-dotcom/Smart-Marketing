import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  confirmOfferFacts,
  createOffer,
  getOffers,
  updateOffer,
  type Offer,
  type OfferInput,
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
  status: Offer["status"];
}

const emptyForm: OfferForm = {
  title: "",
  offer_type: "discount",
  terms_json: "{}",
  eligibility_rules_json: "{}",
  starts_at: "",
  ends_at: "",
  stacking_policy: "",
  usage_limit: "",
  status: "draft",
};

function fromOffer(offer: Offer): OfferForm {
  return {
    title: offer.title,
    offer_type: offer.offer_type,
    terms_json: JSON.stringify(offer.terms_json, null, 2),
    eligibility_rules_json: JSON.stringify(offer.eligibility_rules_json, null, 2),
    starts_at: offer.starts_at ?? "",
    ends_at: offer.ends_at ?? "",
    stacking_policy: offer.stacking_policy ?? "",
    usage_limit: offer.usage_limit === null ? "" : String(offer.usage_limit),
    status: offer.status,
  };
}

function jsonObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label}必须是有效 JSON 对象。`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label}必须是 JSON 对象。`);
  }
  return parsed as Record<string, unknown>;
}

function utcTimestamp(value: string, label: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (!/(Z|[+-]\\d{2}:\\d{2})$/i.test(trimmed)) {
    throw new Error(`${label}必须包含时区，例如 2026-12-01T09:00:00+08:00。`);
  }
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) throw new Error(`${label}不是有效日期时间。`);
  return parsed.toISOString();
}

function toOffer(form: OfferForm): OfferInput {
  const usage = form.usage_limit.trim();
  if (usage && (!/^\\d+$/.test(usage) || Number(usage) < 1)) {
    throw new Error("使用次数上限必须是大于 0 的整数。");
  }
  const startsAt = utcTimestamp(form.starts_at, "开始时间");
  const endsAt = utcTimestamp(form.ends_at, "结束时间");
  if (startsAt && endsAt && new Date(endsAt) <= new Date(startsAt)) {
    throw new Error("结束时间必须晚于开始时间。");
  }
  return {
    title: form.title.trim(),
    offer_type: form.offer_type.trim(),
    terms_json: jsonObject(form.terms_json, "优惠规则"),
    eligibility_rules_json: jsonObject(form.eligibility_rules_json, "适用条件"),
    starts_at: startsAt,
    ends_at: endsAt,
    stacking_policy: form.stacking_policy.trim() || null,
    usage_limit: usage ? Number(usage) : null,
    status: form.status,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败，请稍后重试。";
}

function TextField({ label, value, onChange, placeholder }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return <label className="field"><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function prettyTime(value: string | null): string {
  if (!value) return "未设置";
  return new Date(value).toLocaleString();
}

export default function OfferWorkspace({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<Offer[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Offer | null>(null);
  const [form, setForm] = useState<OfferForm>(emptyForm);
  const [route, setRoute] = useState(window.location.hash || "#store:offers");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const editing = route.startsWith("#store-editor:offer:");

  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await getOffers(storeId);
      setItems(response.items);
      setTotal(response.total);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    const onRouteChange = () => setRoute(window.location.hash || "#store:offers");
    window.addEventListener("hashchange", onRouteChange);
    void reload();
    return () => window.removeEventListener("hashchange", onRouteChange);
  }, [reload]);

  useEffect(() => {
    if (!editing) return;
    const id = route.slice("#store-editor:offer:".length);
    if (id === "new") {
      setSelected(null);
      setForm(emptyForm);
      return;
    }
    const offer = items.find((item) => item.id === id);
    if (offer) {
      setSelected(offer);
      setForm(fromOffer(offer));
    }
  }, [editing, items, route]);

  function change<K extends keyof OfferForm>(key: K, value: OfferForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setNotice("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const input = toOffer(form);
      const saved = selected
        ? await updateOffer(storeId, selected, input)
        : await createOffer(storeId, input);
      setItems((current) => selected
        ? current.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...current]);
      setTotal((current) => selected ? current : current + 1);
      setSelected(saved);
      setForm(fromOffer(saved));
      setNotice(`活动已保存为 V${saved.current_version}，事实状态为待确认。`);
      window.location.hash = "#store:offers";
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  async function confirmFacts(offer: Offer) {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const confirmed = await confirmOfferFacts(storeId, offer);
      setItems((current) => current.map((item) => item.id === confirmed.id ? confirmed : item));
      setSelected((current) => current?.id === confirmed.id ? confirmed : current);
      setNotice(`${confirmed.title} 的活动规则 V${confirmed.current_version} 已确认。`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  const statusLabel: Record<Offer["status"], string> = {
    draft: "草稿",
    active: "进行中",
    paused: "已暂停",
    expired: "已结束",
    archived: "已归档",
  };

  return (
    <>
      <div className="page-heading">
        <div><p className="eyebrow">STORE OFFERS</p><h1>活动与优惠</h1><p className="muted">维护可执行的优惠机制、适用范围、有效期和使用限制，避免 AI 编造促销承诺。</p></div>
        {!editing && <button className="primary" type="button" onClick={() => { window.location.hash = "#store-editor:offer:new"; }}>新增活动</button>}
        {editing && <button className="secondary" type="button" onClick={() => { window.location.hash = "#store:offers"; }}>返回列表</button>}
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {notice && <div className="alert success" role="status">{notice}</div>}
      {editing ? (
        <form className="profile-form" onSubmit={save}>
          <section className="form-card">
            <div className="section-title"><div><h2>{selected ? "编辑活动" : "新增活动"}</h2><p>规则、适用条件和有效期均作为结构化经营事实保存。</p></div></div>
            <div className="form-grid">
              <TextField label="活动名称 *" value={form.title} onChange={(v) => change("title", v)} placeholder="例如：工作日下午茶双人套餐" />
              <TextField label="活动类型 *" value={form.offer_type} onChange={(v) => change("offer_type", v)} placeholder="discount / buy_x_get_y / bundle…" />
              <TextField label="开始时间（含时区）" value={form.starts_at} onChange={(v) => change("starts_at", v)} placeholder="2026-12-01T09:00:00+08:00" />
              <TextField label="结束时间（含时区）" value={form.ends_at} onChange={(v) => change("ends_at", v)} placeholder="2026-12-31T23:59:59+08:00" />
              <TextField label="叠加规则" value={form.stacking_policy} onChange={(v) => change("stacking_policy", v)} placeholder="not_stackable / stackable…" />
              <TextField label="使用次数上限" value={form.usage_limit} onChange={(v) => change("usage_limit", v)} placeholder="未知或不限次数请留空" />
              <div className="field"><span>活动状态</span><select value={form.status} onChange={(e) => change("status", e.target.value as Offer["status"])}><option value="draft">草稿</option><option value="active">进行中</option><option value="paused">已暂停</option><option value="expired">已结束</option><option value="archived">已归档</option></select></div>
              <div className="field span-2"><span>优惠规则（JSON 对象） *</span><textarea rows={5} value={form.terms_json} onChange={(e) => change("terms_json", e.target.value)} placeholder='例如：{"kind":"buy_x_get_y","buy_quantity":1,"gift_quantity":1,"gift_product_id":"..."}' /></div>
              <div className="field span-2"><span>适用条件（JSON 对象）</span><textarea rows={4} value={form.eligibility_rules_json} onChange={(e) => change("eligibility_rules_json", e.target.value)} placeholder='例如：{"product_ids":["..."],"channels":["douyin"],"member_only":false}' /></div>
            </div>
          </section>
          <div className="form-footer"><p>{selected ? `当前版本 V${selected.current_version} · ${selected.fact_status === "confirmed" ? "已确认" : "待确认"}` : "创建后需核对优惠规则、适用范围和时间，再确认事实。"}</p><div className="form-actions">{selected && selected.fact_status !== "confirmed" && <button className="secondary" type="button" disabled={saving} onClick={() => void confirmFacts(selected)}>确认事实</button>}<button className="secondary" type="button" onClick={() => { window.location.hash = "#store:offers"; }}>取消</button><button className="primary" type="submit" disabled={saving || !form.title.trim() || !form.offer_type.trim()}>{saving ? "保存中…" : "保存活动"}</button></div></div>
        </form>
      ) : loading ? (
        <div className="loading-card"><span className="spinner" />正在读取活动资料…</div>
      ) : items.length === 0 ? (
        <section className="empty-card"><h2>还没有活动与优惠</h2><p>记录真实可执行的活动机制、适用商品、有效期和使用限制。没有确认的活动规则不会作为确定事实供 AI 使用。</p><button className="primary" type="button" onClick={() => { window.location.hash = "#store-editor:offer:new"; }}>创建第一项活动</button></section>
      ) : (
        <section className="catalog-list"><div className="catalog-summary"><span>共 {total} 项活动</span><button className="text-button" onClick={() => void reload()}>刷新</button></div>
          {items.map((offer) => <article className="catalog-item" key={offer.id}>
            <div className="catalog-item-main"><div><h2>{offer.title}</h2><p>{offer.offer_type} · {statusLabel[offer.status]}</p></div><span className={offer.fact_status === "confirmed" ? "status-chip confirmed" : "status-chip"}>{offer.fact_status === "confirmed" ? "事实已确认" : "待确认"}</span></div>
            <div className="catalog-meta"><span>开始：{prettyTime(offer.starts_at)}</span><span>结束：{prettyTime(offer.ends_at)}</span><span>V{offer.current_version}</span></div>
            <div className="catalog-actions"><button className="secondary" onClick={() => { window.location.hash = `#store-editor:offer:${offer.id}`; }}>编辑</button>{offer.fact_status !== "confirmed" && <button className="secondary" disabled={saving} onClick={() => void confirmFacts(offer)}>确认事实</button>}</div>
          </article>)}
        </section>
      )}
    </>
  );
}
