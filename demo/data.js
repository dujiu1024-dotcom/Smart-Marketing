export const seed = {
  store:{id:"store-001",name:"拾光茶研社（万象城店）",brand:"拾光茶研社",code:"SG-001",businessEntity:"杭州拾光品牌管理有限公司",latitude:"30.2501",longitude:"120.2123",closedDates:"",type:"直营门店",industry:"餐饮 · 茶饮",category:"现制茶饮",intro:"主打鲜果茶与轻乳茶，坚持当季水果、门店现制。",country:"中国",province:"浙江省",city:"杭州市",district:"上城区",address:"钱江路 158 号万象城 B1 层",phone:"0571-8800-1234",contact:"林店长",contactPhone:"138****6201",hours:"10:00-22:00",weekdayHours:"10:00-22:00",weekendHours:"10:00-22:30",holidayHours:"节假日 10:00-22:30",storeSize:"约 90 平方米",seats:"18 个座位",serviceType:"堂食 / 自取 / 外卖",serviceRadius:"3 公里",capacity:"高峰时段约 80 杯/小时",openedAt:"2023-05-18",audience:"18-35 岁周边白领、年轻家庭、逛街客群",scenes:"午后休闲、逛街途中、下班带走、周末朋友聚会",positioning:"新鲜、轻负担、门店现制的日常茶饮",tone:"自然、清爽、有生活感，不夸张、不网红腔",strengths:"当季水果现切；茶底每日现泡；门店交通便利",goals:"提升工作日下午到店订单；推广当季鲜果系列",peak:"周五晚间、周末下午；工作日 14:00-17:00 较弱",constraints:"晚间备料有限；鲜果类商品售完即止",logo:"拾光茶研社",primaryColor:"#245B4A",secondaryColor:"#E7B96B",font:"清爽现代黑体",visualStyle:"自然光、木质、真实水果质感",forbidden:"零添加（未经证明）、全网第一、治疗、减肥",cta:"到店尝鲜 / 查看本店菜单",lastUpdated:"2026-11-08"},
  products:[
    {id:"p1",name:"当季草莓鲜奶",category:"鲜果茶",sku:"ST-450",spec:"中杯 450ml / 大杯 650ml",price:22,unit:"杯",status:"在售",stock:"每日限量 120 杯",selling:"当季草莓现切、鲜奶茶底、酸甜清爽",description:"使用当季草莓与鲜奶制作，门店现制。",ingredients:"草莓、鲜奶、茶底、冰糖",allergens:"含乳制品",service:"现点现做，约 3-5 分钟",delivery:"到店自取 / 外卖",priority:"主推",availableHours:"10:00-22:00",cost:"内部字段 · 仅授权角色可见",margin:"未接入成本数据",assetIds:["a1"],confirmed:true},
    {id:"p2",name:"桂花乌龙轻乳茶",category:"轻乳茶",sku:"OL-500",spec:"中杯 500ml / 大杯 700ml",price:19,unit:"杯",status:"在售",stock:"常规供应",selling:"桂花香气、乌龙茶底、轻乳口感",description:"乌龙茶与轻乳融合，茶香明显。",ingredients:"乌龙茶、牛乳、桂花",allergens:"含乳制品",service:"现点现做，约 3 分钟",delivery:"到店自取 / 外卖",priority:"常规",availableHours:"10:00-22:00",cost:"内部字段 · 仅授权角色可见",margin:"未接入成本数据",assetIds:[],confirmed:true},
    {id:"p3",name:"青提茉莉冰茶",category:"果茶",sku:"GT-480",spec:"中杯 480ml",price:21,unit:"杯",status:"在售",stock:"受当日水果供应影响",selling:"青提果香、茉莉茶底、清爽回甘",description:"青提与茉莉茶底组合。",ingredients:"青提、茉莉茶、糖浆",allergens:"无已知常见过敏原，需以实际配方为准",service:"现点现做",delivery:"到店自取 / 外卖",priority:"主推",availableHours:"10:00-22:00",cost:"内部字段 · 仅授权角色可见",margin:"未接入成本数据",assetIds:[],confirmed:true}
  ],
  offers:[{id:"o1",name:"下午茶双杯组合",type:"组合优惠",products:"当季草莓鲜奶、桂花乌龙轻乳茶",rule:"两杯立减 5 元",start:"2026-11-01",end:"2026-11-30",audience:"全体顾客",condition:"堂食及自取可用",stack:"不可与其他优惠叠加",quota:"每日限量 40 组",redemption:"收银台报活动名称",approvedBy:"店长",status:"进行中"}],
  knowledge:[{id:"k1",title:"品牌介绍与门店故事",type:"品牌资料",source:"商家录入",version:"v2",owner:"店长",valid:"长期有效",effectiveAt:"2026-01-01",expireAt:"",visibility:"门店运营",status:"已确认",body:"拾光茶研社专注现制鲜果茶与轻乳茶，强调当季水果和真实茶香。"} ,{id:"k2",title:"鲜果类产品制作规范",type:"产品规范",source:"门店 SOP",version:"v1",owner:"运营经理",valid:"2026-12-31",effectiveAt:"2026-01-01",expireAt:"2026-12-31",visibility:"门店运营",status:"已确认",body:"水果每日验收，现切现用；售完即止，不得宣传全天供应。"}],
  assets:[{id:"a1",name:"草莓鲜奶产品图.jpg",type:"产品图",format:"JPG",size:"1.8 MB",dimensions:"1600 × 1600",product:"当季草莓鲜奶",rights:"门店自有",status:"可使用",source:"商家上传",dataUrl:"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='640'%3E%3Crect width='640' height='640' fill='%23f4e8df'/%3E%3Ccircle cx='320' cy='270' r='150' fill='%23c85b5b' opacity='.7'/%3E%3Cpath d='M180 400 Q320 480 460 400' stroke='%23245b4a' stroke-width='24' fill='none'/%3E%3Ctext x='320' y='560' text-anchor='middle' font-size='34' fill='%23245b4a'%3E%E8%8D%89%E8%8E%93%E9%B2%9C%E5%A5%B6%E6%BA%90%E5%9B%BE%E6%BC%94%E7%A4%BA%3C/text%3E%3C/svg%3E",uploadedBy:"店长",tags:"门店,环境",uploadedAt:"2026-11-02",uploadedBy:"店长",tags:"草莓,产品主图",uploadedAt:"2026-11-02"},{id:"a2",name:"门店吧台环境.jpg",type:"门店环境",format:"JPG",size:"2.4 MB",dimensions:"1920 × 1280",product:"全店",rights:"门店自有",status:"可使用",source:"商家上传",dataUrl:"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='420'%3E%3Crect width='640' height='420' fill='%23e5e8df'/%3E%3Crect x='90' y='90' width='460' height='240' rx='24' fill='%23b6a68e'/%3E%3Crect x='140' y='130' width='360' height='160' rx='12' fill='%23f4eee4'/%3E%3Ctext x='320' y='375' text-anchor='middle' font-size='28' fill='%23245b4a'%3E%E9%97%A8%E5%BA%97%E5%90%A7%E5%8F%B0%E6%BA%90%E5%9B%BE%E6%BC%94%E7%A4%BA%3C/text%3E%3C/svg%3E"}],
  channels:[{id:"c1",platform:"小红书",account:"拾光茶研社杭州店",accountId:"xhs_store_001",status:"未连接",scopes:"草稿 / 数据读取",expires:"—",capabilities:"内容预览",lastSync:"—"},{id:"c2",platform:"抖音",account:"拾光茶研社",accountId:"dy_store_001",status:"未连接",scopes:"视频 / 数据读取",expires:"—",capabilities:"内容预览",lastSync:"—"},{id:"c3",platform:"微信视频号",account:"拾光茶研社",accountId:"wx_video_001",status:"未连接",scopes:"视频 / 数据读取",expires:"—",capabilities:"内容预览",lastSync:"—"},{id:"c4",platform:"快手",account:"拾光茶研社",accountId:"ks_store_001",status:"未连接",scopes:"内容 / 数据读取",expires:"—",capabilities:"内容预览",lastSync:"—"}],
  tasks:[
    {id:"t1001",title:"当季草莓鲜奶新品推广",goal:"提升当季鲜果系列的本地曝光与到店尝鲜",type:"新品推广",product:"当季草莓鲜奶",audience:"周边 18-35 岁白领与逛街客群",channels:["小红书","抖音"],status:"待文案审核",copyStatus:"pending",imageStatus:"not_started",publishStatus:"未发布",createdAt:"2026-11-09 10:20",updatedAt:"2026-11-10 09:40",scheduledAt:"待确认",strategy:{objective:"提升新品认知与到店尝鲜意愿",kpi:"内容互动、菜单点击、到店咨询（数据接入后验证）",audience:"周边白领、年轻家庭、周末逛街客群",scene:"工作日下午茶与商场逛街途中",insight:"门店工作日 14:00-17:00 为相对弱时段；新品草莓鲜奶有明确季节性卖点。",selling:"当季草莓现切、鲜奶茶底、门店现制",theme:"把当季草莓的清甜，留给下午",channels:"小红书用于图文种草；抖音用于制作过程短视频",offer:"本任务不自动创建优惠；如需活动需商家确认规则。",assets:"草莓产品图、吧台制作过程图",risks:"鲜果供应每日变化；不可承诺全天有货；含乳制品需注意过敏提示。",measurement:"发布后接入平台内容指标；经营数据源接入后观察到店/订单变化。"},copy:{xhs:{title:"把当季草莓的清甜，留给一个好下午",body:"最近门店的草莓鲜奶进入当季供应啦。\n草莓现切，搭配鲜奶茶底，酸甜清爽。\n下午逛街或下班路过，可以来店里尝一杯。\n鲜果供应以当日实际情况为准。",tags:"#杭州探店 #鲜果茶 #下午茶"},douyin:{title:"当季草莓鲜奶，今天现切",body:"镜头从草莓清洗、现切开始，展示鲜奶茶底与出杯过程。口播：当季草莓现切，搭配鲜奶茶底，酸甜清爽。到店可询问当日供应。",tags:"#现制茶饮 #草莓季"},video:{title:"门店今日鲜果制作记录",body:"用门店真实制作画面介绍当日鲜果供应与制作过程。",tags:"#门店日常"},kuaishou:{title:"今天门店的草莓鲜奶",body:"展示真实制作过程，介绍口味与当日供应情况。",tags:"#本地生活"}},
      copyReviews:[],imageVersions:[],events:[{time:"2026-11-10 09:40",label:"文案版本 V1 已生成",detail:"使用门店画像、商品资料和营销策略生成",status:"done"},{time:"2026-11-10 09:42",label:"等待商家审核",detail:"当前审核对象：小红书文案 V1",status:"pending"}]}
  ],
  hotspots:[
    {id:"hot-001",title:"秋冬热饮与暖饮消费场景",category:"季节趋势",region:"全国趋势 · 待本地验证",source:"演示样例数据，非实时采集",collectedAt:"2026-11-10 09:00",expiresAt:"2026-11-17",heat:"高",matchScore:92,matchedProducts:["桂花乌龙轻乳茶"],audience:"通勤白领、偏好热饮的消费者",scene:"降温后的通勤、午后暖饮",reason:"门店已有桂花乌龙轻乳茶，产品特征与秋冬暖饮场景相符；需由门店确认热饮供应与配方",risk:"需确认该商品是否提供热饮规格，不得把全国趋势描述为本地实时热度",angle:"围绕降温时段的热饮选择，制作真实出杯与茶底介绍内容",format:"门店短视频 / 图文",status:"待处理"},
    {id:"hot-002",title:"工作日下午茶与轻休闲内容",category:"消费场景",region:"城市商圈场景 · 待本地验证",source:"演示样例数据，非实时采集",collectedAt:"2026-11-10 09:00",expiresAt:"2026-11-20",heat:"中",matchScore:88,matchedProducts:["当季草莓鲜奶","桂花乌龙轻乳茶"],audience:"周边白领、商场逛街客群",scene:"工作日 14:00-17:00 午后休闲",reason:"与门店已录入的工作日下午弱时段及商圈客群匹配",risk:"场景匹配不等于实际需求增长，需用后续内容数据验证",angle:"把门店下午时段与真实制作过程结合，提供轻量到店理由",format:"小红书图文 / 短视频",status:"待处理"},
    {id:"hot-003",title:"当季草莓与鲜果饮品内容",category:"时令食材",region:"季节性主题 · 供应需核验",source:"演示样例数据，非实时采集",collectedAt:"2026-11-10 09:00",expiresAt:"2026-11-15",heat:"高",matchScore:95,matchedProducts:["当季草莓鲜奶"],audience:"年轻客群、鲜果饮品偏好者",scene:"当季尝鲜、逛街途中",reason:"与门店主推商品及现切草莓卖点直接相关",risk:"鲜果供应每日变化，发布前必须确认库存和可售状态",angle:"以当日真实草莓验收、现切和出杯过程作为内容主体",format:"产品实拍图文 / 制作短视频",status:"待处理"}
  ],
  effects:{reports:[],sources:[]},
  admin:{users:[{id:"u1",name:"门店店长",email:"manager@example.com",status:"启用"},{id:"u2",name:"品牌运营",email:"ops@example.com",status:"启用"}],prompts:[{id:"pr1",name:"门店营销策略生成",version:"v1.4",scope:"策略",status:"草稿",updated:"2026-11-10"},{id:"pr2",name:"平台文案生成",version:"v2.1",scope:"文案",status:"已发布",updated:"2026-11-08"}],budgetConfig:{limit:"",threshold:"80%"},systemConfig:{name:"AI 门店运营官",timezone:"Asia/Shanghai",retention:"365 天"},audit:[],runs:[{id:"run1",task:"t1001",node:"copy_generation",model:"文本模型（示例）",status:"模拟完成",duration:"2.4s",cost:"模拟成本",at:"2026-11-10 09:40"}]}

};
seed.store.industryCategory="饮品";
seed.store.category="现制茶饮";
seed.products.forEach(p=>{delete p.cost;delete p.margin});
seed.offers.forEach(o=>{delete o.approvedBy});
seed.admin.systemConfig.industryCategories=["餐饮","饮品","美容","按摩","健身","零售","生活服务","宠物服务","教育培训"];
seed.stores=[
 {...JSON.parse(JSON.stringify(seed.store)),id:"store-001",name:"拾光茶研社（万象城店）",code:"SG-001",industryCategory:"饮品",industry:"餐饮 · 茶饮",category:"现制茶饮",status:"正常",users:[{id:"u1",name:"林店长",email:"manager@example.com",status:"启用"},{id:"u2",name:"周运营",email:"ops@example.com",status:"启用"}],modelConfig:{vendor:"OpenAI 兼容接口",model:"gpt-6-mini",endpoint:"https://api.example.com/v1",keyRef:"vault://store-001/key",textModel:"gpt-6-mini",imageModel:"image-model-demo"}},
 {...JSON.parse(JSON.stringify(seed.store)),id:"store-002",name:"拾光茶研社（湖滨店）",code:"SG-002",industryCategory:"饮品",industry:"餐饮 · 茶饮",category:"现制茶饮",city:"杭州市",district:"上城区",address:"平海路 124 号",status:"正常",users:[{id:"u3",name:"陈店长",email:"hubin@example.com",status:"启用"}],modelConfig:{vendor:"未配置"}},
 {...JSON.parse(JSON.stringify(seed.store)),id:"store-003",name:"木棉轻食（滨江店）",code:"MM-003",industryCategory:"餐饮",industry:"餐饮 · 轻食",category:"轻食简餐",city:"杭州市",district:"滨江区",address:"江南大道 188 号",status:"正常",users:[{id:"u4",name:"王店长",email:"binjiang@example.com",status:"启用"}],modelConfig:{vendor:"未配置"}},
 {...JSON.parse(JSON.stringify(seed.store)),id:"store-004",name:"悦己皮肤管理（城西店）",code:"YJ-004",industryCategory:"美容",industry:"生活服务 · 美容",category:"皮肤管理",city:"杭州市",district:"西湖区",address:"文三路 88 号",status:"试运营",users:[{id:"u5",name:"许店长",email:"beauty@example.com",status:"启用"}],modelConfig:{vendor:"未配置"}},
 {...JSON.parse(JSON.stringify(seed.store)),id:"store-005",name:"力场健身工作室（钱江店）",code:"LC-005",industryCategory:"健身",industry:"运动健身",category:"私教工作室",city:"杭州市",district:"上城区",address:"钱江路 288 号",status:"正常",users:[{id:"u6",name:"赵店长",email:"fitness@example.com",status:"启用"}],modelConfig:{vendor:"未配置"}}
];
seed.admin.prompts=[
 {id:"pr-food-brief",name:"餐饮需求理解",industryCategory:"餐饮",scope:"需求理解",version:"v1.0",status:"已发布",updated:"2026-11-10",template:"你是餐饮门店营销顾问。识别堂食、外卖、时段、菜品、套餐、产能与食品安全限制。只使用门店确认的价格、原料、供应和优惠事实。输出结构化需求、缺失信息和风险。"},
 {id:"pr-food-copy",name:"餐饮内容生成",industryCategory:"餐饮",scope:"文案生成",version:"v1.0",status:"已发布",updated:"2026-11-10",template:"围绕已确认菜品、真实制作过程、消费场景和活动规则生成多平台内容。禁止虚构食材来源、功效、价格、销量、奖项和优惠。"},
 {id:"pr-drink-strategy",name:"饮品营销策略",industryCategory:"饮品",scope:"营销策略",version:"v1.2",status:"已发布",updated:"2026-11-10",template:"你是现制饮品门店营销策略顾问。结合饮品品类、季节、时段、原料供应、制作产能、商圈和客群制定可执行策略。不得虚构热度、库存、价格或优惠。"},
 {id:"pr-drink-copy",name:"饮品平台文案",industryCategory:"饮品",scope:"文案生成",version:"v1.1",status:"已发布",updated:"2026-11-10",template:"为饮品门店生成小红书、抖音、视频号等独立内容。突出真实口味、原料、制作过程和适用场景。不得编造零添加、健康功效、全天供应或未确认优惠。"},
 {id:"pr-beauty",name:"美容服务内容规范",industryCategory:"美容",scope:"文案生成",version:"v1.0",status:"已发布",updated:"2026-11-10",template:"围绕已备案服务项目、流程、环境、资质和顾客体验生成内容。严禁医疗化表述、疗效保证、前后对比夸大和绝对化承诺。"},
 {id:"pr-massage",name:"按摩养护内容规范",industryCategory:"按摩",scope:"文案生成",version:"v1.0",status:"已发布",updated:"2026-11-10",template:"描述服务流程、环境、时长、适用场景与预约信息。不得宣称治疗疾病、保证疗效或替代医疗建议。"},
 {id:"pr-fitness",name:"健身课程营销",industryCategory:"健身",scope:"营销策略",version:"v1.0",status:"已发布",updated:"2026-11-10",template:"结合课程类型、教练资质、训练目标、场地容量和体验课规则设计内容。不得承诺固定减重、塑形结果或未经验证的效果。"},
 {id:"pr-retail",name:"零售商品营销",industryCategory:"零售",scope:"文案生成",version:"v1.0",status:"已发布",updated:"2026-11-10",template:"围绕真实商品参数、使用场景、库存和售后规则生成零售内容。不得虚构原价、折扣、库存和用户评价。"},
 {id:"pr-general-quality",name:"通用营销事实质检",industryCategory:"通用",scope:"内容质检",version:"v1.0",status:"已发布",updated:"2026-11-10",template:"检查商品、价格、优惠、供应、门店地址、营业时间、健康功效、绝对化用语和版权风险。未确认事实必须标记为待商家核验。"}
];
seed.products.push(
 {id:"p4",name:"杨枝甘露",category:"经典甜品饮品",sku:"YG-520",spec:"中杯 520ml",price:23,unit:"杯",status:"在售",stock:"每日限量 80 杯",selling:"芒果果肉与椰乳搭配",description:"现制芒果风味饮品。",ingredients:"芒果、椰乳、西米",allergens:"含椰乳",service:"现点现做",delivery:"到店自取 / 外卖",priority:"常规",availableHours:"10:00-22:00",assetIds:[],confirmed:true},
 {id:"p5",name:"冬季桂圆红枣茶",category:"季节热饮",sku:"DR-400",spec:"热饮 400ml",price:18,unit:"杯",status:"在售",stock:"每日限量 60 杯",selling:"桂圆与红枣风味热饮",description:"冬季限定热饮。",ingredients:"桂圆、红枣、茶底",allergens:"以实际配方为准",service:"现点现做",delivery:"到店自取",priority:"主推",availableHours:"10:00-22:00",assetIds:[],confirmed:true},
 {id:"p6",name:"双人下午茶套餐",category:"组合套餐",sku:"AF-002",spec:"饮品 2 杯 + 甜点 1 份",price:48,unit:"套",status:"在售",stock:"常规供应",selling:"适合朋友分享的组合套餐",description:"双人分享套餐。",ingredients:"按所选饮品和甜点",allergens:"需按具体商品核对",service:"现点现做",delivery:"堂食 / 自取",priority:"常规",availableHours:"14:00-18:00",assetIds:[],confirmed:true}
);
seed.offers.push(
 {id:"o2",name:"草莓鲜奶买一赠一",type:"买一赠一",products:"当季草莓鲜奶",rule:"指定时段买一杯赠同规格一杯",start:"2026-11-12",end:"2026-11-20",audience:"全体顾客",condition:"工作日 14:00-17:00；每日限量 30 组",stack:"不可与其他优惠叠加",quota:"每日 30 组",redemption:"点单时告知活动名称",status:"待确认"},
 {id:"o3",name:"双人下午茶组合",type:"套餐优惠",products:"双人下午茶套餐",rule:"套餐价 48 元",start:"2026-11-01",end:"2026-12-31",audience:"双人到店顾客",condition:"堂食适用",stack:"不与其他优惠同享",quota:"每日 20 套",redemption:"点单选择套餐",status:"进行中"},
 {id:"o4",name:"第二杯半价",type:"第二件半价",products:"桂花乌龙轻乳茶、青提茉莉冰茶",rule:"同单第二杯指定饮品半价",start:"2026-11-15",end:"2026-11-30",audience:"全体顾客",condition:"同一订单且指定商品",stack:"不可叠加",quota:"不限量，售完即止",redemption:"收银时自动核对",status:"待确认"}
);
seed.knowledge.push(
 {id:"k3",title:"门店服务与退款说明",type:"FAQ",source:"商家录入",version:"v1",owner:"门店维护",valid:"长期有效",effectiveAt:"2026-01-01",expireAt:"",visibility:"门店运营",status:"已确认",body:"外卖、堂食、自取方式以门店当日实际开放服务为准。"},
 {id:"k4",title:"活动优惠使用规范",type:"活动规则",source:"门店录入",version:"v1",owner:"门店维护",valid:"2026-12-31",effectiveAt:"2026-11-01",expireAt:"2026-12-31",visibility:"门店运营",status:"已确认",body:"所有优惠需明确商品范围、时间、数量限制和叠加规则。"}
);
const cloneTask=JSON.parse(JSON.stringify(seed.tasks[0]));
const extraTasks=[
 ["t1002","工作日下午茶到店内容","到店引流","双人下午茶套餐","待策略确认","内容制作中","未发布"],
 ["t1003","桂花乌龙轻乳茶秋冬热饮","新品推广","桂花乌龙轻乳茶","待文案审核","待审核","未发布"],
 ["t1004","双人下午茶套餐推广","活动促销","双人下午茶套餐","待图片审核","已通过","未发布"],
 ["t1005","门店真实制作过程内容","品牌内容","当季草莓鲜奶","待发布","已通过","待人工发布"],
 ["t1006","草莓鲜奶买一赠一活动","活动促销","当季草莓鲜奶","策略确认中","内容制作中","未发布"],
 ["t1007","青提茉莉冰茶内容更新","新品推广","青提茉莉冰茶","已发布","已通过","已发布"],
 ["t1008","周末商圈客群内容","到店引流","杨枝甘露","已归档","已通过","已归档"]
];
extraTasks.forEach((row,i)=>{const t=JSON.parse(JSON.stringify(cloneTask));Object.assign(t,{id:row[0],title:row[1],goal:row[1]+"，结合门店真实商品与活动规则完成内容制作。",type:row[2],product:row[3],status:row[4],copyStatus:row[5],publishStatus:row[6],createdAt:"2026-11-"+String(3+i).padStart(2,"0")+" 10:00",updatedAt:"2026-11-"+String(8+i%3).padStart(2,"0")+" 15:30",briefConfirmed:i!==1,strategyStatus:i===1?"draft":"confirmed",confirmedStrategySnapshot:null,activityContent:i===4?"买一赠一（待商家确认）":"无额外活动",events:[{time:"2026-11-10 15:30",label:"演示任务节点",detail:"用于检验任务列表、筛选和监控详情",status:"done"}]});if(t.strategyStatus==="confirmed")t.confirmedStrategySnapshot=JSON.stringify(t.strategy);if(i===6){t.publishPackage={snapshotId:"pkg-demo-1007",createdAt:"2026-11-09 18:20",channels:t.channels};t.briefConfirmed=true}if(i===7)t.archived=true;seed.tasks.push(t)});
seed.effects.reports=[
 {id:"er1",taskId:"t1007",date:"2026-11-10",title:"青提茉莉冰茶内容表现（演示）",period:"发布后 7 天观察样例",source:"模拟平台数据",metrics:{内容曝光:"12,480",互动:"612",收藏:"148",咨询:"36"},note:"数据完全为演示值，不代表真实平台采集或营销归因。"},
 {id:"er2",taskId:"t1005",date:"2026-11-09",title:"门店制作过程内容表现（演示）",period:"发布后 3 天观察样例",source:"模拟平台数据",metrics:{视频播放:"8,920",互动:"431",主页访问:"205",私信:"18"},note:"仅用于检验报告列表与指标呈现。"},
 {id:"er3",taskId:"t1003",date:"2026-11-08",title:"秋冬热饮主题内容（演示）",period:"发布后 2 天观察样例",source:"模拟平台数据",metrics:{内容曝光:"6,240",互动:"288",收藏:"92",咨询:"14"},note:"数据为本地构造样例，未连接真实渠道。"}
];
seed.admin.runs.push(
 {id:"run2",task:"t1002",node:"strategy_generation",model:"策略模型（模拟）",status:"模拟完成",duration:"3.1s",cost:"未计费",detail:"生成门店下午茶策略",at:"2026-11-10 10:02"},
 {id:"run3",task:"t1003",node:"copy_generation",model:"文本模型（模拟）",status:"模拟完成",duration:"2.8s",cost:"未计费",detail:"生成小红书与抖音文案",at:"2026-11-10 10:15"},
 {id:"run4",task:"t1004",node:"image_generation",model:"图像适配器（模拟）",status:"模拟完成",duration:"4.2s",cost:"未计费",detail:"生成活动海报示意图",at:"2026-11-10 11:20"},
 {id:"run5",task:"t1005",node:"quality_check",model:"规则质检（模拟）",status:"模拟完成",duration:"0.6s",cost:"未计费",detail:"完成内容规则检查",at:"2026-11-10 12:10"},
 {id:"run6",task:"t1006",node:"copy_generation",model:"文本模型（模拟）",status:"失败（模拟）",duration:"1.2s",cost:"未计费",detail:"演示一次生成失败，用于异常列表测试",at:"2026-11-10 13:30"},
 {id:"run7",task:"t1006",node:"copy_generation_retry",model:"文本模型（模拟）",status:"模拟完成",duration:"2.3s",cost:"未计费",detail:"模拟重试后成功",at:"2026-11-10 13:32"},
 {id:"run8",task:"t1007",node:"publish_package",model:"本地发布包适配器",status:"模拟完成",duration:"0.2s",cost:"未计费",detail:"仅保存待人工发布快照",at:"2026-11-09 18:20"}
);