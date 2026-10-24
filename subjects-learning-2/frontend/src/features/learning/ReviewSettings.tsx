import { useState } from "react";
import { Notice, message, patch, post, useData } from "./shared";
import { Node, STEM } from "./types";
import { VocabularySettings } from "./VocabularyPage";
type NativeReceipt = { accepted: boolean; receipt: string };
type Notifications = {
  preferences: { desktop_enabled: boolean; time: string }; windows: boolean;
  deliveries: { key: string; title: string; status: string; attempted_at?: string; error?: string; native?: NativeReceipt }[];
};

export function NotificationSettings() {
  const n = useData<Notifications>("/learning/notifications");
  const [error, setError] = useState(""), [feedback, setFeedback] = useState(""), [busy, setBusy] = useState(false);
  async function run(task: () => Promise<unknown>) {
    setError(""); setFeedback(""); setBusy(true);
    try { await task(); } catch (e) { setError(message(e)); }
    finally { await n.reload(); setBusy(false); }
  }
  return <section className="panel">
    <h2>应用内与 Windows 桌面通知</h2>
    <Notice error={error || n.error} /><Notice>{feedback}</Notice>
    {n.data && <>
      <label className="check-label"><input type="checkbox" disabled={busy} checked={n.data.preferences.desktop_enabled}
        onChange={e => run(() => patch("/learning/notifications", { desktop_enabled: e.target.checked }))} />发送桌面提醒</label>
      <label>题目练习提醒时刻<input className="input" type="time" value={n.data.preferences.time} disabled={busy}
        onChange={e => run(() => patch("/learning/notifications", { time: e.target.value }))} /></label>
      <p className="muted">单词使用单词设置中的推送时刻。本地服务运行时发送；关闭期间，下次启动补办。相同日期和类别的提醒只成功发送一次。</p>
      <button className="button secondary" disabled={busy || !n.data.windows} onClick={() => run(async () => {
        const result = await post<{ sent: boolean; receipt: NativeReceipt }>("/learning/notifications/test");
        if (!result.sent || !result.receipt?.accepted || result.receipt.receipt !== "notification_center") throw new Error("尚未取得Windows投递回执，请重试。");
        setFeedback("Windows已确认接收测试通知，可点击通知打开今日安排。");
      })}>{busy ? "正在处理…" : "发送测试通知"}</button>
      <p className="muted">开启勿扰、专注或全屏应用时，Windows可能将提醒收进通知中心，暂不显示横幅。</p>
      <details><summary>最近投递记录</summary>{n.data.deliveries.map(d => <p key={d.key}>
        {d.title || d.key} · {d.status === "sent" ? (d.native?.receipt === "notification_center" ? "Windows已确认接收" : "已发送") : d.status === "failed" ? "发送失败" : "处理中"}
        {d.attempted_at && ` · ${new Date(d.attempted_at).toLocaleString("zh-CN")}`}{d.error && ` · ${d.error}`}
      </p>)}</details>
    </>}
  </section>;
}

export default function ReviewSettings() {
  const [subject, setSubject] = useState("数学"),
    [error, setError] = useState(""), [feedback, setFeedback] = useState(""), [busy, setBusy] = useState(false);
  const nodes = useData<{ items: Node[] }>(`/learning/knowledge?subject=${encodeURIComponent(subject)}`);
  async function run(task: () => Promise<unknown>) { setError(""); setFeedback(""); setBusy(true); try { await task(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  return <><section className="panel"><h2>选用：具体题型重推</h2><p className="muted">设置中的总开关和这里的题型开关同时开启后，才会按过手比例进入检测。关闭时未开始任务暂停，进行中任务可以完成。</p><Notice error={error || nodes.error} /><Notice>{feedback}</Notice><select className="select" aria-label="重推题型学科" value={subject} onChange={e => setSubject(e.target.value)}>{STEM.map(s => <option key={s}>{s}</option>)}</select><div className="study-chips">{nodes.data?.items.filter(n => n.kind === "type" && !n.child_count).map(node => <label key={node.id}><input type="checkbox" disabled={busy} checked={!!node.data.review_enabled} onChange={e => run(async () => { await post(`/learning/knowledge/${node.id}/review-switch`, { enabled: e.target.checked }); await nodes.reload(); })} />{node.name}</label>)}</div></section>
    <VocabularySettings /><NotificationSettings /></>;
}
