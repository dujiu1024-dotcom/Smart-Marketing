import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import HotspotWorkspace from "./HotspotWorkspace";

afterEach(() => cleanup());
const api = vi.hoisted(() => ({
  getOpportunities: vi.fn(), getOpportunity: vi.fn(), decideOpportunity: vi.fn(), requestOpportunityCollection: vi.fn(),
}));
vi.mock("./api", async () => ({ ...(await vi.importActual<typeof import("./api")>("./api")), ...api }));

describe("hotspot opportunity workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "#hotspots";
    api.getOpportunities.mockResolvedValue({
      items: [], total: 0, source_status: "unavailable",
      empty_reason: "No reviewed source is enabled.",
    });
  });
  it("does not fabricate opportunities when no source is available", async () => {
    render(<HotspotWorkspace storeId="store-1" />);
    expect(await screen.findByRole("heading", { name: "发现营销机会" })).toBeInTheDocument();
    expect(screen.getByText(/不会用演示数据冒充实时热点/)).toBeInTheDocument();
    expect(api.getOpportunities).toHaveBeenCalledWith("store-1");
  });
  it("reports unavailable sources without creating a collection job", async () => {
    api.requestOpportunityCollection.mockResolvedValue({ status: "unavailable", job_id: null, message: "没有已启用且完成使用条款登记的热点来源；未创建采集任务。" });
    render(<HotspotWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "采集并匹配" }));
    expect(await screen.findByText(/没有已启用且完成使用条款登记的热点来源/)).toBeInTheDocument();
    expect(api.requestOpportunityCollection).toHaveBeenCalledWith("store-1", expect.any(String));
  });
  it("records an explicit decision and keeps adoption gated by eligibility", async () => {
    api.getOpportunities.mockResolvedValue({
      items: [{
        id: "11111111-1111-4111-8111-111111111111", title: "Local spring drinks", summary: "A reviewed source item",
        source_url: "https://example.test/item", published_at: null, discovered_at: "2026-11-11T00:00:00Z",
        expires_at: null, region: null, heat_value: null, heat_unit: null, evidence_status: "collected",
        relevance_score: "82.5", match_method: "rules", reason_summary: "Matches a confirmed product",
        suggested_scenario: null, content_angle: null, risk_flags: [], eligibility_status: "eligible", decision: null,
      }], total: 1, source_status: "available", empty_reason: null,
    });
    api.getOpportunity.mockResolvedValue({
      id: "11111111-1111-4111-8111-111111111111", title: "Local spring drinks", summary: "A reviewed source item",
      source: { url: "https://example.test/item", evidence_status: "collected" },
      match: { eligibility_status: "eligible", method: "rules", score: "82.5", reason: "Matches a confirmed product" },
    });
    api.decideOpportunity.mockResolvedValue({ id: "decision-1", decision: "adopt", replayed: false });
    render(<HotspotWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "查看详情" }));
    expect(await screen.findByRole("heading", { name: "Local spring drinks" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "采纳机会" }));
    await waitFor(() => expect(api.decideOpportunity).toHaveBeenCalledWith(
      "store-1", "11111111-1111-4111-8111-111111111111", "adopt", "", expect.any(String),
    ));
    fireEvent.click(await screen.findByRole("button", { name: "基于此机会制作内容" }));
    expect(window.location.hash).toBe("#create");
    expect(JSON.parse(sessionStorage.getItem("store-operator.opportunity-handoff.store-1") ?? "{}"))
      .toMatchObject({ opportunity_id: "11111111-1111-4111-8111-111111111111" });
  });
});
