import { api } from "./api";
import { EmptyState, ErrorBanner, PageHeader, StatusPill, formatTime, useAsyncData } from "./ui";

const TASK_LABELS: Record<string, string> = {
  draft: "草稿",
  active: "进行中",
  waiting_for_user: "待用户处理",
  blocked: "阻塞",
  failed: "失败",
  completed: "已完成",
  cancelled: "已取消",
  archived: "已归档",
};

export default function OverviewPage({
  onOpenStore,
  onOpenDispatch,
}: {
  onOpenStore: (storeId: string) => void;
  onOpenDispatch: () => void;
}) {
  const overview = useAsyncData(() => api.overview(), []);
  const recent = useAsyncData(() => api.dispatches({ limit: 6 }), []);
  const data = overview.data;

  return (
    <section>
      <PageHeader
        title="数据总览"
        description="平台范围内的门店、用户、任务、热点与下发运行情况。"
      />
      {overview.error ? <ErrorBanner message={overview.error} /> : null}
      {overview.loading && !data ? <div className="loading">正在读取平台数据…</div> : null}

      {data ? (
        <>
          <div className="stat-grid">
            <StatCard
              label="门店总数"
              value={data.stores.total}
              hint={`启用 ${data.stores.by_status.active ?? 0} · 暂停 ${
                data.stores.by_status.suspended ?? 0
              } · 关闭 ${data.stores.by_status.closed ?? 0}`}
            />
            <StatCard
              label="活跃门店用户"
              value={data.store_users.active}
              hint="一个用户只绑定一家门店"
            />
            <StatCard
              label="营销任务"
              value={Object.values(data.marketing_tasks.by_status).reduce((sum, n) => sum + n, 0)}
              hint={`进行中 ${data.marketing_tasks.by_status.active ?? 0} · 待用户 ${
                data.marketing_tasks.by_status.waiting_for_user ?? 0
              }`}
            />
            <StatCard
              label="运行中任务作业"
              value={data.jobs.running}
              hint={`排队 ${data.jobs.queued} · 24 小时失败/待人工 ${
                data.jobs.failed_or_needs_human_24h
              }`}
            />
            <StatCard
              label="已采集热点"
              value={data.hot_topics.collected}
              hint={`24 小时匹配 ${data.hot_topics.matches_24h} 条`}
            />
            <StatCard
              label="已发布下发"
              value={data.dispatches.by_status.published ?? 0}
              hint={`失败 ${data.dispatches.by_status.failed ?? 0} · 待人工 ${
                data.dispatches.by_status.needs_human ?? 0
              }`}
            />
          </div>

          <div className="two-column">
            <div className="panel">
              <div className="panel-head">
                <h2>最近下发</h2>
                <button className="link-button" type="button" onClick={onOpenDispatch}>
                  查看全部
                </button>
              </div>
              {recent.loading && !recent.data ? <div className="loading">读取中…</div> : null}
              {recent.data && recent.data.items.length === 0 ? (
                <EmptyState>暂无下发记录。门店完成内容确认后，发布操作会记录在这里。</EmptyState>
              ) : null}
              {recent.data && recent.data.items.length > 0 ? (
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>门店</th>
                      <th>渠道</th>
                      <th>状态</th>
                      <th>更新时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.data.items.map((item) => (
                      <tr key={item.id}>
                        <td className="cell-clamp" title={item.store.name}>
                          {item.store.name}
                        </td>
                        <td className="cell-nowrap">
                          {item.channel_key
                            ? item.channel_key === "douyin"
                              ? "抖音"
                              : item.channel_key
                            : "—"}
                        </td>
                        <td>
                          <StatusPill status={item.status} />
                        </td>
                        <td className="cell-time muted">{formatTime(item.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>任务与作业</h2>
                <button className="link-button" type="button" onClick={() => onOpenStore("")}>
                  去门店管理
                </button>
              </div>
              <div className="status-list">
                {Object.entries(data.marketing_tasks.by_status).map(([key, value]) => (
                  <div className="status-row" key={key}>
                    <span>{TASK_LABELS[key] ?? key}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
                {Object.keys(data.marketing_tasks.by_status).length === 0 ? (
                  <EmptyState>暂无营销任务。</EmptyState>
                ) : null}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      <span className="stat-hint">{hint}</span>
    </div>
  );
}
