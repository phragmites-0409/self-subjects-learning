import { useEffect, useState } from "react";

function Thumbnail({file}: {file:File}) {
  const [url,setUrl]=useState("");
  useEffect(()=>{if(typeof URL.createObjectURL!=="function")return;const value=URL.createObjectURL(file);setUrl(value);return()=>URL.revokeObjectURL(value);},[file]);
  return url ? <img src={url} alt={file.name} /> : null;
}

export function photoKey(files: File[]) {return files.map(file=>`${file.name}:${file.size}:${file.lastModified}`).join("|");}

export default function QuestionPhotos({files,onChange,busy=false}: {files:File[];onChange:(files:File[])=>void;busy?:boolean}) {
  function move(index:number,step:number) {const result=[...files];[result[index],result[index+step]]=[result[index+step],result[index]];onChange(result);}
  return <ol className="question-photo-list" aria-label="同题照片顺序">{files.map((file,index)=><li key={`${file.name}:${file.lastModified}:${index}`}><Thumbnail file={file} /><strong>第{index+1}张 · {file.name}</strong><div className="event-actions"><button type="button" className="button secondary" aria-label={`第${index+1}张前移`} disabled={busy||index===0} onClick={()=>move(index,-1)}>前移</button><button type="button" className="button secondary" aria-label={`第${index+1}张后移`} disabled={busy||index===files.length-1} onClick={()=>move(index,1)}>后移</button><button type="button" className="link-button danger" disabled={busy} onClick={()=>onChange(files.filter((_file,i)=>i!==index))}>删除</button></div></li>)}</ol>;
}
