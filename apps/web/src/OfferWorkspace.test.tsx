import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import OfferWorkspace from "./OfferWorkspace";

afterEach(() => cleanup());

const api = vi.hoisted(() => ({
  getOffers: vi.fn(),
  createOffer: vi.fn(),
  updateOffer: vi.fn(),
  confirmOfferFacts: vi.fn(),
}));

vi.mock("./api", () => api);

const storeId = "store-1";
const offer = {
  id: "offer-1",
  store_id: storeId,
  title: "工作日下午茶买一赠一",
  offer_type: "buy_x_get_y",
  terms_json: { buy_quantity: 1, gift_quantity: 1 },
  eligibility_rules_json: { product_ids: ["product-1"] },
  starts_at: "2026-12-01T01:00:00Z",
  ends_at: "2026-12-31T15:59:59Z",
  stacking_policy: "not_stackable",
  usage_limit: 100,
  status: "draft" as const,
  fact_status: "pending_confirmation",
  current_version: 1,
};

describe("store offer workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "#store:offers";
    api.getOffers.mockResolvedValue({ items: [offer], total: 1 });
    api.createOffer.mockResolvedValue({ ...offer, id: "offer-2", title: "周末套餐优惠" });
    api.updateOffer.mockResolvedValue({ ...offer, title: "下午茶买二赠一", current_version: 2 });
    api.confirmOfferFacts.mockResolvedValue({ ...offer, fact_status: "confirmed", current_version: 2 });
  });

  it("loads and updates structured offer rules with optimistic version", async () => {
    render(<OfferWorkspace storeId={storeId} />);
    expect(await screen.findByText("工作日下午茶买一赠一")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(await screen.findByLabelText("活动名称 *"), { target: { value: "下午茶买二赠一" } });
    fireEvent.click(screen.getByRole("button", { name: "保存活动" }));

    await waitFor(() => {
      expect(api.updateOffer).toHaveBeenCalledWith(
        storeId,
        offer,
        expect.objectContaining({
          title: "下午茶买二赠一",
          terms_json: { buy_quantity: 1, gift_quantity: 1 },
          starts_at: "2026-12-01T01:00:00.000Z",
        }),
      );
    });
  });

  it("requires explicit timezone offsets and preserves structured rules on create", async () => {
    render(<OfferWorkspace storeId={storeId} />);
    await screen.findByText("工作日下午茶买一赠一");
    fireEvent.click(screen.getByRole("button", { name: "新增活动" }));
    fireEvent.change(await screen.findByLabelText("活动名称 *"), { target: { value: "周末套餐优惠" } });
    fireEvent.change(screen.getByLabelText("开始时间（含时区）"), { target: { value: "2026-12-01T09:00:00+08:00" } });
    fireEvent.change(screen.getByLabelText("结束时间（含时区）"), { target: { value: "2026-12-31T23:59:59+08:00" } });
    fireEvent.change(screen.getByLabelText("优惠规则（JSON 对象） *"), {
      target: { value: '{"kind":"bundle","discount_percent":10}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存活动" }));

    await waitFor(() => {
      expect(api.createOffer).toHaveBeenCalledWith(
        storeId,
        expect.objectContaining({
          title: "周末套餐优惠",
          starts_at: "2026-12-01T01:00:00.000Z",
          ends_at: "2026-12-31T15:59:59.000Z",
          terms_json: { kind: "bundle", discount_percent: 10 },
        }),
      );
    });
  });

  it("confirms offer facts separately", async () => {
    render(<OfferWorkspace storeId={storeId} />);
    await screen.findByText("工作日下午茶买一赠一");
    fireEvent.click(screen.getByRole("button", { name: "确认事实" }));
    await waitFor(() => expect(api.confirmOfferFacts).toHaveBeenCalledWith(storeId, offer));
    expect(await screen.findByText("工作日下午茶买一赠一 的活动规则 V2 已确认。")).toBeInTheDocument();
  });
});
