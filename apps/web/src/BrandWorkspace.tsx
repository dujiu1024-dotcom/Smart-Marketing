import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, confirmBrandGuidelineFacts, createBrandGuideline, getBrandGuideline, updateBrandGuideline, type BrandGuideline, type BrandGuidelineInput } from "./api";

interface FormState {
  brand_story: string; positioning: string; differentiators: string; core_values: string;
  tone_of_voice: string; common_phrases: string; prohibited_phrases: string; cta_preferences: string;
  color_palette: string; font_preferences: string; visual_style: string;
}
const empty: FormState = { brand_story:"", positioning:"", differentiators:"", core_values:"", tone_of_voice:"",
  common_phrases:"", prohibited_phrases:"", cta_preferences:"", color_palette:"[]", font_preferences:"", visual_style:"" };
const lines = (value: string) => value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
function fromRecord(record: BrandGuideline): FormState {
  return { brand_story:record.brand_story??"", positioning:record.positioning??"", differentiators:record.differentiators??"",
    core_values:(record.core_values_json??[]).join("\n"), tone_of_voice:record.tone_of_voice??"",
    common_phrases:(record.common_phrases_json??[]).join("\n"), prohibited_phrases:(record.prohibited_phrases_json??[]).join("\n"),
    cta_preferences:(record.cta_preferences_json??[]).join("\n"), color_palette:JSON.stringify(record.color_palette_json??[],null,2),
    font_preferences:(record.font_preferences_json??[]).join("\n"), visual_style:record.visual_style??"" };
}
function toInput(form: FormState, current: BrandGuideline | null): BrandGuidelineInput {
  let palette: unknown;
  try { palette = JSON.parse(form.color_palette || "[]"); } catch { throw new Error("品牌色板必须是有效 JSON 数组。"); }
  if (!Array.isArray(palette) || palette.some(item => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error("品牌色板必须是 JSON 对象数组。");
  }
  return { brand_story:form.brand_story.trim()||null, positioning:form.positioning.trim()||null,
    differentiators:form.differentiators.trim()||null, core_values_json:lines(form.core_values),
    tone_of_voice:form.tone_of_voice.trim()||null, common_phrases_json:lines(form.common_phrases),
    prohibited_phrases_json:lines(form.prohibited_phrases), cta_preferences_json:lines(form.cta_preferences),
    logo_asset_id:current?.logo_asset_id??null, color_palette_json:palette as Array<Record<string,unknown>>,
    font_preferences_json:lines(form.font_preferences), visual_style:form.visual_style.trim()||null };
}
const message=(e:unknown)=>e instanceof Error?e.message:"请求失败，请稍后重试。";
function Field({label,value,onChange,rows=1}:{label:string;value:string;onChange:(v:string)=>void;rows?:number}) {
  return <label className={rows>1?"field span-2":"field"}><span>{label}</span>{rows>1?<textarea rows={rows} value={value} onChange={e=>onChange(e.target.value)}/>:<input value={value} onChange={e=>onChange(e.target.value)}/>}</label>;
}
export default function BrandWorkspace({storeId}:{storeId:string}) {
  const [record,setRecord]=useState<BrandGuideline|null>(null);
  const [form,setForm]=useState<FormState>(empty);
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [dirty,setDirty]=useState(false);
  const reload=useCallback(async()=>{
    setLoading(true);setError("");
    try { const value=await getBrandGuideline(storeId);setRecord(value);setForm(fromRecord(value));setDirty(false); }
    catch(reason) { if(reason instanceof ApiError && reason.status===404){setRecord(null);setForm(empty);setDirty(false);} else setError(message(reason)); }
    finally {setLoading(false);}
  },[storeId]);
  useEffect(()=>{void reload();},[reload]);
  const changed=useMemo(()=>dirty,[dirty]);
  function change<K extends keyof FormState>(key:K,value:FormState[K]) {setForm(p=>({...p,[key]:value}));setDirty(true);setNotice("");}
  async function save(e:FormEvent<HTMLFormElement>) {
    e.preventDefault();setSaving(true);setError("");setNotice("");
    try {
      const payload=toInput(form,record);
      const saved=record?await updateBrandGuideline(storeId,record,payload):await createBrandGuideline(storeId,payload);
      setRecord(saved);setForm(fromRecord(saved));setDirty(false);setNotice(`品牌规范已保存为 V${saved.current_version}，请核对后确认。`);
    } catch(reason){setError(message(reason));} finally{setSaving(false);}
  }
  async function confirm() {
    if(!record||dirty)return;
    setSaving(true);setError("");setNotice("");
    try {const saved=await confirmBrandGuidelineFacts(storeId,record);setRecord(saved);setForm(fromRecord(saved));setNotice(`品牌规范 V${saved.current_version} 已确认。`);}
    catch(reason){setError(message(reason));}finally{setSaving(false);}
  }
  return <>
    <div className="page-heading"><div><p className="eyebrow">BRAND GUIDELINE</p><h1>品牌规范</h1><p className="muted">沉淀品牌定位、表达方式与视觉边界，减少营销内容偏离品牌。</p></div>
      {record&&<span className={record.fact_status==="confirmed"?"status-chip confirmed":"status-chip"}>V{record.current_version} · {record.fact_status==="confirmed"?"已确认":"待确认"}</span>}</div>
    {error&&<div className="alert error" role="alert">{error}{error.includes("VERSION_CONFLICT")&&<button className="text-button" onClick={()=>void reload()}>重新加载</button>}</div>}
    {notice&&<div className="alert success" role="status">{notice}</div>}
    {loading?<div className="loading-card"><span className="spinner"/>正在读取品牌规范…</div>:<form className="profile-form" onSubmit={save}>
      <section className="form-card"><div className="section-title"><div><h2>品牌定位</h2><p>品牌故事、核心价值与差异化优势。</p></div></div><div className="form-grid">
        <Field label="品牌故事" value={form.brand_story} onChange={v=>change("brand_story",v)} rows={3}/>
        <Field label="品牌定位" value={form.positioning} onChange={v=>change("positioning",v)} rows={2}/>
        <Field label="差异化优势" value={form.differentiators} onChange={v=>change("differentiators",v)} rows={2}/>
        <Field label="核心价值（每行一项）" value={form.core_values} onChange={v=>change("core_values",v)} rows={2}/>
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>品牌表达</h2><p>统一语气、常用表达、禁用话术和行动引导。</p></div></div><div className="form-grid">
        <Field label="品牌语气" value={form.tone_of_voice} onChange={v=>change("tone_of_voice",v)} rows={2}/>
        <Field label="常用表达（每行一项）" value={form.common_phrases} onChange={v=>change("common_phrases",v)} rows={2}/>
        <Field label="禁用表达 / 禁止承诺（每行一项）" value={form.prohibited_phrases} onChange={v=>change("prohibited_phrases",v)} rows={2}/>
        <Field label="CTA 偏好（每行一项）" value={form.cta_preferences} onChange={v=>change("cta_preferences",v)} rows={2}/>
      </div></section>
      <section className="form-card"><div className="section-title"><div><h2>视觉规范</h2><p>品牌色、字体与视觉风格；色板按 JSON 对象数组保存。</p></div></div><div className="form-grid">
        <Field label="视觉风格" value={form.visual_style} onChange={v=>change("visual_style",v)} rows={2}/>
        <Field label="字体偏好（每行一项）" value={form.font_preferences} onChange={v=>change("font_preferences",v)} rows={2}/>
        <Field label="品牌色板（JSON 数组）" value={form.color_palette} onChange={v=>change("color_palette",v)} rows={5}/>
        {record?.logo_asset_id&&<div className="field"><span>已关联 Logo 素材</span><input value={record.logo_asset_id} readOnly/></div>}
      </div></section>
      <div className="form-footer"><p>{record?(`当前版本 V${record.current_version} · ${record.fact_status==="confirmed"?"已确认":"待确认"}`):"首次保存后需由门店成员核对并确认品牌规范。"}</p><div className="form-actions">
        {record&&record.fact_status!=="confirmed"&&<button className="secondary" type="button" disabled={saving||changed} title={changed?"请先保存修改，再确认品牌规范":undefined} onClick={()=>void confirm()}>确认规范</button>}
        <button className="primary" type="submit" disabled={saving||!Object.values(form).some(v=>v.trim())}>{saving?"保存中…":record?"保存品牌规范":"创建品牌规范"}</button>
      </div></div>
    </form>}
  </>;
}
