import { useState } from "react";
import { api, ApiError, type StoreRow } from "./api";
import {
  EmptyState,
  ErrorBanner,
  NoticeBanner,
  PageHeader,
  StatusPill,
  formatTime,
  useAsyncData,
} from "./ui";

export default function StoresPage({ onViewUsers }: { onViewUsers: (storeId: string) => void }) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<StoreRow | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const list = useAsyncData(
    () => api.stores({ query: search || undefined, status: statusFilter || undefined, limit: 200 }),
    [search, statusFilter],
  );

  async function changeStatus(store: StoreRow) {
    const next = store.status === "active" ? "suspended" : "active";
    setBusy(store.id);
    setError("");
    try {
      await api.updateStore(store.id, { status: next });
      setNotice(`门店「${store.name}」已${next === "active" ? "恢复启用" : "暂停"}。`);
      list.reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "操作失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <section>
      <PageHeader
        title="门店管理"
        description="维护门店基础状态。门店经营资料、商品、知识库与渠道账号仍在门店前端维护。"
        actions={
          <button className="button primary" type="button" onClick={() => setShowCreate(true)}>
            新建门店
          </button>
        }
      />
      {error ? <ErrorBanner message={error} /> : null}
      {notice ? <NoticeBanner message={notice} /> : null}

      <div className="toolbar">
        <input
          className="input"
          placeholder="搜索门店名称"
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
          <option value="closed">关闭</option>
        </select>
        <span className="toolbar-meta">共 {list.data?.total ?? 0} 家门店</span>
      </div>

      {list.error ? <ErrorBanner message={list.error} /> : null}
      {list.loading && !list.data ? <div className="loading">读取门店…</div> : null}
      {list.data && list.data.items.length === 0 ? (
        <EmptyState>没有匹配的门店。可新建门店或在门店前端完成初始化。</EmptyState>
      ) : null}

      {list.data && list.data.items.length > 0 ? (
        <div className="panel table-panel">
          <table className="table">
            <thead>
              <tr>
                <th>门店</th>
                <th>状态</th>
                <th>时区</th>
                <th>门店用户</th>
                <th>所有者</th>
                <th>创建时间</th>
                <th className="right">操作</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((store) => (
                <tr key={store.id}>
                  <td className="cell-store">
                    <strong>{store.name}</strong>
                    <div className="muted mono cell-clamp">{store.id}</div>
                  </td>
                  <td>
                    <StatusPill status={store.status} />
                  </td>
                  <td className="cell-nowrap muted">{store.timezone}</td>
                  <td className="cell-num">{store.member_count}</td>
                  <td className="muted cell-clamp" title={store.owners.join("、") || undefined}>
                    {store.owners.join("、") || "—"}
                  </td>
                  <td className="cell-time muted">{formatTime(store.created_at)}</td>
                  <td className="right actions-cell">
                    <button className="link-button" type="button" onClick={() => onViewUsers(store.id)}>
                      门店用户
                    </button>
                    <button className="link-button" type="button" onClick={() => setEditing(store)}>
                      编辑
                    </button>
                    <button
                      className="link-button"
                      type="button"
                      disabled={busy === store.id}
                      onClick={() => void changeStatus(store)}
                    >
                      {store.status === "active" ? "暂停" : "恢复"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {showCreate ? (
        <StoreFormDialog
          title="新建门店"
          confirmText="创建门店"
          initial={{ name: "", timezone: "Asia/Shanghai", status: "active" }}
          onClose={() => setShowCreate(false)}
          onSubmit={async (payload) => {
            const created = await api.createStore(payload);
            setNotice(`门店「${created.name}」已创建。请继续为它创建门店用户。`);
            setShowCreate(false);
            list.reload();
          }}
        />
      ) : null}

      {editing ? (
        <StoreFormDialog
          title={`编辑门店 · ${editing.name}`}
          confirmText="保存"
          allowClosed
          initial={{ name: editing.name, timezone: editing.timezone, status: editing.status }}
          onClose={() => setEditing(null)}
          onSubmit={async (payload) => {
            await api.updateStore(editing.id, payload);
            setNotice(`门店「${payload.name}」已更新。`);
            setEditing(null);
            list.reload();
          }}
        />
      ) : null}
    </section>
  );
}

function StoreFormDialog({
  title,
  confirmText,
  initial,
  allowClosed = false,
  onClose,
  onSubmit,
}: {
  title: string;
  confirmText: string;
  initial: { name: string; timezone: string; status: string };
  allowClosed?: boolean;
  onClose: () => void;
  onSubmit: (payload: { name: string; timezone: string; status: string }) => Promise<void>;
}) {
  const [name, setName] = useState(initial.name);
  const [timezone, setTimezone] = useState(initial.timezone);
  const [status, setStatus] = useState(initial.status);
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
          onSubmit({ name, timezone, status })
            .catch((reason: unknown) => {
              setError(reason instanceof ApiError ? reason.message : "保存失败");
            })
            .finally(() => setSubmitting(false));
        }}
      >
        <h2>{title}</h2>
        <label className="field">
          <span>门店名称</span>
          <input
            className="input"
            value={name}
            required
            maxLength={160}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span>时区（IANA）</span>
          <input
            className="input"
            value={timezone}
            required
            onChange={(event) => setTimezone(event.target.value)}
          />
        </label>
        <label className="field">
          <span>状态</span>
          <select className="select" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="active">启用</option>
            <option value="suspended">暂停</option>
            {allowClosed ? <option value="closed">关闭</option> : null}
          </select>
        </label>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="modal-actions">
          <button className="button ghost" type="button" onClick={onClose}>
            取消
          </button>
          <button className="button primary" type="submit" disabled={submitting}>
            {submitting ? "处理中…" : confirmText}
          </button>
        </div>
      </form>
    </div>
  );
}
