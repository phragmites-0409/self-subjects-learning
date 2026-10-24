import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const emptyApiResponse = () => ({
  ok: true,
  json: async () => ({ items: [] }),
});

describe("App navigation", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.includes("/learning/dashboard")
          ? {
              ok: true,
              json: async () => ({
                day: "2026-10-05",
                day_label: "10月5日（星期一）",
                week_end_label: "10月11日（星期日）",
                preferences: { daily_minutes: 75 },
                minutes: 0,
                maximum: 90,
                events: [],
                upcoming: [],
                uploads: [],
                pending_errors: 0,
                pending_minutes: 0,
                reports: [],
                plan_notes: [],
                waiting_topics: [],
              }),
            }
          : emptyApiResponse(),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("exposes core workflow sections without a separate error-book object", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    const links = Array.from(
      screen.getByRole("navigation", { name: "主导航" }).querySelectorAll("a"),
    ).map((link) => ({
      label: link.textContent?.replace(/\\s+/g, "").trim(),
      path: link.getAttribute("href"),
    }));

    expect(links).toEqual([
      { label: "今日安排", path: "/" },
      { label: "题目库", path: "/questions" },
      { label: "知识库", path: "/knowledge" },
      { label: "英语单词", path: "/vocabulary" },
      { label: "设置", path: "/settings" },
    ]);
    expect(screen.queryByText("每日错题")).not.toBeInTheDocument();
    expect(screen.queryByText("考情统计")).not.toBeInTheDocument();
    expect(screen.queryByText("课外内容")).not.toBeInTheDocument();
  });
});
