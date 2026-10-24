import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { MathText, Notice, SourceImage, message, patch, post } from "./shared";
import { Question } from "./types";

type Match = { document_id: string; book: string; edition: string; chapter: string; number: string; filename: string; entries: { page_number: number; answer: string; explanation: string; asset_id: string }[] };

export default function AnswerEditor({ q, onSaved }: { q: Question; onSaved: () => void }) {
  const [source, setSource] = useState(q.data.answer_source || "manual");
  const [answer, setAnswer] = useState(q.answer), [explanation, setExplanation] = useState(q.data.answer_explanation || "");
  const [file, setFile] = useState<File | null>(null), [staged, setStaged] = useState<{file: File; id: string} | null>(null);
  const [book, setBook] = useState(q.data.answer_reference?.book || ""), [chapter, setChapter] = useState(q.data.answer_reference?.chapter || ""), [number, setNumber] = useState(q.data.answer_reference?.number || ""), [edition, setEdition] = useState(q.data.answer_reference?.edition || "");
  const [matches, setMatches] = useState<Match[]>([]), [searched, setSearched] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { setAnswer(q.answer); setExplanation(q.data.answer_explanation || ""); }, [q.answer, q.data.answer_explanation]);
  useEffect(() => {setSource(q.data.answer_source || "manual");},[q.data.answer_source]);
  async function run(task: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await task(); onSaved(); } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  const base = `/learning/questions/${q.id}`;
  async function saveManual() {
    let aid = staged?.file === file ? staged.id : undefined;
    if (file && !aid) {
      const form = new FormData(); form.append("file", file); form.append("purpose", "answer");
      const uploaded = await api<{asset_id: string}>("/assets", { method: "POST", body: form });
      aid = uploaded.asset_id; setStaged({ file, id: aid });
    }
    await post(`${base}/answer`, { source: "manual", answer, explanation, asset_id: aid });
    setFile(null); setStaged(null);
  }
  async function lookup() {
    const params = new URLSearchParams({book, chapter, number, edition});
    const result = await api<{items: Match[]}>(`/learning/answer-bank/lookup?${params}`);
    setMatches(result.items); setSearched(true);
  }
  return <section className="panel answer-editor">
    <h2>3 · 录入答案</h2>
    <fieldset disabled={busy} className="answer-source-options"><legend>选择答案来源</legend>
      {[["manual", "手动输入／拍照"], ["bank", "从答案库提取"], ["ai", "AI作答，人工确认"]].map(([value, label]) => <label className="check-label" key={value}><input type="radio" name={`answer-source-${q.id}`} value={value} checked={source === value} onChange={() => { setSource(value); setError(""); }} />{label}</label>)}
    </fieldset>
    {source === "manual" && <>
      <p className="muted">你提供的答案视为已确认内容，无需AI判断正确性。文字和答案照片可任选，不强制答案、解析两项齐全。</p>
      <label>人工答案<textarea className="textarea" rows={3} value={answer} onChange={e => setAnswer(e.target.value)} disabled={busy} /></label>
      <label>人工解析（可选）<textarea className="textarea" rows={4} value={explanation} onChange={e => setExplanation(e.target.value)} disabled={busy} /></label>
      <label>答案照片（可选）<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" disabled={busy} onChange={e => { setFile(e.target.files?.[0] || null); setStaged(null); }} /></label>
      <button className="button primary" disabled={busy || (!answer.trim() && !explanation.trim() && !file)} onClick={() => run(saveManual)}>{busy ? "保存中…" : "保存人工答案"}</button>
    </>}
    {source === "bank" && <>
      <p className="muted">按资料、章节和题号提取整页中的答案及解析。<Link to="/answer-bank">管理答案库</Link></p>
      <div className="answer-lookup-fields">
        <label>资料名<input className="input" value={book} onChange={e => {setBook(e.target.value); setSearched(false);}} /></label>
        <label>章节<input className="input" value={chapter} onChange={e => {setChapter(e.target.value); setSearched(false);}} /></label>
        <label>题号<input className="input" value={number} onChange={e => {setNumber(e.target.value); setSearched(false);}} placeholder="如 12 或 12(1)" /></label>
        <label>版本（可选）<input className="input" value={edition} onChange={e => {setEdition(e.target.value); setSearched(false);}} /></label>
      </div>
      <button className="button secondary" disabled={busy || !book.trim() || !number.trim()} onClick={() => run(lookup)}>查找答案</button>
      {searched && !matches.length && <Notice>未找到对应答案，请检查资料名、章节和题号，或选择另一种答案来源。</Notice>}
      {searched && matches.map((match, idx) => <div className="answer-match" key={`${match.document_id}:${idx}`}>
        <strong>{match.book} · {match.chapter || "未标章节"} · 第{match.number}题 {match.edition && `· ${match.edition}`}</strong>
        <p className="muted">{match.filename} · 第{match.entries.map(e => e.page_number).join("、")}页</p>
        <MathText text={match.entries.map(e => e.answer || e.explanation).filter(Boolean).join("\n")} />
        <button className="button primary" disabled={busy} onClick={() => run(() => post(`/learning/answer-bank/apply/${q.id}`, {document_id: match.document_id, chapter: match.chapter, number: match.number}))}>提取此答案并自动裁切</button>
      </div>)}
    </>}
    {source === "ai" && <>
      <p className="muted">AI必须同时给出最终答案和完整解析，采纳后需要你确认。</p>
      <button className="button secondary" disabled={busy || ["queued", "running"].includes(q.data.recognition)} onClick={() => run(async () => { await post(`${base}/analysis`); await post(`${base}/answer/use-ai`); })}>{busy ? "AI处理中…" : "生成答案和解析"}</button>
      {q.data.analysis && <button className="button secondary" disabled={busy || q.data.analysis_version !== q.version_id} onClick={() => run(() => post(`${base}/answer/use-ai`))}>采纳已有AI答案和解析</button>}
      {q.data.answer_source === "ai" && <label className="check-label"><input type="checkbox" checked={q.answer_confirmed} disabled={busy} onChange={e => run(() => patch(base, {answer_confirmed: e.target.checked}))} />我已核对AI答案和解析</label>}
    </>}
    <Notice error={error} />
    {q.data.answer_note && <Notice>{q.data.answer_note}</Notice>}
    {(q.answer || q.data.answer_explanation || q.data.answer_asset_ids?.length) && <div className="saved-answer">
      <h3>已保存答案 · {q.data.answer_source === "ai" ? q.answer_confirmed ? "AI内容已人工确认" : "AI内容待人工确认" : "人工提供，已确认"}</h3>
      {q.answer && <MathText text={q.answer} />}
      {q.data.answer_explanation && <><h3>解析</h3><MathText text={q.data.answer_explanation} /></>}
      {(q.data.answer_asset_ids || []).map((id: string, idx: number) => <SourceImage key={`${id}:${idx}`} id={id} alt={`答案裁片${idx + 1}`} />)}
    </div>}
  </section>;
}
