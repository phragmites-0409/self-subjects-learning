import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api/client";
import { message, Notice } from "./shared";
import type { Question } from "./types";
import "./drafts.css";

export default function DraftDeleteButton({
  question,
  onDeleted,
  disabled = false,
}: {
  question: Question;
  onDeleted: () => void | Promise<void>;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const title = question.content.stem?.slice(0, 100) || "图片草稿 · 待整理";

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) setOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open, busy]);

  async function remove() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/learning/questions/${encodeURIComponent(question.id)}/draft`, { method: "DELETE" });
      await onDeleted();
      setOpen(false);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  if (question.status !== "draft" || question.historical) return null;
  return <>
    <button type="button" className="link-button danger draft-delete-button" disabled={disabled || busy}
      aria-label={`删除草稿：${title}`} onClick={() => { setError(""); setOpen(true); }}>删除草稿</button>
    {open && createPortal(<div className="modal-backdrop draft-delete-backdrop">
      <section className="modal panel" role="alertdialog" aria-modal="true" aria-labelledby={`delete-title-${question.id}`}
        aria-describedby={`delete-description-${question.id}`}>
        <h2 id={`delete-title-${question.id}`}>删除未完成草稿</h2>
        <p className="draft-delete-title">{title}</p>
        <p id={`delete-description-${question.id}`}>确认后将删除此草稿、原始照片、缩略图及处理副本，无法恢复。被其他题目、笔记或试卷共用的图片会保留。</p>
        <Notice error={error} />
        <div className="event-actions">
          <button type="button" className="button secondary" autoFocus disabled={busy} onClick={() => setOpen(false)}>取消</button>
          <button type="button" className="button danger" disabled={busy} onClick={() => void remove()}>{busy ? "正在删除…" : "确认删除"}</button>
        </div>
      </section>
    </div>, document.body)}
  </>;
}
