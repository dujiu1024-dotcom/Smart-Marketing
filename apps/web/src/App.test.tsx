import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { ApiError } from "./api";

const api = vi.hoisted(() => ({
  login: vi.fn(),
  getCurrentUser: vi.fn(),
  getStores: vi.fn(),
  setActiveStore: vi.fn(),
  getStoreProfile: vi.fn(),
  createStoreProfile: vi.fn(),
  updateStoreProfile: vi.fn(),
  confirmStoreProfileFacts: vi.fn(),
  clearCsrfToken: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, ...api };
});

const user = { id: "user-1", email: "owner@example.test" };
const store = { id: "store-1", name: "拾光茶研社", role: "owner" as const };
const profile = {
  id: "profile-1",
  store_id: store.id,
  display_name: "拾光茶研社",
  business_type: "直营门店",
  industry_category: "饮品",
  brand_name: "拾光",
  introduction: "现制茶饮",
  country_code: "CN",
  region: "钱江新城",
  province: "浙江省",
  city: "杭州市",
  district: "上城区",
  address: "钱江路 158 号",
  phone: "0571-12345678",
  opening_hours_json: { summary: "10:00-22:00", weekday: "10:00-22:00" },
  temporary_closures_json: [],
  service_radius: "3 公里",
  service_capabilities_json: ["堂食", "自取"],
  fact_status: "pending_confirmation",
  current_version: 1,
};

describe("store profile workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getCurrentUser.mockRejectedValue(new ApiError("Unauthenticated", 401, "UNAUTHENTICATED"));
    api.login.mockResolvedValue(user);
    api.getStores.mockResolvedValue({ items: [store], active_store_id: store.id });
    api.setActiveStore.mockResolvedValue(undefined);
    api.getStoreProfile.mockResolvedValue(profile);
    api.updateStoreProfile.mockResolvedValue({ ...profile, display_name: "拾光茶研社（万象城店）", current_version: 2 });
    api.confirmStoreProfileFacts.mockResolvedValue({ ...profile, fact_status: "confirmed", current_version: 2 });
  });

  it("requires authentication and labels unconnected store modules", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "登录门店工作台" })).toBeInTheDocument();
    expect(screen.getByText("使用已开通门店成员权限的账号登录。")).toBeInTheDocument();
  });

  it("loads a real store profile and saves it with the current version", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("邮箱 *"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("密码 *"), { target: { value: "correct-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByDisplayValue("拾光茶研社")).toBeInTheDocument();
    expect(await screen.findByText("V1 · 待确认")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("门店名称 *"), {
      target: { value: "拾光茶研社（万象城店）" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存档案" }));

    await waitFor(() => {
      expect(api.updateStoreProfile).toHaveBeenCalledWith(
        store.id,
        profile,
        expect.objectContaining({ display_name: "拾光茶研社（万象城店）" }),
      );
    });
    expect(await screen.findByText(/门店档案已保存为 V2/)).toBeInTheDocument();
  });
});


  it("requires an explicit action to confirm store facts", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("邮箱 *"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("密码 *"), { target: { value: "correct-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("V1 · 待确认")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认资料" }));

    await waitFor(() => {
      expect(api.confirmStoreProfileFacts).toHaveBeenCalledWith(store.id, profile);
    });
    expect(await screen.findByText("V2 · 已确认")).toBeInTheDocument();
  });
