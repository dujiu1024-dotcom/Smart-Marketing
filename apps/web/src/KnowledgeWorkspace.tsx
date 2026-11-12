import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { confirmKnowledgeFacts, createKnowledgeItem, deleteKnowledgeItem, getKnowledgeItems, updateKnowledgeItem, type KnowledgeItem, type KnowledgeItemInput } from "./api";

interface FormState {
  title: string;
  category: string;
  content_text: string;
  content_ref: string;
  content_hash: string;
  source_type: string;
  source_ref: string;
  effective_at: string;
  expires_at: string;
}
const empty: FormState = { title: "", category: "经营说明", content_text: "", content_ref: "", content_hash: "", source_type: "merchant_observation", source_ref: "", effective_at: "", expires_at: "" };
const message = (error: unknown) => error instanceof Error ? error.message : "请求失败，请稍后重试。";
function normalizeDate(value: string): string | null {
  const text = value.trim();
  if (!text) return null;
  if (!/(Z|[+-]\\d{2}:\\d{2})$/i.test(text)) throw new Error("生效时间和失效时间必须包含明确时区，例如 2026-11-12T09:00:00+08:00。");
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) throw new Error("时间格式无效，请使用 ISO 8601。");
  return date.toISOString();
}
function fromItem(item: KnowledgeItem): FormState {
  return { title: item.title, category: item.category, content_text: item.content_text ?? "", content_ref: item.content_ref ?? "", content_hash: item.content_hash ?? "", source_type: item.source_type ?? "", source_ref: item.source_ref ?? "", effective_at: item.effective_at ?? "", expires_at: item.expires_at ?? "" };
}
function toInput(form: FormState): KnowledgeItemInput {
  const contentText = form.content_text.trim();
  const contentRef = form.content_ref.trim();
  if (!contentText && !contentRef) throw new Error("知识内容和内容引用至少填写一项。");
  const effectiveAt = normalizeDate(form.effective_at);
  const expiresAt = normalizeDate(form.expires_at);
  if (effectiveAt && expiresAt && new Date(expiresAt) <= new Date(effectiveAt)) throw new Error("失效时间必须晚于生效时间。");
  return { title: form.title.trim(), category: form.category.trim(), content_text: contentText || null, content_ref: contentRef || null, content_hash: form.content_hash.trim() || null, source_type: form.source_type.trim() || null, source_ref: form.source_ref.trim() || null, effective_at: effectiveAt, expires_at: expiresAt };
}
function Field({ label, value, onChange, rows = 1, placeholder }: { label: string; value: string; onChange: (value: string) => void; rows?: number; placeholder?: string }) {
  return <label className={rows > 1 ? "field span-2" : "field"}><span>{label}</span>{rows > 1 ? <textarea rows={rows} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} /> : <input value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} />}</label>;
}
export default function KnowledgeWorkspace({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<KnowledgeItem | null>(null);
  const [form, setForm] = useState<FormState>(empty);
  const [route, setRoute] = useState(window.location.hash || "#store:knowledge");
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const createKey = useRef("");
  const editing = route.startsWith("#store-editor:knowledge:");
  const reload = useCallback(async () => {
    setLoading(true); setLoaded(false); setError("");
    try { const response = await getKnowledgeItems(storeId); setItems(response.items); setTotal(response.total); }
    catch (reason) { setError(message(reason)); }
    finally { setLoading(false); setLoaded(true); }
  }, [storeId]);
  useEffect(() => {
    const onRoute = () => setRoute(window.location.hash || "#store:knowledge");
    window.addEventListener("hashchange", onRoute);
    void reload();
    return () => window.removeEventListener("hashchange", onRoute);
  }, [reload]);
  useEffect(() => {
    if (!editing) { setDirty(false); return; }
    const id = route.slice("#store-editor:knowledge:".length);
    if (id === "new") {
      setSelected(null); setForm(empty); setDirty(false);
      const key = `store-operator.knowledge-create.${storeId}`;
      createKey.current = sessionStorage.getItem(key) ?? crypto.randomUUID();
      sessionStorage.setItem(key, createKey.current);
      return;
    }
    const found = items.find(item => item.id === id);
    if (found) { setSelected(found); setForm(fromItem(found)); setDirty(false); }
    else if (loaded) { setSelected(null); setError("知识记录不存在，或当前门店无权访问。"); }
  }, [editing, items, route, loaded, storeId]);
  function change<K extends keyof FormState>(key: K, value: FormState[K]) { setForm(current => ({ ...current, [key]: value })); setDirty(true); setNotice(""); }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setNotice("");
    try {
      const input = toInput(form);
      const saved = selected ? await updateKnowledgeItem(storeId, selected, input) : await createKnowledgeItem(storeId, input, createKey.current || crypto.randomUUID());
      setItems(current => selected ? current.map(item => item.id === saved.id ? saved : item) : [saved, ...current]);
      setTotal(value => selected ? value : value + 1);
      setSelected(saved); setForm(fromItem(saved)); setDirty(false);
      if (!selected) sessionStorage.removeItem(`store-operator.knowledge-create.${storeId}`);
      setNotice(`知识资料已保存为 V${saved.current_version}，请核对内容与来源后确认。`);
      window.location.hash = "#store:knowledge";
    } catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }
  async function confirm(item: KnowledgeItem) {
    if (dirty || saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const saved = await confirmKnowledgeFacts(storeId, item);
      setItems(current => current.map(value => value.id === saved.id ? saved : value));
      setSelected(saved); setForm(fromItem(saved)); setDirty(false);
      setNotice(`知识资料「${saved.title}」V${saved.current_version} 已确认。`);
    } catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }
  async function remove(item: KnowledgeItem) {
    if (!window.confirm(`确认删除知识资料「${item.title}」？`)) return;
    setSaving(true); setError("");
    try { await deleteKnowledgeItem(storeId, item); setItems(current => current.filter(value => value.id !== item.id)); setTotal(value => Math.max(0, value - 1)); setNotice("知识资料已删除。"); }
    catch (reason) { setError(message(reason)); }
    finally { setSaving(false); }
  }
  if (editing && !route.endsWith(":new") && loaded && !items.some(item => item.id === route.slice("#store-editor:knowledge:".length))) {
    return <section className="empty-card"><h2>无法读取知识资料</h2><p>{error || "知识记录不存在，或当前门店无权访问。"}</p><button className="secondary" type="button" onClick={() => { window.location.hash = "#store:knowledge"; }}>返回知识库</button></section>;
  }
  return <>
    <div className="page-heading"><div><p className="eyebrow">STORE KNOWLEDGE</p><h1>门店知识库</h1><p className="muted">沉淀门店已核实的经营说明、服务规则和品牌事实，为 AI 营销提供可追溯依据。</p></div>{!editing ? <button className="primary" type="button" onClick={() => { window.location.hash = "#store-editor:knowledge:new"; }}>新增知识</button> : <button className="secondary" type="button" onClick={() => { window.location.hash = "#store:knowledge"; }}>返回列表</button>}</div>
    {error && <div className="alert error" role="alert">{error}{error.includes("VERSION_CONFLICT") && <button className="text-button" onClick={() => void reload()}>重新加载</button>}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    {editing ? <form className="profile-form" onSubmit={save}>
      <section className="form-card"><div className="section-title"><div><h2>{selected ? "编辑知识资料" : "新增知识资料"}</h2><p>只记录可核实的门店事实；未确认的信息不得作为 AI 对外宣传依据。</p></div></div><div className="form-grid">
        <Field label="标题 *" value={form.title} onChange={value => change("title", value)} placeholder="例如：到店服务流程" />
        <Field label="分类 *" value={form.category} onChange={value => change("category", value)} placeholder="经营说明 / 服务规则 / 品牌事实" />
        <Field label="知识内容" value={form.content_text} onChange={value => change("content_text", value)} rows={6} placeholder="填写可核实的服务流程、门店规则或其他经营事实。" />
        <Field label="内容引用" value={form.content_ref} onChange={value => change("content_ref", value)} placeholder="内部文档引用或受控资料位置" />
        <Field label="内容 SHA-256" value={form.content_hash} onChange={value => change("content_hash", value)} placeholder="有原始文件或外部内容指纹时填写" />
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>来源与有效期</h2><p>保留来源信息和有效时间；时间必须包含时区，未知信息留空。</p></div></div><div className="form-grid">
        <Field label="来源类型" value={form.source_type} onChange={value => change("source_type", value)} placeholder="merchant_observation / official_document" />
        <Field label="来源说明 / 引用" value={form.source_ref} onChange={value => change("source_ref", value)} />
        <Field label="生效时间（含时区）" value={form.effective_at} onChange={value => change("effective_at", value)} placeholder="2026-11-12T09:00:00+08:00" />
        <Field label="失效时间（含时区）" value={form.expires_at} onChange={value => change("expires_at", value)} placeholder="2026-12-31T23:59:59+08:00" />
      </div></section>
      <div className="form-footer"><p>{selected ? `当前版本 V${selected.current_version} · ${selected.fact_status === "confirmed" ? "已确认" : "待确认"}` : "保存后需核对知识内容和来源，再确认事实。"}</p><div className="form-actions">
        {selected && selected.fact_status !== "confirmed" && <button className="secondary" type="button" disabled={saving || dirty} title={dirty ? "请先保存修改，再确认知识资料" : undefined} onClick={() => void confirm(selected)}>确认事实</button>}
        <button className="secondary" type="button" onClick={() => { window.location.hash = "#store:knowledge"; }}>取消</button>
        <button className="primary" type="submit" disabled={saving || !form.title.trim() || !form.category.trim() || (!form.content_text.trim() && !form.content_ref.trim())}>{saving ? "保存中…" : selected ? "保存知识" : "保存知识"}</button>
      </div></div>
    </form> : loading ? <div className="loading-card"><span className="spinner" />正在读取门店知识…</div>
    : items.length === 0 ? <section className="empty-card"><h2>知识库还是空的</h2><p>可以先记录服务流程、营业规则、产品知识或门店常见问题。没有可靠来源的信息不要作为已确认事实。</p><button className="primary" type="button" onClick={() => { window.location.hash = "#store-editor:knowledge:new"; }}>添加第一条知识</button></section>
    : <section className="catalog-list"><div className="catalog-summary"><span>共 {total} 条知识</span><button className="text-button" onClick={() => void reload()}>刷新</button></div>
      {items.map(item => <article className="catalog-item" key={item.id}><div className="catalog-item-main"><div><h2>{item.title}</h2><p>{item.category} · {item.source_type || "来源未记录"}</p></div><span className={item.fact_status === "confirmed" ? "status-chip confirmed" : "status-chip"}>{item.fact_status === "confirmed" ? "事实已确认" : "待确认"}</span></div>
        <p className="catalog-description">{item.content_text || item.content_ref}</p><div className="catalog-meta"><span>V{item.current_version}</span><span>{item.expires_at ? `失效：${new Date(item.expires_at).toLocaleString()}` : "未设置失效时间"}</span></div>
        <div className="catalog-actions"><button className="secondary" type="button" onClick={() => { window.location.hash = `#store-editor:knowledge:${item.id}`; }}>编辑</button>{item.fact_status !== "confirmed" && <button className="secondary" type="button" disabled={saving} onClick={() => void confirm(item)}>确认事实</button>}<button className="secondary" type="button" disabled={saving} onClick={() => void remove(item)}>删除</button></div>
      </article>)}
    </section>}
  </>;
}
