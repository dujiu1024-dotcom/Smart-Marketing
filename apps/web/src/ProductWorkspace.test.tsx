import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProductWorkspace from "./ProductWorkspace";

afterEach(() => cleanup());

const api = vi.hoisted(() => ({
  getProducts: vi.fn(),
  createProduct: vi.fn(),
  updateProduct: vi.fn(),
  confirmProductFacts: vi.fn(),
}));

vi.mock("./api", () => api);

const storeId = "store-1";
const product = {
  id: "product-1",
  store_id: storeId,
  name: "拾光乌龙",
  category: "饮品",
  sku: "DR-001",
  specification: "中杯",
  unit: "杯",
  price_amount: "18.00",
  currency: "CNY",
  availability_status: "available" as const,
  inventory_quantity: null,
  key_selling_points_json: ["现萃茶汤"],
  description: "现制茶饮",
  ingredients_or_materials: "乌龙茶",
  allergens_and_restrictions_json: [],
  service_process: null,
  delivery_method: "堂食、自取",
  fact_status: "pending_confirmation",
  current_version: 1,
};

describe("store product workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "#store:products";
    api.getProducts.mockResolvedValue({ items: [product], total: 1 });
    api.updateProduct.mockResolvedValue({ ...product, name: "桂花乌龙", current_version: 2 });
    api.createProduct.mockResolvedValue({ ...product, id: "product-2", name: "茉莉绿茶" });
    api.confirmProductFacts.mockResolvedValue({ ...product, fact_status: "confirmed", current_version: 2 });
  });

  it("loads the real store catalog and updates with optimistic version", async () => {
    render(<ProductWorkspace storeId={storeId} />);
    expect(await screen.findByText("拾光乌龙")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(await screen.findByLabelText("商品 / 服务名称 *"), { target: { value: "桂花乌龙" } });
    fireEvent.click(screen.getByRole("button", { name: "保存商品" }));

    await waitFor(() => {
      expect(api.updateProduct).toHaveBeenCalledWith(
        storeId,
        product,
        expect.objectContaining({ name: "桂花乌龙", price_amount: "18.00", currency: "CNY" }),
      );
    });
    expect(await screen.findByText(/商品资料已保存为 V2/)).toBeInTheDocument();
  });

  it("keeps unknown price and currency null when creating a product", async () => {
    render(<ProductWorkspace storeId={storeId} />);
    await screen.findByText("拾光乌龙");
    fireEvent.click(screen.getByRole("button", { name: "新增商品 / 服务" }));
    fireEvent.change(await screen.findByLabelText("商品 / 服务名称 *"), { target: { value: "茉莉绿茶" } });
    fireEvent.change(screen.getByLabelText("价格金额"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存商品" }));

    await waitFor(() => {
      expect(api.createProduct).toHaveBeenCalledWith(
        storeId,
        expect.objectContaining({ name: "茉莉绿茶", price_amount: null, currency: null }),
      );
    });
  });

  it("confirms product facts as a separate explicit action", async () => {
    render(<ProductWorkspace storeId={storeId} />);
    await screen.findByText("拾光乌龙");
    fireEvent.click(screen.getByRole("button", { name: "确认事实" }));

    await waitFor(() => {
      expect(api.confirmProductFacts).toHaveBeenCalledWith(storeId, product);
    });
    expect(await screen.findByText("拾光乌龙 的事实版本 V2 已确认。")).toBeInTheDocument();
  });
});
