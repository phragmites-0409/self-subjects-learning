import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  BookOpen,
  CalendarDays,
  FileStack,
  Settings,
  Sparkles,
} from "lucide-react";
import { api } from "../api/client";

import PlanPage from "../features/learning/PlanPage";
import CapturePage from "../features/learning/CapturePage";
import KnowledgePage from "../features/learning/KnowledgePage";
import QuestionPage from "../features/learning/QuestionPage";
import RoundPage from "../features/learning/RoundPage";
import SettingsPage from "../features/learning/SettingsPage";
import QuestionBankPage from "../features/learning/QuestionBankPage";
import VocabularyPage from "../features/learning/VocabularyPage";
import AnswerBankPage from "../features/learning/AnswerBankPage";

const NAV = [
  { to: "/", label: "今日安排", icon: CalendarDays },
  { to: "/questions", label: "题目库", icon: FileStack },
  { to: "/knowledge", label: "知识库", icon: BookOpen },
  { to: "/vocabulary", label: "英语单词", icon: BookOpen },
  { to: "/settings", label: "设置", icon: Settings },
];
export default function App() {
  const [error, setError] = useState(""),
    [connected, setConnected] = useState(false);
  async function refresh() {
    try {
      await api("/health");
      setConnected(true);
      setError("");
    } catch (e) {
      setConnected(false);
      setError(e instanceof Error ? e.message : "无法连接本地服务");
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Sparkles size={18} />
          </div>
          <div>
            <strong>题研</strong>
            <span>本地学习台 · 单人</span>
          </div>
        </div>
        <nav aria-label="主导航">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}>
              <n.icon size={17} />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className={`local-status ${connected ? "" : "disconnected"}`}>
            <i />
            {connected ? "本地服务已连接" : "正在连接本地服务"}
          </div>
        </div>
      </aside>
      <main className="main-content">
        {error && (
          <div className="connection-warning">
            {error}。请启动本地服务。<button onClick={refresh}>重试连接</button>
          </div>
        )}
        <Routes>
          <Route path="/" element={<PlanPage onCreated={refresh} />} />
          <Route
            path="/capture"
            element={<CapturePage onCreated={refresh} />}
          />
          <Route path="/knowledge" element={<KnowledgePage onCreated={refresh} />} />
          <Route path="/answer-bank" element={<AnswerBankPage />} />
          <Route
            path="/errors"
            element={<Navigate to="/questions?filter=unmastered" replace />}
          />
          <Route path="/papers" element={<Navigate to="/questions?tab=papers" replace />} />
          <Route path="/questions" element={<QuestionBankPage />} />
          <Route path="/vocabulary" element={<VocabularyPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            path="/questions/:id"
            element={<QuestionPage onRefresh={refresh} />}
          />
          <Route path="/rounds/:id" element={<RoundPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
