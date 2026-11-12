import { useCallback, useEffect, useState, type FormEvent } from "react";
import { confirmAudienceFacts, createAudienceProfile, deleteAudienceProfile, getAudienceProfiles, updateAudienceProfile, type AudienceProfile, type AudienceProfileInput } from "./api";

interface FormState {
  name:string; segment_type:AudienceProfile["segment_type"]; audience_description:string;
  consumption_scenarios:string; consumption_periods:string; purchase_motivations:string; common_objections:string;
  source_type:string; source_ref:string; sample_size:string; sampled_at:string; confidence_level:string;
}
const empty:FormState={name:"",segment_type:"core",audience_description:"",consumption_scenarios:"",consumption_periods:"",
  purchase_motivations:"",common_objections:"",source_type:"",source_ref:"",sample_size:"",sampled_at:"",confidence_level:""};
const split=(v:string)=>v.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
const message=(e:unknown)=>e instanceof Error?e.message:"请求失败，请稍后重试。";
function fromAudience(item:AudienceProfile):FormState {
  return {name:item.name,segment_type:item.segment_type,audience_description:item.audience_description??"",
    consumption_scenarios:(item.consumption_scenarios_json??[]).join("\n"),consumption_periods:(item.consumption_periods_json??[]).join("\n"),
    purchase_motivations:(item.purchase_motivations_json??[]).join("\n"),common_objections:(item.common_objections_json??[]).join("\n"),
    source_type:item.source_type??"",source_ref:item.source_ref??"",sample_size:item.sample_size===null?"":String(item.sample_size),
    sampled_at:item.sampled_at?new Date(item.sampled_at).toISOString().slice(0,16):"",confidence_level:item.confidence_level??""};
}
function toInput(form:FormState):AudienceProfileInput {
  const sample=form.sample_size.trim();
  if(sample&&(!/^\d+$/.test(sample)||!Number.isSafeInteger(Number(sample)))) throw new Error("样本量必须为非负整数。");
  return {name:form.name.trim(),segment_type:form.segment_type,audience_description:form.audience_description.trim()||null,
    consumption_scenarios_json:split(form.consumption_scenarios),consumption_periods_json:split(form.consumption_periods),
    purchase_motivations_json:split(form.purchase_motivations),common_objections_json:split(form.common_objections),
    source_type:form.source_type.trim()||null,source_ref:form.source_ref.trim()||null,sample_size:sample?Number(sample):null,
    sampled_at:form.sampled_at?new Date(form.sampled_at).toISOString():null,confidence_level:form.confidence_level.trim()||null};
}
function Field({label,value,onChange,rows=1,placeholder}:{label:string;value:string;onChange:(v:string)=>void;rows?:number;placeholder?:string}) {
  return <label className={rows>1?"field span-2":"field"}><span>{label}</span>{rows>1?<textarea rows={rows} value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder}/>:<input value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder}/>}</label>;
}
export default function AudienceWorkspace({storeId}:{storeId:string}) {
  const [items,setItems]=useState<AudienceProfile[]>([]);const [total,setTotal]=useState(0);
  const [selected,setSelected]=useState<AudienceProfile|null>(null);const [form,setForm]=useState<FormState>(empty);
  const [route,setRoute]=useState(window.location.hash||"#store:audience");
  const [loading,setLoading]=useState(true);const [saving,setSaving]=useState(false);const [dirty,setDirty]=useState(false);
  const [error,setError]=useState("");const [notice,setNotice]=useState("");
  const editing=route.startsWith("#store-editor:audience:");
  const reload=useCallback(async()=>{
    setLoading(true);setError("");
    try{const response=await getAudienceProfiles(storeId);setItems(response.items);setTotal(response.total);}
    catch(reason){setError(message(reason));}finally{setLoading(false);}
  },[storeId]);
  useEffect(()=>{const onRoute=()=>setRoute(window.location.hash||"#store:audience");window.addEventListener("hashchange",onRoute);void reload();return()=>window.removeEventListener("hashchange",onRoute);},[reload]);
  useEffect(()=>{
    if(!editing)return;const id=route.slice("#store-editor:audience:".length);
    if(id==="new"){setSelected(null);setForm(empty);setDirty(false);return;}
    const found=items.find(item=>item.id===id);if(found){setSelected(found);setForm(fromAudience(found));setDirty(false);}
  },[editing,items,route]);
  function change<K extends keyof FormState>(key:K,value:FormState[K]){setForm(p=>({...p,[key]:value}));setDirty(true);setNotice("");}
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();setSaving(true);setError("");setNotice("");
    try{const input=toInput(form);const saved=selected?await updateAudienceProfile(storeId,selected,input):await createAudienceProfile(storeId,input);
      setItems(current=>selected?current.map(item=>item.id===saved.id?saved:item):[saved,...current]);setTotal(n=>selected?n:n+1);
      setSelected(saved);setForm(fromAudience(saved));setDirty(false);setNotice(`客群资料已保存为 V${saved.current_version}，请核对来源后确认。`);window.location.hash="#store:audience";
    }catch(reason){setError(message(reason));}finally{setSaving(false);}
  }
  async function confirm(item:AudienceProfile){
    if(dirty)return;setSaving(true);setError("");setNotice("");
    try{const saved=await confirmAudienceFacts(storeId,item);setItems(current=>current.map(v=>v.id===saved.id?saved:v));setSelected(saved);setNotice(`${saved.name} 的客群事实 V${saved.current_version} 已确认。`);}
    catch(reason){setError(message(reason));}finally{setSaving(false);}
  }
  async function remove(item:AudienceProfile){
    if(!window.confirm(`确认删除客群「${item.name}」？`))return;setSaving(true);setError("");
    try{await deleteAudienceProfile(storeId,item);setItems(current=>current.filter(v=>v.id!==item.id));setTotal(n=>Math.max(0,n-1));setNotice("客群资料已删除。");}
    catch(reason){setError(message(reason));}finally{setSaving(false);}
  }
  const segmentLabel:Record<AudienceProfile["segment_type"],string>={core:"核心客群",secondary:"次要客群",seasonal:"季节客群",scenario:"场景客群"};
  return <>
    <div className="page-heading"><div><p className="eyebrow">AUDIENCE & OPERATIONS</p><h1>客群与经营</h1><p className="muted">记录真实客群、消费场景、购买动机与常见异议，保留样本来源和置信信息。</p></div>
      {!editing&&<button className="primary" type="button" onClick={()=>{window.location.hash="#store-editor:audience:new";}}>新增客群</button>}
      {editing&&<button className="secondary" type="button" onClick={()=>{window.location.hash="#store:audience";}}>返回列表</button>}</div>
    {error&&<div className="alert error" role="alert">{error}{error.includes("VERSION_CONFLICT")&&<button className="text-button" onClick={()=>void reload()}>重新加载</button>}</div>}
    {notice&&<div className="alert success" role="status">{notice}</div>}
    {editing?<form className="profile-form" onSubmit={save}>
      <section className="form-card"><div className="section-title"><div><h2>{selected?"编辑客群":"新增客群"}</h2><p>客群描述应来自经营观察或调研；不要把推测写成已验证事实。</p></div></div>
        <div className="form-grid">
          <Field label="客群名称 *" value={form.name} onChange={v=>change("name",v)}/>
          <label className="field"><span>客群类型</span><select value={form.segment_type} onChange={e=>change("segment_type",e.target.value as FormState["segment_type"])}><option value="core">核心客群</option><option value="secondary">次要客群</option><option value="seasonal">季节客群</option><option value="scenario">场景客群</option></select></label>
          <Field label="客群描述" value={form.audience_description} onChange={v=>change("audience_description",v)} rows={3}/>
          <Field label="消费场景（每行一项）" value={form.consumption_scenarios} onChange={v=>change("consumption_scenarios",v)} rows={3}/>
          <Field label="消费时段（每行一项）" value={form.consumption_periods} onChange={v=>change("consumption_periods",v)} rows={2}/>
          <Field label="购买动机（每行一项）" value={form.purchase_motivations} onChange={v=>change("purchase_motivations",v)} rows={3}/>
          <Field label="常见异议（每行一项）" value={form.common_objections} onChange={v=>change("common_objections",v)} rows={3}/>
        </div>
      </section>
      <section className="form-card"><div className="section-title"><div><h2>样本与来源</h2><p>没有调研证据时，样本量和置信等级留空。</p></div></div><div className="form-grid">
        <Field label="来源类型" value={form.source_type} onChange={v=>change("source_type",v)} placeholder="merchant_observation / survey / POS…"/>
        <Field label="来源说明 / 引用" value={form.source_ref} onChange={v=>change("source_ref",v)}/>
        <Field label="样本量" value={form.sample_size} onChange={v=>change("sample_size",v)}/>
        <Field label="采样时间（本地时间）" value={form.sampled_at} onChange={v=>change("sampled_at",v)}/>
        <label className="field"><span>置信等级</span><select value={form.confidence_level} onChange={e=>change("confidence_level",e.target.value)}><option value="">未评估</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
      </div></section>
      <div className="form-footer"><p>{selected?`当前版本 V${selected.current_version} · ${selected.fact_status==="confirmed"?"已确认":"待确认"}`:"保存后需核对客群来源与描述，再确认事实。"}</p><div className="form-actions">
        {selected&&selected.fact_status!=="confirmed"&&<button className="secondary" type="button" disabled={saving||dirty} title={dirty?"请先保存修改，再确认客群":undefined} onClick={()=>void confirm(selected)}>确认事实</button>}
        <button className="secondary" type="button" onClick={()=>{window.location.hash="#store:audience";}}>取消</button>
        <button className="primary" type="submit" disabled={saving||!form.name.trim()}>{saving?"保存中…":"保存客群"}</button>
      </div></div>
    </form>:loading?<div className="loading-card"><span className="spinner"/>正在读取客群资料…</div>
    :items.length===0?<section className="empty-card"><h2>还没有客群资料</h2><p>先记录核心客群及其消费场景、购买动机和常见异议；没有数据的字段保持空白。</p><button className="primary" onClick={()=>{window.location.hash="#store-editor:audience:new";}}>添加第一类客群</button></section>
    :<section className="catalog-list"><div className="catalog-summary"><span>共 {total} 类客群</span><button className="text-button" onClick={()=>void reload()}>刷新</button></div>
      {items.map(item=><article className="catalog-item" key={item.id}>
        <div className="catalog-item-main"><div><h2>{item.name}</h2><p>{segmentLabel[item.segment_type]} · {item.source_type||"来源未记录"}</p></div><span className={item.fact_status==="confirmed"?"status-chip confirmed":"status-chip"}>{item.fact_status==="confirmed"?"事实已确认":"待确认"}</span></div>
        <div className="catalog-meta"><span>{item.sample_size===null?"样本量未填写":`样本 ${item.sample_size}`}</span><span>{item.confidence_level?({high:"高置信",medium:"中置信",low:"低置信"} as Record<string,string>)[item.confidence_level]??item.confidence_level:"未评估置信度"}</span><span>V{item.current_version}</span></div>
        <div className="catalog-actions"><button className="secondary" onClick={()=>{window.location.hash=`#store-editor:audience:${item.id}`;}}>编辑</button>{item.fact_status!=="confirmed"&&<button className="secondary" disabled={saving} onClick={()=>void confirm(item)}>确认事实</button>}<button className="secondary" disabled={saving} onClick={()=>void remove(item)}>删除</button></div>
      </article>)}
    </section>}
  </>;
}
