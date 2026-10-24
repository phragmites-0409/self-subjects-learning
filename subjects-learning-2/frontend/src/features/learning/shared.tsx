import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import "katex/contrib/mhchem";
import { api, apiUrl } from "../../api/client";

export function useData<T>(path: string) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const sequence = useRef(0);
  const reload = useCallback(async () => {
    const request = ++sequence.current;
    try {
      const r = await api<T>(path);
      if (request === sequence.current) {
        setData(r);
        setError("");
      }
    } catch (e) {
      if (request === sequence.current) setError(message(e));
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setLoading(true);
    reload();
    return () => {
      sequence.current++;
    };
  }, [reload]);
  return { data, error, loading, reload, setData };
}
export const message = (e: unknown) =>
  e instanceof Error ? e.message : "操作失败，请重试";
export function MathText({ text = "", images=[], inline=false }: { text?: string;inline?:boolean;images?: {key:string;asset_id:string;label?:string;kind?:string;placement?:string;display_width?:number}[] }) {
  if(images.length && /\[\[图块:\d+\]\]/.test(text))return <div className="source-document">{text.split(/(\[\[图块:\d+\]\])/g).map((part,index)=>{
    const match=part.match(/^\[\[图块:(\d+)\]\]$/),item=match&&images.find(image=>image.key===match[1]);
    if(!item)return <MathText key={index} text={part} inline/>;
    const picture=<img style={item.display_width?{width:item.display_width}:undefined} src={apiUrl(`/assets/${item.asset_id}/download`)} alt={item.label||'原图公式与题图'}/>;
    return item.placement==='inline'?<span className="source-formula-inline" key={index}>{picture}</span>:<figure className={`source-inline source-inline-${item.kind||'formula'}`} key={index}>{picture}</figure>;
  })}</div>;
  const parts = text.split(
    /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\))/g,
  );
  const Container=inline?'span':'div';
  return (
    <Container className="math-text">
      {parts.map((part, i) => {
        const isMath =
          part.startsWith("$") ||
          part.startsWith("\\[") ||
          part.startsWith("\\(");
        if (!isMath) return <span key={i}>{part}</span>;
        const display = part.startsWith("$$") || part.startsWith("\\[");
        const formula =
          part.startsWith("$$") || part.startsWith("\\")
            ? part.slice(2, -2)
            : part.slice(1, -1);
        return (
          <span
            key={i}
            className={display ? "typeset-math typeset-display" : "typeset-math"}
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(formula, {
                throwOnError: false,
                displayMode: display,
                trust: false,
                strict: false,
              }),
            }}
          />
        );
      })}
    </Container>
  );
}
export function Notice({
  error,
  children,
}: {
  error?: string;
  children?: ReactNode;
}) {
  return error || children ? (
    <div
      className={error ? "notice error-notice" : "notice"}
      role={error ? "alert" : undefined}
    >
      {error || children}
    </div>
  ) : null;
}
export function Header({
  title,
  detail,
  children,
}: {
  title: string;
  detail?: string;
  children?: ReactNode;
}) {
  return (
    <div className="subpage-header">
      <div>
        <p className="eyebrow">题研 · 本地学习台</p>
        <h1>{title}</h1>
        {detail && <p className="muted">{detail}</p>}
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
export function Tabs({
  values,
  value,
  onChange,
}: {
  values: string[];
  value: string;
  onChange: (s: string) => void;
}) {
  return (
    <div className="subject-tabs">
      {values.map((v) => (
        <button
          type="button"
          className={`subject-tab ${v === value ? "active" : ""}`}
          key={v}
          onClick={() => onChange(v)}
        >
          {v}
        </button>
      ))}
    </div>
  );
}
export function SourceImage({
  id,
  alt = "原图",
}: {
  id?: string | null;
  alt?: string;
}) {
  return id ? (
    <a href={apiUrl(`/assets/${id}/download`)} target="_blank" rel="noreferrer">
      <img
        className="source-image"
        src={apiUrl(`/assets/${id}/download`)}
        alt={alt}
      />
    </a>
  ) : null;
}
export async function post<T>(path: string, body: unknown = {}) {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}
export async function patch<T>(path: string, body: unknown) {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}
