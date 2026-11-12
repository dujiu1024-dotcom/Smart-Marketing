import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProductWorkspace from "./ProductWorkspace";

const api = vi.hoisted(() => ({
  listProducts: vi.fn(),
  getProduct: vi.fn(),
  createProduct: vi.fn(),
  updateProduct: vi.fn(),
  deleteProduct: vi.fn(),
  confirmProductFacts: vi.fn(),
}));
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, ...api };
});

const product = {
  id: "product-1",
  store_id: "store-1",
  name: "桂花乌龙",
  category: "饮品",
  sku: "DRINK-001",
  specification: "500ml",
  unit: "杯",
  price_amount: "28.00",
  currency: "CNY",
  availability_status: "available" as const,
  inventory_quantity: "120",
  key_selling_points_json: ["鲜萃乌龙", "桂花香"],
  description: "现制茶饮",
  ingredients_or_materials: "乌龙茶、桂花",
  allergens_and_restrictions_json: [],
  service_process: null,
  delivery_method: "堂食、自取",
  fact_status: "pending_confirmation",
  current_version: 1,
};

afterEach(() => cleanup());
beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = "#store:products";
  api.listProducts.mockResolvedValue({ items: [product], total: 1 });
  api.getProduct.mockResolvedValue(product);
  api.createProduct.mockResolvedValue({ ...product, id: "product-2" });
  api.updateProduct.mockResolvedValue({ ...product, current_version: 2 });
  api.deleteProduct.mockResolvedValue(undefined);
  api.confirmProductFacts.mockResolvedValue({ ...product, fact_status: "confirmed", current_version: 2 });
});

describe("production product workspace", () => {
  it("loads tenant-scoped products and opens the independent editor route", async () => {
    render(<ProductWorkspace storeId="store-1" />);
    expect(await screen.findByText("桂花乌龙")).toBeInTheDocument();
    expect(screen.getByText("CNY 28.00")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /桂花乌龙/ }));
    expect(await screen.findByRole("heading", { name: "编辑商品 / 服务" })).toBeInTheDocument();
    await waitFor(() => expect(api.getProduct).toHaveBeenCalledWith("store-1", "product-1"));
  });

  it("creates a product through the production API contract", async () => {
    api.listProducts.mockResolvedValue({ items: [], total: 0 });
    render(<ProductWorkspace storeId="store-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "新增商品 / 服务" }));
    expect(await screen.findByRole("heading", { name: "新增商品 / 服务" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("商品 / 服务名称 *"), { target: { value: "鲜果茶" } });
    fireEvent.click(screen.getByRole("button", { name: "创建商品" }));

    await waitFor(() => expect(api.createProduct).toHaveBeenCalledWith(
      "store-1",
      expect.objectContaining({ name: "鲜果茶", price_amount: null, currency: null }),
      expect.any(String),
    ));
  });
});
