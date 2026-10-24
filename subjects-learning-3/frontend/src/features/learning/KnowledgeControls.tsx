import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useData } from "./shared";

export type KnowledgeImage = { id: string; name: string; type: string; size: number; sha256: string };
export type KnowledgeEntry = { id: string; title: string; body: string; tags: string[]; images: KnowledgeImage[]; source: string; confirmed: boolean; pinned: boolean; revision: number };
export const MATERIALS = ["主题分类", "主题词汇", "常用短语", "句型表达", "开头", "过渡", "结尾", "高级替换", "主题观点", "范文片段"];
export const unique = (values: string[]) => [...new Set(values.map(v => v.trim()).filter(Boolean))];
const defaults = { note: ["方法", "模型", "公式", "学习材料", "易错点"], question: ["重点题", "模板题", "难题"], node: ["校外", "重点"] };

export function TagSelector({ kind, value, onChange, options = [], onOptions }: { kind: "note" | "question" | "node"; value: string[]; onChange: (v: string[]) => void; options?: string[]; onOptions?: (v: string[]) => void }) {
  const { data, error } = useData<Record<string, string[]>>("/learning/knowledge-tags");
  const [adding, setAdding] = useState(false), [name, setName] = useState(""), [custom, setCustom] = useState<string[]>([]), [notice, setNotice] = useState("");
  const all = unique([...defaults[kind], ...(data?.[kind] || []), ...options, ...value, ...custom]);
  function add() {
    const text = name.trim();
    if (!text || text.length > 100 || /[,，]/.test(text)) { setNotice("请填写一个标签名称，最多100字，不使用逗号。"); return; }
    const next = unique([...custom, text]); setCustom(next); onOptions?.(unique([...options, ...next])); onChange(unique([...value, text])); setName(""); setAdding(false); setNotice("标签已选中，随本次编辑保存。");
  }
  return <fieldset className="kb-tag-selector"><legend>{{ note: "笔记标签", question: "题目标签", node: "题型标签" }[kind]} <small>可多选</small></legend><div className="kb-tag-options">{all.map(t => <label key={t}><input type="checkbox" checked={value.includes(t)} onChange={e => onChange(e.target.checked ? [...value, t] : value.filter(v => v !== t))} /><span>{t}</span></label>)}</div><button className="kb-text-button" type="button" onClick={() => setAdding(!adding)}>＋ 新建标签</button>{adding && <div className="kb-new-tag"><input className="input" aria-label="新标签名称" value={name} maxLength={100} onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); add(); } }} autoFocus /><button type="button" className="button secondary" onClick={add}>添加并选中</button></div>}{(notice || error) && <small role="status">{notice || "标签选项加载失败，可重开编辑重试；已有标签仍可选择。"}</small>}</fieldset>;
}

export function KnowledgeModal({ title, children, onClose, wide = false, busy = false, className = "" }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean; busy?: boolean; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null), heading = useId();
  useEffect(() => { const el = ref.current!; if (!el.open) el.showModal(); return () => el.close(); }, []);
  return <dialog ref={ref} className={`kb-dialog ${wide ? "kb-dialog-wide" : ""} ${className}`} aria-labelledby={heading} onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}><header className="kb-modal-head"><h2 id={heading}>{title}</h2><button type="button" className="kb-close" aria-label="关闭弹窗" disabled={busy} onClick={onClose}>×</button></header>{children}</dialog>;
}
