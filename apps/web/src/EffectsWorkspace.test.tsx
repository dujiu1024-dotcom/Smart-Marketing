import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import EffectsWorkspace from "./EffectsWorkspace";

afterEach(() => cleanup());
const api = vi.hoisted(() => ({
  getEffectsOverview: vi.fn(), getMetricDefinitions: vi.fn(), getMetricObservations: vi.fn(),
  createMetricObservation: vi.fn(), importMetricCsv: vi.fn(),
  getPublishedWorks: vi.fn(), getBusinessOutcomes: vi.fn(), getAttributions: vi.fn(),
  getDataSourceCapabilities: vi.fn(), getPublishReadbacks: vi.fn(), registerPublishedWorkFromReadback: vi.fn(),
}));
vi.mock("./api", async () => ({ ...(await vi.importActual<typeof import("./api")>("./api")), ...api }));

describe("effects workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getEffectsOverview.mockResolvedValue({
      items: [], trends: [],
      data_quality: { total_observations: 0, verified_observations: 0, delayed_observations: 0,
        incomplete_or_anomalous_observations: 0, status: "unavailable", reason: "暂无可核验数据" },
      data_status: "unavailable",
      business_outcomes: { roi: null, sales_growth: null, store_visit_growth: null,
        reason: "没有已核验的真实经营结果与成本证据时，不计算 ROI、销售增长或到店增长。" },
    });
    api.getMetricDefinitions.mockResolvedValue({ items: [{
      id: "metric-views", source_system: "manual", metric_key: "views",
      metric_tier: "content_performance", display_name: "播放/浏览", unit: null,
      definition: "Views", definition_version: 1,
    }] });
    api.getMetricObservations.mockResolvedValue({ items: [] });
    api.getPublishedWorks.mockResolvedValue({ items: [], total: 0, verified_count: 0 });
    api.getBusinessOutcomes.mockResolvedValue({ items: [], total: 0 });
    api.getAttributions.mockResolvedValue({ items: [], total: 0 });
    api.getDataSourceCapabilities.mockResolvedValue({ items: [], total: 0 });
    api.getPublishReadbacks.mockResolvedValue({ items: [], total: 0 });
  });
  it("keeps business outcomes unavailable until verified evidence exists", async () => {
    render(<EffectsWorkspace storeId="store-1" />);
    expect(await screen.findByRole("heading", { name: "经营效果" })).toBeInTheDocument();
    expect(screen.getAllByText("暂无数据").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/不计算 ROI/).length).toBeGreaterThan(0);
    expect(screen.getByText(/手工录入与导入的数据均标记为商家报告/)).toBeInTheDocument();
  });
});
