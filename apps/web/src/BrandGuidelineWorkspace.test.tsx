import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import BrandGuidelineWorkspace from "./BrandGuidelineWorkspace";
import { ApiError } from "./api";

afterEach(() => cleanup());

const api = vi.hoisted(() => ({
  getBrandGuideline: vi.fn(),
  createBrandGuideline: vi.fn(),
  updateBrandGuideline: vi.fn(),
  confirmBrandGuidelineFacts: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, ...api };
});

const storeId = "store-1";
const guideline = {
  id: "brand-1",
  store_id: storeId,
  brand_story: "专注现制茶饮",
  positioning: "城市轻茶饮",
  differentiators: "每日现萃",
  core_values_json: ["品质", "真诚"],
  tone_of_voice: "自然、克制",
  common_phrases_json: ["现萃好茶"],
  prohibited_phrases_json: ["全网第一"],
  cta_preferences_json: ["到店体验"],
  logo_asset_id: null,
  color_palette_json: [{ name: "主色", hex: "#245744" }],
  font_preferences_json: ["思源黑体"],
  visual_style: "自然简约",
  fact_status: "pending_confirmation",
  current_version: 1,
};

describe("store brand guideline workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getBrandGuideline.mockResolvedValue(guideline);
    api.updateBrandGuideline.mockResolvedValue({ ...guideline, positioning: "城市精品茶饮", current_version: 2 });
    api.createBrandGuideline.mockResolvedValue({ ...guideline, id: "brand-2", current_version: 1 });
    api.confirmBrandGuidelineFacts.mockResolvedValue({ ...guideline, fact_status: "confirmed", current_version: 2 });
  });

  it("loads and updates brand voice and visual rules with version control", async () => {
    render(<BrandGuidelineWorkspace storeId={storeId} />);
    expect(await screen.findByDisplayValue("城市轻茶饮")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("品牌定位"), { target: { value: "城市精品茶饮" } });
    fireEvent.click(screen.getByRole("button", { name: "保存规范" }));

    await waitFor(() => {
      expect(api.updateBrandGuideline).toHaveBeenCalledWith(
        storeId,
        guideline,
        expect.objectContaining({
          positioning: "城市精品茶饮",
          prohibited_phrases_json: ["全网第一"],
          color_palette_json: [{ name: "主色", hex: "#245744" }],
        }),
      );
    });
  });

  it("creates a brand guideline when no server record exists", async () => {
    api.getBrandGuideline.mockRejectedValue(new ApiError("Not found", 404, "RESOURCE_NOT_FOUND"));
    render(<BrandGuidelineWorkspace storeId={storeId} />);
    fireEvent.change(await screen.findByLabelText("品牌定位"), { target: { value: "城市轻茶饮" } });
    fireEvent.click(screen.getByRole("button", { name: "创建品牌规范" }));

    await waitFor(() => {
      expect(api.createBrandGuideline).toHaveBeenCalledWith(
        storeId,
        expect.objectContaining({ positioning: "城市轻茶饮" }),
        expect.any(String),
      );
    });
  });

  it("does not confirm a stale brand guideline while edits are unsaved", async () => {
    render(<BrandGuidelineWorkspace storeId={storeId} />);
    await screen.findByDisplayValue("城市轻茶饮");
    fireEvent.change(screen.getByLabelText("品牌定位"), { target: { value: "未保存的新定位" } });

    const confirm = screen.getByRole("button", { name: "确认资料" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(api.confirmBrandGuidelineFacts).not.toHaveBeenCalled();
    expect(screen.getByLabelText("品牌定位")).toHaveValue("未保存的新定位");
  });

  it("confirms brand guideline facts separately", async () => {
    render(<BrandGuidelineWorkspace storeId={storeId} />);
    await screen.findByDisplayValue("城市轻茶饮");
    fireEvent.click(screen.getByRole("button", { name: "确认资料" }));
    await waitFor(() => expect(api.confirmBrandGuidelineFacts).toHaveBeenCalledWith(storeId, guideline));
    expect(await screen.findByText("品牌规范 V2 已确认。")).toBeInTheDocument();
  });
});
