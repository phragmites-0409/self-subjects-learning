import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ImagePlus, LoaderCircle } from "lucide-react";
import { Notice, message } from "./shared";
import { IntakeContext, capturePath, createIntake, uploadQuestion } from "./intakeFlow";
import QuestionPhotos, { photoKey } from "./QuestionPhotos";

/** One photo picker and intake pipeline shared by every entry point. */
export default function CaptureEntry({ context, onCreated, onMore, label = "拍题录入", secondary = false }: {
  context: IntakeContext;
  onCreated?: () => void;
  onMore?: () => void;
  label?: string;
  secondary?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null), pending = useRef(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [bundle, setBundle] = useState(false), [photos,setPhotos]=useState<File[]>([]);
  const staged = useRef<{ key: string; id: string } | null>(null);
  const active = useRef(true);
  useEffect(() => {active.current=true;return () => {active.current=false;};}, []);
  const navigate = useNavigate();
  async function choose(files: File[]) {
    if (!files.length || pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      const key = photoKey(files);
      const qid = staged.current?.key === key ? staged.current.id : await uploadQuestion(files);
      staged.current = { key, id: qid };
      const q = await createIntake(context, { question_id: qid });
      if (active.current) {onCreated?.(); navigate(`/questions/${q.id}`);}
    } catch (e) { if (active.current) setError(message(e)); }
    finally { pending.current = false; if (active.current) setBusy(false); if (input.current) input.current.value = ""; }
  }
  return <div className="capture-entry">
    <button className={`button ${secondary ? "secondary" : "primary"}`} disabled={busy} onClick={() => input.current?.click()}>
      {busy ? <LoaderCircle className="spin" size={15} /> : <ImagePlus size={15} />}{busy ? "正在保存…" : label}
    </button>
    <button className="button secondary" disabled={busy} onClick={()=>{setBundle(true);input.current?.click();}}>多图／跨页</button>
    <input ref={input} type="file" multiple hidden aria-label={`${label}照片`} accept="image/jpeg,image/png,image/webp" capture="environment" disabled={busy} onChange={e => {
      const selected=Array.from(e.target.files||[]);e.target.value="";
      if(bundle||selected.length>1){const next=[...photos,...selected];if(next.length>8){setError("同一道题最多8张照片");return;}setBundle(true);setPhotos(next);setError("");}else{void choose(selected);}
    }} />
    {onMore ? <button className="link-button" disabled={busy} onClick={onMore}>文字／更多设置</button> : <Link className="link-button" aria-disabled={busy} onClick={e => {if(busy)e.preventDefault();}} to={capturePath(context)}>文字／更多设置</Link>}
    <Notice error={error} />
    {bundle&&<div className="multi-photo-intake"><p>同一道题按题干、续页、选项的顺序排列，最多8张。照片有重叠时，合并后请校对。</p><QuestionPhotos files={photos} onChange={setPhotos} busy={busy} /><div className="event-actions"><button className="button secondary" disabled={busy||photos.length>=8} onClick={()=>input.current?.click()}>继续添加照片</button><button className="button primary" disabled={busy||!photos.length} onClick={()=>void choose(photos)}>按此顺序录入同一道题</button><button className="link-button" disabled={busy} onClick={()=>{setBundle(false);setPhotos([]);setError("");}}>取消多图</button></div></div>}
  </div>;
}
