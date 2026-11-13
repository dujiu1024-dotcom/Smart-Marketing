import { useEffect, useState } from "react";
import { api, ApiError, type StoreUserRow } from "./api";
import {
  EmptyState,
  ErrorBanner,
  NoticeBanner,
  PageHeader,
  StatusPill,
  formatTime,
  useAsyncData,
} from "./ui";

export default function UsersPage({ initialStoreId }: { initialStoreId: string }) {
  const [storeFilter, setStoreFilter] = useState(initialStoreId);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [resetting, setResetting] = useState<StoreUserRow | null>(null);

  useEffect(() => {
    setStoreFilter(initialStoreId);
  }, [initialStoreId]);

  const stores = useAsyncData(() => api.stores({ limit: 200 }), []);
  const users = useAsyncData(
    () =>
      api.storeUsers({
        store_id: storeFilter || undefined,
        query: search || undefined,
        status: statusFilter || undefined,
        limit: 200,
      }),
    [storeFilter, search, statusFilter],
  );

  async function updateUser(user: StoreUserRow, payload: { role?: string; status?: string }) {
    setBusy(user.membership_id);
    setError("");
    try {
      await api.updateMembership(user.store.id, user.membership_id, payload);
      setNotice(`已更新 ${user.email}。`);
      users.reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "操作失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <section>
      <PageHeader
        title="门店用户管理"
        description="门店与门店用户为 1:N 绑定；一个门店用户只属于一家门店，登录后无需切换门店。"
        actions={
          <button className="button primary" type="button" onClick={() => setShowCreate(true)}>
            新建门店用户
          </button>
        }
      />
      {error ? <ErrorBanner message={error} /> : null}
      {notice ? <NoticeBanner message={notice} /> : null}

      <div className="toolbar">
        <select
          className="select"
          value={storeFilter}
          onChange={(event) => setStoreFilter(event.target.value)}
        >
          <option value="">全部门店</option>
          {(stores.data?.items ?? []).map((store) => (
            <option key={store.id} value={store.id}>
              {store.name}
            </option>
          ))}
        </select>
        <input
          className="input"
          placeholder="搜索登录邮箱"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          className="select"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="suspended">暂停</option>
          <option value="invited">待激活</option>
          <option value="removed">已移除</option>
        </select>
        <span className="toolbar-meta">共 {users.data?.total ?? 0} 个账号</span>
      </div>

      {users.error ? <ErrorBanner message={users.error} /> : null}
      {users.loading && !users.data ? <div className="loading">读取门店用户…</div> : null}
      {users.data && users.data.items.length === 0 ? (
        <EmptyState>暂无门店用户。先创建门店，再为门店创建所有者账号。</EmptyState>
      ) : null}

      {users.data && users.data.items.length > 0 ? (
        <div className="panel table-panel">
          <table className="table">
            <thead>
              <tr>
                <th>登录邮箱</th>
                <th>所属门店</th>
                <th>角色</th>
                <th>状态</th>
                <th>加入时间</th>
                <th className="right">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.data.items.map((user) => (
                <tr key={user.membership_id}>
                  <td>
                    <strong>{user.email}</strong>
                  </td>
                  <td>{user.store.name}</td>
                  <td>
                    <select
                      className="select small"
                      value={user.role}
                      disabled={busy === user.membership_id}
                      onChange={(event) =>
                        void updateUser(user, { role: event.target.value })
                      }
                    >
                      <option value="owner">所有者</option>
                      <option value="member">成员</option>
                    </select>
                  </td>
                  <td>
                    <StatusPill status={user.status} />
                  </td>
                  <td className="muted">{formatTime(user.joined_at ?? user.created_at)}</td>
                  <td className="right actions-cell">
                    <button className="link-button" type="button" onClick={() => setResetting(user)}>
                      重置密码
                    </button>
                    <button
                      className="link-button"
                      type="button"
                      disabled={busy === user.membership_id}
                      onClick={() =>
                        void updateUser(user, {
                          status: user.status === "active" ? "suspended" : "active",
                        })
                      }
                    >
                      {user.status === "active" ? "停用" : "启用"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {showCreate ? (
        <CreateUserDialog
          stores={(stores.data?.items ?? []).filter((store) => store.status === "active")}
          defaultStoreId={storeFilter}
          onClose={() => setShowCreate(false)}
          onSubmit={async (payload) => {
            const created = await api.createStoreUser(payload);
            setNotice(`已创建 ${created.email}，并绑定到「${created.store.name}」。`);
            setShowCreate(false);
            users.reload();
          }}
        />
      ) : null}

      {resetting ? (
        <ResetPasswordDialog
          user={resetting}
          onClose={() => setResetting(null)}
          onSubmit={async (password) => {
            await api.resetPassword(resetting.store.id, resetting.membership_id, password);
            setNotice(`${resetting.email} 的密码已重置，其他会话已失效。`);
            setResetting(null);
          }}
        />
      ) : null}
    </section>
  );
}

function CreateUserDialog({
  stores,
  defaultStoreId,
  onClose,
  onSubmit,
}: {
  stores: { id: string; name: string }[];
  defaultStoreId: string;
  onClose: () => void;
  onSubmit: (payload: {
    store_id: string;
    email: string;
    password: string;
    role: string;
  }) => Promise<void>;
}) {
  const [storeId, setStoreId] = useState(
    defaultStoreId || (stores.length > 0 ? stores[0].id : ""),
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("owner");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        className="modal"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitting(true);
          setError("");
          onSubmit({ store_id: storeId, email, password, role })
            .catch((reason: unknown) => {
              setError(reason instanceof ApiError ? reason.message : "创建失败");
            })
            .finally(() => setSubmitting(false));
        }}
      >
        <h2>新建门店用户</h2>
        <p className="muted">账号创建后只绑定所选门店，登录门店前端时不再提供门店切换。</p>
        <label className="field">
          <span>所属门店</span>
          <select
            className="select"
            value={storeId}
            required
            onChange={(event) => setStoreId(event.target.value)}
          >
            {stores.map((store) => (
              <option key={store.id} value={store.id}>
                {store.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>登录邮箱</span>
          <input
            className="input"
            type="email"
            value={email}
            required
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="field">
          <span>初始密码（至少 12 位）</span>
          <input
            className="input"
            type="password"
            value={password}
            minLength={12}
            required
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <label className="field">
          <span>角色</span>
          <select className="select" value={role} onChange={(event) => setRole(event.target.value)}>
            <option value="owner">所有者</option>
            <option value="member">成员</option>
          </select>
        </label>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="modal-actions">
          <button className="button ghost" type="button" onClick={onClose}>
            取消
          </button>
          <button className="button primary" type="submit" disabled={submitting || !storeId}>
            {submitting ? "创建中…" : "创建账号"}
          </button>
        </div>
      </form>
    </div>
  );
}

function ResetPasswordDialog({
  user,
  onClose,
  onSubmit,
}: {
  user: StoreUserRow;
  onClose: () => void;
  onSubmit: (password: string) => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        className="modal"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitting(true);
          setError("");
          onSubmit(password)
            .catch((reason: unknown) => {
              setError(reason instanceof ApiError ? reason.message : "重置失败");
            })
            .finally(() => setSubmitting(false));
        }}
      >
        <h2>重置密码 · {user.email}</h2>
        <p className="muted">重置后该账号的现有登录会话会全部失效。</p>
        <label className="field">
          <span>新密码（至少 12 位）</span>
          <input
            className="input"
            type="password"
            value={password}
            minLength={12}
            required
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="modal-actions">
          <button className="button ghost" type="button" onClick={onClose}>
            取消
          </button>
          <button className="button primary" type="submit" disabled={submitting}>
            {submitting ? "处理中…" : "确认重置"}
          </button>
        </div>
      </form>
    </div>
  );
}
