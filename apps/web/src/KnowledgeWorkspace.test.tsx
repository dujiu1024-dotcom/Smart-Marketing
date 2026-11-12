import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import KnowledgeWorkspace from "./KnowledgeWorkspace";

afterEach(() => cleanup());
const api = vi.hoisted(() => ({
  getKnowledgeItems: vi.fn(),
  createKnowledgeItem: vi.fn(),
  updateKnowledgeItem: vi.fn(),
  deleteKnowledgeItem: vi.fn(),
  confirmKnowledgeFacts: vi.fn(),
}));
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, ...api };
});
const storeId = "store-1";
const item = {
  id: "knowledge-1", store_id: storeId, title: "到店服务流程", category: "服务规则",
  content_text: "顾客到店后先确认预约信息。", content_ref: null, content_hash: null,
  source_type: "merchant_observation", source_ref: "店长确认", effective_at: null, expires_at: null,
  fact_status: "pending_confirmation", current_version: 1,
};
describe("store knowledge workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "#store:knowledge";
    api.getKnowledgeItems.mockResolvedValue({ items: [item], total: 1 });
    api.createKnowledgeItem.mockResolvedValue({ ...item, id: "knowledge-2", title: "营业规则" });
    api.updateKnowledgeItem.mockResolvedValue({ ...item, title: "新版服务流程", current_version: 2 });
    api.confirmKnowledgeFacts.mockResolvedValue({ ...item, fact_status: "confirmed", current_version: 2 });
  });
  it("loads the current store knowledge and edits with optimistic version", async () => {
    render(<KnowledgeWorkspace storeId={storeId} />);
    expect(await screen.findByText("到店服务流程")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(await screen.findByLabelText("标题 *"), { target: { value: "新版服务流程" } });
    fireEvent.click(screen.getByRole("button", { name: "保存知识" }));
    await waitFor(() => expect(api.updateKnowledgeItem).toHaveBeenCalledWith(
      storeId, item, expect.objectContaining({ title: "新版服务流程", content_text: item.content_text }),
    ));
  });
  it("creates knowledge with a stable idempotency key and keeps empty references null", async () => {
    api.getKnowledgeItems.mockResolvedValue({ items: [], total: 0 });
    render(<KnowledgeWorkspace storeId={storeId} />);
    fireEvent.click(await screen.findByRole("button", { name: "添加第一条知识" }));
    fireEvent.change(await screen.findByLabelText("标题 *"), { target: { value: "营业规则" } });
    fireEvent.change(screen.getByLabelText("知识内容"), { target: { value: "每日 10:00 开门。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存知识" }));
    await waitFor(() => expect(api.createKnowledgeItem).toHaveBeenCalledWith(
      storeId, expect.objectContaining({ title: "营业规则", content_text: "每日 10:00 开门。", content_ref: null }), expect.any(String),
    ));
  });
  it("requires timezone-qualified effective dates", async () => {
    api.getKnowledgeItems.mockResolvedValue({ items: [], total: 0 });
    render(<KnowledgeWorkspace storeId={storeId} />);
    fireEvent.click(await screen.findByRole("button", { name: "添加第一条知识" }));
    fireEvent.change(await screen.findByLabelText("标题 *"), { target: { value: "节假日安排" } });
    fireEvent.change(screen.getByLabelText("知识内容"), { target: { value: "节假日营业时间以公告为准。" } });
    fireEvent.change(screen.getByLabelText("生效时间（含时区）"), { target: { value: "2026-11-12T09:00:00" } });
    fireEvent.click(screen.getByRole("button", { name: "保存知识" }));
    expect(await screen.findByText(/必须包含明确时区/)).toBeInTheDocument();
    expect(api.createKnowledgeItem).not.toHaveBeenCalled();
  });
  it("does not confirm stale server data while edits are unsaved", async () => {
    render(<KnowledgeWorkspace storeId={storeId} />);
    await screen.findByText("到店服务流程");
    fireEvent.click(screen.getByRole("button", { name: "确认事实" }));
    // List confirmation is allowed because no editor changes are pending.
    await waitFor(() => expect(api.confirmKnowledgeFacts).toHaveBeenCalledWith(storeId, item));
  });
});
