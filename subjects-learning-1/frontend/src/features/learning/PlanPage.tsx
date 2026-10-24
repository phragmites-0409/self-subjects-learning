import { useState } from "react";
import { Link } from "react-router-dom";
import { CalendarDays, CheckCircle2, Clock3, Plus } from "lucide-react";
import { Dashboard, Event, statusLabel } from "./types";
import { Header, Notice, post, useData, message } from "./shared";

export default function PlanPage() {
  const { data: d, error, reload } = useData<Dashboard>("/learning/dashboard");
  const [busy, setBusy] = useState(false),
    [feedback, setFeedback] = useState(""),
    [newEvent, setNewEvent] = useState(false),
    [title, setTitle] = useState(""),
    [eventDay, setEventDay] = useState(""),
    [notes, setNotes] = useState(""),
    [reason, setReason] = useState(""),
    [abandon, setAbandon] = useState<Event | null>(null),
    [report, setReport] = useState(""),
    [view, setView] = useState("today");
  async function run(task: () => Promise<unknown>) {
    setBusy(true);
    setFeedback("");
    try {
      await task();
      await reload();
    } catch (e) {
      setFeedback(message(e));
    } finally {
      setBusy(false);
    }
  }
  const action = (e: Event, action: string) =>
    run(() => post(`/learning/events/${e.id}/action`, { action }));
  if (!d)
    return (
      <div className="page">
        <Header title="每日安排" />
        <Notice error={error} />
        <p>正在读取本地安排…</p>
      </div>
    );
  const rows = d.events.filter(
    (e) =>
      view === "week" ||
      (e.status === "open" && e.day <= d.day) ||
      e.day === d.day,
  );
  const dailyDone = d.uploads.filter((e) => e.status === "completed").length;
  const selectedReport = d.reports.find((r) => r.week === report);
  return (
    <div className="page learning-page">
      <Header
        title="每日安排"
        detail={`${d.day_label} · 本周截止 ${d.week_end_label} 24:00`}
      >
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => {
            setEventDay(d.day);
            setNewEvent(true);
          }}
        >
          <Plus size={16} />
          添加事项
        </button>
        <button
          className="button primary"
          disabled={busy}
          onClick={() => run(() => post("/learning/plan"))}
        >
          更新安排
        </button>
      </Header>
      <Notice error={error || feedback} />
      <div className="stats-grid">
        <div className="stat-card">
          <span>
            <CheckCircle2 size={15} /> 当日日清
          </span>
          <strong>{dailyDone}/4</strong>
          <small>仅检查上传，不涉及过手</small>
        </div>
        <div className="stat-card">
          <span>
            <Clock3 size={15} /> 四科预计用时
          </span>
          <strong>
            {d.minutes}
            <em> 分钟</em>
          </strong>
          <small>
            正常 {d.preferences.daily_minutes} · 上限 {d.maximum} 分钟
          </small>
        </div>
        <div className="stat-card">
          <span>尚待排期的错题</span>
          <strong>{d.pending_errors}</strong>
          <small>预计 {d.pending_minutes} 分钟（含未来目标）</small>
        </div>
      </div>
      <section className="panel daily-panel">
        <h2>每天四科都要销账</h2>
        <p className="muted">
          有错题：拍题入库后点击上传完成。没有错题：明确选择当日没有错题。
        </p>
        <div className="upload-grid">
          {d.uploads.map((e) => (
            <div className="upload-card" key={e.id}>
              <strong>{e.subject}</strong>
              <span className={`status status-${e.status}`}>
                {statusLabel[e.status]}
              </span>
              {e.status === "open" ? (
                <>
                  <Link
                    className="button secondary"
                    to={`/capture?subject=${e.subject}`}
                  >
                    录入错题
                  </Link>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => action(e, "uploaded")}
                  >
                    上传完成
                  </button>
                  <button
                    className="link-button"
                    disabled={busy}
                    onClick={() => action(e, "no_errors")}
                  >
                    当日没有错题
                  </button>
                </>
              ) : (
                <small>
                  {e.data.outcome === "no_errors"
                    ? "当日没有错题"
                    : e.status === "abandoned"
                      ? "已记录放弃"
                      : "上传已确认"}
                </small>
              )}
            </div>
          ))}
        </div>
      </section>
      {d.waiting_topics.map((t) => (
        <div className="notice" key={t.id}>
          {t.name} 已达到常规停推条件，请人工确认。
          <button
            className="button primary"
            disabled={busy}
            onClick={() =>
              run(() =>
                post(`/learning/knowledge/${t.id}/stop-decision`, {
                  stop: true,
                }),
              )
            }
          >
            确认停推
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() =>
              run(() =>
                post(`/learning/knowledge/${t.id}/stop-decision`, {
                  stop: false,
                }),
              )
            }
          >
            保持15天
          </button>
        </div>
      ))}
      {d.plan_notes.length > 0 && (
        <details className="panel">
          <summary>排期说明与待排内容</summary>
          <ul>
            {d.plan_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}
      <section className="panel">
        <div className="panel-heading">
          <h2>
            <CalendarDays size={18} /> 待办与处理记录
          </h2>
          <select
            aria-label="事件范围"
            className="select"
            value={view}
            onChange={(e) => setView(e.target.value)}
          >
            <option value="today">今日与未处理积压</option>
            <option value="week">本周全部</option>
          </select>
        </div>
        <div className="event-list">
          {rows.map((e) => (
            <div className="event-row" key={e.id}>
              <div>
                <strong>{e.title}</strong>
                <small>
                  {e.day_label} · {statusLabel[e.status]}
                  {e.minutes > 0 && ` · ${e.minutes}分钟`}
                  {e.data.carry_history?.length > 0 &&
                    ` · 已结转${e.data.carry_history.length}周，原截止${e.deadline_label}`}
                </small>
                {e.data.abandon_reason && (
                  <p>放弃说明：{e.data.abandon_reason}</p>
                )}
              </div>
              <div className="event-actions">
                {e.data.round_id && (
                  <Link
                    className="button secondary"
                    to={`/rounds/${e.data.round_id}?event=${e.id}`}
                  >
                    查看与回收
                  </Link>
                )}
                {e.status === "open" && e.kind === "general" && (
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => action(e, "complete")}
                  >
                    完成
                  </button>
                )}
                {e.status === "open" &&
                  e.kind === "upload" &&
                  e.day !== d.day && (
                    <>
                      <button
                        className="button secondary"
                        disabled={busy}
                        onClick={() => action(e, "uploaded")}
                      >
                        补确认上传
                      </button>
                      <button
                        className="link-button"
                        disabled={busy}
                        onClick={() => action(e, "no_errors")}
                      >
                        确认无错题
                      </button>
                    </>
                  )}
                {e.status === "open" && (
                  <button
                    className="link-button danger"
                    disabled={busy}
                    onClick={() => {
                      setAbandon(e);
                      setReason("");
                    }}
                  >
                    放弃
                  </button>
                )}
              </div>
            </div>
          ))}
          {!rows.length && <p className="muted">暂无事项。</p>}
        </div>
      </section>
      {d.upcoming.length > 0 && (
        <details className="panel">
          <summary>已拆分的未来安排（尚未进入执行周）</summary>
          {d.upcoming.map((e) => (
            <div className="event-row" key={e.id}>
              <span>
                {e.day_label} · {e.title} · {e.minutes}分钟
              </span>
              <Link to={`/rounds/${e.data.round_id}?event=${e.id}`}>查看</Link>
            </div>
          ))}
        </details>
      )}
      <section className="panel">
        <h2>每周留档报告</h2>
        <p className="muted">
          周日24:00结算。未完成事项带着原进度进入下周，后续完成不会覆盖历史报告。
        </p>
        {!d.reports.length ? (
          <p className="empty-state">首份报告将在本周结束后生成。</p>
        ) : (
          <>
            <select
              className="select"
              value={report}
              onChange={(e) => setReport(e.target.value)}
              aria-label="选择周报告"
            >
              <option value="">选择已留档的一周</option>
              {d.reports.map((r) => (
                <option key={r.week} value={r.week}>
                  {r.label}
                </option>
              ))}
            </select>
            {selectedReport && (
              <div>
                <p>
                  完成 {selectedReport.completed.length} · 未完成及结转{" "}
                  {selectedReport.unfinished.length} · 放弃{" "}
                  {selectedReport.abandoned.length}
                </p>
                {selectedReport.events.map((e) => (
                  <div className="event-row" key={e.id}>
                    <div>
                      {e.title}
                      <small>
                        {e.day_label} · {statusLabel[e.status]}
                        {e.kind === "upload" &&
                          ` · ${e.data.outcome === "no_errors" ? "无错题" : e.data.outcome === "uploaded" ? "上传完成" : "未确认"}`}
                        {e.data.abandon_reason && ` · ${e.data.abandon_reason}`}
                      </small>
                    </div>
                    {e.data.round_id && (
                      <Link to={`/rounds/${e.data.round_id}`}>查看记录</Link>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>
      {newEvent && (
        <div className="modal-backdrop">
          <form
            className="modal panel"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                await post("/learning/events", { title, day: eventDay, notes });
                setNewEvent(false);
                setTitle("");
                setNotes("");
              });
            }}
          >
            <h2>添加作业或其他事项</h2>
            <label>
              事项名称
              <input
                className="input"
                required
                maxLength={200}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              计划日期
              <input
                className="input"
                type="date"
                required
                value={eventDay}
                onChange={(e) => setEventDay(e.target.value)}
              />
            </label>
            <label>
              补充说明
              <textarea
                className="textarea"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </label>
            <div className="event-actions">
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={() => setNewEvent(false)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                保存事项
              </button>
            </div>
            <Notice error={feedback} />
          </form>
        </div>
      )}
      {abandon && (
        <div className="modal-backdrop">
          <div className="modal panel">
            <h2>记录放弃</h2>
            <p>{abandon.title}</p>
            <p className="muted">会如实记入周报告；放弃推送不代表题目过手。</p>
            <label>
              原因（可不填）
              <textarea
                className="textarea"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <div className="event-actions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setAbandon(null)}
              >
                继续处理
              </button>
              <button
                className="button danger"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await post(`/learning/events/${abandon.id}/action`, {
                      action: "abandon",
                      reason,
                    });
                    setAbandon(null);
                  })
                }
              >
                确认放弃并留档
              </button>
            </div>
            <Notice error={feedback} />
          </div>
        </div>
      )}
    </div>
  );
}
