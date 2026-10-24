import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  BookOpen,
  CalendarDays,
  FileStack,
  ImagePlus,
  Settings,
  Sparkles,
} from "lucide-react";
import { api } from "../api/client";
import type { Paper, Question } from "../api/types";
import PlanPage from "../features/learning/PlanPage";
import CapturePage from "../features/learning/CapturePage";
import KnowledgePage from "../features/learning/KnowledgePage";
import QuestionPage from "../features/learning/QuestionPage";
import RoundPage from "../features/learning/RoundPage";
import SettingsPage from "../features/learning/SettingsPage";
import PapersPage from "../features/papers/PapersPage";
import AnswerBankPage from "../features/learning/AnswerBankPage";

const NAV = [
  { to: "/", label: "每日安排", icon: CalendarDays },
  { to: "/capture", label: "拍题录入", icon: ImagePlus },
  { to: "/knowledge", label: "知识库", icon: BookOpen },
  { to: "/papers", label: "自主组卷", icon: FileStack },
  { to: "/settings", label: "设置", icon: Settings },
];
export default function App() {
  const [questions, setQuestions] = useState<Question[]>([]),
    [papers, setPapers] = useState<Paper[]>([]),
    [error, setError] = useState(""),
    [connected, setConnected] = useState(false);
  async function refresh() {
    try {
      const [q, p] = await Promise.all([
        api<{ items: Question[] }>("/questions?limit=100"),
        api<{ items: Paper[] }>("/papers"),
      ]);
      setQuestions(q.items);
      setPapers(p.items);
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
          <Route path="/" element={<PlanPage />} />
          <Route
            path="/capture"
            element={<CapturePage onCreated={refresh} />}
          />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/answer-bank" element={<AnswerBankPage />} />
          <Route
            path="/errors"
            element={<Navigate to="/knowledge" replace />}
          />
          <Route
            path="/papers"
            element={
              <PapersPage
                questions={questions}
                papers={papers}
                onRefresh={refresh}
              />
            }
          />
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
