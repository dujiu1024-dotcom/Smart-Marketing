import {seed} from "./data.js";
const KEY="ai-store-ops-storefront-v1";
const ADMIN_KEY="ai-store-ops-platform-admin-v1";
const LEGACY_KEY="ai-store-ops-demo-v2";
const SCHEMA_VERSION=8;
const clone=x=>JSON.parse(JSON.stringify(x));
let state;
let persistedSnapshot=null;
const array=(v,fallback=[])=>Array.isArray(v)?v:clone(fallback);
function normalize(){
  const previousSchema=Number(state.schemaVersion||0);
  const base=clone(seed);
  state.store={...base.store,...(state.store||{})};
  state.stores=array(state.stores,base.stores||[]);
  for(const key of ["tasks","products","assets","offers","knowledge","channels","hotspots"])state[key]=array(state[key],base[key]);
  delete state.dataSources;
  state.effects=state.effects||clone(base.effects);
  state.effects.reports=array(state.effects.reports);
  state.effects.sources=array(state.effects.sources);
  state.admin={...base.admin,...(state.admin||{})};
  for(const key of ["users","prompts","audit","runs"])state.admin[key]=array(state.admin[key],base.admin[key]);
  state.admin.prompts=[...base.admin.prompts.filter(p=>!state.admin.prompts.some(x=>x.id===p.id)),...state.admin.prompts];
  state.stores=state.stores.map(st=>({id:st.id,name:st.name,code:st.code,brand:st.brand,type:st.type,industryCategory:st.industryCategory,industry:st.industry,category:st.category,status:st.status,province:st.province,city:st.city,district:st.district,address:st.address,users:array(st.users),modelConfig:st.modelConfig||{vendor:"未配置"}}));
  state.admin.selectedStoreTab=state.admin.selectedStoreTab||"users";
  for(const key of ["tenants","models","roles","workflows","tickets","workflowConfig","attributionConfig"])delete state.admin[key];
  delete state.admin.budgetConfig;
  state.admin.systemConfig={...base.admin.systemConfig,...(state.admin.systemConfig||{})};
  state.admin.systemConfig.industryCategories=previousSchema<SCHEMA_VERSION?[...new Set([...(base.admin.systemConfig.industryCategories||[]),...array(state.admin.systemConfig.industryCategories)])]:array(state.admin.systemConfig.industryCategories,base.admin.systemConfig.industryCategories||[]);
  state.admin.selectedStoreId=state.admin.selectedStoreId||state.stores[0]?.id||state.store.id;
  state.admin.selectedIndustryCategory=state.admin.selectedIndustryCategory||"饮品";
  state.admin.selectedPromptId=state.admin.selectedPromptId||state.admin.prompts[0]?.id||"";
  state.admin.selectedMonitorTaskId=state.admin.selectedMonitorTaskId||"";
  state.products.forEach(p=>{delete p.cost;delete p.margin});
  state.offers.forEach(o=>{delete o.approvedBy});
  state.tasks.forEach(t=>{
    t.copy=t.copy&&typeof t.copy==="object"?t.copy:{};
    t.copyStates=t.copyStates||{};t.copyReviews=array(t.copyReviews);t.copyHistory=array(t.copyHistory);
    t.copyVersionNumbers=t.copyVersionNumbers||{};t.imageVersions=array(t.imageVersions);
    t.channels=array(t.channels);t.events=array(t.events);t.strategy=t.strategy||{};
    t.strategyStatus=t.strategyStatus||"draft";t.briefConfirmed=!!t.briefConfirmed;t.briefSnapshot=t.briefSnapshot||null;t.confirmedStrategySnapshot=t.confirmedStrategySnapshot||null;t.channelAdaptedPlatforms=array(t.channelAdaptedPlatforms);t.qualityChecks=t.qualityChecks||null;
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
  try{
    const frontRaw=localStorage.getItem(KEY)||localStorage.getItem(LEGACY_KEY);
    const adminRaw=localStorage.getItem(ADMIN_KEY);
    state=frontRaw?JSON.parse(frontRaw):clone(seed);
    if(adminRaw){const adminState=JSON.parse(adminRaw);state.admin=adminState.admin||state.admin;state.stores=adminState.stores||state.stores}
    persistedSnapshot={front:frontRaw,admin:adminRaw};
  }catch{state=clone(seed);persistedSnapshot={front:null,admin:null}}
  if(!state||typeof state!=="object"||Array.isArray(state))state=clone(seed);
  normalize();
  return state;
}
function restorePersisted(){
  let restored;
  try{
    restored=persistedSnapshot?.front?JSON.parse(persistedSnapshot.front):clone(seed);
    if(persistedSnapshot?.admin){const adminState=JSON.parse(persistedSnapshot.admin);restored.admin=adminState.admin||restored.admin;restored.stores=adminState.stores||restored.stores}
  }catch{restored=clone(seed)}
  for(const key of Object.keys(state))delete state[key];
  Object.assign(state,restored);
  normalize();
}
export function save(){
  const frontData={...state};delete frontData.admin;delete frontData.stores;
  const adminData={admin:state.admin,stores:state.stores};
  const frontSerialized=JSON.stringify(frontData),adminSerialized=JSON.stringify(adminData);
  try{
    localStorage.setItem(ADMIN_KEY,adminSerialized);
    localStorage.setItem(KEY,frontSerialized);
    persistedSnapshot={front:frontSerialized,admin:adminSerialized};
    window.dispatchEvent(new CustomEvent("demo:changed"));
    return true;
  }catch(error){
    try{if(persistedSnapshot?.admin)localStorage.setItem(ADMIN_KEY,persistedSnapshot.admin);else localStorage.removeItem(ADMIN_KEY)}catch{}
    try{if(persistedSnapshot?.front)localStorage.setItem(KEY,persistedSnapshot.front);else localStorage.removeItem(KEY)}catch{}
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
