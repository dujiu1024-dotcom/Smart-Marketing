import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import {
  ApiError, archiveMediaAsset, completeAssetUpload, confirmMediaAssetUsageRights,
  createAssetUploadIntent, getMediaAssetDownloadUrl, getMediaAssets, putAssetFile,
  type MediaAsset,
} from "./api";

const MAX_BYTES = 25_000_000;
const MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const statusLabels: Record<MediaAsset["status"], string> = {
  uploading: "上传中", quarantined: "待隔离处理", scanning: "安全扫描中",
  ready: "扫描通过", rejected: "扫描未通过", archived: "已归档",
};
const rightsLabels: Record<MediaAsset["usage_rights_status"], string> = {
  unknown: "使用权未确认", confirmed_allowed: "已确认可使用", restricted: "限制使用",
};
const message = (reason: unknown) => reason instanceof Error ? reason.message : "请求失败，请稍后重试。";
async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
function formatSize(size: number): string {
  return size >= 1024 * 1024 ? (size / 1024 / 1024).toFixed(1) + " MB" : Math.max(1, Math.round(size / 1024)) + " KB";
}
export default function MediaAssetsWorkspace({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<MediaAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [rightsAssetId, setRightsAssetId] = useState("");
  const [rightsChoice, setRightsChoice] = useState<"confirmed_allowed" | "restricted">("confirmed_allowed");
  const [licenseNote, setLicenseNote] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const reload = useCallback(async () => {
    setLoading(true); setError("");
    try { const result = await getMediaAssets(storeId); setItems(result.items); setTotal(result.total); }
    catch (reason) { setError(message(reason)); }
    finally { setLoading(false); }
  }, [storeId]);
  useEffect(() => { void reload(); }, [reload]);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(""); setNotice(""); setBusy(true);
    try {
      if (!MIME_TYPES.has(file.type)) throw new Error("仅支持 JPEG、PNG、WebP 图片。");
      if (file.size <= 0 || file.size > MAX_BYTES) throw new Error("图片大小必须大于 0 且不超过 25 MB。");
      const digest = await sha256(file);
      const keyName = "store-operator.asset-upload." + storeId + "." + digest + "." + encodeURIComponent(file.name);
      const storedState = sessionStorage.getItem(keyName);
      const state: { idempotencyKey: string; intentId?: string } = storedState
        ? JSON.parse(storedState) as { idempotencyKey: string; intentId?: string }
        : { idempotencyKey: crypto.randomUUID() };
      sessionStorage.setItem(keyName, JSON.stringify(state));
      let intentId = state.intentId;
      let uploadIntent: Awaited<ReturnType<typeof createAssetUploadIntent>> | null = null;
      if (!intentId) {
        const intent = await createAssetUploadIntent(storeId, {
          expected_mime_type: file.type as "image/jpeg" | "image/png" | "image/webp",
          expected_byte_size: file.size,
          expected_sha256: digest,
          original_filename: file.name,
        }, state.idempotencyKey);
        uploadIntent = intent;
        intentId = intent.id;
        state.intentId = intentId;
        sessionStorage.setItem(keyName, JSON.stringify(state));
      }
      let completed: Awaited<ReturnType<typeof completeAssetUpload>> | null = null;
      if (storedState && intentId) {
        try { completed = await completeAssetUpload(storeId, intentId); }
        catch (reason) {
          if (!(reason instanceof ApiError && reason.code === "UPLOAD_OBJECT_NOT_FOUND")) throw reason;
        }
      }
      if (!completed) {
        if (!uploadIntent) {
          uploadIntent = await createAssetUploadIntent(storeId, {
            expected_mime_type: file.type as "image/jpeg" | "image/png" | "image/webp",
            expected_byte_size: file.size,
            expected_sha256: digest,
            original_filename: file.name,
          }, state.idempotencyKey);
        }
        if (uploadIntent.id !== intentId) {
          intentId = uploadIntent.id;
          state.intentId = intentId;
          sessionStorage.setItem(keyName, JSON.stringify(state));
        }
        await putAssetFile(uploadIntent, file);
        completed = await completeAssetUpload(storeId, uploadIntent.id);
      }
      sessionStorage.removeItem(keyName);
      setNotice("图片已上传并完成服务端哈希校验，当前状态：" + (statusLabels[completed.asset.status] ?? completed.status) + "。安全扫描完成前不会开放下载或用于营销内容。");
      await reload();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function confirmRights(event: FormEvent<HTMLFormElement>, asset: MediaAsset) {
    event.preventDefault();
    if (licenseNote.trim().length < 3) { setError("请填写至少 3 个字符的来源或授权说明。"); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await confirmMediaAssetUsageRights(storeId, asset, rightsChoice, licenseNote.trim(), crypto.randomUUID());
      setItems(current => current.map(item => item.id === updated.id ? updated : item));
      setRightsAssetId(""); setLicenseNote("");
      setNotice(updated.usage_rights_status === "confirmed_allowed" ? "已记录商家使用权确认。只有扫描通过且使用权允许的素材才能下载。" : "已记录限制使用；该素材不会开放下载。");
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function archive(asset: MediaAsset) {
    if (!window.confirm("确认归档「" + (asset.original_filename_sanitized ?? "该素材") + "」？归档不会删除原始文件。")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await archiveMediaAsset(storeId, asset, crypto.randomUUID());
      setItems(current => current.map(item => item.id === updated.id ? updated : item));
      setNotice("素材已归档，原始文件保留用于历史追溯。");
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function preview(asset: MediaAsset) {
    setError("");
    try { const url = await getMediaAssetDownloadUrl(storeId, asset.id); setPreviewUrl(url); }
    catch (reason) { setError(message(reason)); }
  }

  return <>
    <div className="page-heading">
      <div><p className="eyebrow">MEDIA ASSETS</p><h1>素材资产库</h1><p className="muted">上传并管理门店图片原件，记录来源与使用权。原始素材不会被编辑结果覆盖。</p></div>
      <label className="primary asset-upload-button">{busy ? "处理中…" : "上传图片"}<input aria-label="上传图片" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => void upload(event)}/></label>
    </div>
    <div className="asset-policy">支持 JPEG / PNG / WebP，单张最大 25 MB。上传后进入隔离与扫描流程；文件哈希和 MIME 校验不等于恶意文件扫描，扫描通过且商家确认使用权后才允许下载。</div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    {previewUrl && <section className="asset-preview"><div><strong>素材预览</strong><button className="text-button" type="button" onClick={() => setPreviewUrl("")}>关闭预览</button></div><a href={previewUrl} target="_blank" rel="noreferrer">在新窗口打开原图</a></section>}
    {loading ? <div className="loading-card"><span className="spinner"/>正在读取素材…</div>
    : items.length === 0 ? <section className="empty-card"><h2>还没有素材</h2><p>上传门店商品图、环境图或品牌视觉素材。每张图片会独立校验、隔离扫描并记录使用权。</p></section>
    : <section className="catalog-list">
      <div className="catalog-summary"><span>共 {total} 个素材</span><button className="text-button" type="button" onClick={() => void reload()}>刷新状态</button></div>
      {items.map(asset => <article className="catalog-item" key={asset.id}>
        <div className="catalog-item-main"><div><h2>{asset.original_filename_sanitized ?? "未命名图片"}</h2><p>{asset.mime_type} · {formatSize(asset.byte_size)} · V{asset.version_no}</p></div><span className={asset.status === "ready" ? "status-chip confirmed" : "status-chip"}>{statusLabels[asset.status]}</span></div>
        <div className="catalog-meta"><span>{rightsLabels[asset.usage_rights_status]}</span><span>SHA-256：{asset.sha256.slice(0, 12)}…</span><span>{new Date(asset.created_at).toLocaleString()}</span></div>
        {rightsAssetId === asset.id && asset.status === "ready" && asset.usage_rights_status === "unknown" && <form className="asset-rights-form" onSubmit={event => void confirmRights(event, asset)}>
          <label className="field"><span>使用权结论</span><select value={rightsChoice} onChange={event => setRightsChoice(event.target.value as typeof rightsChoice)}><option value="confirmed_allowed">我确认门店拥有该素材的使用权</option><option value="restricted">限制使用，不允许用于营销内容</option></select></label>
          <label className="field"><span>来源 / 授权说明 *</span><textarea rows={2} value={licenseNote} onChange={event => setLicenseNote(event.target.value)} placeholder="例如：门店自行拍摄；摄影师授权用于门店官方账号"/></label>
          <div className="catalog-actions"><button className="secondary" type="button" onClick={() => setRightsAssetId("")}>取消</button><button className="primary" type="submit" disabled={busy}>提交确认</button></div>
        </form>}
        <div className="catalog-actions">
          {asset.status === "ready" && asset.usage_rights_status === "confirmed_allowed" && <button className="secondary" type="button" disabled={busy} onClick={() => void preview(asset)}>查看原图</button>}
          {asset.status === "ready" && asset.usage_rights_status === "unknown" && <button className="secondary" type="button" disabled={busy} onClick={() => {setRightsAssetId(asset.id);setRightsChoice("confirmed_allowed");setLicenseNote("");}}>确认使用权</button>}
          {(asset.status === "ready" || asset.status === "rejected") && <button className="secondary" type="button" disabled={busy} onClick={() => void archive(asset)}>归档</button>}
        </div>
      </article>)}
    </section>}
  </>;
}
