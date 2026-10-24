import { useRef, useState } from "react";
import { api, apiUrl } from "../../api/client";
import { Node } from "./types";
import { MathText, Notice, message, patch, post } from "./shared";
import { KnowledgeEntry, KnowledgeImage, KnowledgeModal, TagSelector } from "./KnowledgeControls";

export const imageUrl = (image: KnowledgeImage, download = false) => apiUrl(`/learning/knowledge-images/${image.id}?name=${encodeURIComponent(image.name)}&download=${download}`);
const fileSize = (size: number) => size > 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(2)} MB` : `${(size / 1024).toFixed(1)} KB`;

export function ImageViewer({ image, onClose }: { image: KnowledgeImage; onClose: () => void }) {
  const [actual, setActual] = useState(false), [error, setError] = useState(false);
  return <KnowledgeModal title={image.name} wide onClose={onClose} className="kb-image-dialog"><div className="kb-image-actions"><small>{fileSize(image.size)} · 保留原始文件</small><button className="button secondary" onClick={() => setActual(!actual)}>{actual ? "适应窗口" : "原始尺寸"}</button><a className="button primary" download={image.name} href={imageUrl(image, true)}>下载原图</a></div><div className={`kb-original-stage ${actual ? "kb-actual" : ""}`}>{error ? <p>此格式暂不支持预览，请下载原图查看。</p> : <img src={imageUrl(image)} alt={image.name} onError={() => setError(true)} />}</div></KnowledgeModal>;
}

export function EntryEditor({ node, kind, entry, onClose, onSaved }: { node: Node; kind: "note_entries" | "pain_entries"; entry?: KnowledgeEntry; onClose: () => void; onSaved: (entry: KnowledgeEntry) => void }) {
  const pain = kind === "pain_entries", label = pain ? "痛点" : "笔记";
  const [title, setTitle] = useState(entry?.title || ""), [body, setBody] = useState(entry?.body || ""), [tags, setTags] = useState(entry?.tags || []), [tagOptions, setTagOptions] = useState<string[]>([]), [images, setImages] = useState<KnowledgeImage[]>(entry?.images || []), [pinned, setPinned] = useState(entry?.pinned || false), [source, setSource] = useState(entry?.source || "manual"), [confirmed, setConfirmed] = useState(entry?.confirmed || false), [error, setError] = useState(""), [saving, setSaving] = useState(false), [uploading, setUploading] = useState(false), [image, setImage] = useState<KnowledgeImage | null>(null);
  const alive = useRef(true);
  async function upload(files: FileList | null) {
    if (!files?.length) return; setUploading(true); setError("");
    try {
      const added: KnowledgeImage[] = [];
      for (const file of Array.from(files)) { const data = new FormData(); data.append("file", file); const result = await api<KnowledgeImage>("/learning/knowledge-images", { method: "POST", body: data }); added.push(result); }
      if (alive.current) setImages(old => [...old, ...added.filter(i => !old.some(o => o.id === i.id))]);
    } catch (e) { if (alive.current) setError(message(e)); }
    finally { if (alive.current) setUploading(false); }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); if (uploading || saving) return; setSaving(true); setError("");
    try {
      const payload = { title, body, tags, tag_options: tagOptions, images, pinned, source, confirmed, revision: entry?.revision };
      const base = `/learning/knowledge/${node.id}/entries/${kind}`;
      const result = entry ? await patch<KnowledgeEntry>(`${base}/${entry.id}`, payload) : await post<KnowledgeEntry>(base, payload);
      onSaved(result);
    } catch (e) { setError(message(e)); } finally { setSaving(false); }
  }
  return <KnowledgeModal title={`${entry ? "编辑" : "新增"}${label}`} wide busy={saving || uploading} onClose={() => { alive.current = false; onClose(); }}><form onSubmit={save} className="kb-entry-form"><div className="kb-modal-scroll"><label>标题<input className="input" required maxLength={100} value={title} onChange={e => setTitle(e.target.value)} autoFocus /></label><label>正文<textarea className="textarea" rows={6} required={pain} value={body} onChange={e => setBody(e.target.value)} placeholder={pain ? "记录一个具体问题…" : "记录方法、公式或材料，也可只添加图片…"} /></label>{!pain && <><TagSelector kind="note" value={tags} onChange={setTags} options={tagOptions} onOptions={setTagOptions} /><section className="kb-upload-zone"><div className="kb-section-head"><strong>笔记图片</strong><label className="button secondary kb-upload-button">＋ 添加图片<input aria-label="上传笔记原图" type="file" accept="image/*" multiple disabled={uploading || saving} onChange={e => { upload(e.target.files); e.target.value = ""; }} /></label></div><p className="muted">保留原图，不识别、不压缩。每张最多10 MB，可多张上传。</p><div className="kb-image-grid">{images.map(i => <figure key={i.id}><button type="button" onClick={() => setImage(i)} aria-label={`查看原图：${i.name}`}><img src={imageUrl(i)} alt={i.name} /></button><figcaption>{i.name}<small>{fileSize(i.size)} · 原图</small></figcaption><button type="button" className="kb-remove-image" aria-label={`移除图片：${i.name}`} onClick={() => setImages(images.filter(v => v.id !== i.id))}>移除</button></figure>)}</div><small role="status">{uploading ? "正在保存原图，请稍候…" : `${images.length} 张原图`}</small></section></>}<label className="check-label"><input type="checkbox" checked={pinned} onChange={e => setPinned(e.target.checked)} />置顶这条内容</label><label>内容来源<select className="select" value={source} onChange={e => { setSource(e.target.value); setConfirmed(false); }}><option value="manual">手动输入</option><option value="external">外部资料整理</option><option value="ai">AI / 对话整理</option></select></label>{source !== "manual" && <label className="check-label"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已校对，并确认收录</label>}<Notice error={error} /></div><footer className="kb-modal-foot"><button className="button secondary" type="button" disabled={saving || uploading} onClick={onClose}>取消</button><button className="button primary" disabled={saving || uploading}>{saving ? "正在保存…" : "保存条目"}</button></footer></form>{image && <ImageViewer image={image} onClose={() => setImage(null)} />}</KnowledgeModal>;
}

export function EntryList({ node, kind, detail, setDetail, onEdit }: { node: Node; kind: "note_entries" | "pain_entries"; detail: string; setDetail: (id: string) => void; onEdit: (entry?: KnowledgeEntry) => void }) {
  const [image, setImage] = useState<KnowledgeImage | null>(null), label = kind === "pain_entries" ? "痛点" : "笔记";
  const entries: KnowledgeEntry[] = [...(node.data[kind] || [])].sort((a, b) => Number(b.pinned) - Number(a.pinned)), current = entries.find(e => e.id === detail);
  return <>{current ? <><div className="kb-section-head"><button className="button secondary" onClick={() => setDetail("")}>← 返回{label}列表</button><button className="button secondary" onClick={() => onEdit(current)}>编辑条目</button></div><div className="kb-entry-heading"><small>{label} {current.pinned && <span className="kb-pin">置顶</span>}</small><h2>{current.title}</h2><div className="kb-chips">{current.tags.map(t => <span key={t}>{t}</span>)}</div></div><MathText text={current.body} /><div className="kb-image-grid">{current.images.map(i => <figure key={i.id}><button onClick={() => setImage(i)} aria-label={`查看原图：${i.name}`}><img src={imageUrl(i)} alt={i.name} /></button><figcaption>{i.name}<small>{fileSize(i.size)} · 原图</small></figcaption></figure>)}</div><p className="kb-source">{{ manual: "手动输入", external: "外部资料整理", ai: "AI / 对话整理" }[current.source]} · 已确认收录</p></> : <><div className="kb-section-head"><div><h2>{label}<small>{entries.length} 条</small></h2><p className="muted">{kind === "note_entries" ? "方法、模型和学习材料，逐条整理。" : "每个问题单独记录，逐项整理。"}</p></div><button className="button primary" onClick={() => onEdit()}>＋ 新增{label}</button></div><div className="kb-entry-list">{entries.map(e => <section className={`kb-entry-card ${e.pinned ? "kb-pinned" : ""}`} key={e.id}><div className="kb-section-head"><button className="kb-entry-title" onClick={() => setDetail(e.id)}>{e.title}</button>{e.pinned && <span className="kb-pin">置顶</span>}<button className="kb-text-button" aria-label={`编辑${e.title}`} onClick={() => onEdit(e)}>编辑</button></div><button className="kb-entry-excerpt" onClick={() => setDetail(e.id)}>{e.body || `${e.images.length} 张原图`}</button>{kind === "note_entries" && <div className="kb-chips">{e.tags.length ? e.tags.map(t => <span key={t}>{t}</span>) : <small>未设置标签</small>}</div>}<div className="kb-card-footer"><small>独立条目{e.images.length ? ` · ${e.images.length} 张原图` : ""}</small><button className="kb-text-button" onClick={() => setDetail(e.id)}>阅读全文 →</button></div></section>)}</div>{!entries.length && <div className="kb-empty">还没有{label}条目，点击“新增{label}”开始记录。</div>}</>}{image && <ImageViewer image={image} onClose={() => setImage(null)} />}</>;
}
