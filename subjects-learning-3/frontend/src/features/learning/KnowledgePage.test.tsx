import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import KnowledgePage from "./KnowledgePage";

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const entry = { id: "entry-1", title: "配方法步骤", body: "先配方，再检查区间", pinned: true, tags: ["方法"], images: [], source: "manual", confirmed: true, revision: 1 };
const base = { id: "n1", subject: "数学", kind: "type", name: "函数模型", parent_id: null, summary: "", child_count: 0, issue_count: 0, active: false, cadence: 7, mastery: { total: 0, mastered: 0, ratio: null, pool: 0 }, data: { note_entries: [entry], pain_entries: [{ ...entry, id: "pain-1", title: "容易漏端点", body: "别忘了检查端点" }], tags: [] } };
const response = (payload: unknown) => ({ ok: true, json: async () => payload });
function setup() {
  let nodes: any[] = [structuredClone(base)];
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/learning/knowledge-tags")) return response({ note: ["方法", "易错点"], question: ["模板题", "难题"], node: ["校外"] });
    if (url.endsWith("/learning/knowledge") && options?.method === "POST") { const payload = JSON.parse(String(options.body)); const next = { ...base, ...payload, id: "new-node", data: { note_entries: [], pain_entries: [], tags: [] } }; nodes.push(next); return response(next); }
    if (url.endsWith("/learning/knowledge")) return response({ items: nodes });
    if (url.includes("/entries/")) { const payload = JSON.parse(String(options?.body)); const saved = { ...entry, ...payload, id: "new-entry" }; nodes = nodes.map(n => n.id === "n1" ? { ...n, data: { ...n.data, note_entries: [...n.data.note_entries, saved] } } : n); return response(saved); }
    if (url.includes("/learning/knowledge-images")) return response({ id: "image-1", name: "original.png", type: "image/png", size: 3, sha256: "a".repeat(64) });
    if (url.includes("/learning/questions")) { const tag = new URL(url, "http://local").searchParams.get("tag"); return response({ items: tag === "难题" ? [] : [{ id: "q1", content: { stem: "求最值" }, tags: ["模板题"], minutes: 8, ever_wrong: false, subject: "数学", question_type: "配方法", status: "approved" }], total: tag === "难题" ? 0 : 1, base_total: 1, tag_counts: [{ tag: "模板题", count: 1 }, { tag: "难题", count: 0 }], untagged_total: 0 }); }
    return response({});
  });
  vi.stubGlobal("fetch", fetch);
  render(<MemoryRouter initialEntries={["/knowledge?subject=数学&branch=type"]}><KnowledgePage /></MemoryRouter>);
  return fetch;
}

describe("persistent knowledge workspace", () => {
  it("creates from a node's plus with title only and sends its implicit parent", async () => {
    const fetch = setup();
    fireEvent.click(await screen.findByRole("button", { name: "在函数模型下新增分支" }));
    const dialog = screen.getByRole("dialog", { name: "新增节点" });
    expect(within(dialog).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("位置")).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("标题"), { target: { value: "参数情形" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建节点" }));
    await waitFor(() => expect(fetch.mock.calls.some(([url, options]) => url.endsWith("/learning/knowledge") && options?.method === "POST" && JSON.parse(String(options.body)).parent_id === "n1")).toBe(true));
  });
  it("cancelling a child creation does not leak its parent into root creation", async () => {
    const fetch = setup();
    fireEvent.click(await screen.findByRole("button", { name: "在函数模型下新增分支" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "＋ 根分支" }));
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "新根" } });
    fireEvent.click(screen.getByRole("button", { name: "创建节点" }));
    await waitFor(() => expect(fetch.mock.calls.some(([url, options]) => url.endsWith("/learning/knowledge") && options?.method === "POST" && JSON.parse(String(options.body)).parent_id === null)).toBe(true));
  });
  it("switches independent pages and entry detail without rendering all bodies", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "阅读函数模型" }));
    expect(screen.queryByRole("tab", { name: /总览|过手进入/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "配方法步骤" }));
    expect(screen.getByText("先配方，再检查区间")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "02 痛点" }));
    expect(screen.queryByText("先配方，再检查区间")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "容易漏端点" })).toBeInTheDocument();
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });
  it("selects tags and a custom option, uploads an image without OCR, and saves an image-only note", async () => {
    const fetch = setup();
    fireEvent.click(await screen.findByRole("button", { name: "阅读函数模型" }));
    fireEvent.click(screen.getByRole("button", { name: "＋ 新增笔记" }));
    const dialog = screen.getByRole("dialog", { name: "新增笔记" });
    fireEvent.change(within(dialog).getByLabelText("标题"), { target: { value: "图片记录" } });
    fireEvent.click(within(dialog).getByLabelText("方法"));
    fireEvent.click(within(dialog).getByRole("button", { name: "＋ 新建标签" }));
    fireEvent.change(within(dialog).getByLabelText("新标签名称"), { target: { value: "原图资料" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "添加并选中" }));
    fireEvent.change(within(dialog).getByLabelText("上传笔记原图"), { target: { files: [new File(["abc"], "original.png", { type: "image/png" })] } });
    await waitFor(() => expect(within(dialog).getByText("1 张原图")).toBeInTheDocument());
    fireEvent.click(within(dialog).getByRole("button", { name: "保存条目" }));
    await waitFor(() => expect(fetch.mock.calls.some(([url, options]) => url.includes("/entries/note_entries") && options?.method === "POST" && JSON.parse(String(options.body)).images[0].id === "image-1")).toBe(true));
    const savedCall = fetch.mock.calls.find(([url]) => url.includes("/entries/note_entries"))!;
    expect(JSON.parse(String(savedCall[1]?.body))).toMatchObject({ body: "", tags: ["方法", "原图资料"] });
    expect(fetch.mock.calls.some(([url]) => /recognize|intake|analysis/.test(url))).toBe(false);
  });
  it("uses server facets and an exact tag query for the question pool", async () => {
    const fetch = setup();
    fireEvent.click(await screen.findByRole("button", { name: "阅读函数模型" }));
    fireEvent.click(screen.getByRole("tab", { name: "03 题目池" }));
    fireEvent.click(await screen.findByRole("button", { name: "难题 0" }));
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => new URL(url, "http://local").searchParams.get("tag") === "难题")).toBe(true));
    expect(await screen.findByText("没有符合当前标签与状态的题目。")).toBeInTheDocument();
  });
});
