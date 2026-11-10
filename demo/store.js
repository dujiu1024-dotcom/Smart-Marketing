import {seed} from "./data.js";
const KEY="ai-store-ops-demo-v2";
const clone=x=>JSON.parse(JSON.stringify(x));
let state;
export function load(){if(state)return state;try{const raw=localStorage.getItem(KEY);state=raw?JSON.parse(raw):clone(seed)}catch{state=clone(seed)}return state}
export function save(){localStorage.setItem(KEY,JSON.stringify(state));window.dispatchEvent(new CustomEvent("demo:changed"))}
export function db(){return load()}
export function patch(path,value){const keys=path.split(".");let obj=state;while(keys.length>1)obj=obj[keys.shift()];obj[keys[0]]=value;save();return value}
export function add(collection,item){let list=pathGet(collection);if(!Array.isArray(list)){patch(collection,[]);list=pathGet(collection)}list.unshift({...item,id:item.id||"id-"+Date.now()});save();return list[0]}
export function update(collection,id,changes){const list=pathGet(collection);const i=list.findIndex(x=>x.id===id);if(i<0)return null;list[i]={...list[i],...changes};save();return list[i]}
export function remove(collection,id){const list=pathGet(collection);const i=list.findIndex(x=>x.id===id);if(i<0)return false;list.splice(i,1);save();return true}
export function pathGet(path){return path.split(".").reduce((o,k)=>o?.[k],state)}
export function reset(){state=clone(seed);save();return state}
export function audit(action,object,detail=""){state.admin.audit.unshift({id:"log-"+Date.now(),at:new Date().toLocaleString("zh-CN"),actor:"当前演示管理员",action,object,detail});save()}
export function event(taskId,label,detail="",status="done"){const t=state.tasks.find(x=>x.id===taskId);if(!t)return;t.events=t.events||[];t.events.unshift({time:new Date().toLocaleString("zh-CN"),label,detail,status});t.updatedAt=new Date().toLocaleString("zh-CN");save()}
