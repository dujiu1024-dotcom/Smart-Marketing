import { useEffect, useState, type ReactNode } from "react";

export function useAsyncData<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader()
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version]);

  return {
    data,
    loading,
    error,
    reload: () => setVersion((current) => current + 1),
  };
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

export function formatScore(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const score = Number(value);
  if (!Number.isFinite(score)) return String(value);
  return `${Math.round(score)} 分`;
}

export function formatHeat(
  value: string | number | null | undefined,
  unit?: string | null,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return unit ? `${value} ${unit}` : String(value);
  const formatted = Number.isInteger(numeric)
    ? numeric.toLocaleString("zh-CN")
    : numeric.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
  return unit ? `${formatted} ${unit}` : formatted;
}

export function dash(value: string | null | undefined): string {
  return value && value.trim() ? value : "—";
}

const STATUS_LABELS: Record<string, string> = {
  active: "启用",
  suspended: "暂停",
  closed: "关闭",
  invited: "待激活",
  removed: "已移除",
  owner: "所有者",
  member: "成员",
  queued: "排队中",
  pending: "待处理",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  needs_human: "待人工",
  retry_wait: "等待重试",
  cancelled: "已取消",
  skipped: "已跳过",
  draft: "草稿",
  waiting_for_user: "待用户处理",
  blocked: "已阻塞",
  completed: "已完成",
  archived: "已归档",
  paused: "已暂停",
  uploading: "上传中",
  submitting: "提交中",
  processing: "处理中",
  published: "已发布",
  eligible: "可执行",
  review_required: "需复核",
  ineligible: "不适用",
  unassessed: "未评估",
  collected: "已采集",
  partial: "部分采集",
  unverified: "未核验",
  expired: "已过期",
  healthy: "健康",
  degraded: "降级",
  unknown: "未知",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`pill pill-${status}`}>
      {STATUS_LABELS[status] ?? "状态未知"}
    </span>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function ErrorBanner({ message }: { message: string }) {
  return <div className="error-banner">{message}</div>;
}

export function NoticeBanner({ message }: { message: string }) {
  return <div className="notice-banner">{message}</div>;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
