import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, apiUrl } from "../../api/client";
import { Header, MathText, Notice, message, patch, post, useData } from "./shared";
import { Node, Question, SUBJECTS, STEM, localDay } from "./types";
import "./study.css";
import QuestionImport from "./QuestionImport";

type Pick = { question: Question; points: number; section_name: string; answer_space_mm: number };
type Pool = { items: Question[]; total: number; tag_counts: { tag: string; count: number }[] };
type Paper = { id: string; title: string; subject: string; total_points: number; items: unknown[] };
type Revision = { revision_id: string; revision: number; snapshot: { items: { question_id: string; version_id: string; data: Record<string, any> }[] }; revisions: { id: string; number: number }[] };
const basketKey = "question-bank-basket-v1";

export default function QuestionBankPage() {
  const [params, setParams] = useSearchParams();
  const subject = params.get("subject") || "数学", tab = params.get("tab") || "bank";
  const [search, setSearch] = useState(params.get("q") || ""), [filter, setFilter] = useState(params.get("filter") || ""),
    [topics, setTopics] = useState<string[]>(params.getAll("topic_ids")), [tags, setTags] = useState<string[]>([]),
    [mode, setMode] = useState("all"), [none, setNone] = useState(false), [from, setFrom] = useState(""), [to, setTo] = useState(""),
    [offset, setOffset] = useState(0), [title, setTitle] = useState("高中专项练习"), [editing, setEditing] = useState(""),
    [basket, setBasket] = useState<Pick[]>(() => { try { return JSON.parse(localStorage.getItem(basketKey) || "[]"); } catch { return []; } }),
    [busy, setBusy] = useState(false), [error, setError] = useState(""), [feedback, setFeedback] = useState(""),
    [preview, setPreview] = useState(false), [day, setDay] = useState(localDay()), [revisions, setRevisions] = useState<Record<string, Revision>>({});
  const query = new URLSearchParams({ subject, q: search, filter, offset: String(offset), limit: "30", tag_mode: mode, untagged: String(none), date_from: from, date_to: to });
  topics.forEach(t => query.append("topic_ids", t)); tags.forEach(t => query.append("tags", t));
  if (!topics.length && params.get("topic_id")) query.set("topic_id", params.get("topic_id")!);
  if (params.get("knowledge_id")) query.set("knowledge_id", params.get("knowledge_id")!);
  const pool = useData<Pool>(`/learning/questions?${query}`), nodes = useData<{ items: Node[] }>(`/learning/knowledge?subject=${encodeURIComponent(subject)}`), papers = useData<{ items: Paper[] }>("/papers");
  useEffect(() => { localStorage.setItem(basketKey, JSON.stringify(basket)); }, [basket]);
  useEffect(() => { setOffset(0); }, [search, filter, topics, tags, mode, none, from, to, subject]);
  const leaves = (nodes.data?.items || []).filter(n => n.kind === "type" && !n.child_count);
  const switchTab = (value: string) => { const next = new URLSearchParams(params); next.set("tab", value); setParams(next); };
  function toggle(q: Question) {
    setBasket(previous => previous.some(p => p.question.id === q.id) ? previous.filter(p => p.question.id !== q.id) : [...previous, { question: q, points: 5, section_name: "基础题", answer_space_mm: 30 }]);
  }
  function changePick(n: number, body: Partial<Pick>) { setBasket(items => items.map((p, i) => i === n ? { ...p, ...body } : p)); }
  function move(n: number, direction: number) { setBasket(items => { const next = [...items]; [next[n], next[n + direction]] = [next[n + direction], next[n]]; return next; }); }
  async function run(task: () => Promise<void>) { setBusy(true); setError(""); setFeedback(""); try { await task(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  async function save() {
    if (!basket.length || !title.trim()) throw new Error("请填写试卷名称并选择题目");
    const paperSubject = basket[0].question.subject;
    if (basket.some(p => p.question.subject !== paperSubject)) throw new Error("一份试卷请选择同一学科；选题篮保留了其他学科题目，请先移除");
    const body = { title, subject: paperSubject, grade: "高中", items: basket.map(p => ({ question_id: p.question.id, question_version_id: p.question.version_id, points: p.points, section_name: p.section_name, answer_space_mm: p.answer_space_mm })) };
    const saved = editing ? await patch<Paper>(`/papers/${editing}`, body) : await post<Paper>("/papers", body);
    setEditing(saved.id); setFeedback("试卷已保存，题面和答案已冻结。可在历史试卷下载或加入计划。"); await papers.reload();
  }
  async function download(id: string, answers: boolean, revision = "") {
    const result = await post<{ download_url: string }>(`/papers/${id}/export?include_answers=${answers}&revision_id=${revision}`);
    const link = document.createElement("a"); link.href = apiUrl(result.download_url.replace("/api/v1", "")); link.target = "_blank"; link.rel = "noopener"; link.click();
  }
  async function editPaper(paper: Paper, copy: boolean) {
    const p = copy ? await post<Paper>(`/papers/${paper.id}/copy`) : paper;
    const r = await api<Revision>(`/papers/${p.id}/revisions`);
    setTitle(p.title); setEditing(p.id);
    const picks = r.snapshot.items.map(i => ({ question: { id: i.question_id, version_id: i.version_id, subject: p.subject, question_type: i.data.section_name, content: i.data.content, tags: [], status: "approved", source_asset_id: i.data.source_asset_id, source_sha256: null, topic_id: null, minutes: i.data.minutes, answer: i.data.answer, answer_confirmed: i.data.answer_confirmed, ever_wrong: i.data.initial_state?.ever_wrong || false, mastered: i.data.initial_state?.mastered || false, data: {} } as Question, points: i.data.points, section_name: i.data.section_name, answer_space_mm: i.data.answer_space_mm }));
    setBasket(picks); switchTab("bank"); setPreview(true); await papers.reload();
  }
  return <div className="page learning-page study-page"><Header title="题目库" detail="六科题目统一归档，筛选选题，自由组卷。"></Header>
    <Notice error={error || pool.error || nodes.error || papers.error} /><Notice>{feedback}</Notice>
    <div className="toolbar"><button className={`button ${tab === "bank" ? "primary" : "secondary"}`} onClick={() => switchTab("bank")}>题库与选题篮（{basket.length}）</button><button className={`button ${tab === "papers" ? "primary" : "secondary"}`} onClick={() => switchTab("papers")}>历史试卷</button></div>
    {tab === "papers" ? <section className="panel"><div className="study-inline"><h2>历史试卷</h2><label>加入计划日期<input className="input" type="date" value={day} onChange={e => setDay(e.target.value)} /></label></div>{papers.data?.items.map(p => <article className="bank-row" key={p.id}><div><h3>{p.title}</h3><p>{p.subject} · {p.items.length}题 · {p.total_points}分</p></div><div className="toolbar wrap-toolbar">
      <button className="button secondary" disabled={busy} onClick={() => run(() => download(p.id, false))}>题目卷</button><button className="button secondary" disabled={busy} onClick={() => run(() => download(p.id, true))}>答案解析卷</button><button className="button secondary" disabled={busy} onClick={() => run(() => editPaper(p, true))}>复制修改</button><button className="button secondary" disabled={busy} onClick={() => run(() => editPaper(p, false))}>编辑为新版本</button>
      <button className="button primary" disabled={busy} onClick={() => run(async () => { await post(`/papers/${p.id}/schedule`, { day }); setFeedback("已加入学习计划，重复加入会返回原任务。"); })}>加入计划</button>
      <button className="link-button" onClick={() => run(async () => { const r = await api<Revision>(`/papers/${p.id}/revisions`); setRevisions(previous => ({ ...previous, [p.id]: r })); })}>查看版本</button>
    </div>{revisions[p.id]?.revisions.map(r => <div className="toolbar" key={r.id}><span>第{r.number}版</span><button className="link-button" disabled={busy} onClick={() => run(() => download(p.id, false, r.id))}>题目卷</button><button className="link-button" disabled={busy} onClick={() => run(() => download(p.id, true, r.id))}>答案解析卷</button></div>)}</article>)}{!papers.data?.items.length && <p>尚无历史试卷。先从题库选择题目。</p>}</section> : <div className="bank-layout"><section>
      <div className="panel bank-filters"><label>学科<select className="select" value={subject} onChange={e => { setParams({ subject: e.target.value, tab: "bank" }); setTopics([]); setTags([]); }} aria-label="题库学科">{SUBJECTS.map(s => <option key={s}>{s}</option>)}</select></label>
        <label>搜索<input className="input" aria-label="题库搜索" placeholder="题干、题型、标签或知识点" value={search} onChange={e => setSearch(e.target.value)} /></label>
        <label>题目状态<select className="select" value={filter} onChange={e => setFilter(e.target.value)}><option value="">全部正式题</option><option value="ordinary">普通题</option><option value="unmastered">未过手错题</option><option value="mastered">已过手错题</option><option value="unassigned">待归类</option><option value="draft">草稿</option></select></label>
        <label>开始日期<input className="input" type="date" value={from} onChange={e => setFrom(e.target.value)} /></label><label>结束日期<input className="input" type="date" value={to} onChange={e => setTo(e.target.value)} /></label>
        <fieldset className="bank-wide"><legend>叶子题型 · 可多选</legend><div className="study-chips">{leaves.map(n => <label key={n.id}><input type="checkbox" checked={topics.includes(n.id)} onChange={e => setTopics(v => e.target.checked ? [...v, n.id] : v.filter(id => id !== n.id))} />{n.name}</label>)}{!leaves.length && <span className="muted">当前学科暂无叶子题型</span>}</div>{params.get("topic_id") && !topics.length && <small>当前汇总知识库所选节点及其后代。<button className="link-button" onClick={() => setParams({ subject })}>清除节点范围</button></small>}</fieldset>
        <fieldset className="bank-wide"><legend>题目标签</legend><div className="study-chips">{Array.from(new Set([...(pool.data?.tag_counts || []).map(t => t.tag), ...tags])).map(t => <label key={t}><input type="checkbox" checked={tags.includes(t)} onChange={e => { setNone(false); setTags(v => e.target.checked ? [...v, t] : v.filter(tag => tag !== t)); }} />{t}</label>)}<label><input type="checkbox" checked={none} onChange={e => { setNone(e.target.checked); setTags([]); }} />未设标签</label><select className="select" aria-label="标签匹配方式" value={mode} onChange={e => setMode(e.target.value)}><option value="all">满足全部标签</option><option value="any">满足任一标签</option></select></div></fieldset>
      </div><div className="study-inline"><strong role="status">共{pool.data?.total || 0}题</strong><span>筛选不会清空选题篮</span></div>
      {pool.loading ? <p>正在读取题库…</p> : pool.data?.items.map(q => <article className="panel" key={q.id}><div className="study-inline"><Link to={`/questions/${q.id}`}>{q.question_type || "待归类"} · {q.subject}</Link><span>{q.status === "draft" ? "草稿" : q.awaiting_correction ? "待改错" : q.ever_wrong ? q.mastered ? "已过手" : "未过手错题" : "普通题"}</span></div><MathText text={q.content.stem} images={q.content.inline_images} /><div className="study-chips">{q.tags.map(t => <small key={t}>{t}</small>)}</div><div className="toolbar"><button className="button secondary" disabled={q.status === "draft"} onClick={() => toggle(q)}>{basket.some(p => p.question.id === q.id) ? "移出选题篮" : "加入选题篮"}</button>{STEM.includes(q.subject) && q.status !== "draft" && <button className="link-button" disabled={busy} onClick={() => run(async () => { await post(`/learning/questions/${q.id}/error`); await pool.reload(); setFeedback("已加入待改错，点击改错后开始重推计时。"); })}>记录错题</button>}</div></article>)}
      {!pool.loading && !pool.data?.items.length && <div className="panel">当前条件下没有题目。</div>}<div className="toolbar"><button className="button secondary" disabled={offset === 0} onClick={() => setOffset(v => Math.max(0, v - 30))}>上一页</button><span>第{Math.floor(offset / 30) + 1}页</span><button className="button secondary" disabled={offset + 30 >= (pool.data?.total || 0)} onClick={() => setOffset(v => v + 30)}>下一页</button></div>
      <QuestionImport subject={subject} nodes={leaves} onSaved={pool.reload} />
    </section><aside className="panel basket-panel"><div className="study-inline"><h2>选题篮 · {basket.length}题</h2><button className="link-button" onClick={() => { setBasket([]); setEditing(""); }}>清空</button></div><label>试卷名称<input className="input" value={title} onChange={e => setTitle(e.target.value)} /></label><p className="muted">共{basket.reduce((n, p) => n + p.points, 0)}分 · 预计{basket.reduce((n, p) => n + (p.question.minutes || 8), 0)}分钟</p>
      {basket.map((p, n) => <div className="basket-item" key={p.question.id}><strong>{n + 1}. {p.question.question_type}</strong><p>{p.question.content.stem?.slice(0, 80)}</p><div className="bank-filters"><label>分组<input className="input" value={p.section_name} onChange={e => changePick(n, { section_name: e.target.value })} /></label><label>分值<input className="input" type="number" min="0" max="100" value={p.points} onChange={e => changePick(n, { points: Number(e.target.value) })} /></label><label>作答空间（毫米）<input className="input" type="number" min="0" max="180" value={p.answer_space_mm} onChange={e => changePick(n, { answer_space_mm: Number(e.target.value) })} /></label></div><div className="toolbar"><button className="link-button" disabled={n === 0} onClick={() => move(n, -1)}>上移</button><button className="link-button" disabled={n === basket.length - 1} onClick={() => move(n, 1)}>下移</button><button className="link-button" onClick={() => toggle(p.question)}>移除</button></div></div>)}
      <div className="toolbar wrap-toolbar"><button className="button secondary" disabled={!basket.length} onClick={() => setPreview(!preview)}>{preview ? "收起预览" : "预览试卷"}</button><button className="button primary" disabled={busy || !basket.length} onClick={() => run(save)}>保存{editing ? "新版本" : "试卷"}</button></div>{preview && <div className="paper-preview"><h3>{title}</h3>{basket.map((p, n) => <div key={p.question.id}><h4>{p.section_name} · 第{n + 1}题 · {p.points}分</h4><MathText text={p.question.content.stem} images={p.question.content.inline_images} />{p.question.content.options?.map((o, i) => <MathText key={i} text={o} images={p.question.content.inline_images} />)}<div style={{ minHeight: `${Math.min(p.answer_space_mm, 60)}mm` }} /></div>)}</div>}
    </aside></div>}</div>;
}
