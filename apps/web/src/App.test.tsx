import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

const user = { id: "user-1", email: "owner@example.com" };
const store = { id: "store-1", name: "测试门店", role: "owner" as const };

describe("identity and store context", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("logs in, loads memberships and selects a store through the server", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return jsonResponse({ error: { message: "Unauthenticated" } }, 401);
      if (path.endsWith("/auth/login")) return jsonResponse({ user, csrf_token: "csrf-login", session: { expires_at: "2030-01-01T00:00:00Z" } });
      if (path.endsWith("/me/stores")) return jsonResponse({ items: [store], active_store_id: null });
      if (path.endsWith("/session/active-store") && init?.method === "POST") return jsonResponse({ active_store: { id: store.id, name: store.name }, membership: { role: "owner" } });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await screen.findByRole("heading", { name: "登录工作台" });
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "correct-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await screen.findByRole("heading", { name: "选择门店" });
    fireEvent.click(screen.getByRole("button", { name: /测试门店/ }));
    await screen.findByRole("heading", { name: "门店工作台" });

    const selection = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/session/active-store") && init?.method === "POST");
    expect(selection).toBeDefined();
    expect((selection?.[1]?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-login");
    expect(screen.getByText("当前门店：测试门店")).toBeInTheDocument();
  });

  it("restores an existing HttpOnly-cookie session and obtains a fresh CSRF token", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return jsonResponse({ user, active_store: { id: store.id, name: store.name }, session: { expires_at: "2030-01-01T00:00:00Z" } });
      if (path.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-restored" });
      if (path.endsWith("/me/stores")) return jsonResponse({ items: [store], active_store_id: store.id });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await screen.findByRole("heading", { name: "门店工作台" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/csrf",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    ));
    expect(screen.getByText("当前门店：测试门店")).toBeInTheDocument();
  });

  it("logs out with the in-memory CSRF token", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return jsonResponse({ user, active_store: { id: store.id, name: store.name }, session: { expires_at: "2030-01-01T00:00:00Z" } });
      if (path.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-restored" });
      if (path.endsWith("/me/stores")) return jsonResponse({ items: [store], active_store_id: store.id });
      if (path.endsWith("/auth/logout") && init?.method === "POST") return { ok: true, status: 204 } as Response;
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await screen.findByRole("heading", { name: "门店工作台" });
    fireEvent.click(screen.getByRole("button", { name: "退出" }));
    await screen.findByRole("heading", { name: "登录工作台" });
    const logout = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/auth/logout"));
    expect((logout?.[1]?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-restored");
  });
});
