import { useEffect, useState } from "react";
import { api, ApiError, clearCsrfToken, setCsrfToken, type AdminIdentity } from "./api";
import DispatchesPage from "./DispatchesPage";
import HotspotPage from "./HotspotPage";
import OverviewPage from "./OverviewPage";
import StoresPage from "./StoresPage";
import UsersPage from "./UsersPage";

type Tab = "overview" | "stores" | "users" | "hotspot" | "dispatches";
type SessionState = "loading" | "anonymous" | "forbidden" | "ready";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "数据总览" },
  { key: "stores", label: "门店管理" },
  { key: "users", label: "门店用户" },
  { key: "hotspot", label: "热点与匹配" },
  { key: "dispatches", label: "下发记录" },
];

function currentTab(): Tab {
  const hash = window.location.hash.replace("#", "");
  return TABS.some((item) => item.key === hash) ? (hash as Tab) : "overview";
}

export default function App() {
  const [session, setSession] = useState<SessionState>("loading");
  const [identity, setIdentity] = useState<AdminIdentity | null>(null);
  const [tab, setTab] = useState<Tab>(currentTab);
  const [userStoreFilter, setUserStoreFilter] = useState("");
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    void bootstrap();
    const onHashChange = () => setTab(currentTab());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  async function bootstrap() {
    try {
      const me = await api.me();
      const csrf = await api.refreshCsrf();
      setCsrfToken(csrf.csrf_token);
      setIdentity(me);
      setSession("ready");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 403) {
        setSession("forbidden");
      } else {
        setSession("anonymous");
      }
    }
  }

  function navigate(next: Tab) {
    setNavOpen(false);
    window.location.hash = next;
    setTab(next);
  }

  async function handleLogout() {
    try {
      const csrf = await api.refreshCsrf();
      setCsrfToken(csrf.csrf_token);
      await api.logout();
    } catch {
      // Session may already be expired; clearing local state is enough.
    } finally {
      clearCsrfToken();
      setIdentity(null);
      setSession("anonymous");
    }
  }

  if (session === "loading") {
    return <div className="boot">正在校验平台管理员身份…</div>;
  }

  if (session === "anonymous") {
    return <LoginScreen onSuccess={bootstrap} />;
  }

  if (session === "forbidden") {
    return (
      <div className="boot">
        <div className="boot-card">
          <h1>没有平台管理员权限</h1>
          <p className="muted">
            当前账号是门店用户，不能进入平台运营后台。门店经营、知识库与渠道授权请前往门店前端。
          </p>
          <button className="button primary" type="button" onClick={() => void handleLogout()}>
            退出登录
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      {navOpen ? (
        <button
          className="nav-backdrop"
          type="button"
          aria-label="关闭导航菜单"
          onClick={() => setNavOpen(false)}
        />
      ) : null}
      <aside className={navOpen ? "sidebar open" : "sidebar"}>
        <div className="brand">
          <span className="brand-mark">AI</span>
          <div>
            <strong>平台运营后台</strong>
            <span>AI 门店运营官</span>
          </div>
        </div>
        <nav>
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={tab === item.key ? "nav-item active" : "nav-item"}
              onClick={() => navigate(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          门店经营资料、知识库、素材与渠道账号留在门店前端，不在后台维护。
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="mobile-nav-toggle"
              type="button"
              aria-label={navOpen ? "关闭导航菜单" : "打开导航菜单"}
              aria-expanded={navOpen}
              onClick={() => setNavOpen((current) => !current)}
            >
              <span />
              <span />
              <span />
            </button>
            <span className="muted">平台管理员</span>
          </div>
          <div className="topbar-right">
            <span>{identity?.user.email}</span>
            <button className="button ghost small" type="button" onClick={() => void handleLogout()}>
              退出
            </button>
          </div>
        </header>
        <main className="content">
          {tab === "overview" ? (
            <OverviewPage
              onOpenStore={(storeId) => {
                if (storeId) setUserStoreFilter(storeId);
                navigate(storeId ? "users" : "stores");
              }}
              onOpenDispatch={() => navigate("dispatches")}
            />
          ) : null}
          {tab === "stores" ? (
            <StoresPage
              onViewUsers={(storeId) => {
                setUserStoreFilter(storeId);
                navigate("users");
              }}
            />
          ) : null}
          {tab === "users" ? <UsersPage initialStoreId={userStoreFilter} /> : null}
          {tab === "hotspot" ? <HotspotPage /> : null}
          {tab === "dispatches" ? <DispatchesPage /> : null}
        </main>
      </div>
    </div>
  );
}

function LoginScreen({ onSuccess }: { onSuccess: () => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  return (
    <div className="boot">
      <form
        className="login-card"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitting(true);
          setError("");
          api
            .login(email, password)
            .then((result) => {
              setCsrfToken(result.csrf_token);
              return onSuccess();
            })
            .catch((reason: unknown) => {
              if (
                reason instanceof ApiError &&
                reason.code === "PLATFORM_ADMIN_REQUIRED"
              ) {
                setError("该账号不是平台管理员，无法登录后台");
              } else {
                setError(
                  reason instanceof ApiError ? reason.message : "登录失败，请稍后重试",
                );
              }
            })
            .finally(() => setSubmitting(false));
        }}
      >
        <div className="brand">
          <span className="brand-mark">AI</span>
          <div>
            <strong>平台运营后台</strong>
            <span>AI 门店运营官</span>
          </div>
        </div>
        <p className="muted">使用已授予平台管理员权限的账号登录。</p>
        <label className="field">
          <span>邮箱</span>
          <input
            className="input"
            type="email"
            autoComplete="username"
            value={email}
            required
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="field">
          <span>密码</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            required
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <div className="error-banner">{error}</div> : null}
        <button className="button primary block" type="submit" disabled={submitting}>
          {submitting ? "登录中…" : "登录后台"}
        </button>
      </form>
    </div>
  );
}
