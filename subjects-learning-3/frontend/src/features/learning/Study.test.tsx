import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QuestionBankPage from "./QuestionBankPage";
import VocabularyPage, { VocabularySettings } from "./VocabularyPage";
import { NotificationSettings } from "./ReviewSettings";
const response = (body: unknown) => ({ ok: true, json: async () => body });

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("confirmed study workflows", () => {
  it("reports Windows acceptance only after a native receipt and refreshes delivery history", async () => {
    let delivered = false;
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      if (String(input).endsWith("/notifications/test")) {
        delivered = true;
        return response({ sent: true, receipt: { accepted: true, receipt: "notification_center" } });
      }
      return response({ windows: true, preferences: { desktop_enabled: true, time: "18:00" }, deliveries: delivered ? [{ key: "test", title: "题研 · 测试通知", status: "sent", native: { receipt: "notification_center" } }] : [] });
    }));
    render(<NotificationSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "发送测试通知" }));
    await screen.findByText("Windows已确认接收测试通知，可点击通知打开今日安排。");
    expect(await screen.findByText(/题研 · 测试通知 · Windows已确认接收/)).toBeInTheDocument();
  });

  it("keeps missing native receipts visible as an error", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => response(String(input).endsWith("/notifications/test") ? { sent: true } : { windows: true, preferences: { desktop_enabled: true, time: "18:00" }, deliveries: [] })));
    render(<NotificationSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "发送测试通知" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("尚未取得Windows投递回执");
    expect(screen.queryByText("Windows已确认接收测试通知，可点击通知打开今日安排。")).not.toBeInTheDocument();
  });

  it("keeps cross-page selections while applying multiple leaf filters", async () => {
    const requests: string[] = [];
    const question = (id: string) => ({ id, subject: "数学", question_type: "方程", status: "approved", tags: ["重点"], version_id: `v-${id}`, content: { stem: `题面${id}` }, minutes: 8 });
    vi.stubGlobal("fetch", vi.fn(async (input: unknown, options: RequestInit = {}) => {
      const url = String(input); requests.push(url);
      if (url.includes("/learning/knowledge")) return response({ items: [{ id: "leaf-a", name: "代入", kind: "type", child_count: 0 }, { id: "leaf-b", name: "消元", kind: "type", child_count: 0 }] });
      if (url.includes("/learning/questions")) return response({ items: [question(url.includes("offset=30") ? "q2" : "q1")], total: 31, tag_counts: [{ tag: "重点", count: 31 }] });
      if (url.endsWith("/papers") && options.method === "POST") return response({ id: "paper", items: [] });
      return response({ items: [] });
    }));
    render(<MemoryRouter><QuestionBankPage /></MemoryRouter>);
    await screen.findByText("题面q1");
    fireEvent.click(screen.getByRole("button", { name: "加入选题篮" }));
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("题面q2");
    fireEvent.click(screen.getByRole("button", { name: "加入选题篮" }));
    expect(screen.getByRole("heading", { name: "选题篮 · 2题" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "代入" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "消元" }));
    await waitFor(() => expect(requests.some(url => url.includes("topic_ids=leaf-a") && url.includes("topic_ids=leaf-b"))).toBe(true));
    expect(screen.getByRole("heading", { name: "选题篮 · 2题" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存试卷" }));
    await screen.findByText(/试卷已保存/);
    const calls = vi.mocked(fetch).mock.calls;
    const body = JSON.parse(String(calls.find(([url, options]) => String(url).endsWith("/papers") && options?.method === "POST")?.[1]?.body));
    expect(body.items.map((i: { question_id: string }) => i.question_id)).toEqual(["q1", "q2"]);
  });

  it("shows a failed word answer for explicit adjudication and finishes after acceptance", async () => {
    const settings = { mode: "any", intervals: [1, 3, 7, 15, 30] };
    const item = { id: "item", word: "abandon", status: "pending", targets: [{ pos: "任一义项" }], senses: [] };
    const session = { id: "session", day: "2026-10-24", status: "open", preferences: settings, total: 1, completed: 0, items: [item] };
    let current: any = session;
    vi.stubGlobal("fetch", vi.fn(async (input: unknown, options: RequestInit = {}) => {
      const url = String(input);
      if (url.endsWith("/vocabulary/sessions")) return response({ items: [current] });
      if (url.endsWith("/vocabulary/sessions/session")) return response(current);
      if (url.endsWith("/answer")) { current = { ...session, items: [{ ...item, status: "review", senses: [{ id: "sense", pos: "v.", meaning: "放弃", aliases: [] }], last: { answers: ["放下"], matched: {} } }] }; return response(current); }
      if (url.endsWith("/decision")) { expect(JSON.parse(String(options.body)).corrections).toEqual([{ answer_index: 0, sense_id: "sense" }]); current = { ...session, status: "completed", completed: 1, items: [{ ...item, status: "passed" }] }; return response(current); }
      return response({});
    }));
    render(<MemoryRouter initialEntries={["/vocabulary?tab=practice"]}><VocabularyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "abandon" })).toBeInTheDocument();
    expect(screen.queryByText("放弃")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "中文义项1" }), { target: { value: "放下" } });
    fireEvent.click(screen.getByRole("button", { name: "提交答案" }));
    await screen.findByText("标准义项");
    fireEvent.change(screen.getByRole("combobox", { name: "认可回答1的义项" }), { target: { value: "sense" } });
    fireEvent.click(screen.getByRole("button", { name: "我的答案也正确，保存认可答案" }));
    expect(await screen.findByRole("heading", { name: "本轮已完成 · 1/1词" })).toBeInTheDocument();
  });

  it("saves configurable word quota and review intervals", async () => {
    const settings = { enabled: true, daily_count: 20, time: "18:00", mode: "any", scope: "all", order: "oldest", intervals: [1, 3, 7, 15, 30] };
    let saved: any;
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, options: RequestInit = {}) => { if (options.method === "PATCH") saved = JSON.parse(String(options.body)); return response(saved || settings); }));
    render(<VocabularySettings />);
    fireEvent.change(await screen.findByRole("spinbutton", { name: "每日总词数（新词＋复习）" }), { target: { value: "35" } });
    fireEvent.change(screen.getByRole("textbox", { name: "逐阶段复习间隔（天，逗号分隔）" }), { target: { value: "2,5,10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存单词规则" }));
    await screen.findByText(/已保存，影响后续新建任务/);
    expect(saved.daily_count).toBe(35); expect(saved.intervals).toEqual([2, 5, 10]);
  });
});
