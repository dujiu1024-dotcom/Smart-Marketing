import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import HotspotWorkspace from "./HotspotWorkspace";

afterEach(() => cleanup());
const api = vi.hoisted(() => ({
  getOpportunities: vi.fn(), getOpportunity: vi.fn(), decideOpportunity: vi.fn(),
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
  it("records an explicit decision and keeps adoption gated by eligibility", async () => {
    api.getOpportunities.mockResolvedValue({
      items: [{
        id: "opportunity-1", title: "Local spring drinks", summary: "A reviewed source item",
        source_url: "https://example.test/item", published_at: null, discovered_at: "2026-11-11T00:00:00Z",
        expires_at: null, region: null, heat_value: null, heat_unit: null, evidence_status: "collected",
        relevance_score: "82.5", match_method: "rules", reason_summary: "Matches a confirmed product",
        suggested_scenario: null, content_angle: null, risk_flags: [], eligibility_status: "eligible", decision: null,
      }], total: 1, source_status: "available", empty_reason: null,
    });
    api.getOpportunity.mockResolvedValue({
      id: "opportunity-1", title: "Local spring drinks", summary: "A reviewed source item",
      source: { url: "https://example.test/item", evidence_status: "collected" },
      match: { eligibility_status: "eligible", method: "rules", score: "82.5", reason: "Matches a confirmed product" },
    });
    api.decideOpportunity.mockResolvedValue({ id: "decision-1", decision: "adopt", replayed: false });
    render(<HotspotWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "查看详情" }));
    expect(await screen.findByRole("heading", { name: "Local spring drinks" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "采纳机会" }));
    await waitFor(() => expect(api.decideOpportunity).toHaveBeenCalledWith(
      "store-1", "opportunity-1", "adopt", "", expect.any(String),
    ));
  });
});
