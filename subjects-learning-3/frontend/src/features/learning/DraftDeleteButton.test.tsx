import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DraftDeleteButton from "./DraftDeleteButton";
import type { Question } from "./types";

const draft: Question = {
  id: "draft-1", subject: "数学", question_type: "待归类", status: "draft", tags: [],
  content: { stem: "没有整理完成的题目" }, version_id: "v1", source_asset_id: null,
  source_sha256: null, topic_id: null, minutes: 8, answer: "", answer_confirmed: false,
  ever_wrong: false, mastered: false, data: { recognition: "running" },
};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps the draft until confirmation, including when recognition is running", async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ deleted: true }) }));
  vi.stubGlobal("fetch", fetch);
  const onDeleted = vi.fn();
  render(<DraftDeleteButton question={draft} onDeleted={onDeleted} />);

  fireEvent.click(screen.getByRole("button", { name: /删除草稿/ }));
  expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  expect(screen.getByRole("alertdialog")).toHaveTextContent("原始照片、缩略图及处理副本");
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: /删除草稿/ }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenCalledWith('/api/v1/learning/questions/draft-1/draft', expect.objectContaining({ method: 'DELETE' }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("shows a server rejection and keeps the draft visible", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => ({ error: { message: "此题已正式入库" } }) })));
  const onDeleted = vi.fn();
  render(<DraftDeleteButton question={draft} onDeleted={onDeleted} />);
  fireEvent.click(screen.getByRole("button", { name: /删除草稿/ }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("此题已正式入库");
  expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  expect(onDeleted).not.toHaveBeenCalled();
});

it("does not offer draft deletion for an archived question or historical version", () => {
  const { rerender } = render(<DraftDeleteButton question={{ ...draft, status: "approved" }} onDeleted={vi.fn()} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  rerender(<DraftDeleteButton question={{ ...draft, historical: true }} onDeleted={vi.fn()} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
