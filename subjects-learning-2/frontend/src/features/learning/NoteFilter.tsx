import { useEffect,useState,useRef } from "react";
import { apiUrl } from "../../api/client";
import { Question } from "./types";
import { post,Notice,message } from "./shared";

export default function NoteFilter({q,pageIndex,onSaved}:{q:Question;pageIndex:number;onSaved:()=>void}) {
 const [boxes,setBoxes]=useState<number[][]>([]),[box,setBox]=useState([0,0,0,0]),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const origin=useRef([0,0]),drawing=useRef(false);
 const source=q.data.source_pages?.[pageIndex]?.asset_id||q.source_asset_id;
 useEffect(()=>{setBoxes(q.data.note_filters?.pages?.[String(pageIndex)]||[]);setBox([0,0,0,0]);},[q.id,pageIndex,q.data.note_filters]);
 if(!source||q.historical)return null;
 const disabled=busy||["queued","running"].includes(q.data.recognition);
 function point(e:React.PointerEvent<HTMLDivElement>){const r=e.currentTarget.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];}
 async function save(){setBusy(true);setError("");try{await post(`/learning/questions/${q.id}/notes/filter`,{version_id:q.version_id,page_index:pageIndex,boxes});onSaved();}catch(e){setError(message(e));}finally{setBusy(false);}}
 return <details className="note-filter"><summary>框选黑笔等手写笔记，排除文字与图块识别</summary><p className="muted">只框手写计算、批注和作答区域。与印刷内容重叠的笔迹请用局部修复；排除框内内容会从识别副本中遮去。原图保留，识别先出草稿，核对后采用。</p>
 <div className="crop-stage note-filter-stage" onPointerDown={e=>{if(disabled)return;e.preventDefault();origin.current=point(e);drawing.current=true;e.currentTarget.setPointerCapture(e.pointerId);setBox([...origin.current,...origin.current]);}} onPointerMove={e=>{if(!drawing.current)return;const p=point(e);setBox([Math.min(origin.current[0],p[0]),Math.min(origin.current[1],p[1]),Math.max(origin.current[0],p[0]),Math.max(origin.current[1],p[1])]);}} onPointerUp={()=>{drawing.current=false;}} onPointerCancel={()=>{drawing.current=false;}}>
 <img src={apiUrl(`/assets/${source}/download`)} alt="框选笔记的原图" draggable={false}/>{[...boxes,box].map((b,i)=><div key={i} className="note-exclusion" style={{left:`${b[0]*100}%`,top:`${b[1]*100}%`,width:`${(b[2]-b[0])*100}%`,height:`${(b[3]-b[1])*100}%`}}/>)}
 </div><div className="event-actions"><button className="button secondary" disabled={disabled||box[2]<=box[0]||box[3]<=box[1]||boxes.length>=16} onClick={()=>{setBoxes([...boxes,box]);setBox([0,0,0,0]);}}>加入笔记排除框</button><button className="button secondary" disabled={disabled||!boxes.length} onClick={()=>setBoxes(boxes.slice(0,-1))}>撤掉最后一框</button><button className="link-button" disabled={disabled} onClick={()=>setBoxes([])}>清空本页排除框</button></div><p className="muted">本页已标记{boxes.length}个区域</p><button className="button primary" disabled={disabled} onClick={()=>void save()}>{busy?"正在保存…":"保存排除框并重新识别"}</button><Notice error={error}/></details>;
}
