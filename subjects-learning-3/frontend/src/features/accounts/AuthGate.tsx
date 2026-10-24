import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../../api/client";

type User = { id: string; email: string };
type AuthState = { user: User | null; logout: () => Promise<void> };
const AuthContext = createContext<AuthState>({ user: null, logout: async () => {} });
export const useAccount = () => useContext(AuthContext);

export default function AuthGate({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<"loading" | "legacy" | "login" | "ready">("loading");
  const [user, setUser] = useState<User | null>(null);
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let alive = true;
    api<{ enabled: boolean }>("/auth/config")
      .then(async ({ enabled }) => {
        if (!alive) return;
        if (!enabled) { setMode("legacy"); return; }
        try {
          const current = await api<User>("/auth/me");
          if (alive) { setUser(current); setMode("ready"); }
        } catch {
          if (alive) setMode("login");
        }
      })
      .catch(() => { if (alive) { setNotice("无法连接本地服务，请启动后重试。"); setMode("login"); } });
    return () => { alive = false; };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setNotice("");
    try {
      if (register) {
        const result = await api<{ email_confirmation_required: boolean }>("/auth/register", {
          method: "POST", body: JSON.stringify({ email, password }),
        });
        setNotice(result.email_confirmation_required
          ? "注册成功，请打开验证邮件，确认邮箱后再登录。"
          : "注册成功，请登录。");
        setRegister(false);
        setPassword("");
      } else {
        const result = await api<{ user: User }>("/auth/login", {
          method: "POST", body: JSON.stringify({ email, password }),
        });
        setPassword("");
        setUser(result.user);
        setMode("ready");
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      setUser(null);
      setMode("login");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "退出登录失败，请重试。");
    }
  }

  if (mode === "loading") return <main className="account-screen">正在检查登录状态…</main>;
  if (mode === "login") return <main className="account-screen">
    <section className="account-card" aria-label={register ? "注册" : "登录"}>
      <h1>题研</h1>
      <p>个人学习资料保存在这台主设备的独立账号目录。</p>
      <form onSubmit={submit}>
        <label>邮箱<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></label>
        <label>密码<input type="password" autoComplete={register ? "new-password" : "current-password"} required minLength={6} value={password} onChange={event => setPassword(event.target.value)} /></label>
        <button className="button primary" type="submit" disabled={busy}>{busy ? "请稍候…" : register ? "注册" : "登录"}</button>
      </form>
      {notice && <p role="status">{notice}</p>}
      <button className="link-button" type="button" onClick={() => { setRegister(!register); setNotice(""); }}>{register ? "已有账号？登录" : "没有账号？注册"}</button>
    </section>
  </main>;
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>;
}
