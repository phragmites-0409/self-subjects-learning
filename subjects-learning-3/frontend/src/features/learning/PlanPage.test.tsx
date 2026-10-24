import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlanPage from "./PlanPage";
import type { Question } from "./types";

const response = (body: unknown) => ({ ok: true, json: async () => body });
const makeEvent = (id: string, kind: string, title: string, day = "2026-10-24") => ({ id, kind, title, day, day_label: "10月24日（星期六）", subject: "数学", status: "open", minutes: 0, data: {} });
function setup(initialDrafts: Question[] = []) {
  let waiting = true;
  let drafts = [...initialDrafts];
  const dashboard = {
    day: "2026-10-24", day_label: "10月24日（星期六）", preferences: { daily_minutes: 75, redo_days: 7 }, minutes: 8,
    uploads: ["数学", "物理", "化学", "生物"].map(s => ({ ...makeEvent(`upload-${s}`, "upload", `${s}录入`), subject: s })),
    events: [makeEvent("general", "general", "整理课堂笔记"), { ...makeEvent("redo", "error", "数学错题过关"), data: { round_id: "round" } }, makeEvent("words", "vocabulary", "英语单词过关"), makeEvent("future", "general", "明天的事项", "2026-10-25")],
    reports: [], waiting_topics: [], plan_notes: [], upcoming: [],
  };
  const calls: { url: string; body: any; method?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: unknown, options: RequestInit = {}) => {
    const url = String(input), body = JSON.parse(String(options.body || "{}")); calls.push({ url, body, method: options.method });
    if (options.method === "DELETE" && url.endsWith("/draft")) {
      drafts = drafts.filter(q => !url.endsWith(`/questions/${q.id}/draft`));
      return response({ deleted: true });
    }
    if (url.endsWith("/questions/q1/correct")) { waiting = false; return response({}); }
    if (url.includes("/corrections")) return response({ counts: { 数学: waiting ? 1 : 0, 物理: 0, 化学: 0, 生物: 0 }, total: waiting ? 1 : 0, items: waiting && url.includes(encodeURIComponent("数学")) ? [{ question_id: "q1", subject: "数学", title: "解方程 x+1=2", recorded_label: "10月20日（星期二）", occurrence_count: 1 }] : [] });
    if (url.includes("filter=draft")) {
      const params = new URL(url, 'http://local').searchParams;
      const offset = Number(params.get('offset') || 0), limit = Number(params.get('limit') || 100);
      return response({ items: drafts.slice(offset, offset + limit), total: drafts.length });
    }
    if (url.endsWith("/learning/events") && options.method === "POST") { dashboard.events.push(makeEvent("new", "general", body.title)); return response({}); }
    if (url.includes("/events/") && url.endsWith("/action")) { const item = dashboard.events.find(e => url.includes(`/events/${e.id}/`)); if (item) item.status = "completed"; return response({}); }
    return response(dashboard);
  }));
  render(<MemoryRouter><PlanPage /></MemoryRouter>);
  return calls;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("today dashboard", () => {
  it("deletes the last draft on a later page, refreshes the count and returns to the previous page", async () => {
    const drafts: Question[] = Array.from({ length: 31 }, (_, index) => ({
      id: `draft-${index}`, subject: '数学', question_type: '待归类', status: 'draft', tags: [],
      content: { stem: `未整理题目${index + 1}` }, version_id: 'v1', source_asset_id: null,
      source_sha256: null, topic_id: null, minutes: 8, answer: '', answer_confirmed: false,
      ever_wrong: false, mastered: false, data: {},
    }));
    const calls = setup(drafts);
    fireEvent.click(await screen.findByRole('button', { name: /继续录入草稿.*31 道/ }));
    await screen.findByText('未整理题目1');
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await screen.findByText('未整理题目31');
    fireEvent.click(screen.getByRole('button', { name: '删除草稿：未整理题目31' }));
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await screen.findByText('未整理题目1');
    expect(screen.queryByText('未整理题目31')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /继续录入草稿.*30 道/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled();
    expect(calls.filter(c => c.method === 'DELETE')).toHaveLength(1);
  });

  it("shows exactly four sections, dates, separated lists and direct correction confirmation", async () => {
    const calls = setup();
    await screen.findByRole("heading", { name: "今日安排" });
    expect(await screen.findByText("2026-10-24 · 星期六")).toBeInTheDocument();
    expect(screen.getAllByRole("region")).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: "录入完成" })).toHaveLength(4);
    expect(screen.getByRole("button", { name: "拍照录入题目" })).toBeInTheDocument();
    const todos = screen.getByRole("region", { name: /今日事项/ });
    expect(within(todos).getByText("整理课堂笔记")).toBeInTheDocument();
    expect(within(todos).queryByText("数学错题过关")).not.toBeInTheDocument();
    expect(screen.queryByText("明天的事项")).not.toBeInTheDocument();
    const practice = screen.getByRole("region", { name: /今日需过关/ });
    expect(within(practice).getByText("数学错题过关")).toBeInTheDocument();
    expect(within(practice).getByText("英语单词过关")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "改错：解方程 x+1=2" }));
    await waitFor(() => expect(screen.queryByText("解方程 x+1=2")).not.toBeInTheDocument());
    expect(calls.filter(c => c.url.endsWith("/questions/q1/correct"))).toHaveLength(1);
  });

  it("creates and completes a personal matter from the same compact panel", async () => {
    const calls = setup();
    fireEvent.click(await screen.findByRole("button", { name: "新建事项" }));
    fireEvent.change(screen.getByRole("textbox", { name: "事项名称" }), { target: { value: "复习实验记录" } });
    fireEvent.click(screen.getByRole("button", { name: "保存事项" }));
    await screen.findByText("复习实验记录");
    const row = screen.getByText("复习实验记录").closest(".today-row") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "完成" }));
    await waitFor(() => expect(within(screen.getByText("复习实验记录").closest(".today-row") as HTMLElement).getByText("已完成")).toBeInTheDocument());
    expect(calls.some(c => c.url.endsWith("/events/new/action") && c.body.action === "complete")).toBe(true);
  });
});
