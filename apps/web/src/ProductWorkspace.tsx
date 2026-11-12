import { useCallback, useEffect, useState, type FormEvent } from "react";
import { confirmProductFacts, createProduct, deleteProduct, getProduct, listProducts, updateProduct, type Product, type ProductInput } from "./api";

interface FormState {
  name: string; category: string; sku: string; specification: string; unit: string;
  price: string; currency: string; availability: Product["availability_status"];
  inventory: string; sellingPoints: string; description: string; materials: string;
  allergens: string; serviceProcess: string; deliveryMethod: string;
}
const empty: FormState = {
  name: "", category: "", sku: "", specification: "", unit: "", price: "", currency: "CNY",
  availability: "unknown", inventory: "", sellingPoints: "", description: "", materials: "",
  allergens: "", serviceProcess: "", deliveryMethod: "",
};
const routeFromHash = () => window.location.hash.match(/^#store-editor:product:(.+)$/)?.[1] ?? "";
const lines = (value: string) => value.split("\n").map((x) => x.trim()).filter(Boolean);
const list = (value: string) => value.split(/[、,，]/).map((x) => x.trim()).filter(Boolean);
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : "请求失败，请稍后重试";

function fromProduct(p: Product): FormState {
  return {
    name: p.name, category: p.category ?? "", sku: p.sku ?? "", specification: p.specification ?? "",
    unit: p.unit ?? "", price: p.price_amount ?? "", currency: p.currency ?? "CNY",
    availability: p.availability_status, inventory: p.inventory_quantity ?? "",
    sellingPoints: (p.key_selling_points_json ?? []).join("\n"), description: p.description ?? "",
    materials: p.ingredients_or_materials ?? "", allergens: (p.allergens_and_restrictions_json ?? []).join("、"),
    serviceProcess: p.service_process ?? "", deliveryMethod: p.delivery_method ?? "",
  };
}
function toProductInput(f: FormState): ProductInput {
  const price = f.price.trim();
  return {
    name: f.name.trim(), category: f.category.trim() || null, sku: f.sku.trim() || null,
    specification: f.specification.trim() || null, unit: f.unit.trim() || null,
    price_amount: price || null, currency: price ? f.currency.trim().toUpperCase() : null,
    availability_status: f.availability, inventory_quantity: f.inventory.trim() || null,
    key_selling_points_json: lines(f.sellingPoints), description: f.description.trim() || null,
    ingredients_or_materials: f.materials.trim() || null, allergens_and_restrictions_json: list(f.allergens),
    service_process: f.serviceProcess.trim() || null, delivery_method: f.deliveryMethod.trim() || null,
  };
}
function Input({ label, value, onChange, type = "text", placeholder }: {
  label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string;
}) {
  return <label className="field"><span>{label}</span><input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} /></label>;
}

export default function ProductWorkspace({ storeId }: { storeId: string }) {
  const [route, setRoute] = useState(routeFromHash);
  const [items, setItems] = useState<Product[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [form, setForm] = useState<FormState>(empty);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [deletePending, setDeletePending] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems((await listProducts(storeId)).items); }
    catch (reason) { setError(errorText(reason)); }
    finally { setLoading(false); }
  }, [storeId]);

  useEffect(() => {
    const sync = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    if (!route) { void refresh(); return; }
    if (route === "new") { setProduct(null); setForm(empty); setDirty(false); setError(""); setNotice(""); return; }
    let active = true;
    setLoading(true); setError("");
    void getProduct(storeId, route).then((p) => {
      if (!active) return;
      setProduct(p); setForm(fromProduct(p)); setDirty(false);
    }).catch((reason: unknown) => {
      if (active) setError(errorText(reason));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [route, storeId, refresh]);

  const open = (id: string) => { window.location.hash = `#store-editor:product:${id}`; };
  const back = () => { window.location.hash = "#store:products"; };
  const change = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value })); setDirty(true); setNotice("");
  };

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.name.trim()) return;
    const price = form.price.trim();
    if (price && !/^\d{3}$/.test(form.currency.trim().toUpperCase())) {
      setError("填写价格时必须提供三位币种代码，例如 CNY。"); return;
    }
    setSaving(true); setError(""); setNotice("");
    try {
      const input = toProductInput(form);
      const saved = product ? await updateProduct(storeId, product, input) : await createProduct(storeId, input);
      setProduct(saved); setForm(fromProduct(saved)); setDirty(false);
      setNotice(`商品资料已保存为 V${saved.current_version}，经营事实状态为待确认。`);
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function confirmFacts() {
    if (!product || dirty || saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const confirmed = await confirmProductFacts(storeId, product);
      setProduct(confirmed); setForm(fromProduct(confirmed));
      setNotice(`商品事实 V${confirmed.current_version} 已确认。`);
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function remove() {
    if (!product || !deletePending) return;
    setSaving(true); setError("");
    try { await deleteProduct(storeId, product); back(); }
    catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); setDeletePending(false); }
  }

  if (!route) return <>
    <div className="page-heading"><div><p className="eyebrow">PRODUCTS & SERVICES</p><h1>商品与服务</h1><p className="muted">维护商品事实、价格、供应状态和服务信息，供营销内容准确引用。</p></div><button className="primary" type="button" onClick={() => open("new")}>新增商品 / 服务</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {loading ? <div className="loading-card"><span className="spinner" />正在读取商品资料…</div> : items.length === 0 ?
      <section className="empty-card"><h2>还没有商品或服务资料</h2><p>添加真实商品、服务、价格和供应信息，后续 AI 才能基于已确认事实生成营销内容。</p><button className="primary" type="button" onClick={() => open("new")}>添加第一项</button></section> :
      <section className="form-card"><div className="section-title"><div><h2>商品与服务清单</h2><p>共 {items.length} 项 · 最近创建优先</p></div></div><div className="product-list">
        {items.map((p) => <button className="product-row" type="button" key={p.id} onClick={() => open(p.id)}>
          <span className="product-main"><strong>{p.name}</strong><small>{[p.category, p.specification, p.sku].filter(Boolean).join(" · ") || "未填写分类与规格"}</small></span>
          <span className="product-price">{p.price_amount !== null && p.currency ? `${p.currency} ${p.price_amount}` : "价格未填写"}</span>
          <span className="product-meta">{({available:"在售",unavailable:"停售",seasonal:"季节供应",limited:"限量供应",unknown:"供应未知"})[p.availability_status]}</span>
          <span className={p.fact_status === "confirmed" ? "fact-status confirmed" : "fact-status pending"}>{p.fact_status === "confirmed" ? "已确认" : "待确认"}</span><span>›</span>
        </button>)}
      </div></section>}
  </>;

  if (loading) return <div className="loading-card"><span className="spinner" />正在读取商品资料…</div>;
  return <>
    <div className="page-heading"><div><p className="eyebrow">PRODUCT EDITOR</p><h1>{route === "new" ? "新增商品 / 服务" : "编辑商品 / 服务"}</h1><p className="muted">按真实情况填写。未知价格、库存或规格请留空，不用估算值代替。</p></div>{product && <div className="version-chip">V{product.current_version} · {product.fact_status === "confirmed" ? "已确认" : "待确认"}</div>}</div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    <form className="profile-form" onSubmit={save}>
      <section className="form-card"><div className="section-title"><div><h2>基础信息</h2><p>商品/服务名称、分类、规格与交付方式。</p></div></div><div className="form-grid">
        <Input label="商品 / 服务名称 *" value={form.name} onChange={(v) => change("name", v)} />
        <Input label="分类" value={form.category} onChange={(v) => change("category", v)} placeholder="饮品、套餐、美容服务…" />
        <Input label="SKU / 内部编码" value={form.sku} onChange={(v) => change("sku", v)} />
        <Input label="规格" value={form.specification} onChange={(v) => change("specification", v)} placeholder="500ml、大杯、60 分钟…" />
        <Input label="计价单位" value={form.unit} onChange={(v) => change("unit", v)} placeholder="份、杯、次、小时…" />
        <Input label="交付方式" value={form.deliveryMethod} onChange={(v) => change("deliveryMethod", v)} placeholder="堂食、自取、配送、到店服务…" />
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>价格与供应</h2><p>价格和币种必须同时填写；未知数据留空。</p></div></div><div className="form-grid">
        <Input label="价格" type="number" value={form.price} onChange={(v) => change("price", v)} placeholder="例如 28.00" />
        <Input label="币种代码" value={form.currency} onChange={(v) => change("currency", v)} placeholder="CNY" />
        <label className="field"><span>供应状态</span><select value={form.availability} onChange={(e) => change("availability", e.target.value as FormState["availability"])}><option value="unknown">未知</option><option value="available">在售</option><option value="unavailable">停售</option><option value="seasonal">季节供应</option><option value="limited">限量供应</option></select></label>
        <Input label="库存 / 可用数量" type="number" value={form.inventory} onChange={(v) => change("inventory", v)} placeholder="未知可留空" />
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>营销事实与服务说明</h2><p>影响 AI 对商品卖点和服务承诺的表达。</p></div></div><div className="form-grid">
        <label className="field span-2"><span>核心卖点（每行一项）</span><textarea rows={3} value={form.sellingPoints} onChange={(e) => change("sellingPoints", e.target.value)} /></label>
        <label className="field span-2"><span>商品 / 服务介绍</span><textarea rows={3} value={form.description} onChange={(e) => change("description", e.target.value)} /></label>
        <label className="field span-2"><span>原料 / 材质</span><textarea rows={2} value={form.materials} onChange={(e) => change("materials", e.target.value)} /></label>
        <Input label="过敏原 / 使用限制（顿号分隔）" value={form.allergens} onChange={(v) => change("allergens", v)} />
        <Input label="服务流程" value={form.serviceProcess} onChange={(v) => change("serviceProcess", v)} />
      </div></section>
      <div className="form-footer"><p>保存会生成新版本并重置事实确认状态。</p><div className="form-actions">
        <button className="secondary" type="button" onClick={back}>返回清单</button>
        {product && product.fact_status !== "confirmed" && <button className="secondary" type="button" onClick={() => void confirmFacts()} disabled={saving || dirty} title={dirty ? "请先保存修改，再确认商品事实" : undefined}>确认事实</button>}
        {product && <button className="secondary" type="button" onClick={() => setDeletePending(true)} disabled={saving}>删除</button>}
        <button className="primary" type="submit" disabled={saving || !form.name.trim()}>{saving ? "处理中…" : product ? "保存修改" : "创建商品"}</button>
      </div></div>
    </form>
    {deletePending && <div className="alert error" role="alert"><span>确认删除「{product?.name}」？系统会保留审计历史。</span><button className="text-button" type="button" onClick={() => setDeletePending(false)}>取消</button><button className="text-button" type="button" onClick={() => void remove()} disabled={saving}>确认删除</button></div>}
  </>;
}
