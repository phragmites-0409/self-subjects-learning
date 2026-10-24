import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AuthGate, { useAccount } from "./AuthGate";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function PrivateView() {
  const { user, logout } = useAccount();
  return <div>{user?.email}<button onClick={() => void logout()}>退出登录</button></div>;
}

it("requires Supabase sign-in before mounting private content and clears it on logout", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/auth/config")) return { ok: true, json: async () => ({ enabled: true }) };
    if (url.endsWith("/auth/me")) return { ok: false, json: async () => ({ error: { message: "请先登录" } }) };
    if (url.endsWith("/auth/login")) {
      expect(options?.method).toBe("POST");
      return { ok: true, json: async () => ({ user: { id: "u1", email: "first@example.com" } }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
  });
  vi.stubGlobal("fetch", fetch);
  render(<AuthGate><PrivateView /></AuthGate>);
  await screen.findByRole("region", { name: "登录" });
  expect(screen.queryByText("first@example.com")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "first@example.com" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password123" } });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByText("first@example.com");
  fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
  await waitFor(() => expect(screen.getByRole("region", { name: "登录" })).toBeInTheDocument());
  expect(screen.queryByText("first@example.com")).not.toBeInTheDocument();
});
