import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  clearCsrfToken,
  confirmStoreProfileFacts,
  createStoreProfile,
  getCurrentUser,
  getStoreProfile,
  getStores,
  login,
  logout,
  refreshCsrfToken,
  setActiveStore,
  updateStoreProfile,
  type ProfileInput,
  type StoreMembership,
  type StoreProfile,
  type User,
} from "./api";
import ProductWorkspace from "./ProductWorkspace";
import OfferWorkspace from "./OfferWorkspace";
import BrandGuidelineWorkspace from "./BrandGuidelineWorkspace";
import AudienceWorkspace from "./AudienceWorkspace";
import KnowledgeWorkspace from "./KnowledgeWorkspace";
import MediaAssetsWorkspace from "./MediaAssetsWorkspace";
import MarketingTaskWorkspace from "./MarketingTaskWorkspace";
import ChannelAccountsWorkspace from "./ChannelAccountsWorkspace";
import HotspotWorkspace from "./HotspotWorkspace";
import EffectsWorkspace from "./EffectsWorkspace";

interface ProfileForm {
  display_name: string;
  business_type: string;
  industry_category: string;
  brand_name: string;
  introduction: string;
  country_code: string;
  region: string;
  province: string;
  city: string;
  district: string;
  address: string;
  phone: string;
  opening_summary: string;
  weekday_hours: string;
  weekend_hours: string;
  holiday_hours: string;
  temporary_closures: string;
  service_radius: string;
  service_capabilities: string;
}

const emptyForm: ProfileForm = {
  display_name: "",
  business_type: "",
  industry_category: "",
  brand_name: "",
  introduction: "",
  country_code: "CN",
  region: "",
  province: "",
  city: "",
  district: "",
  address: "",
  phone: "",
  opening_summary: "",
  weekday_hours: "",
  weekend_hours: "",
  holiday_hours: "",
  temporary_closures: "[]",
  service_radius: "",
  service_capabilities: "",
};

function formFromProfile(profile: StoreProfile): ProfileForm {
  const hours = profile.opening_hours_json ?? {};
  return {
    display_name: profile.display_name,
    business_type: profile.business_type ?? "",
    industry_category: profile.industry_category ?? "",
    brand_name: profile.brand_name ?? "",
    introduction: profile.introduction ?? "",
    country_code: profile.country_code ?? "CN",
    region: profile.region ?? "",
    province: profile.province ?? "",
    city: profile.city ?? "",
    district: profile.district ?? "",
    address: profile.address ?? "",
    phone: profile.phone ?? "",
    opening_summary: String(hours.summary ?? ""),
    weekday_hours: String(hours.weekday ?? ""),
    weekend_hours: String(hours.weekend ?? ""),
    holiday_hours: String(hours.holiday ?? ""),
    temporary_closures: JSON.stringify(profile.temporary_closures_json ?? [], null, 2),
    service_radius: profile.service_radius ?? "",
    service_capabilities: (profile.service_capabilities_json ?? []).join("、"),
  };
}

function profileInput(form: ProfileForm): ProfileInput {
  let closures: unknown;
  try {
    closures = JSON.parse(form.temporary_closures.trim() || "[]");
  } catch {
    throw new Error("临时停业日期必须是有效 JSON 数组");
  }
  if (!Array.isArray(closures) || closures.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error("临时停业日期必须是对象数组，例如 [{\"date\":\"2026-12-25\",\"reason\":\"节假日停业\"}]");
  }
  return {
    display_name: form.display_name.trim(),
    business_type: form.business_type.trim(),
    industry_category: form.industry_category.trim(),
    brand_name: form.brand_name.trim(),
    introduction: form.introduction.trim(),
    country_code: form.country_code.trim().toUpperCase(),
    region: form.region.trim(),
    province: form.province.trim(),
    city: form.city.trim(),
    district: form.district.trim(),
    address: form.address.trim(),
    phone: form.phone.trim(),
    opening_hours_json: {
      summary: form.opening_summary.trim(),
      weekday: form.weekday_hours.trim(),
      weekend: form.weekend_hours.trim(),
      holiday: form.holiday_hours.trim(),
    },
    temporary_closures_json: closures as Array<Record<string, unknown>>,
    service_radius: form.service_radius.trim(),
    service_capabilities_json: form.service_capabilities
      .split(/[、,，]/)
      .map((value) => value.trim())
      .filter(Boolean),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误，请稍后重试";
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="field">
      <span>{label}{required ? " *" : ""}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
      />
    </label>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [stores, setStores] = useState<StoreMembership[]>([]);
  const [storesReady, setStoresReady] = useState(false);
  const [storeId, setStoreId] = useState("");
  const [profile, setProfile] = useState<StoreProfile | null>(null);
  const [form, setForm] = useState<ProfileForm>(emptyForm);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [profileLoading, setProfileLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [route, setRoute] = useState(window.location.hash || "#store:profile");
  const [navOpen, setNavOpen] = useState(false);
  const productRoute = route === "#store:products" || route.startsWith("#store-editor:product:");
  const offerRoute = route === "#store:offers" || route.startsWith("#store-editor:offer:");
  const brandRoute = route === "#store:brand";
  const audienceRoute = route === "#store:audience" || route.startsWith("#store-editor:audience:");
  const knowledgeRoute = route === "#store:knowledge" || route.startsWith("#store-editor:knowledge:");
  const assetsRoute = route === "#store:assets";
  const channelsRoute = route === "#store:channels";
  const hotspotRoute = route === "#hotspots" || route.startsWith("#hotspot-detail:");
  const effectsRoute = route === "#effects";
  const taskWorkspaceRoute = ["#ai", "#tasks", "#create", "#task"].includes(route);

  const loadStoreContext = useCallback(async () => {
    setStoresReady(false);
    const response = await getStores();
    setStores(response.items);
    if (!response.items.length) {
      setStoreId("");
      setStoresReady(true);
      return;
    }
    let activeId = response.active_store_id;
    if (!activeId || !response.items.some((store) => store.id === activeId)) {
      activeId = response.items[0].id;
      setStoreId(activeId);
      try {
        await setActiveStore(activeId);
      } catch (reason) {
        // Keep the locally selected store usable; surface the context error separately.
        setError(errorMessage(reason));
      }
    }
    setStoreId(activeId);
    setStoresReady(true);
  }, []);

  useEffect(() => {
    const onRouteChange = () => {
      setRoute(window.location.hash || "#store:profile");
      setNavOpen(false);
    };
    window.addEventListener("hashchange", onRouteChange);
    return () => window.removeEventListener("hashchange", onRouteChange);
  }, []);

  useEffect(() => {
    let active = true;
    void getCurrentUser()
      .then(async (currentUser) => {
        if (!active) return;
        setUser(currentUser);
        await refreshCsrfToken();
        await loadStoreContext();
      })
      .catch((reason: unknown) => {
        if (active && !(reason instanceof ApiError && reason.status === 401)) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loadStoreContext]);

  useEffect(() => {
    if (!storeId) {
      setProfile(null);
      setForm(emptyForm);
      return;
    }
    let active = true;
    setProfileLoading(true);
    setError("");
    void getStoreProfile(storeId)
      .then((value) => {
        if (!active) return;
        setProfile(value);
        setForm(formFromProfile(value));
        setDirty(false);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 404) {
          setProfile(null);
          setForm(emptyForm);
          setDirty(false);
        } else {
          setError(errorMessage(reason));
        }
      })
      .finally(() => {
        if (active) setProfileLoading(false);
      });
    return () => {
      active = false;
    };
  }, [storeId]);

  function change<K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setDirty(true);
    setNotice("");
  }

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const currentUser = await login(email, password);
      setUser(currentUser);
      await loadStoreContext();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!storeId) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const payload = profileInput(form);
      const saved = profile
        ? await updateStoreProfile(storeId, profile, payload)
        : await createStoreProfile(storeId, payload);
      setProfile(saved);
      setForm(formFromProfile(saved));
      setDirty(false);
      setNotice(`门店档案已保存为 V${saved.current_version}。关键经营事实变更后需要重新确认。`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  async function confirmFacts() {
    if (!storeId || !profile || dirty) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const confirmed = await confirmStoreProfileFacts(storeId, profile);
      setProfile(confirmed);
      setForm(formFromProfile(confirmed));
      setDirty(false);
      setNotice(`门店档案 V${confirmed.current_version} 已确认。`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  async function reloadProfile() {
    if (!storeId) return;
    setProfileLoading(true);
    setError("");
    try {
      const latest = await getStoreProfile(storeId);
      setProfile(latest);
      setForm(formFromProfile(latest));
      setDirty(false);
      setNotice("已加载服务器最新版本。");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setProfileLoading(false);
    }
  }

  async function signOut() {
    setError("");
    try {
      await logout();
      clearCsrfToken();
      setUser(null);
      setStores([]);
      setStoresReady(false);
      setStoreId("");
      setProfile(null);
      setPassword("");
      setNotice("");
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }

  async function retryStoreContext() {
    setLoading(true);
    setError("");
    try {
      await loadStoreContext();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return <main className="center-state"><span className="spinner" />正在验证登录状态…</main>;
  }

  if (!user) {
    return (
      <main className="auth-layout">
        <section className="auth-card">
          <div className="brand-line"><span className="brand-mark">AI</span><strong>AI 门店运营官</strong></div>
          <p className="eyebrow">STORE OPERATIONS</p>
          <h1>登录门店工作台</h1>
          <p className="muted">使用已开通门店成员权限的账号登录。</p>
          {error && <div className="alert error" role="alert">{error}</div>}
          <form onSubmit={submitLogin}>
            <Field label="邮箱" value={email} onChange={setEmail} placeholder="name@example.com" required />
            <label className="field">
              <span>密码 *</span>
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
            </label>
            <button className="primary full" type="submit" disabled={!email.trim() || !password || loading}>
              {loading ? "登录中…" : "登录"}
            </button>
          </form>
          <p className="footnote">登录使用服务端 Session Cookie 与 CSRF 防护；本页面不保存密码。</p>
        </section>
      </main>
    );
  }

  const storeContextFallback = !stores.length ? (
    storesReady ? (
      <section className="empty-card">
        <h2>当前账号尚未加入门店</h2>
        <p>请联系门店所有者邀请你加入后，再维护门店经营资料。平台管理员账号不绑定门店，请从平台运营后台登录。</p>
        <button className="text-button" type="button" onClick={() => void signOut()}>退出并切换账号</button>
      </section>
    ) : (
      <section className="empty-card">
        <h2>门店信息读取失败</h2>
        <p>登录状态已建立，但未能读取门店归属，请重试。</p>
        <button className="text-button" type="button" onClick={() => void retryStoreContext()}>重新读取</button>
      </section>
    )
  ) : null;

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className="nav-toggle"
          type="button"
          aria-label={navOpen ? "关闭导航菜单" : "打开导航菜单"}
          aria-expanded={navOpen}
          onClick={() => setNavOpen((current) => !current)}
        >
          <span className="nav-toggle-bars" aria-hidden="true" />
        </button>
        <div className="brand-line"><span className="brand-mark">AI</span><strong>AI 门店运营官</strong></div>
        <div className="top-actions">
          {stores.length > 0 && (
            <span className="store-picker static">
              <span>当前门店</span>
              <strong>{stores.find((store) => store.id === storeId)?.name ?? stores[0].name}</strong>
            </span>
          )}
          <span className="user-email">{user.email}</span>
          <button className="quiet-button" type="button" onClick={() => void signOut()}>退出</button>
        </div>
      </header>
      <div className="workspace">
        {navOpen && <button className="nav-backdrop" type="button" aria-label="关闭导航菜单" onClick={() => setNavOpen(false)} />}
        <aside className={navOpen ? "sidebar open" : "sidebar"} onClick={(event) => { if ((event.target as HTMLElement).closest("a")) setNavOpen(false); }}>
          <div className="side-label">门店工作台</div>
          <a className={route === "#ai" ? "side-link active" : "side-link"} href="#ai">AI 营销</a>
          <a className={["#tasks", "#create", "#task"].includes(route) ? "side-link active" : "side-link"} href="#tasks">营销任务</a>
          <a className={hotspotRoute ? "side-link active" : "side-link"} href="#hotspots">发现营销机会</a>
          <a className={effectsRoute ? "side-link active" : "side-link"} href="#effects">经营效果</a>
          <div className="side-label spaced">门店资料</div>
          <a className={productRoute || offerRoute || brandRoute || audienceRoute || knowledgeRoute || assetsRoute || channelsRoute || taskWorkspaceRoute || hotspotRoute || effectsRoute ? "side-link" : "side-link active"} href="#store:profile">门店档案</a>
          <a className={productRoute ? "side-link active" : "side-link"} href="#store:products">商品与服务</a>
          <a className={offerRoute ? "side-link active" : "side-link"} href="#store:offers">活动与优惠</a>
          <a className={brandRoute ? "side-link active" : "side-link"} href="#store:brand">品牌规范</a>
          <a className={audienceRoute ? "side-link active" : "side-link"} href="#store:audience">客群与经营</a>
          
          <a className={knowledgeRoute ? "side-link active" : "side-link"} href="#store:knowledge">门店知识库</a>
          <a className={assetsRoute ? "side-link active" : "side-link"} href="#store:assets">素材资产库</a>
          <a className={channelsRoute ? "side-link active" : "side-link"} href="#store:channels">渠道账号</a>
          <div className="sidebar-foot">当前已接入真实门店档案、商品与服务、活动与优惠、品牌规范、客群与经营、门店知识库、素材资产，以及营销任务的需求确认、策略生成与确认、文案与图片生成审核。内容质检、渠道适配与交付需先由平台管理员发布经官方来源核验的渠道规格后方可使用；抖音账号 OAuth 页面已接入，真实应用凭据与账号授权验收仍待完成，不使用演示数据冒充生产数据。</div>
        </aside>
        <main className="content">
          {!stores.length ? storeContextFallback : taskWorkspaceRoute ? <MarketingTaskWorkspace storeId={storeId} /> : hotspotRoute ? <HotspotWorkspace storeId={storeId} /> : effectsRoute ? <EffectsWorkspace storeId={storeId} /> : productRoute ? <ProductWorkspace storeId={storeId} /> : offerRoute ? <OfferWorkspace storeId={storeId} /> : brandRoute ? <BrandGuidelineWorkspace storeId={storeId} /> : audienceRoute ? <AudienceWorkspace storeId={storeId} /> : knowledgeRoute ? <KnowledgeWorkspace storeId={storeId} /> : assetsRoute ? <MediaAssetsWorkspace storeId={storeId} /> : channelsRoute ? <ChannelAccountsWorkspace storeId={storeId} /> : <>
          <div className="page-heading">
            <div>
              <p className="eyebrow">STORE PROFILE</p>
              <h1>门店档案</h1>
              <p className="muted">维护门店基础经营事实，为后续策略与内容生成提供可信上下文。</p>
            </div>
            {profile && <div className="version-chip">V{profile.current_version} · {profile.fact_status === "confirmed" ? "已确认" : "待确认"}</div>}
          </div>
          {error && (
            <div className="alert error" role="alert">
              <span>{error}</span>
              {error.includes("VERSION_CONFLICT") || error.includes("changed") ? <button className="text-button" onClick={() => void reloadProfile()}>重新加载最新版本</button> : null}
            </div>
          )}
          {notice && <div className="alert success" role="status">{notice}</div>}
          {!stores.length ? storeContextFallback : profileLoading ? (
            <div className="loading-card"><span className="spinner" />正在读取门店档案…</div>
          ) : (
            <form className="profile-form" onSubmit={saveProfile}>
              <section className="form-card">
                <div className="section-title"><div><h2>门店基本信息</h2><p>门店主体、业态和品牌归属。</p></div></div>
                <div className="form-grid">
                  <Field label="门店名称" value={form.display_name} onChange={(value) => change("display_name", value)} required />
                  <Field label="品牌 / 连锁归属" value={form.brand_name} onChange={(value) => change("brand_name", value)} />
                  <Field label="门店类型" value={form.business_type} onChange={(value) => change("business_type", value)} placeholder="直营门店 / 加盟门店 / 单体门店" />
                  <Field label="业态分类" value={form.industry_category} onChange={(value) => change("industry_category", value)} placeholder="餐饮、饮品、美容、零售…" />
                  <div className="field span-2">
                    <span>门店简介</span>
                    <textarea rows={3} value={form.introduction} onChange={(event) => change("introduction", event.target.value)} placeholder="介绍门店主营业务、服务特色和经营定位。" />
                  </div>
                </div>
              </section>
              <section className="form-card">
                <div className="section-title"><div><h2>联系方式与地址</h2><p>请填写可用于经营信息核对的真实资料。</p></div></div>
                <div className="form-grid">
                  <Field label="国家 / 地区代码" value={form.country_code} onChange={(value) => change("country_code", value)} placeholder="CN" />
                  <Field label="联系电话" value={form.phone} onChange={(value) => change("phone", value)} />
                  <Field label="省 / 州" value={form.province} onChange={(value) => change("province", value)} />
                  <Field label="城市" value={form.city} onChange={(value) => change("city", value)} />
                  <Field label="区 / 县" value={form.district} onChange={(value) => change("district", value)} />
                  <Field label="区域 / 商圈" value={form.region} onChange={(value) => change("region", value)} />
                  <div className="field span-2">
                    <span>详细地址</span>
                    <input value={form.address} onChange={(event) => change("address", event.target.value)} placeholder="街道、门牌号、楼层及店铺位置" />
                  </div>
                </div>
              </section>
              <section className="form-card">
                <div className="section-title"><div><h2>营业与接待</h2><p>明确营业时间和服务边界，避免 AI 对外作出未经确认的承诺。</p></div></div>
                <div className="form-grid">
                  <Field label="营业时间摘要" value={form.opening_summary} onChange={(value) => change("opening_summary", value)} placeholder="例如 10:00–22:00" />
                  <Field label="工作日营业时间" value={form.weekday_hours} onChange={(value) => change("weekday_hours", value)} />
                  <Field label="周末营业时间" value={form.weekend_hours} onChange={(value) => change("weekend_hours", value)} />
                  <Field label="节假日营业时间" value={form.holiday_hours} onChange={(value) => change("holiday_hours", value)} />
                  <Field label="服务半径" value={form.service_radius} onChange={(value) => change("service_radius", value)} placeholder="例如 3 公里" />
                  <Field label="服务能力" value={form.service_capabilities} onChange={(value) => change("service_capabilities", value)} placeholder="堂食、自取、外卖（用顿号分隔）" />
                  <div className="field span-2">
                    <span>临时停业日期（JSON 数组）</span>
                    <textarea rows={3} value={form.temporary_closures} onChange={(event) => change("temporary_closures", event.target.value)} />
                    <small>示例：[{"{"}"date":"2026-12-25","reason":"节假日停业"{"}"}]</small>
                  </div>
                </div>
              </section>
              <div className="form-footer">
                <p>保存会创建新版本，并将档案事实状态重置为「待确认」。</p>
                <div className="form-actions">
                  {profile && <button className="secondary" type="button" onClick={() => void reloadProfile()}>放弃修改</button>}
                  {profile && profile.fact_status !== "confirmed" && (
                    <button className="secondary" type="button" onClick={() => void confirmFacts()} disabled={saving || dirty} title={dirty ? "请先保存修改，再确认资料" : undefined}>
                      确认资料
                    </button>
                  )}
                  <button className="primary" type="submit" disabled={saving || !form.display_name.trim()}>
                    {saving ? "处理中…" : profile ? "保存档案" : "创建门店档案"}
                  </button>
                </div>
              </div>
            </form>
          )}
          </>}
        </main>
      </div>
    </div>
  );
}
