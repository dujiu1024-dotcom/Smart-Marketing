import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import MediaAssetsWorkspace from "./MediaAssetsWorkspace";
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const api = vi.hoisted(() => ({
  getMediaAssets: vi.fn(), createAssetUploadIntent: vi.fn(), putAssetFile: vi.fn(),
  completeAssetUpload: vi.fn(), confirmMediaAssetUsageRights: vi.fn(), archiveMediaAsset: vi.fn(),
  getMediaAssetDownloadUrl: vi.fn(),
}));
vi.mock("./api", () => api);
const asset = {
  id: "asset-1", store_id: "store-1", asset_type: "image", mime_type: "image/png", byte_size: 1024,
  sha256: "a".repeat(64), original_filename_sanitized: "store-front.png", usage_rights_status: "unknown" as const,
  status: "ready" as const, parent_asset_id: null, version_no: 2, created_at: "2026-11-12T02:00:00Z",
};
describe("media assets workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getMediaAssets.mockResolvedValue({ items: [asset], total: 1 });
    api.confirmMediaAssetUsageRights.mockResolvedValue({ ...asset, usage_rights_status: "confirmed_allowed" });
    api.archiveMediaAsset.mockResolvedValue({ ...asset, status: "archived" });
    api.getMediaAssetDownloadUrl.mockResolvedValue("https://private.example/signed-object");
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });
  it("loads only the current store asset list", async () => {
    render(<MediaAssetsWorkspace storeId="store-1" />);
    expect(await screen.findByText("store-front.png")).toBeInTheDocument();
    expect(api.getMediaAssets).toHaveBeenCalledWith("store-1");
    expect(screen.getByText("扫描通过")).toBeInTheDocument();
    expect(screen.getByText("使用权未确认")).toBeInTheDocument();
  });
  it("requires an explicit source note before recording usage rights", async () => {
    render(<MediaAssetsWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "确认使用权" }));
    fireEvent.click(screen.getByRole("button", { name: "提交确认" }));
    expect(await screen.findByText("请填写至少 3 个字符的来源或授权说明。")).toBeInTheDocument();
    expect(api.confirmMediaAssetUsageRights).not.toHaveBeenCalled();
  });
  it("records version- and hash-bound usage rights", async () => {
    render(<MediaAssetsWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "确认使用权" }));
    fireEvent.change(screen.getByLabelText("来源 / 授权说明 *"), { target: { value: "门店自行拍摄，门店拥有使用权" } });
    fireEvent.click(screen.getByRole("button", { name: "提交确认" }));
    await waitFor(() => expect(api.confirmMediaAssetUsageRights).toHaveBeenCalledWith(
      "store-1", asset, "confirmed_allowed", "门店自行拍摄，门店拥有使用权", expect.any(String),
    ));
    expect(await screen.findByText("已确认可使用")).toBeInTheDocument();
  });
  it("does not expose preview before usage rights are confirmed", async () => {
    render(<MediaAssetsWorkspace storeId="store-1" />);
    expect(screen.queryByRole("button", { name: "查看原图" })).not.toBeInTheDocument();
    expect(api.getMediaAssetDownloadUrl).not.toHaveBeenCalled();
  });
  it("requests a short-lived download URL only for allowed assets", async () => {
    api.getMediaAssets.mockResolvedValue({ items: [{ ...asset, usage_rights_status: "confirmed_allowed" }], total: 1 });
    render(<MediaAssetsWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "查看原图" }));
    expect(await screen.findByRole("link", { name: "在新窗口打开原图" })).toHaveAttribute("href", "https://private.example/signed-object");
    expect(api.getMediaAssetDownloadUrl).toHaveBeenCalledWith("store-1", "asset-1");
  });
  it("archives without deleting the original object", async () => {
    render(<MediaAssetsWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "归档" }));
    await waitFor(() => expect(api.archiveMediaAsset).toHaveBeenCalledWith("store-1", asset, expect.any(String)));
    expect(await screen.findByText("已归档")).toBeInTheDocument();
  });
  it("uses upload-intent, private PUT and complete before refreshing the asset list", async () => {
    const file = new File(["image"], "new-image.png", { type: "image/png" });
    Object.defineProperty(file, "arrayBuffer", {
      value: vi.fn().mockResolvedValue(new TextEncoder().encode("image").buffer),
    });
    vi.stubGlobal("crypto", {
      subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).buffer) },
      randomUUID: vi.fn().mockReturnValue("stable-upload-key"),
    });
    api.createAssetUploadIntent.mockResolvedValue({
      id: "intent-1", upload_url: "https://private.example/upload", method: "PUT",
      required_headers: { "Content-Type": "image/png", "If-None-Match": "*", "x-amz-meta-sha256": "0".repeat(64) },
      expires_at: "2026-11-12T03:00:00Z",
    });
    api.completeAssetUpload.mockResolvedValue({ asset: { ...asset, id: "asset-2", status: "scanning" }, status: "scanning" });
    render(<MediaAssetsWorkspace storeId="store-1" />);
    const input = screen.getByLabelText("上传图片") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(api.createAssetUploadIntent).toHaveBeenCalledWith(
      "store-1",
      expect.objectContaining({ expected_mime_type: "image/png", expected_byte_size: 5, expected_sha256: "0".repeat(64) }),
      "stable-upload-key",
    ));
    await waitFor(() => expect(api.putAssetFile).toHaveBeenCalledWith(expect.objectContaining({ id: "intent-1" }), file));
    await waitFor(() => expect(api.completeAssetUpload).toHaveBeenCalledWith("store-1", "intent-1"));
  });
  it("rejects unsupported files before creating an upload intent", async () => {
    render(<MediaAssetsWorkspace storeId="store-1" />);
    const input = screen.getByLabelText("上传图片") as HTMLInputElement;
    const file = new File(["not an image"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("仅支持 JPEG、PNG、WebP 图片。")).toBeInTheDocument();
    expect(api.createAssetUploadIntent).not.toHaveBeenCalled();
  });
});
