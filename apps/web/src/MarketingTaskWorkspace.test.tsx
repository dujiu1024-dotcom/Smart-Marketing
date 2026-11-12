import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import MarketingTaskWorkspace from "./MarketingTaskWorkspace";

afterEach(() => cleanup());
const api = vi.hoisted(() => ({
  archiveMarketingTask: vi.fn(), cancelMarketingTask: vi.fn(),
  confirmMarketingTaskRequirement: vi.fn(), confirmMarketingTaskStrategy: vi.fn(),
  createMarketingTask: vi.fn(), createTaskArtifact: vi.fn(), createTaskArtifactVersion: vi.fn(), createTaskArtifactReview: vi.fn(),
  createChannelContent: vi.fn(), runChannelContentQuality: vi.fn(), createQualityResolution: vi.fn(),
  freezePublishPackage: vi.fn(), confirmPublishPackage: vi.fn(), listChannelContents: vi.fn(),
  listPublishPackages: vi.fn(), listChannelSpecs: vi.fn(), listTaskBusinessFacts: vi.fn(),
  getMediaAssets: vi.fn(), listTaskArtifacts: vi.fn(), getAudienceProfiles: vi.fn(), getBrandGuideline: vi.fn(),
  getKnowledgeItems: vi.fn(), getMarketingTask: vi.fn(), listOffers: vi.fn(),
  getProducts: vi.fn(), getStoreProfile: vi.fn(), listMarketingTasks: vi.fn(),
  recoverMarketingTaskStep: vi.fn(), skipMarketingTaskStep: vi.fn(),
  updateMarketingTaskRequirement: vi.fn(), updateMarketingTaskStrategy: vi.fn(),
}));
vi.mock("./api", () => api);
const storeId = "store-1";
const task = {
  id: "task-1", store_id: storeId, task_type: "full_marketing", lifecycle_status: "draft",
  title: "周末新品推广", version: 1, current_requirement_snapshot_id: null,
  current_strategy_snapshot_id: null, created_at: "2026-11-12T01:00:00Z",
  updated_at: "2026-11-12T01:00:00Z", pending_steps_count: 8, blocked_steps_count: 0,
  requirement_draft: { goal: "提高周末到店转化", target_audience: "附近白领" },
  strategy_draft: {}, task_options: { includes_copy: true, includes_image: true, opportunity_applicable: false, selected_channel_keys: ["douyin"], requires_external_delivery: false },
  steps: [
    "requirement_understanding", "context_snapshot", "opportunity_decision", "strategy_confirmation",
    "copy_production_review", "image_production_review", "channel_adaptation", "quality_check",
    "final_confirmation", "delivery",
  ].map((step_key, index) => ({
    id: `step-${index}`, step_key, status: index === 2 || index === 8 || index === 9 ? "skipped" : "pending",
    applicability: index === 2 || index === 8 || index === 9 ? "not_applicable" : "required",
    version: 1, skip_reason: null, input_fingerprint: null, output_refs: [], blocked_by: [],
    block_code: null, block_detail: null, started_at: null, finished_at: null,
  })),
};
function mockFactSources() {
  api.getStoreProfile.mockResolvedValue({ id: "profile-1", display_name: "测试门店", fact_status: "confirmed", current_version: 2 });
  api.getProducts.mockResolvedValue({ items: [], total: 0 });
  api.listOffers.mockResolvedValue({ items: [], total: 0 });
  api.getBrandGuideline.mockRejectedValue(new Error("not found"));
  api.getAudienceProfiles.mockResolvedValue({ items: [], total: 0 });
  api.getKnowledgeItems.mockResolvedValue({ items: [], total: 0 });
}
describe("marketing task workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    window.location.hash = "#tasks";
    api.listMarketingTasks.mockResolvedValue({ items: [{ ...task, steps: undefined }], total: 1 });
    api.getMarketingTask.mockResolvedValue(task);
    api.createMarketingTask.mockResolvedValue(task);
    api.listTaskArtifacts.mockResolvedValue([]);
    api.getMediaAssets.mockResolvedValue({ items: [], total: 0 });
    api.listChannelContents.mockResolvedValue([]);
    api.listPublishPackages.mockResolvedValue([]);
    api.listChannelSpecs.mockResolvedValue([]);
    api.listTaskBusinessFacts.mockResolvedValue([]);
    api.createTaskArtifact.mockResolvedValue({ id: "artifact-copy", task_id: task.id, artifact_type: "copy", current_version_id: "version-1", created_at: "2026-11-12T01:00:00Z", updated_at: "2026-11-12T01:00:00Z", versions: [] });
    api.createTaskArtifactReview.mockResolvedValue({ id: "review-1" });
    api.confirmMarketingTaskRequirement.mockResolvedValue({ ...task, lifecycle_status: "active", version: 2 });
    mockFactSources();
  });

  it("shows the channel verification gate and publish confirmation workspace", async () => {
    sessionStorage.setItem(`store-operator.current-task-id.${storeId}`, task.id);
    window.location.hash = "#task";
    render(<MarketingTaskWorkspace storeId={storeId} />);
    expect(await screen.findByText("渠道适配与质检")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建抖音适配快照" })).toBeDisabled();
    expect(screen.getByText("最终发布确认")).toBeInTheDocument();
  });
  it("lists current-store tasks and opens the selected task", async () => {
    render(<MarketingTaskWorkspace storeId={storeId} />);
    expect(await screen.findByText("周末新品推广")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /周末新品推广/ }));
    await waitFor(() => expect(api.getMarketingTask).toHaveBeenCalledWith(storeId, "task-1"));
    expect(screen.getByText("固定执行流程")).toBeInTheDocument();
  });
  it("creates a task with a stable idempotency key and explicit scope", async () => {
    window.location.hash = "#create";
    render(<MarketingTaskWorkspace storeId={storeId} />);
    fireEvent.change(screen.getByLabelText("任务名称 *"), { target: { value: "周末新品推广" } });
    fireEvent.change(screen.getByLabelText("经营目标 *"), { target: { value: "提高周末到店转化" } });
    fireEvent.change(screen.getByLabelText("目标客群"), { target: { value: "附近白领" } });
    fireEvent.click(screen.getByRole("button", { name: "创建营销任务" }));
    await waitFor(() => expect(api.createMarketingTask).toHaveBeenCalledWith(
      storeId,
      expect.objectContaining({
        task_type: "full_marketing",
        title: "周末新品推广",
        requirement_draft: expect.objectContaining({ goal: "提高周末到店转化", target_audience: "附近白领" }),
        task_options: expect.objectContaining({ includes_copy: true, includes_image: true, selected_channel_keys: ["douyin"] }),
      }),
      expect.any(String),
    ));
  });

  it("creates a merchant-edited copy artifact through the real artifact API", async () => {
    sessionStorage.setItem(`store-operator.current-task-id.${storeId}`, task.id);
    window.location.hash = "#task";
    render(<MarketingTaskWorkspace storeId={storeId} />);
    fireEvent.change(await screen.findByLabelText("文案标题"), { target: { value: "周末新品" } });
    fireEvent.change(screen.getByLabelText("文案正文"), { target: { value: "本周末到店体验新品。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存文案版本" }));
    await waitFor(() => expect(api.createTaskArtifact).toHaveBeenCalledWith(
      storeId, task.id, "copy",
      expect.objectContaining({
        source_type: "manual_edit",
        content_json: expect.objectContaining({ title: "周末新品", body: "本周末到店体验新品。" }),
      }),
      expect.any(String),
    ));
  });
  it("records approval against the exact current artifact version", async () => {
    const artifact = {
      id: "artifact-copy", task_id: task.id, artifact_type: "copy", current_version_id: "version-1",
      created_at: "2026-11-12T01:00:00Z", updated_at: "2026-11-12T01:00:00Z",
      versions: [{
        id: "version-1", artifact_id: "artifact-copy", version_no: 3, source_type: "manual_edit",
        source_refs: [], instruction: null, content_json: { title: "周末新品", body: "到店体验。" },
        content_hash: "abc", provider_id: null, model_id: null, prompt_version_id: null,
        input_fingerprint: "fingerprint", created_at: "2026-11-12T01:00:00Z",
      }],
    };
    api.listTaskArtifacts.mockResolvedValue([artifact]);
    sessionStorage.setItem(`store-operator.current-task-id.${storeId}`, task.id);
    window.location.hash = "#task";
    render(<MarketingTaskWorkspace storeId={storeId} />);
    fireEvent.click(await screen.findByRole("button", { name: "审核通过" }));
    await waitFor(() => expect(api.createTaskArtifactReview).toHaveBeenCalledWith(
      storeId, task.id, artifact, artifact.versions[0],
      { expected_version: 3, review_type: "copy", decision: "approved", comment: null },
      expect.any(String),
    ));
  });
  it("requires an explicit selection of confirmed store facts before requirement confirmation", async () => {
    sessionStorage.setItem(`store-operator.current-task-id.${storeId}`, task.id);
    window.location.hash = "#task";
    render(<MarketingTaskWorkspace storeId={storeId} />);
    expect(await screen.findByText("门店档案 · 测试门店")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "确认需求与事实" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(api.confirmMarketingTaskRequirement).toHaveBeenCalledWith(
      storeId, task, [{ fact_key: "store_profile", record_type: "store_profile", record_id: "profile-1", expected_version_no: 2 }],
    ));
  });
});
