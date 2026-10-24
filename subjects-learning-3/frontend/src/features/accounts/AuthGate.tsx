import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../../api/client";

type User = { id: string; username: string };
type AuthState = { user: User | null; logout: () => Promise<void> };
const AuthContext = createContext<AuthState>({ user: null, logout: async () => {} });
export const useAccount = () => useContext(AuthContext);

export default function AuthGate({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<"loading" | "legacy" | "login" | "ready">("loading");
  const [user, setUser] = useState<User | null>(null);
  const [register, setRegister] = useState(false);
  const [username, setUsername] = useState("");
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
        await api<{ username: string }>("/auth/register", {
          method: "POST", body: JSON.stringify({ username, password }),
        });
        setNotice("注册成功，请登录。");
        setRegister(false);
        setPassword("");
      } else {
        const result = await api<{ user: User }>("/auth/login", {
          method: "POST", body: JSON.stringify({ username, password }),
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
      <p>个人学习资料保存在这台设备的独立账号目录；登录后会更新云端目录。</p>
      <form onSubmit={submit}>
        <label>用户名<input type="text" autoComplete="username" required minLength={3} maxLength={24} value={username} onChange={event => setUsername(event.target.value)} /></label>
        <label>密码<input type="password" autoComplete={register ? "new-password" : "current-password"} required minLength={8} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} /></label>
        <button className="button primary" type="submit" disabled={busy}>{busy ? "请稍候…" : register ? "注册" : "登录"}</button>
      </form>
      {register && <p>用户名支持 3–24 个字母、数字、下划线或连字符。未绑定邮箱，忘记密码后暂时无法自助找回。</p>}
      {notice && <p role="status">{notice}</p>}
      <button className="link-button" type="button" onClick={() => { setRegister(!register); setNotice(""); }}>{register ? "已有账号？登录" : "没有账号？注册"}</button>
    </section>
  </main>;
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>;
}
