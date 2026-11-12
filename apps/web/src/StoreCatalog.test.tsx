import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import StoreCatalog from "./StoreCatalog";

const api = vi.hoisted(() => ({
  getProducts: vi.fn(), getOffers: vi.fn(), createProduct: vi.fn(), updateProduct: vi.fn(),
  deleteProduct: vi.fn(), createOffer: vi.fn(), updateOffer: vi.fn(), deleteOffer: vi.fn(),
}));
vi.mock("./api", () => api);
afterEach(() => cleanup());

describe("StoreCatalog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getProducts.mockResolvedValue({ items: [], total: 0 });
    api.getOffers.mockResolvedValue({ items: [], total: 0 });
    api.createProduct.mockResolvedValue({ id: "p1" });
    api.createOffer.mockResolvedValue({ id: "o1" });
  });

  it("loads the current store's products and creates through the API", async () => {
    render(<StoreCatalog storeId="store-1" initialTab="products" />);
    expect(await screen.findByText("暂无商品或服务记录。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新增商品 / 服务" }));
    fireEvent.change(screen.getByLabelText("名称 *"), { target: { value: "招牌奶茶" } });
    fireEvent.click(screen.getByRole("button", { name: "保存商品资料" }));
    await waitFor(() => expect(api.createProduct).toHaveBeenCalledWith(
      "store-1", expect.objectContaining({ name: "招牌奶茶", availability_status: "unknown" }),
    ));
  });

  it("loads and creates offers with structured rules", async () => {
    render(<StoreCatalog storeId="store-1" initialTab="offers" />);
    expect(await screen.findByText("暂无活动或优惠记录。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新增活动" }));
    fireEvent.change(screen.getByLabelText("活动名称 *"), { target: { value: "第二杯半价" } });
    fireEvent.click(screen.getByRole("button", { name: "保存活动优惠" }));
    await waitFor(() => expect(api.createOffer).toHaveBeenCalledWith(
      "store-1", expect.objectContaining({ title: "第二杯半价", terms_json: {}, status: "draft" }),
    ));
  });
});
