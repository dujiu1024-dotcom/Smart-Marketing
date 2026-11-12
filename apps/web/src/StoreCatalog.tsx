import { useEffect, useState, type FormEvent } from "react";
import {
  confirmStoreRecordFacts, createOffer, createProduct, deleteOffer, deleteProduct, getOffers, getProducts,
  updateOffer, updateProduct, type OfferInput, type OfferRecord, type ProductInput, type ProductRecord,
} from "./api";

const emptyProduct: ProductInput = {
  name: "", category: "", sku: "", specification: "", unit: "份", price_amount: null, currency: null,
  availability_status: "unknown", inventory_quantity: null, key_selling_points_json: [], description: "",
  ingredients_or_materials: "", allergens_and_restrictions_json: [], service_process: "", delivery_method: "",
};
const emptyOffer: OfferInput = {
  title: "", offer_type: "discount", terms_json: {}, eligibility_rules_json: {},
  starts_at: null, ends_at: null, stacking_policy: "not_stackable", usage_limit: null, status: "draft",
};
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : "请求失败，请稍后重试";

export default function StoreCatalog({ storeId, initialTab }: { storeId: string; initialTab: "products" | "offers" }) {
  const [tab, setTab] = useState(initialTab);
  const [products, setProducts] = useState<ProductRecord[]>([]);
  const [offers, setOffers] = useState<OfferRecord[]>([]);
  const [product, setProduct] = useState<ProductRecord | null>(null);
  const [offer, setOffer] = useState<OfferRecord | null>(null);
  const [productForm, setProductForm] = useState<ProductInput>(emptyProduct);
  const [offerForm, setOfferForm] = useState<OfferInput>(emptyOffer);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function reload() {
    setBusy(true); setError("");
    try {
      const [p, o] = await Promise.all([getProducts(storeId), getOffers(storeId)]);
      setProducts(p.items); setOffers(o.items);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  useEffect(() => { void reload(); }, [storeId]);

  function startProduct(item?: ProductRecord) {
    setProduct(item ?? null);
    setProductForm(item ? {
      name: item.name, category: item.category ?? "", sku: item.sku ?? "", specification: item.specification ?? "",
      unit: item.unit ?? "", price_amount: item.price_amount, currency: item.currency,
      availability_status: item.availability_status, inventory_quantity: item.inventory_quantity,
      key_selling_points_json: item.key_selling_points_json ?? [], description: item.description ?? "",
      ingredients_or_materials: item.ingredients_or_materials ?? "",
      allergens_and_restrictions_json: item.allergens_and_restrictions_json ?? [],
      service_process: item.service_process ?? "", delivery_method: item.delivery_method ?? "",
    } : emptyProduct);
    setEditing(true); setError(""); setNotice("");
  }
  function startOffer(item?: OfferRecord) {
    setOffer(item ?? null);
    setOfferForm(item ? {
      title: item.title, offer_type: item.offer_type, terms_json: item.terms_json,
      eligibility_rules_json: item.eligibility_rules_json, starts_at: item.starts_at, ends_at: item.ends_at,
      stacking_policy: item.stacking_policy, usage_limit: item.usage_limit, status: item.status,
    } : emptyOffer);
    setEditing(true); setError(""); setNotice("");
  }
  async function saveProduct(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const payload = { ...productForm, name: productForm.name.trim(),
        price_amount: productForm.price_amount === "" ? null : productForm.price_amount,
        inventory_quantity: productForm.inventory_quantity === "" ? null : productForm.inventory_quantity };
      if ((payload.price_amount === null) !== (payload.currency === null || payload.currency === "")) {
        throw new Error("填写售价时必须同时提供币种；不填写售价则清空币种");
      }
      if (product) await updateProduct(storeId, product, payload);
      else await createProduct(storeId, payload);
      setEditing(false); setNotice("商品 / 服务资料已保存。请在业务使用前核对事实状态。"); await reload();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  async function saveOffer(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const payload = { ...offerForm, title: offerForm.title.trim(),
        starts_at: offerForm.starts_at || null, ends_at: offerForm.ends_at || null,
        usage_limit: offerForm.usage_limit === 0 ? null : offerForm.usage_limit };
      if (offer) await updateOffer(storeId, offer, payload);
      else await createOffer(storeId, payload);
      setEditing(false); setNotice("活动优惠已保存。请核对规则、适用条件和有效期。"); await reload();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  async function confirmProduct(item: ProductRecord) {
    setBusy(true); setError("");
    try { await confirmStoreRecordFacts(storeId, "products", item); setNotice("商品 / 服务事实已确认。"); await reload(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  }
  async function confirmOffer(item: OfferRecord) {
    setBusy(true); setError("");
    try { await confirmStoreRecordFacts(storeId, "offers", item); setNotice("活动优惠事实已确认。"); await reload(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  }
  async function removeProduct(item: ProductRecord) {
    if (!window.confirm(`确认删除「${item.name}」？`)) return;
    setBusy(true); setError("");
    try { await deleteProduct(storeId, item); setNotice("商品 / 服务已删除。"); await reload(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  }
  async function removeOffer(item: OfferRecord) {
    if (!window.confirm(`确认删除活动「${item.title}」？`)) return;
    setBusy(true); setError("");
    try { await deleteOffer(storeId, item); setNotice("活动优惠已删除。"); await reload(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  }

  const input = (label: string, value: string | number | null, onChange: (v: string) => void, type = "text") =>
    <label className="field"><span>{label}</span><input type={type} value={value ?? ""} onChange={e => onChange(e.target.value)} /></label>;
  return <section>
    <div className="page-heading"><div><p className="eyebrow">STORE KNOWLEDGE</p>
      <h1>{tab === "products" ? "商品与服务" : "活动与优惠"}</h1>
      <p className="muted">资料直接读写当前门店服务端记录；修改使用版本控制，不写入浏览器演示数据。</p></div>
      <div className="form-actions"><button className={tab === "products" ? "primary" : "secondary"} onClick={() => { setTab("products"); setEditing(false); }}>商品与服务</button>
      <button className={tab === "offers" ? "primary" : "secondary"} onClick={() => { setTab("offers"); setEditing(false); }}>活动与优惠</button></div>
    </div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    {editing && tab === "products" && <form className="form-card profile-form" onSubmit={saveProduct}>
      <div className="section-title"><h2>{product ? "编辑商品 / 服务" : "新增商品 / 服务"}</h2></div>
      <div className="form-grid">
        {input("名称 *", productForm.name, v => setProductForm(p => ({...p,name:v})))}
        {input("分类", productForm.category, v => setProductForm(p => ({...p,category:v})))}
        {input("SKU", productForm.sku, v => setProductForm(p => ({...p,sku:v})))}
        {input("规格", productForm.specification, v => setProductForm(p => ({...p,specification:v})))}
        {input("售价", productForm.price_amount, v => setProductForm(p => ({...p,price_amount:v})), "number")}
        {input("币种", productForm.currency, v => setProductForm(p => ({...p,currency:v.toUpperCase()})))}
        {input("单位", productForm.unit, v => setProductForm(p => ({...p,unit:v})))}
        {input("库存 / 可服务数量", productForm.inventory_quantity, v => setProductForm(p => ({...p,inventory_quantity:v})), "number")}
        <label className="field"><span>可售状态</span><select value={productForm.availability_status} onChange={e => setProductForm(p => ({...p,availability_status:e.target.value as ProductInput["availability_status"]}))}>
          {["available","unavailable","seasonal","limited","unknown"].map(v => <option key={v} value={v}>{({available:"可售",unavailable:"停售",seasonal:"季节性",limited:"限量",unknown:"未知"} as Record<string,string>)[v]}</option>)}</select></label>
        <label className="field span-2"><span>商品 / 服务说明</span><textarea rows={3} value={productForm.description ?? ""} onChange={e => setProductForm(p => ({...p,description:e.target.value}))}/></label>
        <label className="field span-2"><span>卖点（每行一项）</span><textarea rows={2} value={(productForm.key_selling_points_json ?? []).join("\n")} onChange={e => setProductForm(p => ({...p,key_selling_points_json:e.target.value.split("\n").map(x=>x.trim()).filter(Boolean)}))}/></label>
        {input("原料 / 材质", productForm.ingredients_or_materials, v => setProductForm(p => ({...p,ingredients_or_materials:v})))}
        {input("过敏原 / 限制（逗号分隔）", (productForm.allergens_and_restrictions_json ?? []).join("、"), v => setProductForm(p => ({...p,allergens_and_restrictions_json:v.split(/[、,，]/).map(x=>x.trim()).filter(Boolean)})))}
        {input("服务流程", productForm.service_process, v => setProductForm(p => ({...p,service_process:v})))}
        {input("交付方式", productForm.delivery_method, v => setProductForm(p => ({...p,delivery_method:v})))}
      </div><div className="form-actions"><button className="secondary" type="button" onClick={() => setEditing(false)}>取消</button>
      <button className="primary" disabled={busy || !productForm.name.trim()}>{busy ? "保存中…" : "保存商品资料"}</button></div>
    </form>}
    {editing && tab === "offers" && <form className="form-card profile-form" onSubmit={saveOffer}>
      <div className="section-title"><h2>{offer ? "编辑活动优惠" : "新增活动优惠"}</h2></div><div className="form-grid">
        {input("活动名称 *", offerForm.title, v => setOfferForm(p => ({...p,title:v})))}
        <label className="field"><span>活动类型</span><select value={offerForm.offer_type} onChange={e => setOfferForm(p => ({...p,offer_type:e.target.value}))}>
          {["discount","bundle","gift","threshold","other"].map(v => <option key={v} value={v}>{({discount:"折扣",bundle:"组合优惠",gift:"赠品",threshold:"满额优惠",other:"其他"} as Record<string,string>)[v]}</option>)}</select></label>
        {input("开始时间", offerForm.starts_at, v => setOfferForm(p => ({...p,starts_at:v})), "datetime-local")}
        {input("结束时间", offerForm.ends_at, v => setOfferForm(p => ({...p,ends_at:v})), "datetime-local")}
        {input("使用次数上限", offerForm.usage_limit, v => setOfferForm(p => ({...p,usage_limit:v ? Number(v) : null})), "number")}
        <label className="field"><span>状态</span><select value={offerForm.status} onChange={e => setOfferForm(p => ({...p,status:e.target.value as OfferInput["status"]}))}>
          {["draft","active","paused","expired","archived"].map(v => <option key={v} value={v}>{({draft:"草稿",active:"生效中",paused:"已暂停",expired:"已过期",archived:"已归档"} as Record<string,string>)[v]}</option>)}</select></label>
        <label className="field span-2"><span>优惠规则（JSON 对象）</span><textarea rows={3} value={JSON.stringify(offerForm.terms_json,null,2)} onChange={e => {try {setOfferForm(p=>({...p,terms_json:JSON.parse(e.target.value)}));} catch { /* retain last valid object */ }}} /></label>
        <label className="field span-2"><span>适用条件（JSON 对象）</span><textarea rows={3} value={JSON.stringify(offerForm.eligibility_rules_json,null,2)} onChange={e => {try {setOfferForm(p=>({...p,eligibility_rules_json:JSON.parse(e.target.value)}));} catch { /* retain last valid object */ }}} /></label>
        {input("叠加策略", offerForm.stacking_policy, v => setOfferForm(p => ({...p,stacking_policy:v})))}
      </div><div className="form-actions"><button className="secondary" type="button" onClick={() => setEditing(false)}>取消</button>
      <button className="primary" disabled={busy || !offerForm.title.trim()}>{busy ? "保存中…" : "保存活动优惠"}</button></div>
    </form>}
    {!editing && tab === "products" && <div className="form-card"><div className="section-title"><div><h2>商品与服务</h2><p>售价与币种必须成对填写；未知信息保持未知，不自动补值。</p></div><button className="primary" onClick={() => startProduct()}>新增商品 / 服务</button></div>
      {busy ? <p className="muted">正在读取…</p> : products.length === 0 ? <p className="muted">暂无商品或服务记录。</p> : <div className="table-wrap"><table><thead><tr><th>名称</th><th>分类 / SKU</th><th>规格</th><th>售价</th><th>可售状态</th><th>事实状态</th><th>操作</th></tr></thead><tbody>{products.map(item=><tr key={item.id}>
        <td>{item.name}</td><td>{item.category || "—"}<small>{item.sku || ""}</small></td><td>{item.specification || "—"}</td>
        <td>{item.price_amount === null ? "未填写" : `${item.currency} ${item.price_amount}`} / {item.unit || "—"}</td>
        <td>{({available:"可售",unavailable:"停售",seasonal:"季节性",limited:"限量",unknown:"未知"} as Record<string,string>)[item.availability_status]}</td><td>{item.fact_status === "confirmed" ? "已确认" : "待核对"} · V{item.current_version}</td>
        <td><button className="text-button" onClick={() => startProduct(item)}>编辑</button>{item.fact_status !== "confirmed" && <button className="text-button" onClick={() => void confirmProduct(item)} disabled={busy}>确认</button>}<button className="text-button" onClick={() => void removeProduct(item)} disabled={busy}>删除</button></td>
      </tr>)}</tbody></table></div>}</div>}
    {!editing && tab === "offers" && <div className="form-card"><div className="section-title"><div><h2>活动与优惠</h2><p>活动规则与适用条件按结构化 JSON 保存，AI 只能引用经核实的规则。</p></div><button className="primary" onClick={() => startOffer()}>新增活动</button></div>
      {busy ? <p className="muted">正在读取…</p> : offers.length === 0 ? <p className="muted">暂无活动或优惠记录。</p> : <div className="table-wrap"><table><thead><tr><th>活动名称</th><th>类型</th><th>有效期</th><th>状态</th><th>事实状态</th><th>操作</th></tr></thead><tbody>{offers.map(item=><tr key={item.id}>
        <td>{item.title}</td><td>{({discount:"折扣",bundle:"组合优惠",gift:"赠品",threshold:"满额优惠",other:"其他"} as Record<string,string>)[item.offer_type] ?? item.offer_type}</td><td>{item.starts_at || "不限"} — {item.ends_at || "不限"}</td><td>{({draft:"草稿",active:"生效中",paused:"已暂停",expired:"已过期",archived:"已归档"} as Record<string,string>)[item.status]}</td>
        <td>{item.fact_status === "confirmed" ? "已确认" : "待核对"} · V{item.current_version}</td>
        <td><button className="text-button" onClick={() => startOffer(item)}>编辑</button>{item.fact_status !== "confirmed" && <button className="text-button" onClick={() => void confirmOffer(item)} disabled={busy}>确认</button>}<button className="text-button" onClick={() => void removeOffer(item)} disabled={busy}>删除</button></td>
      </tr>)}</tbody></table></div>}</div>}
  </section>;
}
