import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import RoundPage from "./RoundPage";
import PlanPage from "./PlanPage";
import CapturePage from "./CapturePage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const event = {
  id: "event-1",
  kind: "error",
  subject: "数学",
  title: "数学错题重做",
  day: "2026-10-05",
  day_label: "10月5日（星期一）",
  week: "2026-10-05",
  deadline_label: "10月11日（星期日）",
  status: "open",
  minutes: 8,
  data: { round_id: "round-1", slice: 1 },
};
const round = {
  id: "round-1",
  kind: "error",
  subject: "数学",
  target_label: "10月5日（星期一）",
  status: "open",
  data: {},
  events: [event],
  items: [
    {
      id: "item-1",
      question_id: "q-1",
      event_id: "event-1",
      position: 1,
      status: "pending",
      verdict: "pending",
      data: {
        stem: "求x",
        answer: "1",
        answer_confirmed: true,
        student_answer: "1",
      },
    },
  ],
};
const response = (data: unknown) => ({ ok: true, json: async () => data });

describe("confirmed core workflows", () => {
  it("keeps correct answer and manual mastery confirmation as separate user decisions", async () => {
    const fetch = vi.fn(async (_url: string, _options?: RequestInit) =>
      response(round),
    );
    vi.stubGlobal("fetch", fetch);
    render(
      <MemoryRouter initialEntries={["/rounds/round-1"]}>
        <Routes>
          <Route path="/rounds/:id" element={<RoundPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const select = await screen.findByLabelText("最终判定（可人工改判）");
    fireEvent.change(select, { target: { value: "correct" } });
    expect(
      screen.getByRole("button", { name: "我确认已过手" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "仍未过手 · 次日重做" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "我确认已过手" }));
    await waitFor(() =>
      expect(
        fetch.mock.calls.some((call) =>
          String(call[1]?.body).includes('"mastered":true'),
        ),
      ).toBe(true),
    );
  });
  it("wrong answer requires explanation before learned click and sends explicit confirmation", async () => {
    const fetch = vi.fn(async (_url: string, _options?: RequestInit) =>
      response(round),
    );
    vi.stubGlobal("fetch", fetch);
    render(
      <MemoryRouter initialEntries={["/rounds/round-1"]}>
        <Routes>
          <Route path="/rounds/:id" element={<RoundPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByLabelText("最终判定（可人工改判）"), {
      target: { value: "wrong" },
    });
    expect(
      screen.getByRole("button", { name: "已学习解析 · 次日重做" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("解析或差异说明"), {
      target: { value: "核对原题答案" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "已学习解析 · 次日重做" }),
    );
    await waitFor(() =>
      expect(
        fetch.mock.calls.some((call) =>
          String(call[1]?.body).includes('"learned":true'),
        ),
      ).toBe(true),
    );
  });
  it("type round all-correct still exposes manual pass or fail", async () => {
    const data = {
      ...round,
      kind: "type",
      events: [{ ...event, kind: "type" }],
      items: [{ ...round.items[0], status: "resolved", verdict: "correct" }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(data)),
    );
    render(
      <MemoryRouter initialEntries={["/rounds/round-1"]}>
        <Routes>
          <Route path="/rounds/:id" element={<RoundPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("button", { name: "我确认本轮通过并销账" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "全部答对，但本轮未通过" }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "我确认已过手" }),
    ).not.toBeInTheDocument();
  });
  it("daily upload no-error action is explicit and independent of mastery", async () => {
    const uploads = ["数学", "物理", "化学", "生物"].map((s, i) => ({
      ...event,
      id: `upload-${i}`,
      kind: "upload",
      subject: s,
      data: {},
      minutes: 0,
    }));
    const dashboard = {
      day: "2026-10-05",
      day_label: "10月5日（星期一）",
      week_end_label: "10月11日（星期日）",
      preferences: { daily_minutes: 75 },
      minutes: 0,
      maximum: 90,
      events: [],
      upcoming: [],
      uploads,
      pending_errors: 1,
      pending_minutes: 8,
      reports: [],
      plan_notes: [],
      waiting_topics: [],
    };
    const fetch = vi.fn(async (_url: string, _options?: RequestInit) =>
      response(_url.includes("/corrections") ? { items: [], counts: {}, total: 0 } : _url.includes("filter=draft") ? { items: [], total: 0 } : dashboard),
    );
    vi.stubGlobal("fetch", fetch);
    render(
      <MemoryRouter>
        <PlanPage />
      </MemoryRouter>,
    );
    const buttons = await screen.findAllByRole("button", {
      name: "无错题",
    });
    expect(buttons).toHaveLength(4);
    fireEvent.click(buttons[0]);
    await waitFor(() =>
      expect(
        fetch.mock.calls.some((call) =>
          String(call[1]?.body).includes('"action":"no_errors"'),
        ),
      ).toBe(true),
    );
  });
  it("text intake saves a draft without forcing AI analysis or final archive", async () => {
    const fetch = vi.fn(async (_url: string, _options?: RequestInit) =>
      response(_url.includes("filter=draft") ? {items: []} : { id: "q-1" }),
    );
    vi.stubGlobal("fetch", fetch);
    render(
      <MemoryRouter>
        <CapturePage onCreated={() => {}} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("题目文字或识别提示（可不填）"), {
      target: { value: "x+1=2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿并继续" }));
    await waitFor(() => expect(fetch.mock.calls.some(call => String(call[0]).endsWith("/learning/intake"))).toBe(true));
    expect(
      fetch.mock.calls.every(
        (call) =>
          !String(call[0]).includes("/analysis") &&
          !String(call[0]).includes("/archive") &&
          !String(call[0]).includes("/parse"),
      ),
    ).toBe(true);
  });
});
