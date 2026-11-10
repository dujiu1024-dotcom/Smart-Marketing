// Performance/effect page renderer. Data filtering remains in the application layer.
export function createEffectRenderers({db,pageHead,btn,stat,pill,esc,filteredEffectReports,effectDateRange,renderLinkedContentEffects,getEffectWindow,getEffectTask}) {
 function renderEffects(){const d=db(),reports=filteredEffectReports(),range=effectDateRange(),effectWindow=getEffectWindow(),effectTask=getEffectTask();
return pageHead("PERFORMANCE CENTER","经营效果","独立评估营销表现。只有在发布后产生数据并达到观察窗口，才展示可用的效果指标。",btn("管理渠道账号","nav-store:channels"))+
'<div class="grid g4 mb">'+stat("可分析营销活动",reports.length,"符合筛选条件的数据快照")+stat("可用数据来源","待接入","报告中标注来源与可信度")+stat("当前观察窗口",effectWindow,"按日期过滤")+stat("归因可信度","待接入","需有来源、口径和数据关联")+
'</div>'+renderLinkedContentEffects(d)+
'<div class="card mb"><div class="card-head"><h3>效果分析筛选</h3><div class="segmented">'+["24小时","7天","30天","自定义"].map(x=>'<button data-window="'+x+
'" class="'+(effectWindow===x?"active":"")+
'">'+x+
'</button>').join("")+
'</div></div><div class="field-row three"><div class="field"><label>开始日期</label><input id="effectStart" type="date" value="'+range.start+
'"></div><div class="field"><label>结束日期</label><input id="effectEnd" type="date" value="'+range.end+
'"></div><div class="field"><label>分析对象</label><select id="effectTask"><option value="">全部营销活动</option>'+d.tasks.map(t=>'<option value="'+esc(t.id)+
'" '+(effectTask===t.id?'selected':'')+
'>'+esc(t.title)+
'</option>').join("")+
'</select></div></div><div class="small muted">按报告日期和所选任务过滤；未记录日期的数据不会纳入统计。演示数据明确标注为样例。</div></div>'+(reports.length?'<div class="notice info mb">以下为明确标注的演示样例数据，不代表真实门店经营结果。</div>'+reports.map(r=>'<div class="card mb"><div class="card-head"><div><h3>'+esc(r.title)+
'</h3><div class="small muted">'+esc(r.period)+
' · '+esc(r.date)+
' · 来源：'+esc(r.source)+
'</div></div>'+pill("演示数据")+
'</div><div class="grid g4">'+Object.entries(r.metrics).map(x=>stat(x[0],x[1],"样例指标 · 非真实采集")).join("")+
'</div><div class="notice mt">归因说明：'+esc(r.note)+
'</div></div>').join(""):'<div class="card empty"><div class="symbol">◷</div><b>当前筛选条件下没有可用的经营效果数据</b>可调整日期或分析对象。没有连接真实数据源时，不生成经营结论。<div class="actions" style="justify-content:center;margin-top:18px">'+btn("加载明确标注的演示数据","load-demo-effects","","soft")+btn("管理渠道账号","nav-store:channels")+
'</div></div>')+
'<div class="grid g2 mt"><div class="card"><h3>效果指标口径</h3><div class="list">'+[["内容表现","曝光、阅读、播放、互动、收藏、分享"],["意向表现","私信、咨询、点击、领券"],["经营表现","到店、订单、销售额、客单价、核销"],["营销效率","转化率、获客成本、投入产出比"]].map(x=>'<div class="list-item"><div><strong>'+x[0]+
'</strong><div class="meta">'+x[1]+
'</div></div></div>').join("")+
'</div></div><div class="card"><h3>数据可信度规则</h3><div class="notice">每项指标都必须携带数据来源、采集时间、统计周期、统计口径、真实性标记和归因可信度。不能证明因果时只描述相关性。</div></div></div>'}

 return {renderEffects};
}
