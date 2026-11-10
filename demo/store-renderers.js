// Store profile and operating-data renderers. Editing actions remain in app.js.
export function createStoreRenderers({db,field,select,textarea,btn,esc,pill,pageHead,table,getStoreTab,getStoreNav}) {
 function renderStore(section){const d=db(),s=d.store,products=d.products,offers=d.offers,assets=d.assets,knowledge=d.knowledge,channels=d.channels;
let body="";
if(section==="profile")body='<div class="grid"><div class="card"><h3>门店基本信息</h3><form id="storeProfileForm"><div class="field-row">'+field("门店名称","name",s.name)+field("门店编码","code",s.code)+
'</div><div class="field-row">'+field("品牌/连锁归属","brand",s.brand)+select("门店类型","type",["直营门店","加盟门店","单体门店","品牌总部"],s.type)+
'</div><div class="field-row">'+select("门店业态分类","industryCategory",["食品","餐饮","饮品","美容","按摩","健身","零售","生活服务"],s.industryCategory||"饮品")+field("行业说明","industry",s.industry)+field("主营类目","category",s.category)+
'</div>'+textarea("门店简介","intro",s.intro)+ '<div class="field-row">'+field("联系电话","phone",s.phone)+field("门店联系人","contact",s.contact)+
'</div><div class="field-row">'+field("联系人电话","contactPhone",s.contactPhone)+field("开业时间","openedAt",s.openedAt,"date")+
'</div><div class="field-row three">'+field("省份","province",s.province)+field("城市","city",s.city)+field("区县","district",s.district)+
'</div>'+field("详细地址","address",s.address)+field("营业时间（摘要）","hours",s.hours,"text","详细时段按工作日、周末和节假日分别维护。")+field("工作日营业时间","weekdayHours",s.weekdayHours)+field("周末营业时间","weekendHours",s.weekendHours)+field("节假日营业时间","holidayHours",s.holidayHours)+field("门店面积","storeSize",s.storeSize)+field("座位 / 接待能力","seats",s.seats)+field("服务类型","serviceType",s.serviceType)+field("临时停业日期","closedDates","","text","如有临时歇业，应在营销决策中阻止错误宣传。")+
'<div class="actions">'+btn("保存门店档案","save-store","","primary")+
'</div></form></div></div>';
if(section==="products")body='<div class="card"><div class="card-head"><div><h3>商品与服务</h3><p class="small muted">商品事实会被 AI 用于策略、文案和图片质检。</p></div>'+btn("新增商品 / 服务","add-product","","primary")+
'</div>'+table(["商品名称","分类 / SKU","规格","售价","可售状态","库存 / 产能","确认状态","操作"],products.map(p=>'<tr><td><strong>'+esc(p.name)+
'</strong><div class="mono">'+esc(p.selling)+
'</div></td><td>'+esc(p.category)+
'<div class="mono">'+esc(p.sku)+
'</div></td><td>'+esc(p.spec)+
'</td><td>¥'+esc(p.price)+
' / '+esc(p.unit)+
'</td><td>'+pill(p.status)+
'</td><td>'+esc(p.stock)+
'</td><td>'+pill(p.confirmed?"已确认":"待确认")+
'</td><td>'+btn("编辑","edit-product",p.id)+(p.confirmed?"":btn("确认资料","confirm-product",p.id,"primary"))+btn("删除","delete-product",p.id,"danger")+
'</td></tr>').join(""))+
'</div>';
if(section==="offers")body='<div class="card"><div class="card-head"><div><h3>活动与优惠</h3><p class="small muted">AI 只能引用状态有效且规则已确认的活动。</p></div>'+btn("新增活动","add-offer","","primary")+
'</div>'+table(["活动名称","类型","适用商品","优惠规则","有效期","适用条件","状态","操作"],offers.map(o=>'<tr><td><strong>'+esc(o.name)+
'</strong></td><td>'+esc(o.type)+
'</td><td>'+esc(o.products)+
'</td><td>'+esc(o.rule)+
'</td><td>'+esc(o.start)+
' 至 '+esc(o.end)+
'</td><td>'+esc(o.condition)+
'</td><td>'+pill(o.status)+
'</td><td>'+btn("编辑","edit-offer",o.id)+btn("删除","delete-offer",o.id,"danger")+
'</td></tr>').join(""))+
'</div>';
if(section==="brand")body='<div class="grid g2"><div class="card"><h3>品牌视觉规范</h3><form id="brandForm">'+field("品牌名称","brand",s.brand)+field("Logo / 品牌标识文字","logo",s.logo)+field("品牌主色","primaryColor",s.primaryColor)+field("品牌辅助色","secondaryColor",s.secondaryColor)+field("字体偏好","font",s.font)+textarea("视觉风格","visualStyle",s.visualStyle)+
'<div class="actions">'+btn("保存品牌规范","save-brand","","primary")+
'</div></form></div><div class="card"><h3>内容表达规范</h3><form id="toneForm">'+textarea("品牌定位","positioning",s.positioning)+textarea("品牌语气","tone",s.tone)+textarea("核心差异化","strengths",s.strengths)+textarea("禁用词 / 禁止承诺","forbidden",s.forbidden)+textarea("行动引导偏好（CTA）","cta",s.cta)+
'<div class="actions">'+btn("保存表达规范","save-tone","","primary")+
'</div></form><div class="notice warn mt">禁止词将用于文案质检。商品功效、健康、绝对化宣传等必须有合法依据。</div></div></div>';
if(section==="audience")body='<div class="grid g2"><div class="card"><h3>客群与消费场景</h3><form id="audienceForm">'+textarea("核心客群","audience",s.audience)+textarea("消费场景","scenes",s.scenes)+textarea("经营目标","goals",s.goals)+textarea("淡旺季与高峰时段","peak",s.peak)+textarea("产能 / 服务限制","constraints",s.constraints)+field("服务半径","serviceRadius",s.serviceRadius)+
'<div class="actions">'+btn("保存客群与经营策略","save-audience","","primary")+
'</div></form></div><div class="card"><h3>画像数据来源</h3><div class="notice info">客群画像需要标记数据来源和样本时间。当前展示的客群信息为商家录入，不是平台推断。</div><div class="list mt">'+[["核心客群","商家录入 · 2026-11-08"],["消费时段","商家录入 · 2026-11-08"],["经营目标","商家录入 · 2026-11-08"]].map(x=>'<div class="list-item"><div><strong>'+x[0]+
'</strong><div class="meta">'+x[1]+
'</div></div>'+pill("已确认")+
'</div>').join("")+
'</div></div></div>';
if(section==="knowledge")body='<div class="card"><div class="card-head"><div><h3>门店知识库</h3><p class="small muted">SOP、菜单、FAQ、品牌故事、服务说明与活动规则。</p></div>'+btn("新增知识","add-knowledge","","primary")+
'</div>'+table(["标题","类型","来源","版本","负责人","有效期","状态","操作"],knowledge.map(k=>'<tr><td><strong>'+esc(k.title)+
'</strong><div class="mono">'+esc(k.id)+
'</div></td><td>'+esc(k.type)+
'</td><td>'+esc(k.source)+
'</td><td>'+esc(k.version)+
'</td><td>'+esc(k.owner)+
'</td><td>'+esc(k.valid)+
'</td><td>'+pill(k.status)+
'</td><td>'+btn("编辑","edit-knowledge",k.id)+btn("删除","delete-knowledge",k.id,"danger")+
'</td></tr>').join(""))+
'</div>';
if(section==="assets")body='<div class="card"><div class="card-head"><div><h3>素材资产库</h3><p class="small muted">原始素材只读；AI 衍生图片必须记录源素材关系。</p></div>'+btn("上传素材","add-asset","","primary")+
'</div><div class="grid g3 mb">'+assets.map(a=>'<div class="card flat">'+(a.dataUrl?'<div class="asset-thumb"><img src="'+a.dataUrl+
'" style="max-width:100%;max-height:115px;object-fit:contain"></div>':'<div class="asset-thumb">▧</div>')+
'<strong>'+esc(a.name)+
'</strong><div class="small muted mt">'+esc(a.type)+
' · '+esc(a.dimensions)+
'</div><div class="row between mt">'+pill(a.status)+
'<span class="tiny muted">'+esc(a.rights)+
'</span></div></div>').join("")+
'</div>'+table(["文件","格式/大小","类型","关联商品","版权授权","状态","操作"],assets.map(a=>'<tr><td><strong>'+esc(a.name)+
'</strong><div class="mono">'+esc(a.id)+
'</div></td><td>'+esc(a.format)+
' / '+esc(a.size)+
' / '+esc(a.dimensions)+
'</td><td>'+esc(a.type)+
'</td><td>'+esc(a.product)+
'</td><td>'+esc(a.rights)+
'</td><td>'+pill(a.status)+
'</td><td>'+btn("删除","delete-asset",a.id,"danger")+
'</td></tr>').join(""))+
'</div>';
if(section==="channels")body='<div class="card"><div class="card-head"><div><h3>平台账号与授权</h3><p class="small muted">连接状态决定草稿保存、发布与数据读取能力。</p></div></div>'+table(["平台","账号主体","账号 ID","授权状态","授权范围","能力","到期时间","操作"],channels.map(c=>'<tr><td><strong>'+esc(c.platform)+
'</strong></td><td>'+esc(c.account)+
'</td><td class="mono">'+esc(c.accountId)+
'</td><td>'+pill(c.status)+
'</td><td>'+esc(c.scopes)+
'</td><td>'+esc(c.capabilities)+
'</td><td>'+esc(c.expires)+
'</td><td>'+btn("连接账号","connect-channel",c.id)+btn("断开","disconnect-channel",c.id,"danger")+
'</td></tr>').join(""))+
'</div><div class="notice warn mt">真实 OAuth 授权流程未接入。点击连接只会记录演示状态，不会获得真实平台权限。</div>';
if(section==="users"){const users=[];
body='<div class="card"><h3>门店用户</h3><p class="small muted">用户归属当前门店，仅维护姓名、邮箱和启停状态。</p>'+table(["姓名","邮箱","状态","操作"],users.map(u=>'<tr><td>'+esc(u.name)+
'</td><td>'+esc(u.email)+
'</td><td>'+pill(u.status)+
'</td><td>'+btn(u.status==="启用"?"禁用":"启用","admin-toggle-store-user",u.id)+
'</td></tr>').join(""))+
'</div><div class="card mt"><h3>添加门店用户</h3><div class="field-row"><div class="field"><label>姓名</label><input id="newStoreUserName"></div><div class="field"><label>邮箱</label><input id="newStoreUserEmail" type="email"></div></div>'+btn("添加用户","admin-add-store-user","","primary")+
'</div>'}
if(section==="model"){const m=s.modelConfig||{};
body='<div class="card"><h3>门店专属模型配置</h3><div class="notice warn mb">仅保存演示配置与密钥引用，不保存真实 API Key，不发起模型请求。</div><div class="field-row"><div class="field"><label>供应商</label><input id="storeModelVendor" value="'+esc(m.vendor||"")+
'"></div><div class="field"><label>默认模型</label><input id="storeModelName" value="'+esc(m.model||"")+
'"></div></div><div class="field"><label>API Base URL</label><input id="storeModelEndpoint" value="'+esc(m.endpoint||"")+
'"></div><div class="field"><label>API Key 安全引用</label><input id="storeModelKeyRef" value="'+esc(m.keyRef||"")+
'"></div><div class="field-row"><div class="field"><label>文本模型</label><input id="storeTextModel" value="'+esc(m.textModel||"")+
'"></div><div class="field"><label>图片模型</label><input id="storeImageModel" value="'+esc(m.imageModel||"")+
'"></div></div>'+btn("保存模型配置","admin-save-store-model","","primary")+
'</div>'}
return pageHead("STORE WORKSPACE",s.name+
" · 门店资料","门店经营资料由本店在前端维护，与平台管理员后台独立。",btn("返回工作台","nav-ai"))+
'<div class="tabs store-tabs" role="tablist" aria-label="门店资料分类">'+getStoreNav().map(x=>'<button type="button" role="tab" aria-selected="'+(getStoreTab()===x[0]?"true":"false")+
'" id="store-tab-'+x[0]+'" aria-controls="store-tab-panel" data-store-tab="'+x[0]+
'" class="'+(getStoreTab()===x[0]?"active":"")+
'">'+x[1]+
'</button>').join("")+
'</div><div id="store-tab-panel" role="tabpanel" aria-labelledby="store-tab-'+getStoreTab()+'" tabindex="0">'+body+'</div>'}
 return {renderStore};
}
