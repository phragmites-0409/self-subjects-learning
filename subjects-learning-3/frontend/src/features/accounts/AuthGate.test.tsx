import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AuthGate, { useAccount } from "./AuthGate";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function PrivateView() {
  const { user, logout } = useAccount();
  return <div>{user?.username}<button onClick={() => void logout()}>退出登录</button></div>;
}

it("requires Supabase sign-in before mounting private content and clears it on logout", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/auth/config")) return { ok: true, json: async () => ({ enabled: true }) };
    if (url.endsWith("/auth/me")) return { ok: false, json: async () => ({ error: { message: "请先登录" } }) };
    if (url.endsWith("/auth/login")) {
      expect(options?.method).toBe("POST");
      expect(JSON.parse(String(options?.body))).toEqual({ username: "first", password: "password123" });
      return { ok: true, json: async () => ({ user: { id: "u1", username: "first" } }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
  });
  vi.stubGlobal("fetch", fetch);
  render(<AuthGate><PrivateView /></AuthGate>);
  await screen.findByRole("region", { name: "登录" });
  expect(screen.queryByText("first")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "first" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password123" } });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByText("first");
  fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
  await waitFor(() => expect(screen.getByRole("region", { name: "登录" })).toBeInTheDocument());
  expect(screen.queryByText("first")).not.toBeInTheDocument();
});
