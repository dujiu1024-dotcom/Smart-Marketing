import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import OfferWorkspace from "./OfferWorkspace";

const api = vi.hoisted(() => ({
  listOffers: vi.fn(), getOffer: vi.fn(), getProducts: vi.fn(), createOffer: vi.fn(),
  updateOffer: vi.fn(), deleteOffer: vi.fn(), confirmOfferFacts: vi.fn(),
}));
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, ...api };
});

const offer = {
  id: "offer-1", store_id: "store-1", title: "新客八折", offer_type: "discount_percent",
  terms_json: { percent: 80 }, eligibility_rules_json: { new_customer: true },
  starts_at: "2026-12-01T01:00:00Z", ends_at: "2026-12-31T15:59:59Z",
  stacking_policy: "not_stackable", usage_limit: null, status: "draft" as const,
  fact_status: "pending_confirmation", current_version: 1,
};
const product = {
  id: "product-1", store_id: "store-1", name: "桂花乌龙", category: "饮品", sku: null,
  specification: "500ml", unit: "杯", price_amount: "28.00", currency: "CNY",
  availability_status: "available" as const, inventory_quantity: null, key_selling_points_json: [],
  description: null, ingredients_or_materials: null, allergens_and_restrictions_json: [],
  service_process: null, delivery_method: "堂食", fact_status: "confirmed", current_version: 1,
};

afterEach(() => cleanup());
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  window.location.hash = "#store:offers";
  api.listOffers.mockResolvedValue({ items: [offer], total: 1 });
  api.getOffer.mockResolvedValue(offer);
  api.getProducts.mockResolvedValue({ items: [product], total: 1 });
  api.createOffer.mockResolvedValue({ ...offer, id: "offer-2" });
  api.updateOffer.mockResolvedValue({ ...offer, current_version: 2 });
  api.deleteOffer.mockResolvedValue(undefined);
  api.confirmOfferFacts.mockResolvedValue({ ...offer, fact_status: "confirmed", current_version: 2 });
});

describe("production offer workspace", () => {
  it("loads store offers and opens a dedicated editor route", async () => {
    render(<OfferWorkspace storeId="store-1" />);
    expect(await screen.findByText("新客八折")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /新客八折/ }));
    expect(await screen.findByRole("heading", { name: "编辑活动与优惠" })).toBeInTheDocument();
    await waitFor(() => expect(api.getOffer).toHaveBeenCalledWith("store-1", "offer-1"));
  });

  it("creates a structured discount offer with a stable idempotency key", async () => {
    api.listOffers.mockResolvedValue({ items: [], total: 0 });
    render(<OfferWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "新增活动" }));
    await screen.findByRole("heading", { name: "新增活动与优惠" });
    fireEvent.change(screen.getByLabelText("活动名称 *"), { target: { value: "新客八折" } });
    fireEvent.change(screen.getByLabelText("折扣比例（百分比）"), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "创建活动" }));

    await waitFor(() => expect(api.createOffer).toHaveBeenCalledWith(
      "store-1",
      expect.objectContaining({ title: "新客八折", offer_type: "discount_percent", terms_json: { percent: 80 } }),
      expect.any(String),
    ));
  });

  it("does not allow confirming an offer while edits are unsaved", async () => {
    render(<OfferWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: /新客八折/ }));
    await screen.findByRole("heading", { name: "编辑活动与优惠" });
    fireEvent.change(screen.getByLabelText("活动名称 *"), { target: { value: "新客七五折" } });
    const confirm = screen.getByRole("button", { name: "确认事实" });
    expect(confirm).toBeDisabled();
    expect(api.confirmOfferFacts).not.toHaveBeenCalled();
  });
});
