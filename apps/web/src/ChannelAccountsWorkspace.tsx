import { useCallback, useEffect, useState } from "react";
import {
  listDouyinAccounts, refreshDouyinAccount, startDouyinAuthorization,
  type DouyinAccount,
} from "./api";

const statusLabels: Record<DouyinAccount["status"], string> = {
  active: "已连接",
  reauth_required: "需要重新授权",
  revoked: "已撤销",
  error: "连接异常",
};
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请稍后重试。";

export default function ChannelAccountsWorkspace({ storeId }: { storeId: string }) {
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [authorizationUrl, setAuthorizationUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setAccounts(await listDouyinAccounts(storeId)); }
    catch (reason) { setError(errorText(reason)); }
    finally { setLoading(false); }
  }, [storeId]);

  useEffect(() => { void loadAccounts(); }, [loadAccounts]);

  async function connectDouyin() {
    setSaving(true); setError(""); setNotice(""); setAuthorizationUrl("");
    try {
      const response = await startDouyinAuthorization(storeId);
      setAuthorizationUrl(response.authorization_url);
      setNotice("授权链接已生成，有效期 10 分钟。请在新标签页完成抖音官方授权，再返回本页刷新账号状态。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  async function refreshAccount(account: DouyinAccount) {
    setSaving(true); setError(""); setNotice("");
    try {
      await refreshDouyinAccount(storeId, account.id);
      await loadAccounts();
      setNotice("账号状态已重新验证。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  return <>
    <div className="page-heading">
      <div><p className="eyebrow">STORE CHANNELS</p><h1>渠道账号</h1><p className="muted">首期仅接入抖音官方 OAuth。授权、账号状态和发布权限均以服务端核验结果为准。</p></div>
      <button className="secondary" type="button" disabled={loading || saving} onClick={() => void loadAccounts()}>刷新账号</button>
    </div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    <section className="task-panel channel-connect-panel">
      <div className="section-title"><div><h2>连接抖音账号</h2><p>通过官方授权页申请 user_info、video.create、video.list 权限；不会采集或保存账号密码。</p></div><span className="status-chip">首期渠道</span></div>
      <button className="primary" type="button" disabled={saving} onClick={() => void connectDouyin()}>{saving ? "处理中…" : "生成官方授权链接"}</button>
      {authorizationUrl && <p className="channel-auth-link"><a href={authorizationUrl} target="_blank" rel="noopener noreferrer">打开抖音官方授权页面</a></p>}
      <p className="muted">如果系统提示 CHANNEL_NOT_CONFIGURED 或 SECRET_STORE_UNAVAILABLE，表示服务端尚未配置抖音应用凭据或 Secret Manager；此时不会创建假账号。</p>
    </section>
    <section className="task-panel">
      <div className="section-title"><div><h2>已连接账号</h2><p>账号仅属于当前门店。Token 不会返回浏览器。</p></div><span className="status-chip">{accounts.length} 个账号</span></div>
      {loading ? <div className="loading-card"><span className="spinner" />正在读取账号…</div>
      : accounts.length === 0 ? <section className="empty-card"><h3>当前门店尚未连接抖音账号</h3><p>生成官方授权链接并完成授权后，账号会显示在这里。</p></section>
      : <div className="channel-account-list">{accounts.map(account => <article className="channel-account-card" key={account.id}>
        <div className="channel-account-main">
          {account.avatar_url ? <img src={account.avatar_url} alt="" referrerPolicy="no-referrer" /> : <span className="channel-avatar">抖</span>}
          <div><strong>{account.display_name || "抖音账号"}</strong><small>账号 ID：{account.external_account_id}</small><small>授权于 {new Date(account.connected_at).toLocaleString()}</small></div>
        </div>
        <div className="channel-account-meta"><span className={account.status === "active" ? "status-chip" : "status-chip danger"}>{statusLabels[account.status]}</span><small>授权范围：{account.granted_scopes.join("、") || "未返回"}</small><small>Access Token 到期：{new Date(account.access_token_expires_at).toLocaleString()}</small><small>最近验证：{account.last_verified_at ? new Date(account.last_verified_at).toLocaleString() : "尚未验证"}</small></div>
        <button className="text-button" type="button" disabled={saving || account.status !== "active"} onClick={() => void refreshAccount(account)}>重新验证授权</button>
      </article>)}</div>}
    </section>
  </>;
}
