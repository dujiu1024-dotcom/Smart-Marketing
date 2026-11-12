import { useCallback, useEffect, useState, type FormEvent } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

type ApiError = Error & { status?: number };
type User = { id: string; email: string };
type Store = { id: string; name: string; role: "owner" | "member" };
type StoresResponse = { items: Store[]; active_store_id: string | null };
type MeResponse = {
  user: User;
  active_store: { id: string; name: string } | null;
  session: { expires_at: string };
};
type LoginResponse = { user: User; csrf_token: string; session: { expires_at: string } };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let message = "请求失败，请稍后重试";
    try {
      const payload = await response.json();
      message = payload.error?.message ?? message;
    } catch {
      // Keep the stable public message when the response is not JSON.
    }
    const error = new Error(message) as ApiError;
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export default function App() {
  const [view, setView] = useState<"loading" | "login" | "stores" | "workspace">("loading");
  const [user, setUser] = useState<User | null>(null);
  const [stores, setStores] = useState<Store[]>([]);
  const [activeStore, setActiveStore] = useState<{ id: string; name: string } | null>(null);
  const [csrfToken, setCsrfToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadStores = useCallback(async () => {
    const result = await request<StoresResponse>("/me/stores");
    setStores(result.items);
    const active = result.items.find((store) => store.id === result.active_store_id);
    if (active) {
      setActiveStore({ id: active.id, name: active.name });
      setView("workspace");
    } else {
      setActiveStore(null);
      setView("stores");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function restoreSession() {
      try {
        const me = await request<MeResponse>("/auth/me");
        const csrf = await request<{ csrf_token: string }>("/auth/csrf", { method: "POST" });
        if (cancelled) return;
        setUser(me.user);
        setCsrfToken(csrf.csrf_token);
        await loadStores();
      } catch (reason) {
        if (cancelled) return;
        const failure = reason as ApiError;
        if (failure.status === 401) {
          setView("login");
        } else {
          setError(failure.message);
          setView("login");
        }
      }
    }
    void restoreSession();
    return () => {
      cancelled = true;
    };
  }, [loadStores]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await request<LoginResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setUser(result.user);
      setCsrfToken(result.csrf_token);
      setPassword("");
      await loadStores();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSelectStore(store: Store) {
    setBusy(true);
    setError("");
    try {
      await request("/session/active-store", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
        body: JSON.stringify({ store_id: store.id }),
      });
      setActiveStore({ id: store.id, name: store.name });
      setView("workspace");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setBusy(true);
    setError("");
    try {
      await request("/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
      });
      setUser(null);
      setStores([]);
      setActiveStore(null);
      setCsrfToken("");
      setView("login");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (view === "loading") {
    return <main className="auth-shell"><p role="status">正在验证登录状态…</p></main>;
  }

  if (view === "login") {
    return (
      <main className="auth-shell">
        <section className="auth-card" aria-labelledby="login-title">
          <div className="brand-lockup"><span className="brand-mark">AI</span><strong>AI 门店运营官</strong></div>
          <p className="eyebrow">STORE OPERATOR</p>
          <h1 id="login-title">登录工作台</h1>
          <p className="muted">使用已开通门店成员权限的账号登录。</p>
          <form onSubmit={handleLogin}>
            <label htmlFor="email">邮箱</label>
            <input id="email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} />
            <label htmlFor="password">密码</label>
            <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
            {error && <p className="error" role="alert">{error}</p>}
            <button type="submit" disabled={busy}>{busy ? "正在登录…" : "登录"}</button>
          </form>
          <p className="security-note">登录凭证由服务端通过 HttpOnly Cookie 管理；页面不会保存 Session Token。</p>
        </section>
      </main>
    );
  }

  if (view === "stores") {
    return (
      <main className="auth-shell">
        <section className="auth-card store-card" aria-labelledby="store-title">
          <div className="brand-lockup"><span className="brand-mark">AI</span><strong>AI 门店运营官</strong></div>
          <p className="eyebrow">STORE CONTEXT</p>
          <h1 id="store-title">选择门店</h1>
          <p className="muted">{user?.email} · 请选择本次要操作的门店</p>
          {error && <p className="error" role="alert">{error}</p>}
          {stores.length === 0 ? (
            <div className="empty-state"><strong>当前账号暂无可访问门店</strong><p>请联系门店管理员确认成员关系。</p></div>
          ) : (
            <ul className="store-list">
              {stores.map((store) => (
                <li key={store.id}>
                  <button className="store-choice" type="button" disabled={busy} onClick={() => void handleSelectStore(store)}>
                    <span><strong>{store.name}</strong><small>{store.role === "owner" ? "门店负责人" : "门店成员"}</small></span>
                    <span aria-hidden="true">进入 →</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button className="text-button" type="button" disabled={busy} onClick={() => void handleLogout()}>退出登录</button>
        </section>
      </main>
    );
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand-lockup"><span className="brand-mark">AI</span><strong>AI 门店运营官</strong></div>
        <div className="account-actions">
          <span className="active-store">{activeStore?.name}</span>
          <button className="secondary-button" type="button" onClick={() => setView("stores")}>切换门店</button>
          <button className="text-button" type="button" disabled={busy} onClick={() => void handleLogout()}>退出</button>
        </div>
      </header>
      <main className="workspace">
        <p className="eyebrow">STORE WORKSPACE</p>
        <h1>门店工作台</h1>
        <p className="muted">当前门店：{activeStore?.name}</p>
        <section className="notice">
          <strong>身份与门店上下文已连接</strong>
          <p>登录、Session Cookie、CSRF 校验和服务端门店成员授权已接入。</p>
          <p>门店档案、商品服务、活动优惠、品牌规范、客群、知识库和素材资产页面将按 Demo v1.8 分批接入；当前尚未开放这些业务操作。</p>
        </section>
        {error && <p className="error" role="alert">{error}</p>}
      </main>
      <footer>当前阶段仅开放身份认证与门店上下文，不代表完整业务页面已交付。</footer>
    </div>
  );
}
