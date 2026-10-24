import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarDays, CheckCircle2, Clock3, ImagePlus, Plus, X } from "lucide-react";
import { Dashboard, Event, Question, STEM, statusLabel } from "./types";
import { Header, Notice, post, useData, message } from "./shared";
import { questionPath } from "./intakeFlow";
import CaptureEntry from "./CaptureEntry";
import "./today.css";

type Correction = { question_id: string; subject: string; title: string; recorded_label: string; occurrence_count: number };
type Corrections = { items: Correction[]; total: number; counts: Record<string, number> };

function Drafts({ day, close }: { day: string; close: () => void }) {
  const [offset, setOffset] = useState(0);
  const { data, error } = useData<{ items: Question[]; total: number }>(`/learning/questions?filter=draft&offset=${offset}&limit=30`);
  return <div className="modal-backdrop"><section className="modal panel" role="dialog" aria-modal="true" aria-label="继续录入草稿">
    <div className="panel-heading"><h2>继续录入草稿</h2><button className="icon-button" aria-label="关闭草稿" onClick={close}><X size={18} /></button></div>
    <Notice error={error} />
    {data?.items.map(q => <Link className="knowledge-question" key={q.id} to={questionPath(q.id, { from: "plan", day })}>
      <div><strong>{q.content.stem?.slice(0, 100) || "图片草稿 · 待整理"}</strong><small>{q.subject} · 待完成入库</small></div><span>继续 →</span>
    </Link>)}
    {data && !data.items.length && <p className="muted">没有未完成的草稿。</p>}
    <div className="event-actions"><button className="button secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</button><button className="button secondary" disabled={offset + 30 >= (data?.total || 0)} onClick={() => setOffset(offset + 30)}>下一页</button></div>
  </section></div>;
}

export default function PlanPage({ onCreated }: { onCreated?: () => void }) {
  const { data: d, error, reload } = useData<Dashboard>("/learning/dashboard");
  const [busy, setBusy] = useState(false), [feedback, setFeedback] = useState("");
  const [newEvent, setNewEvent] = useState(false), [title, setTitle] = useState(""), [eventDay, setEventDay] = useState(""), [notes, setNotes] = useState("");
  const [history, setHistory] = useState(false), [report, setReport] = useState(""), [drafts, setDrafts] = useState(false);
  const [abandon, setAbandon] = useState<Event | null>(null), [reason, setReason] = useState("");
  const [subject, setSubject] = useState("数学"), [correctionOffset, setCorrectionOffset] = useState(0);
  const corrections = useData<Corrections>(`/learning/corrections?subject=${encodeURIComponent(subject)}&offset=${correctionOffset}&limit=30`);
  const draftCount = useData<{ total: number }>("/learning/questions?filter=draft&limit=1");
  async function refresh() { await Promise.all([reload(), corrections.reload(), draftCount.reload()]); }
  async function run(task: () => Promise<unknown>) {
    setBusy(true); setFeedback("");
    try { await task(); await refresh(); } catch (e) { setFeedback(message(e)); } finally { setBusy(false); }
  }
  const action = (e: Event, name: string) => run(() => post(`/learning/events/${e.id}/action`, { action: name }));
  useEffect(() => {
    const update = () => { void reload(); void corrections.reload(); void draftCount.reload(); };
    const timer = window.setInterval(update, 30000); window.addEventListener("focus", update);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", update); };
  }, [reload, corrections.reload, draftCount.reload]);
  useEffect(() => { if (correctionOffset && corrections.data?.items.length === 0 && corrections.data.total <= correctionOffset) setCorrectionOffset(Math.max(0, correctionOffset - 30)); }, [corrections.data, correctionOffset]);
  if (!d) return <div className="page learning-page today-page"><Header title="今日安排" /><Notice error={error} /><p>正在读取本地安排…</p></div>;

  const general = d.events.filter(e => e.kind === "general" && (e.day === d.day || (e.status === "open" && e.day < d.day)))
    .sort((a, b) => Number(a.status !== "open") - Number(b.status !== "open") || a.day.localeCompare(b.day));
  const practice = d.events.filter(e => ["error", "type", "paper", "vocabulary"].includes(e.kind) && e.day <= d.day && e.status === "open");
  const dailyDone = d.uploads.filter(e => e.status === "completed").length;
  const selectedReport = d.reports.find(r => r.week === report);
  const correctionTotal = Object.values(corrections.data?.counts || {}).reduce((sum, n) => sum + n, 0);
  function abandonButton(e: Event) {
    return ["open", "planned", "paused"].includes(e.status) && <button className="link-button danger" disabled={busy} onClick={() => { setAbandon(e); setReason(""); }}>放弃</button>;
  }
  return <div className="page learning-page today-page">
    <Header title="今日安排" detail={`${d.day} · ${d.day_label.split("（")[1]?.replace("）", "") || d.day_label}`}>
      <button className="button secondary" disabled={busy} onClick={() => setHistory(true)}>记录与周报告</button>
      <button className="button secondary" disabled={busy} onClick={() => run(() => post("/learning/plan"))}>更新安排</button>
    </Header>
    <Notice error={error || feedback} />
    <div className="today-grid">
      <section className="panel today-panel" id="daily-uploads" aria-labelledby="today-intake-title">
        <div className="today-panel-heading"><h2 id="today-intake-title"><ImagePlus size={17} />错题录入</h2><span className="today-count">{dailyDone}/4 科完成</span></div>
        <div className="today-scroll" tabIndex={0} aria-label="错题录入列表">
          <div className="today-entry"><CaptureEntry context={{ from: "plan", day: d.day }} onCreated={onCreated} label="拍照录入题目" /></div>
          <button className="today-drafts" onClick={() => setDrafts(true)}>继续录入草稿<span>{draftCount.data?.total || 0} 道 →</span></button>
          {d.uploads.map(e => <div className="today-row today-upload-row" key={e.id}>
            <div className="today-row-copy"><strong>{e.subject}</strong><small>{e.status === "completed" ? e.data.outcome === "no_errors" ? "今日无错题" : "录入已完成" : "今日录入待确认"}</small></div>
            {e.status === "open" ? <div className="today-actions"><button className="button secondary" disabled={busy} onClick={() => action(e, "uploaded")}>录入完成</button><button className="link-button" disabled={busy} onClick={() => action(e, "no_errors")}>无错题</button></div> : <span className={`status status-${e.status}`}><CheckCircle2 size={13} />{statusLabel[e.status]}</span>}
          </div>)}
        </div>
        <div className="today-panel-foot">录入后先改错，再开始过关与重推计时。</div>
      </section>

      <section className="panel today-panel" aria-labelledby="today-events-title">
        <div className="today-panel-heading"><h2 id="today-events-title"><CalendarDays size={17} />今日事项<span className="today-count">{general.filter(e => e.status === "open").length}</span></h2>
          <button className="button secondary" disabled={busy} onClick={() => { setEventDay(d.day); setNewEvent(true); }}><Plus size={14} />新建事项</button></div>
        <div className="today-scroll" tabIndex={0} aria-label="今日事项列表">
          {general.map(e => <div className={`today-row ${e.status === "completed" ? "today-row-done" : ""}`} key={e.id}>
            <div className="today-row-copy"><strong title={e.title}>{e.title}</strong><small title={e.data.notes}>{e.day < d.day ? `${e.day_label} · 未完成` : e.data.notes || e.day_label}</small></div>
            <div className="today-actions">{e.status === "open" ? <button className="button primary" disabled={busy} onClick={() => action(e, "complete")}>完成</button> : <span className="status status-completed">{statusLabel[e.status]}</span>}{abandonButton(e)}</div>
          </div>)}
          {!general.length && <p className="today-empty">今天还没有事项，点击“新建事项”添加。</p>}
        </div>
        <div className="today-panel-foot">保留未完成事项，点击“完成”即可销账。</div>
      </section>

      <section className="panel today-panel today-corrections" aria-labelledby="today-corrections-title">
        <div className="today-panel-heading"><h2 id="today-corrections-title">待改错<span className="today-count">{correctionTotal} 道</span></h2><span className="muted">改错后开始计时</span></div>
        <div className="today-subjects" role="group" aria-label="待改错学科">{STEM.map(s => <button key={s} aria-pressed={subject === s} onClick={() => { setSubject(s); setCorrectionOffset(0); }}>{s}<span>{corrections.data?.counts?.[s] || 0}</span></button>)}</div>
        <Notice error={corrections.error} />
        <div className="today-scroll" tabIndex={0} aria-label="待改错列表">
          {!corrections.loading && corrections.data?.items?.map(q => <div className="today-row" key={q.question_id}>
            <div className="today-row-copy"><Link className="today-question-title" title={q.title} to={questionPath(q.question_id, { from: "plan", day: d.day })}>{q.title}</Link><small>{q.recorded_label}录入{q.occurrence_count > 1 && ` · ${q.occurrence_count}次记录`}</small></div>
            <button className="button primary" disabled={busy} aria-label={`改错：${q.title}`} onClick={() => run(() => post(`/learning/questions/${q.question_id}/correct`))}>改错</button>
          </div>)}
          {corrections.loading ? <p className="today-empty">正在读取…</p> : !corrections.data?.items.length && <p className="today-empty">{subject}没有待改错题目。</p>}
          {(correctionOffset > 0 || (corrections.data?.total || 0) > 30) && <div className="today-pagination"><button className="link-button" disabled={!correctionOffset} onClick={() => setCorrectionOffset(Math.max(0, correctionOffset - 30))}>上一页</button><span>共{corrections.data?.total || 0}道</span><button className="link-button" disabled={correctionOffset + 30 >= (corrections.data?.total || 0)} onClick={() => setCorrectionOffset(correctionOffset + 30)}>下一页</button></div>}
        </div>
        <div className="today-panel-foot">点击“改错”即确认已改错，首次重推间隔 {d.preferences.redo_days} 天。</div>
      </section>

      <section className="panel today-panel" aria-labelledby="today-practice-title">
        <div className="today-panel-heading"><h2 id="today-practice-title"><Clock3 size={17} />今日需过关<span className="today-count">{practice.length} 项</span></h2><span className="muted">四科 {d.minutes} 分钟</span></div>
        <div className="today-scroll" tabIndex={0} aria-label="今日过关列表">
          {d.waiting_topics.map(t => <div className="today-row" key={t.id}><div className="today-row-copy"><strong>{t.name}</strong><small>已达到停推条件，请确认</small></div><div className="today-actions"><button className="button secondary" disabled={busy} onClick={() => run(() => post(`/learning/knowledge/${t.id}/stop-decision`, { stop: true }))}>停推</button><button className="link-button" disabled={busy} onClick={() => run(() => post(`/learning/knowledge/${t.id}/stop-decision`, { stop: false }))}>继续</button></div></div>)}
          {practice.map(e => <div className="today-row" key={e.id}>
            <div className="today-row-copy"><strong title={e.title}>{e.title}</strong><small>{e.subject || "英语"} · {e.kind === "vocabulary" ? "单词过关" : `${e.minutes}分钟`}{e.day < d.day && " · 未完成"}</small></div>
            <div className="today-actions"><Link className="button secondary" to={e.kind === "vocabulary" ? "/vocabulary?tab=practice" : `/rounds/${e.data.round_id}?event=${e.id}`}>去过关</Link>{abandonButton(e)}</div>
          </div>)}
          {!practice.length && !d.waiting_topics.length && <p className="today-empty">今日暂无需要过关的内容。</p>}
        </div>
        <div className="today-panel-foot">题目 {d.preferences.daily_minutes} 分钟预算 · 单词单独计算</div>
      </section>
    </div>

    {drafts && <Drafts day={d.day} close={() => setDrafts(false)} />}
    {newEvent && <div className="modal-backdrop"><form className="modal panel" role="dialog" aria-modal="true" aria-label="新建事项" onSubmit={e => { e.preventDefault(); void run(async () => { await post("/learning/events", { title, day: eventDay, notes }); setNewEvent(false); setTitle(""); setNotes(""); }); }}>
      <h2>新建事项</h2><label>事项名称<input className="input" required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label>计划日期<input className="input" type="date" required value={eventDay} onChange={e => setEventDay(e.target.value)} /></label>
      <label>补充说明<textarea className="textarea" value={notes} onChange={e => setNotes(e.target.value)} /></label>
      <div className="event-actions"><button className="button secondary" type="button" disabled={busy} onClick={() => setNewEvent(false)}>取消</button><button className="button primary" disabled={busy}>保存事项</button></div><Notice error={feedback} />
    </form></div>}
    {abandon && <div className="modal-backdrop"><section className="modal panel" role="dialog" aria-modal="true" aria-label="记录放弃"><h2>记录放弃</h2><p>{abandon.title}</p><label>原因（可不填）<textarea className="textarea" value={reason} onChange={e => setReason(e.target.value)} /></label>
      <div className="event-actions"><button className="button secondary" disabled={busy} onClick={() => setAbandon(null)}>继续处理</button><button className="button danger" disabled={busy} onClick={() => run(async () => { await post(`/learning/events/${abandon.id}/action`, { action: "abandon", reason }); setAbandon(null); })}>确认放弃并留档</button></div><Notice error={feedback} />
    </section></div>}
    {history && <div className="modal-backdrop"><section className="modal panel today-history" role="dialog" aria-modal="true" aria-label="记录与周报告">
      <div className="panel-heading"><h2>记录与周报告</h2><button className="icon-button" aria-label="关闭记录" onClick={() => setHistory(false)}><X size={18} /></button></div>
      <details><summary>排期说明与未来安排</summary>{d.plan_notes.map(n => <p key={n}>{n}</p>)}{d.upcoming.map(e => <p key={e.id}>{e.day_label} · {e.title} <Link to={`/rounds/${e.data.round_id}?event=${e.id}`}>查看</Link></p>)}</details>
      <details><summary>本周处理记录</summary>{d.events.map(e => <div className="event-row" key={e.id}><div><strong>{e.title}</strong><small>{e.day_label} · {statusLabel[e.status]}</small></div><div className="event-actions">{e.kind === "upload" && e.status === "open" && <><button className="button secondary" disabled={busy} onClick={() => action(e, "uploaded")}>录入完成</button><button className="link-button" disabled={busy} onClick={() => action(e, "no_errors")}>无错题</button></>}{e.data.round_id && <Link to={`/rounds/${e.data.round_id}?event=${e.id}`}>查看</Link>}{abandonButton(e)}</div></div>)}</details>
      <h3>每周留档报告</h3><p className="muted">周日结算，未完成事项保留进度结转。</p>
      {d.reports.length ? <><select className="select" aria-label="选择周报告" value={report} onChange={e => setReport(e.target.value)}><option value="">选择已留档的一周</option>{d.reports.map(r => <option key={r.week} value={r.week}>{r.label}</option>)}</select>{selectedReport && <><p>完成 {selectedReport.completed.length} · 未完成 {selectedReport.unfinished.length} · 放弃 {selectedReport.abandoned.length}</p>{selectedReport.events.map(e => <div className="event-row" key={e.id}><div>{e.title}<small>{e.day_label} · {statusLabel[e.status]}</small></div>{e.data.round_id && <Link to={`/rounds/${e.data.round_id}`}>查看</Link>}</div>)}</>}</> : <p className="muted">首份报告将在本周结束后生成。</p>}
    </section></div>}
  </div>;
}
