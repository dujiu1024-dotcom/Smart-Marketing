import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  confirmProductFacts,
  createProduct,
  getProducts,
  updateProduct,
  type Product,
  type ProductInput,
} from "./api";

interface ProductForm {
  name: string;
  category: string;
  sku: string;
  specification: string;
  unit: string;
  price_amount: string;
  currency: string;
  availability_status: ProductInput["availability_status"];
  inventory_quantity: string;
  selling_points: string;
  description: string;
  ingredients_or_materials: string;
  allergens: string;
  service_process: string;
  delivery_method: string;
}

const emptyForm: ProductForm = {
  name: "",
  category: "",
  sku: "",
  specification: "",
  unit: "",
  price_amount: "",
  currency: "",
  availability_status: "unknown",
  inventory_quantity: "",
  selling_points: "",
  description: "",
  ingredients_or_materials: "",
  allergens: "",
  service_process: "",
  delivery_method: "",
};

function fromProduct(product: Product): ProductForm {
  return {
    name: product.name,
    category: product.category ?? "",
    sku: product.sku ?? "",
    specification: product.specification ?? "",
    unit: product.unit ?? "",
    price_amount: product.price_amount ?? "",
    currency: product.currency ?? "",
    availability_status: product.availability_status,
    inventory_quantity: product.inventory_quantity ?? "",
    selling_points: (product.key_selling_points_json ?? []).join("、"),
    description: product.description ?? "",
    ingredients_or_materials: product.ingredients_or_materials ?? "",
    allergens: (product.allergens_and_restrictions_json ?? []).join("、"),
    service_process: product.service_process ?? "",
    delivery_method: product.delivery_method ?? "",
  };
}

function toProduct(form: ProductForm): ProductInput {
  const amount = form.price_amount.trim();
  const currency = form.currency.trim().toUpperCase();
  if (Boolean(amount) !== Boolean(currency)) {
    throw new Error("价格和币种必须同时填写；未知价格请留空。");
  }
  return {
    name: form.name.trim(),
    category: form.category.trim() || null,
    sku: form.sku.trim() || null,
    specification: form.specification.trim() || null,
    unit: form.unit.trim() || null,
    price_amount: amount || null,
    currency: amount ? currency : null,
    availability_status: form.availability_status,
    inventory_quantity: form.inventory_quantity.trim() || null,
    key_selling_points_json: form.selling_points.split(/[、,，]/).map((v) => v.trim()).filter(Boolean),
    description: form.description.trim() || null,
    ingredients_or_materials: form.ingredients_or_materials.trim() || null,
    allergens_and_restrictions_json: form.allergens.split(/[、,，]/).map((v) => v.trim()).filter(Boolean),
    service_process: form.service_process.trim() || null,
    delivery_method: form.delivery_method.trim() || null,
  };
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败，请稍后重试。";
}

function Field({ label, value, onChange, placeholder }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return <label className="field"><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

export default function ProductWorkspace({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Product | null>(null);
  const [form, setForm] = useState<ProductForm>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [route, setRoute] = useState(window.location.hash || "#store:products");

  const reload = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError("");
    try {
      const response = await getProducts(storeId);
      setItems(response.items);
      setTotal(response.total);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    const updateRoute = () => setRoute(window.location.hash || "#store:products");
    window.addEventListener("hashchange", updateRoute);
    void reload();
    return () => window.removeEventListener("hashchange", updateRoute);
  }, [reload]);

  useEffect(() => {
    if (!route.startsWith("#store-editor:product:")) return;
    const id = route.slice("#store-editor:product:".length);
    if (id === "new") {
      setSelected(null);
      setForm(emptyForm);
      return;
    }
    const product = items.find((item) => item.id === id);
    if (product) {
      setSelected(product);
      setForm(fromProduct(product));
    }
  }, [route, items]);

  function change<K extends keyof ProductForm>(key: K, value: ProductForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setNotice("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const input = toProduct(form);
      const saved = selected
        ? await updateProduct(storeId, selected, input)
        : await createProduct(storeId, input);
      setItems((current) => selected
        ? current.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...current]);
      setTotal((current) => selected ? current : current + 1);
      setSelected(saved);
      setForm(fromProduct(saved));
      setNotice(`商品资料已保存为 V${saved.current_version}，状态为待确认。`);
      window.location.hash = "#store:products";
    } catch (reason) {
      setError(message(reason));
    } finally {
      setSaving(false);
    }
  }

  async function confirmProduct(product: Product) {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const confirmed = await confirmProductFacts(storeId, product);
      setItems((current) => current.map((item) => item.id === confirmed.id ? confirmed : item));
      setSelected((current) => current?.id === confirmed.id ? confirmed : current);
      setNotice(`${confirmed.name} 的事实版本 V${confirmed.current_version} 已确认。`);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setSaving(false);
    }
  }

  const editing = route.startsWith("#store-editor:product:");
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">STORE CATALOG</p>
          <h1>商品与服务</h1>
          <p className="muted">维护商品价格、规格、供应状态和卖点。AI 只能将已确认事实作为确定信息引用。</p>
        </div>
        {!editing && <button className="primary" type="button" onClick={() => { window.location.hash = "#store-editor:product:new"; }}>新增商品 / 服务</button>}
        {editing && <button className="secondary" type="button" onClick={() => { window.location.hash = "#store:products"; }}>返回列表</button>}
      </div>
      {error && <div className="alert error" role="alert">{error}{error.includes("VERSION_CONFLICT") || error.includes("changed") ? <button className="text-button" onClick={() => void reload()}>重新加载</button> : null}</div>}
      {notice && <div className="alert success" role="status">{notice}</div>}
      {editing ? (
        <form className="profile-form" onSubmit={save}>
          <section className="form-card">
            <div className="section-title"><div><h2>{selected ? "编辑商品 / 服务" : "新增商品 / 服务"}</h2><p>商品价格采用明确币种；未知价格留空，不用 0 代替未知值。</p></div></div>
            <div className="form-grid">
              <Field label="商品 / 服务名称 *" value={form.name} onChange={(v) => change("name", v)} />
              <Field label="分类" value={form.category} onChange={(v) => change("category", v)} />
              <Field label="SKU / 编码" value={form.sku} onChange={(v) => change("sku", v)} />
              <Field label="规格" value={form.specification} onChange={(v) => change("specification", v)} />
              <Field label="计价单位" value={form.unit} onChange={(v) => change("unit", v)} placeholder="份、杯、次、小时…" />
              <div className="field"><span>供应状态</span><select value={form.availability_status} onChange={(e) => change("availability_status", e.target.value as ProductInput["availability_status"])}><option value="unknown">未知</option><option value="available">在售</option><option value="unavailable">停售</option><option value="seasonal">季节性供应</option><option value="limited">限量供应</option></select></div>
              <Field label="价格金额" value={form.price_amount} onChange={(v) => change("price_amount", v)} placeholder="例如 28.00；未知请留空" />
              <Field label="币种" value={form.currency} onChange={(v) => change("currency", v)} placeholder="CNY" />
              <Field label="库存 / 可用产能" value={form.inventory_quantity} onChange={(v) => change("inventory_quantity", v)} />
              <Field label="交付方式" value={form.delivery_method} onChange={(v) => change("delivery_method", v)} />
              <Field label="原料 / 材质" value={form.ingredients_or_materials} onChange={(v) => change("ingredients_or_materials", v)} />
              <Field label="过敏原 / 限制" value={form.allergens} onChange={(v) => change("allergens", v)} placeholder="用顿号分隔" />
              <div className="field span-2"><span>核心卖点</span><textarea rows={2} value={form.selling_points} onChange={(e) => change("selling_points", e.target.value)} placeholder="用顿号分隔，每条应为可核实事实" /></div>
              <div className="field span-2"><span>商品介绍</span><textarea rows={3} value={form.description} onChange={(e) => change("description", e.target.value)} /></div>
              <div className="field span-2"><span>服务流程</span><textarea rows={2} value={form.service_process} onChange={(e) => change("service_process", e.target.value)} /></div>
            </div>
          </section>
          <div className="form-footer">
            <p>{selected ? `当前版本 V${selected.current_version} · ${selected.fact_status === "confirmed" ? "已确认" : "待确认"}` : "创建后需要核对并确认经营事实。"}</p>
            <div className="form-actions">{selected && selected.fact_status !== "confirmed" && <button className="secondary" type="button" disabled={saving} onClick={() => void confirmProduct(selected)}>确认事实</button>}<button className="secondary" type="button" onClick={() => { window.location.hash = "#store:products"; }}>取消</button><button className="primary" type="submit" disabled={saving || !form.name.trim()}>{saving ? "保存中…" : "保存商品"}</button></div>
          </div>
        </form>
      ) : loading ? (
        <div className="loading-card"><span className="spinner" />正在读取商品资料…</div>
      ) : items.length === 0 ? (
        <section className="empty-card"><h2>还没有商品或服务资料</h2><p>添加门店实际销售的商品或服务，并维护价格、供应状态和可核实卖点。资料确认后，AI 才能将其作为确定事实用于营销内容。</p><button className="primary" type="button" onClick={() => { window.location.hash = "#store-editor:product:new"; }}>添加第一项资料</button></section>
      ) : (
        <section className="catalog-list">
          <div className="catalog-summary"><span>共 {total} 项资料</span><button className="text-button" onClick={() => void reload()}>刷新</button></div>
          {items.map((product) => (
            <article className="catalog-item" key={product.id}>
              <div className="catalog-item-main"><div><h2>{product.name}</h2><p>{[product.category, product.specification, product.sku].filter(Boolean).join(" · ") || "未填写分类与规格"}</p></div><span className={product.fact_status === "confirmed" ? "status-chip confirmed" : "status-chip"}>{product.fact_status === "confirmed" ? "事实已确认" : "待确认"}</span></div>
              <div className="catalog-meta"><span>{product.price_amount === null ? "价格未填写" : `${product.currency} ${product.price_amount}`}</span><span>{({ available: "在售", unavailable: "停售", seasonal: "季节供应", limited: "限量供应", unknown: "供应状态未知" })[product.availability_status]}</span><span>V{product.current_version}</span></div>
              <div className="catalog-actions"><button className="secondary" onClick={() => { window.location.hash = `#store-editor:product:${product.id}`; }}>编辑</button>{product.fact_status !== "confirmed" && <button className="secondary" disabled={saving} onClick={() => void confirmProduct(product)}>确认事实</button>}</div>
            </article>
          ))}
        </section>
      )}
    </>
  );
}
