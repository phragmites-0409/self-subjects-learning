import { useState } from "react";
import { api } from "../../api/client";
import { message, useData } from "./shared";

type Counts = { questions?: number; drafts?: number; papers?: number; knowledge_entries?: number; words?: number; assets?: number; asset_bytes?: number };
type Device = { device_id: string; counts: Counts; indexed_at: string };
type Item = { device_id: string; kind: string; local_id: string; title: string; excerpt: string; subject: string; status: string; parent_kind: string; parent_local_id: string; relations: Record<string, unknown>; local_available: boolean; content_sha256: string | null };
type Overview = { devices: Device[]; items: Item[]; shown_limit: number; offset: number; pending_draft_deletions: number; formal_overrides: number };
const kinds = [["", "全部"], ["question", "题目"], ["paper", "试卷"], ["node", "知识节点"], ["knowledge", "知识条目"], ["asset", "文件"], ["word", "单词"]];

export default function CloudCatalog() {
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const { data, error, reload } = useData<Overview>(`/cloud-catalog?kind=${kind}&offset=${offset}`);
  async function sync() {
    setBusy(true);
    setFeedback("");
    try {
      const result = await api<{ changed: boolean; counts: Counts; formal_overrides: string[] }>("/cloud-catalog/sync", { method: "POST" });
      setFeedback(result.formal_overrides.length
        ? `发现 ${result.formal_overrides.length} 道题已在本机正式入库，已按入库优先保留并更新云端目录。`
        : result.changed ? "目录已同步；云端仅保存摘要和校验信息。" : "云端目录已经是最新版本。");
      await reload();
    } catch (reason) {
      setFeedback(message(reason));
    } finally {
      setBusy(false);
    }
  }
  return <section className="panel">
    <h2>云端学习目录</h2>
    <p className="muted">同步正式题目的最多 120 字摘要，以及题目、知识节点、条目、试卷、单词和文件的目录与关联信息。草稿不上传题干；完整内容、照片和长文仍在设备上。此目录尚不提供跨设备内容传输或原件恢复。</p>
    <button className="button primary" type="button" disabled={busy} onClick={() => void sync()}>{busy ? "正在同步…" : "从这台设备同步目录"}</button>
    {feedback && <p role="status">{feedback}</p>}
    {error && <p role="alert">{error}</p>}
    {!!data?.formal_overrides && <p role="status">已有 {data.formal_overrides} 条草稿删除记录被正式入库版本覆盖。原先删除草稿的设备仍需从保有正式版本的设备取得完整内容。</p>}
    {data?.devices.map(device => <p key={device.device_id} className="muted">设备 {device.device_id.slice(0, 8)} · 上次同步 {new Date(device.indexed_at).toLocaleString()} · 题目 {device.counts.questions || 0}（草稿 {device.counts.drafts || 0}） · 试卷 {device.counts.papers || 0} · 知识条目 {device.counts.knowledge_entries || 0} · 单词 {device.counts.words || 0}</p>)}
    {!data?.devices.length && !error && <p className="muted">尚无云端目录。登录已有数据的设备后点击同步。</p>}
    <label>查看类型 <select className="select" value={kind} onChange={event => { setKind(event.target.value); setOffset(0); }}>{kinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <div>{data?.items.map(item => <div key={`${item.device_id}-${item.kind}-${item.local_id}`} className="panel"><strong>{item.title || item.kind}</strong><p className="muted">{item.subject} · {item.status} · 条目 ID {item.local_id} · 设备 {item.device_id.slice(0, 8)} · {item.local_available ? "本机条目或文件存在（未完成副本校验）" : "本机文件缺失"}</p>{item.parent_local_id && <p className="muted">上级 {item.parent_kind}：{item.parent_local_id}</p>}{item.excerpt && <p>{item.excerpt}</p>}{item.content_sha256 && <small>内容 SHA-256：{item.content_sha256}</small>}{Object.keys(item.relations || {}).length > 0 && <details><summary>查看关联信息</summary><pre>{JSON.stringify(item.relations, null, 2)}</pre></details>}</div>)}</div>
    <div className="toolbar wrap-toolbar"><button className="button secondary" type="button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>上一页</button><button className="button secondary" type="button" disabled={(data?.items.length || 0) < 100} onClick={() => setOffset(offset + 100)}>下一页</button></div>
  </section>;
}
