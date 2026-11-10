import {seed} from "./data.js";
const KEY="ai-store-ops-demo-v2";
const SCHEMA_VERSION=3;
const clone=x=>JSON.parse(JSON.stringify(x));
let state;
let persistedSnapshot=null;
const array=(v,fallback=[])=>Array.isArray(v)?v:clone(fallback);
function normalize(){
  const base=clone(seed);
  state.store={...base.store,...(state.store||{})};
  for(const key of ["tasks","products","assets","offers","knowledge","channels","dataSources"])state[key]=array(state[key],base[key]);
  state.effects=state.effects||clone(base.effects);
  state.effects.reports=array(state.effects.reports);
  state.effects.sources=array(state.effects.sources);
  state.admin={...base.admin,...(state.admin||{})};
  for(const key of ["tenants","users","models","prompts","roles","workflows","tickets","audit","runs"])state.admin[key]=array(state.admin[key],base.admin[key]);
  state.admin.workflowConfig={...base.admin.workflowConfig,...(state.admin.workflowConfig||{})};
  state.admin.attributionConfig={...base.admin.attributionConfig,...(state.admin.attributionConfig||{})};
  state.admin.budgetConfig={...base.admin.budgetConfig,...(state.admin.budgetConfig||{})};
  state.admin.systemConfig={...base.admin.systemConfig,...(state.admin.systemConfig||{})};
  state.tasks.forEach(t=>{
    t.copy=t.copy&&typeof t.copy==="object"?t.copy:{};
    t.copyStates=t.copyStates||{};t.copyReviews=array(t.copyReviews);t.copyHistory=array(t.copyHistory);
    t.copyVersionNumbers=t.copyVersionNumbers||{};t.imageVersions=array(t.imageVersions);
    t.channels=array(t.channels);t.events=array(t.events);t.strategy=t.strategy||{};
    t.strategyStatus=t.strategyStatus||"draft";t.qualityChecks=t.qualityChecks||null;
    t.publishPackage=t.publishPackage||null;
  });
  state.products.forEach(p=>{
    p.assetIds=Array.isArray(p.assetIds)?p.assetIds:String(p.assetIds||"").split(",").map(x=>x.trim()).filter(Boolean);
    if(typeof p.confirmed!=="boolean")p.confirmed=false;
  });
  state.assets.forEach(a=>{a.tags=a.tags||"";a.rights=a.rights||"待确认";a.status=a.status||"待审核"});
  state.schemaVersion=SCHEMA_VERSION;
}
export function load(){
  if(state)return state;
  try{const raw=localStorage.getItem(KEY);state=raw?JSON.parse(raw):clone(seed);persistedSnapshot=raw||null}
  catch{state=clone(seed);persistedSnapshot=null}
  if(!state||typeof state!=="object"||Array.isArray(state))state=clone(seed);
  normalize();
  return state;
}
function restorePersisted(){
  let restored;
  try{restored=persistedSnapshot?JSON.parse(persistedSnapshot):clone(seed)}catch{restored=clone(seed)}
  for(const key of Object.keys(state))delete state[key];
  Object.assign(state,restored);
  normalize();
}
export function save(){
  try{
    const serialized=JSON.stringify(state);
    localStorage.setItem(KEY,serialized);
    persistedSnapshot=serialized;
    window.dispatchEvent(new CustomEvent("demo:changed"));
    return true;
  }catch(error){
    restorePersisted();
    window.dispatchEvent(new CustomEvent("demo:storage-error",{detail:{name:error?.name||"StorageError"}}));
    return false;
  }
}
export function db(){return load()}
export function patch(path,value){const keys=path.split(".");let obj=state;while(keys.length>1)obj=obj[keys.shift()];obj[keys[0]]=value;return save()?value:null}
export function add(collection,item){let list=pathGet(collection);if(!Array.isArray(list)){const keys=collection.split(".");let parent=state;while(keys.length>1)parent=parent[keys.shift()];parent[keys[0]]=[];list=pathGet(collection)}const entry={...item,id:item.id||"id-"+Date.now()};list.unshift(entry);return save()?entry:null}
export function update(collection,id,changes){const list=pathGet(collection);if(!Array.isArray(list))return null;const i=list.findIndex(x=>x.id===id);if(i<0)return null;const previous=list[i];list[i]={...previous,...changes};return save()?list[i]:null}
export function remove(collection,id){const list=pathGet(collection);if(!Array.isArray(list))return false;const i=list.findIndex(x=>x.id===id);if(i<0)return false;const [removed]=list.splice(i,1);if(save())return true;return false}
export function pathGet(path){return path.split(".").reduce((o,k)=>o?.[k],state)}
export function reset(){state=clone(seed);normalize();save();return state}
export function audit(action,object,detail=""){state.admin.audit.unshift({id:"log-"+Date.now(),at:new Date().toLocaleString("zh-CN"),actor:"当前演示管理员",action,object,detail});return save()}
export function event(taskId,label,detail="",status="done"){const t=state.tasks.find(x=>x.id===taskId);if(!t)return false;t.events=t.events||[];t.events.unshift({time:new Date().toLocaleString("zh-CN"),label,detail,status});t.updatedAt=new Date().toLocaleString("zh-CN");return save()}
