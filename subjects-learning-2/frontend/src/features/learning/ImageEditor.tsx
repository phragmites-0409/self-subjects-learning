import { useEffect, useRef, useState } from "react";
import { api, apiUrl } from "../../api/client";
import { Question } from "./types";
import { message, Notice, post } from "./shared";

type Stroke = { points: number[][]; radius: number };
type Part = { box: number[]; label: string };

export default function ImageEditor({ q, onSaved }: { q: Question; onSaved: () => void }) {
  const [sourceKind, setSourceKind] = useState("processed");
  const inlineImages: NonNullable<Question['content']['inline_images']> = q.data.inline_images || q.content.inline_images || [];
  const source = (sourceKind.startsWith('inline:') ? inlineImages.find(item=>`inline:${item.key}`===sourceKind)?.asset_id : sourceKind === "original" ? q.source_asset_id : sourceKind === "print" ? q.data.crop_asset_id : q.data.processed_asset_id) || q.source_asset_id;
  const [tool, setTool] = useState("crop"), [box, setBox] = useState([0, 0, 1, 1]);
  const [parts, setParts] = useState<Part[]>([]), [label, setLabel] = useState("");
  const [strokes, setStrokes] = useState<Stroke[]>([]), [radius, setRadius] = useState(.008);
  const [protectStrokes, setProtectStrokes] = useState<Stroke[]>([]), [brush, setBrush] = useState("remove");
  const [repairReady, setRepairReady] = useState(false);
  const [handwritingReady,setHandwritingReady]=useState(false);
  const [unwarpReady,setUnwarpReady]=useState(false),[enhancement,setEnhancement]=useState('paper');
  useEffect(()=>{let alive=true;api<{unwarp_ready?:boolean}>('/learning/image/repair-status').then(result=>{if(alive)setUnwarpReady(!!result.unwarp_ready)}).catch(()=>{});return()=>{alive=false}},[]);
  useEffect(() => { let alive=true; api<{ready:boolean;handwriting_ready?:boolean}>("/learning/image/repair-status").then(data => {if(alive){setRepairReady(data.ready);setHandwritingReady(!!data.handwriting_ready);}}).catch(() => {}); return () => {alive=false;}; }, []);
  const [pencil, setPencil] = useState(q.data.pencil_mode || "balanced"), [method, setMethod] = useState("white");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [dimensions, setDimensions] = useState([1000, 1000]);
  const origin = useRef([0, 0]), drawing = useRef(false);
  if (!q.source_asset_id) return null;
  const clear = () => { setParts([]); setStrokes([]); setProtectStrokes([]); setBox([0, 0, 1, 1]); };
  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); clear(); onSaved(); } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  function location(e: React.PointerEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (e.clientX-r.left)/r.width)), Math.max(0, Math.min(1, (e.clientY-r.top)/r.height))];
  }
  return <details open className="crop-editor image-editor">
    <summary>题图处理、铅笔擦除与多框裁图</summary>
    <p className="muted">复杂公式优先保留原图位置与结构；可在下方单独选择公式或题图清理。轻度和标准处理保护浅色曲线，空白处笔迹可擦白，压住曲线或标注时可先试局部修复预览，须对照原图核对。擦除并保存整页处理稿后，可重新提取文字。已保存的人工答案不受影响。</p>
    <label>铅笔处理强度<select className="select" value={pencil} onChange={e => setPencil(e.target.value)}>
      <option value="off">关闭（彩色原题或需保留灰线）</option><option value="gentle">轻度减淡</option><option value="balanced">标准减淡</option><option value="strong">强度减淡（可能影响浅色印刷线）</option>
    </select></label>
    <button className="button secondary" disabled={busy} onClick={() => run(() => post(`/learning/questions/${q.id}/image/process`, { pencil }))}>从原图重新处理铅笔与背景</button>
    <label>编辑图像<select className="select" value={sourceKind} onChange={e => { setSourceKind(e.target.value); clear(); }}>
      <option value="processed">处理稿（裁切保留清理效果）</option><option value="original">原图（对照或重新框选）</option>{q.data.crop_asset_id && !inlineImages.length && <option value="print">当前打印图（局部擦除）</option>}
      {inlineImages.map(item=><option key={item.key} value={`inline:${item.key}`}>原位{item.kind==='diagram'?'题图':'公式'} {item.key}（单独裁切／清理）</option>)}
    </select></label>
    <label>图像增强与矫正<select className="select" value={enhancement} onChange={e=>setEnhancement(e.target.value)}><option value="paper">分离纸张光照与墨迹，减弱背景噪点</option><option value="ink_layer" disabled={!handwritingReady}>高阈值笔迹分层（单个图块，先预览）</option><option value="deskew">按印刷行校正轻微倾斜</option><option value="unwarp" disabled={!unwarpReady}>文档弯曲与透视矫正（先核对边缘和曲线）</option></select></label>
    <button className="button secondary" disabled={busy||['queued','running'].includes(q.data.recognition)} onClick={()=>run(()=>post(`/learning/questions/${q.id}/image/enhance-preview`,{asset_id:source,mode:enhancement,protect_strokes:protectStrokes}))}>生成增强／矫正对比稿</button>
    <p className="muted">背景增强不补画公式或曲线。高阈值分层会修补候选笔迹，采用前须检查是否误擦；可先用蓝笔保护原有线条。几何矫正请优先选择单个原位图块，检查边缘后采用。</p>
    <label>工具<select className="select" value={tool} onChange={e => { setTool(e.target.value); clear(); }}><option value="crop">多框裁图</option><option value="erase">涂抹手写笔迹（黑笔／铅笔）</option></select></label>
    {tool === "erase" ? <>
      <label>画笔半径<input type="range" min=".002" max=".03" step=".001" value={radius} onChange={e => setRadius(Number(e.target.value))} /></label>
      <label>笔刷用途<select className="select" value={brush} onChange={e => setBrush(e.target.value)}><option value="remove">标记要擦的笔迹（红色）</option><option value="protect">保护原有曲线和字母（蓝色）</option></select></label>
      <label>擦除方式<select className="select" value={method} onChange={e => setMethod(e.target.value)}><option value="white">擦白（空白区独立笔迹）</option><option value="inpaint">邻域修复（重叠处需复核）</option><option value="handwriting" disabled={!handwritingReady}>笔迹模型细化笔刷（黑笔／铅笔，先预览）{!handwritingReady && " · 未就绪"}</option><option value="lama" disabled={!repairReady}>本地模型修复（先预览）{!repairReady && " · 未就绪"}</option></select></label>
      {method==="handwriting" && <p className="muted">涂抹笔记的大致范围，模型只选择其中高置信笔画像素，再修补背景；每次处理一处。图中线条或印刷文字仍可能误判，请先用蓝笔保护，再核对对比稿。整页自动擦除未启用。</p>}
      <p className="muted">先用红色标出笔迹，再用蓝色保护虚线、轨迹、坐标和字母。模型只修复标记区域，蓝色区域保留原像素。遮挡处的补线需要对照原图检查。</p>
    </> : <label>当前图块<select className="select" value={label} onChange={e => setLabel(e.target.value)}><option value="">主图 / 保留原有标注</option>{"ABCDEFGH".split("").map(letter => <option key={letter} value={letter}>选项 {letter}（裁掉旧编号后重排）</option>)}</select></label>}
    <div className="crop-stage image-edit-stage" onPointerDown={e => {
      if (busy) return;
      e.preventDefault(); const point = location(e); origin.current = point; drawing.current = true; e.currentTarget.setPointerCapture(e.pointerId);
      if (tool === "crop") setBox([...point, ...point]); else (brush === "protect" ? setProtectStrokes : setStrokes)(old => [...old, { points: [point], radius }]);
    }} onPointerMove={e => {
      if (!drawing.current) return; const p = location(e);
      if (tool === "crop") setBox([Math.min(origin.current[0], p[0]), Math.min(origin.current[1], p[1]), Math.max(origin.current[0], p[0]), Math.max(origin.current[1], p[1])]);
      else (brush === "protect" ? setProtectStrokes : setStrokes)(old => old.map((s, i) => i === old.length-1 && s.points.length < 3000 ? { ...s, points: [...s.points, p] } : s));
    }} onPointerUp={() => { drawing.current = false; }} onPointerCancel={() => { drawing.current = false; }}>
      <img src={apiUrl(`/assets/${source}/download`)} alt="用于清理和框选的题图副本" draggable={false} onLoad={e => setDimensions([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} />
      {tool === "crop" ? <div className="crop-rectangle" style={{ left: `${box[0]*100}%`, top: `${box[1]*100}%`, width: `${(box[2]-box[0])*100}%`, height: `${(box[3]-box[1])*100}%` }} /> :
        <svg className="ink-mask-overlay" viewBox={`0 0 ${dimensions[0]} ${dimensions[1]}`} aria-hidden="true">{[...strokes.map(s=>({...s,color:'#df755e'})),...protectStrokes.map(s=>({...s,color:'#3c8fdf'}))].map((s, i) => <g key={i} opacity=".6"><polyline points={s.points.map(p => `${p[0]*dimensions[0]},${p[1]*dimensions[1]}`).join(" ")} fill="none" stroke={s.color} strokeWidth={s.radius*dimensions[0]*2} strokeLinecap="round" strokeLinejoin="round" />{s.points.length === 1 && <circle cx={s.points[0][0]*dimensions[0]} cy={s.points[0][1]*dimensions[1]} r={s.radius*dimensions[0]} fill={s.color} />}</g>)}</svg>}
    </div>
    {tool === "crop" ? <>
      <div className="event-actions"><button className="button secondary" disabled={busy || box[2] <= box[0] || box[3] <= box[1] || parts.length >= 12} onClick={() => setParts(old => [...old, { box: [...box], label }])}>加入图块</button>
        <button className="button secondary" disabled={busy} onClick={() => setBox([0, 0, 1, 1])}>选择整图</button></div>
      {parts.map((part, i) => <p key={i}>图块 {i+1} · {part.label ? `选项 ${part.label}` : "主图"} <button className="link-button" onClick={() => setParts(old => old.filter((_, n) => n !== i))}>移除</button></p>)}
      <button className="button primary" disabled={busy || box[2] <= box[0] || box[3] <= box[1]} onClick={() => run(() => post(`/learning/questions/${q.id}/image/crop`, { asset_id: source, boxes: parts.length ? parts : [{ box, label }] }))}>保存打印裁图</button>
    </> : <div className="event-actions"><button className="button secondary" disabled={busy || !(brush === "protect" ? protectStrokes : strokes).length} onClick={() => (brush === "protect" ? setProtectStrokes : setStrokes)(old => old.slice(0, -1))}>撤掉上一笔</button><button className="button secondary" disabled={busy || !strokes.length} onClick={() => run(() => post(`/learning/questions/${q.id}/image/repair-preview`, { asset_id: source, strokes, protect_strokes: protectStrokes, method }))}>{busy ? "修复处理中…" : "生成局部修复预览"}</button>{!["lama","handwriting"].includes(method) && <button className="button primary" disabled={busy || !strokes.length} onClick={() => run(() => post(`/learning/questions/${q.id}/image/erase`, { asset_id: source, strokes, protect_strokes: protectStrokes, method }))}>应用局部擦除</button>}</div>}
    {q.data.image_repair_draft && <section className="repair-preview"><h3>{q.data.image_repair_draft.method?.startsWith("enhance:")?"图像处理对比稿":"局部修复对比稿"}</h3><p className="muted">左为修复前，右为修复后。检查虚线、轨迹与字母后采用，原照片保留。处理用时 {q.data.image_repair_draft.seconds} 秒。</p><div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}><img style={{width:'100%'}} src={apiUrl(`/assets/${q.data.image_repair_draft.source_asset_id}/download`)} alt="局部修复前"/><img style={{width:'100%'}} src={apiUrl(`/assets/${q.data.image_repair_draft.asset_id}/download`)} alt="局部修复预览"/></div><button className="button primary" disabled={busy || q.data.image_repair_draft.adoptable===false || ['queued','running'].includes(q.data.recognition)} onClick={() => run(() => post(`/learning/questions/${q.id}/image/repair-adopt`,{asset_id:q.data.image_repair_draft.asset_id}))}>采用此修复稿</button>{q.data.image_repair_draft.adoptable===false&&<p className="muted">整页矫正仅作对照；请选择单个公式或打印图再矫正，以保留原有框选匹配。</p>}</section>}
    <div className="event-actions image-editor-actions"><button className="button secondary" disabled={busy || !q.data.image_history?.length} onClick={() => run(() => post(`/learning/questions/${q.id}/image/undo`))}>回退上次图像修改</button>
      <button className="button secondary" disabled={busy || !q.data.processed_asset_id || ["queued", "running"].includes(q.data.recognition)} onClick={() => run(() => post(`/learning/questions/${q.id}/recognize`, { source: "processed" }))}>从已保存处理稿提取文字草稿</button>
      <button className="button primary" disabled={busy || !(q.data.crop_asset_id || inlineImages.length)} onClick={() => run(() => post(`/learning/questions/${q.id}/image/confirm`))}>确认打印图已校对</button></div>
    <Notice error={error} />
  </details>;
}
