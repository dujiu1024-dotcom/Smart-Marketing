import { useState } from "react";
import { api } from "./api";
import {
  EmptyState,
  ErrorBanner,
  PageHeader,
  StatusPill,
  formatTime,
  useAsyncData,
} from "./ui";

export default function DispatchesPage() {
  const [storeFilter, setStoreFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const stores = useAsyncData(() => api.stores({ limit: 200 }), []);
  const dispatches = useAsyncData(
    () =>
      api.dispatches({
        store_id: storeFilter || undefined,
        status: statusFilter || undefined,
        limit: 200,
      }),
    [storeFilter, statusFilter],
  );

  return (
    <section>
      <PageHeader
        title="下发记录"
        description="门店内容确认后发往渠道的发布操作记录，包含状态、重试次数与失败原因。"
      />
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
        <select
          className="select"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="">全部状态</option>
          <option value="queued">排队中</option>
          <option value="uploading">上传中</option>
          <option value="submitting">提交中</option>
          <option value="processing">处理中</option>
          <option value="published">已发布</option>
          <option value="failed">失败</option>
          <option value="needs_human">待人工</option>
          <option value="cancelled">已取消</option>
        </select>
        <span className="toolbar-meta">共 {dispatches.data?.total ?? 0} 条</span>
      </div>

      {dispatches.error ? <ErrorBanner message={dispatches.error} /> : null}
      {dispatches.loading && !dispatches.data ? <div className="loading">读取下发记录…</div> : null}
      {dispatches.data && dispatches.data.items.length === 0 ? (
        <EmptyState>暂无下发记录。门店完成内容包确认并发起发布后，记录会出现在这里。</EmptyState>
      ) : null}
      {dispatches.data && dispatches.data.items.length > 0 ? (
        <div className="panel table-panel">
          <table className="table">
            <thead>
              <tr>
                <th>门店</th>
                <th>渠道</th>
                <th>状态</th>
                <th>重试</th>
                <th>平台内容 ID</th>
                <th>失败原因</th>
                <th>创建时间</th>
                <th>发布时间</th>
              </tr>
            </thead>
            <tbody>
              {dispatches.data.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.store.name}</strong>
                    <div className="muted mono">{item.id}</div>
                  </td>
                  <td>{item.channel_key ? (item.channel_key === "douyin" ? "抖音" : "其他渠道") : "—"}</td>
                  <td>
                    <StatusPill status={item.status} />
                  </td>
                  <td>{item.attempt_count}</td>
                  <td className="muted">{item.platform_item_id ?? "—"}</td>
                  <td className="wrap muted">
                    {item.last_error_summary ?? "—"}
                    {item.last_error_code ? (
                      <div className="mono">{item.last_error_code}</div>
                    ) : null}
                  </td>
                  <td className="muted">{formatTime(item.created_at)}</td>
                  <td className="muted">{formatTime(item.published_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
