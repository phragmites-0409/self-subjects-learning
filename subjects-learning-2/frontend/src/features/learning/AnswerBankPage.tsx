import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, apiUrl } from "../../api/client";
import { Header, MathText, Notice, message, patch, post, useData } from "./shared";

type Entry = {number: string; chapter: string; answer: string; explanation: string; regions: {box: number[]}[]};
type Page = {id: string; number: number; asset_id: string; status: string; note: string; items: Entry[]};
type Document = {id: string; book: string; edition: string; chapter: string; filename: string; source_asset_id: string; page_count: number; indexed_count: number; pending: boolean; pages: Page[]};
const status: Record<string, string> = {manual: "原页已保存，待标注", queued: "等待识别", running: "识别中", completed: "已建立题号索引", failed: "识别失败，可重试"};

function PageEditor({page, chapter: defaultChapter, onSaved}: {page: Page; chapter: string; onSaved: () => void}) {
  const [selected, setSelected] = useState<number | null>(null), [number, setNumber] = useState(""), [chapter, setChapter] = useState(defaultChapter), [answer, setAnswer] = useState(""), [explanation, setExplanation] = useState("");
  const [regions, setRegions] = useState<{box: number[]}[]>([]), [drag, setDrag] = useState<number[] | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const origin = useRef<number[] | null>(null);
  function location(e: React.PointerEvent<HTMLImageElement>) {const r = e.currentTarget.getBoundingClientRect(); return [Math.max(0, Math.min(1, (e.clientX-r.left)/r.width)), Math.max(0, Math.min(1, (e.clientY-r.top)/r.height))];}
  function reset() {setSelected(null); setNumber(""); setChapter(defaultChapter); setAnswer(""); setExplanation(""); setRegions([]); setDrag(null);}
  async function save(items: Entry[]) {setBusy(true); setError(""); try {await patch(`/learning/answer-bank/pages/${page.id}`, {items}); reset(); onSaved();} catch(e) {setError(message(e));} finally {setBusy(false);}}
  function edit(idx: number) {const entry=page.items[idx]; setSelected(idx); setNumber(entry.number); setChapter(entry.chapter); setAnswer(entry.answer); setExplanation(entry.explanation); setRegions(entry.regions); setDrag(null);}
  const boxes = [...regions.map(r => r.box), ...(drag ? [drag] : [])];
  return <section className="panel answer-page">
    <h2>第{page.number}页 · {status[page.status] || page.status}</h2>
    {page.note && <Notice>{page.note}</Notice>}
    <div className="answer-index-list">{page.items.map((entry, idx) => <div className="answer-index-entry" key={idx}>
      <strong>{entry.chapter || defaultChapter || "未标章节"} · 第{entry.number}题</strong><MathText text={entry.answer || entry.explanation || "答案保留为图像"} />
      <div className="event-actions"><button className="button secondary" disabled={busy} onClick={() => edit(idx)}>调整题号或裁切范围</button><button className="button danger" disabled={busy} onClick={() => save(page.items.filter((_,i) => i !== idx))}>移除此题索引</button></div>
    </div>)}</div>
    <details open={selected !== null || !page.items.length}>
      <summary>{selected !== null ? `调整第${number}题` : "手动标注一题答案"}</summary>
      <p className="muted">框选这道题的完整答案和解析；跨栏可分多块框选。拖动后点击“保留这块”，再保存题号索引。</p>
      <a href={apiUrl(`/assets/${page.asset_id}/download`)} target="_blank" rel="noreferrer">查看整页原图</a>
      <div className="crop-stage"><img src={apiUrl(`/assets/${page.asset_id}/download`)} alt={`第${page.number}页答案`} draggable={false}
        onPointerDown={e => {if(busy)return; origin.current=location(e);setDrag([...origin.current,...origin.current]);e.currentTarget.setPointerCapture(e.pointerId);}}
        onPointerMove={e => {if(origin.current){const p=location(e);setDrag([Math.min(origin.current[0],p[0]),Math.min(origin.current[1],p[1]),Math.max(origin.current[0],p[0]),Math.max(origin.current[1],p[1])]);}}}
        onPointerUp={() => {origin.current=null;}} onPointerCancel={() => {origin.current=null;setDrag(null);}} />
        {boxes.map((box,idx) => <div className="crop-rectangle" key={idx} style={{left:`${box[0]*100}%`,top:`${box[1]*100}%`,width:`${(box[2]-box[0])*100}%`,height:`${(box[3]-box[1])*100}%`}} />)}
      </div>
      <div className="event-actions"><button className="button secondary" disabled={busy || !drag || drag[2] <= drag[0] || drag[3] <= drag[1]} onClick={() => {if(drag){setRegions([...regions,{box:drag}]);setDrag(null);}}}>保留这块</button><button className="button secondary" disabled={busy || !regions.length} onClick={() => setRegions(regions.slice(0,-1))}>移除最后一块</button><span className="muted">已框选 {regions.length} 块</span></div>
      <label>题号<input className="input" value={number} disabled={busy} onChange={e => setNumber(e.target.value)} placeholder="如 12 或 12(1)" /></label>
      <label>所属章节<input className="input" value={chapter} disabled={busy} onChange={e => setChapter(e.target.value)} /></label>
      <label>答案文字（可选，图像始终保留）<textarea className="textarea" rows={2} value={answer} disabled={busy} onChange={e => setAnswer(e.target.value)} /></label>
      <label>解析文字（可选）<textarea className="textarea" rows={3} value={explanation} disabled={busy} onChange={e => setExplanation(e.target.value)} /></label>
      <div className="event-actions"><button className="button primary" disabled={busy || !number.trim() || !regions.length} onClick={() => {const entry={number:number.trim(),chapter:chapter.trim(),answer,explanation,regions};save(selected === null ? [...page.items,entry] : page.items.map((v,i) => i === selected ? entry : v));}}>保存题号索引</button><button className="button secondary" disabled={busy} onClick={reset}>清空当前标注</button></div>
      <Notice error={error} />
    </details>
  </section>;
}

function DocumentView({id, onChanged}: {id: string; onChanged: () => void}) {
  const {data:doc,error,reload}=useData<Document>(`/learning/answer-bank/${id}`);
  const [feedback,setFeedback]=useState(""),[busy,setBusy]=useState(false);
  useEffect(() => {if(doc?.pending){const timer=setInterval(reload,2500);return () => clearInterval(timer);}},[doc?.pending,reload]);
  useEffect(() => {if(doc && !doc.pending)onChanged();},[doc?.pending,id]);
  async function index() {setBusy(true);setFeedback("");try {await post(`/learning/answer-bank/${id}/index`);reload();onChanged();}catch(e){setFeedback(message(e));}finally{setBusy(false);}}
  return <div><Notice error={error || feedback} />{doc && <>
    <section className="panel"><h2>{doc.book} {doc.edition && `· ${doc.edition}`}</h2><p className="muted">{doc.chapter} · 共{doc.page_count}页 · 已索引{doc.indexed_count}条答案</p><p>整页原件保留；识别只定位和转录现有答案，不重新作答。</p><button className="button secondary" disabled={busy || doc.pending} onClick={index}>{doc.pending ? "正在识别答案页…" : "识别未完成的答案页"}</button></section>
    {doc.pages.map(page => <PageEditor key={page.id} page={page} chapter={doc.chapter} onSaved={() => {reload();onChanged();}} />)}
  </>}</div>;
}

export default function AnswerBankPage() {
  const {data,error,reload}=useData<{items:Document[]}>("/learning/answer-bank");
  const [book,setBook]=useState(""),[chapter,setChapter]=useState(""),[edition,setEdition]=useState(""),[files,setFiles]=useState<File[]>([]),[selected,setSelected]=useState(""),[busy,setBusy]=useState(false),[feedback,setFeedback]=useState("");
  const input=useRef<HTMLInputElement>(null);
  async function upload() {setBusy(true);setFeedback("");try {const form=new FormData();form.append("book",book);form.append("chapter",chapter);form.append("edition",edition);files.forEach(file => form.append("files",file));const doc=await api<Document>("/learning/answer-bank/import",{method:"POST",body:form});setSelected(doc.id);setFiles([]);if(input.current)input.current.value="";reload();}catch(e){setFeedback(message(e));}finally{setBusy(false);}}
  return <div className="page learning-page"><Header title="答案库" detail="整页上传照片或PDF，按资料、章节和题号提取单题答案。"><Link className="button secondary" to="/knowledge">返回知识库</Link></Header><Notice error={error || feedback} />
    <div className="content-grid"><section className="panel"><h2>录入答案资料</h2>
      <label>资料名<input className="input" value={book} onChange={e => setBook(e.target.value)} disabled={busy} maxLength={200} /></label>
      <label>章节（可选，可在索引中细分）<input className="input" value={chapter} onChange={e => setChapter(e.target.value)} disabled={busy} maxLength={200} /></label>
      <label>版本（可选）<input className="input" value={edition} onChange={e => setEdition(e.target.value)} disabled={busy} maxLength={100} placeholder="用于区分同名资料，如2026版" /></label>
      <label>整页照片或PDF<input ref={input} type="file" multiple accept="application/pdf,image/jpeg,image/png,image/webp" disabled={busy} onChange={e => setFiles(Array.from(e.target.files || []))} /></label><p className="muted">同一资料的多页可一起上传。单批最多20个文件、100页；单文件50 MB，合计75 MB。</p>
      <button className="button primary" disabled={busy || !book.trim() || !files.length} onClick={upload}>{busy ? "保存答案资料…" : "保存整页并建立索引"}</button>
    </section><section className="panel"><h2>已保存资料</h2>{(data?.items || []).map(doc => <button className={`answer-document ${selected === doc.id ? "active" : ""}`} key={doc.id} onClick={() => setSelected(doc.id)}><strong>{doc.book} {doc.edition && `· ${doc.edition}`}</strong><small>{doc.chapter || "多个章节"} · {doc.page_count}页 · {doc.indexed_count}条答案</small></button>)}{!data?.items.length && <p className="muted">上传整页即可开始，不需要事先逐题裁切。</p>}</section></div>
    {selected && <DocumentView key={selected} id={selected} onChanged={reload} />}
  </div>;
}
