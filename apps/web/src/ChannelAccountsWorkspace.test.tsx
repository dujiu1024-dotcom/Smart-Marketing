import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ChannelAccountsWorkspace from "./ChannelAccountsWorkspace";

afterEach(() => cleanup());
const api = vi.hoisted(() => ({
  listDouyinAccounts: vi.fn(),
  startDouyinAuthorization: vi.fn(),
  refreshDouyinAccount: vi.fn(),
}));
vi.mock("./api", () => api);

describe("channel accounts workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listDouyinAccounts.mockResolvedValue([]);
    api.startDouyinAuthorization.mockResolvedValue({
      authorization_url: "https://open.douyin.com/platform/oauth/connect?state=test",
      expires_in: "600",
    });
  });
  it("creates an official OAuth link without fabricating a connected account", async () => {
    render(<ChannelAccountsWorkspace storeId="store-1" />);
    expect(await screen.findByText("当前门店尚未连接抖音账号")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "生成官方授权链接" }));
    const link = await screen.findByRole("link", { name: "打开抖音官方授权页面" });
    expect(link).toHaveAttribute("href", "https://open.douyin.com/platform/oauth/connect?state=test");
    expect(api.startDouyinAuthorization).toHaveBeenCalledWith("store-1");
    expect(api.listDouyinAccounts).toHaveBeenCalledTimes(1);
  });
  it("shows the server-owned account status and supports revalidation", async () => {
    api.listDouyinAccounts.mockResolvedValue([{
      id: "account-1", provider: "douyin", external_account_id: "open-id-1",
      display_name: "测试抖音账号", avatar_url: null, granted_scopes: ["user_info", "video.create"],
      access_token_expires_at: "2026-11-13T00:00:00Z", refresh_token_expires_at: null,
      status: "active", connected_at: "2026-11-12T00:00:00Z", last_verified_at: null,
    }]);
    api.refreshDouyinAccount.mockResolvedValue({});
    render(<ChannelAccountsWorkspace storeId="store-1" />);
    expect(await screen.findByText("测试抖音账号")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新验证授权" }));
    await waitFor(() => expect(api.refreshDouyinAccount).toHaveBeenCalledWith("store-1", "account-1"));
  });
});
