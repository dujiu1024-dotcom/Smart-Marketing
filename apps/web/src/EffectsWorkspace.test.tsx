import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import EffectsWorkspace from "./EffectsWorkspace";

afterEach(() => cleanup());
const api = vi.hoisted(() => ({
  getEffectsOverview: vi.fn(), getMetricDefinitions: vi.fn(), getMetricObservations: vi.fn(),
  createMetricObservation: vi.fn(), importMetricCsv: vi.fn(), importMetricXlsx: vi.fn(),
  getPublishedWorks: vi.fn(), getBusinessOutcomes: vi.fn(), getAttributions: vi.fn(),
  getDataSourceCapabilities: vi.fn(), checkDataSourceCapabilities: vi.fn(), getPublishReadbacks: vi.fn(), registerPublishedWorkFromReadback: vi.fn(),
}));
vi.mock("./api", async () => ({ ...(await vi.importActual<typeof import("./api")>("./api")), ...api }));

describe("effects workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getEffectsOverview.mockResolvedValue({
      items: [], trends: [], content_performance: [], insights: [], conversion_rates: [],
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
    api.checkDataSourceCapabilities.mockResolvedValue({ items: [], total: 3 });
    api.getPublishReadbacks.mockResolvedValue({ items: [], total: 0 });
  });
  it("keeps business outcomes unavailable until verified evidence exists", async () => {
    render(<EffectsWorkspace storeId="store-1" />);
    expect(await screen.findByRole("heading", { name: "经营效果" })).toBeInTheDocument();
    expect(screen.getAllByText("暂无数据").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/不计算 ROI/).length).toBeGreaterThan(0);
    expect(screen.getByText(/手工录入与导入的数据均标记为商家报告/)).toBeInTheDocument();
  });

  it("lets merchants refresh channel capability snapshots", async () => {
    render(<EffectsWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "检测渠道能力" }));
    expect(await screen.findByText(/已刷新渠道能力快照：3 项/)).toBeInTheDocument();
    expect(api.checkDataSourceCapabilities).toHaveBeenCalledWith("store-1");
  });

  it("shows verified per-work performance comparisons and their chart", async () => {
    api.getEffectsOverview.mockResolvedValue({
      items: [],
      trends: [],
      insights: [{
        metric_key: "views",
        display_name: "播放量",
        source_system: "official_api",
        channel_key: "douyin",
        period_end: "2026-11-03T00:00:00+00:00",
        sample_count: 2,
        comparison_status: "available",
        observation: "相邻周期上升 50%。",
        next_action: "复核作品主题和发布时间。",
      }],
      content_performance: [{
        published_work_id: "work-verified-1",
        marketing_task_id: "task-1",
        channel_key: "douyin",
        external_work_id: "douyin-post-001",
        metric_key: "views",
        source_system: "official_api",
        definition_version: 1,
        display_name: "作品播放量",
        points: [
          { period_start: "2026-11-01T00:00:00+00:00", period_end: "2026-11-02T00:00:00+00:00", value: "100", sample_count: 1, timezone: "UTC" },
          { period_start: "2026-11-02T00:00:00+00:00", period_end: "2026-11-03T00:00:00+00:00", value: "150", sample_count: 1, timezone: "UTC" },
        ],
        comparison: { status: "available", change_percent: "50.00" },
      }],
      data_quality: { total_observations: 2, verified_observations: 2, delayed_observations: 0,
        incomplete_or_anomalous_observations: 0, status: "available", reason: null },
      data_status: "available",
      business_outcomes: { roi: null, sales_growth: null, store_visit_growth: null,
        reason: "没有已核验的真实经营结果与成本证据时，不计算 ROI、销售增长或到店增长。" },
    });
    render(<EffectsWorkspace storeId="store-1" />);
    expect(await screen.findByText("按作品查看内容表现")).toBeInTheDocument();
    expect(screen.getByText(/抖音 · douyin-post-001/)).toBeInTheDocument();
    expect(screen.getByText(/环比 50.00%/)).toBeInTheDocument();
    expect(screen.getByText(/关联任务：task-1/)).toBeInTheDocument();
    expect(screen.getByText(/复核作品主题和发布时间/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "作品播放量作品表现趋势图" })).toBeInTheDocument();
  });

  it("imports an Excel workbook through the dedicated xlsx endpoint", async () => {
    api.importMetricXlsx.mockResolvedValue({
      created: 2, duplicates_skipped: 1, import_batch_id: "batch-xlsx",
      content_sha256: "abc123", authenticity_status: "merchant_reported", message: "ok",
    });
    render(<EffectsWorkspace storeId="store-1" />);
    const file = new File(["xlsx"], "metrics.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    Object.defineProperty(file, "arrayBuffer", {
      value: vi.fn().mockResolvedValue(new Uint8Array([80, 75, 3, 4]).buffer),
    });
    fireEvent.change(await screen.findByLabelText("Excel 工作簿（.xlsx，最大 5 MB）"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入 Excel" }));
    expect(await screen.findByText(/Excel 导入完成：新增 2 条，重复跳过 1 条/)).toBeInTheDocument();
    expect(api.importMetricXlsx).toHaveBeenCalledWith("store-1", "metrics.xlsx", "UEsDBA==");
  });

});