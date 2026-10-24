import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, apiUrl } from "../../api/client";
import { Round, Item, Event, statusLabel } from "./types";
import {
  Header,
  MathText,
  Notice,
  SourceImage,
  message,
  patch,
  post,
  useData,
} from "./shared";

function ItemEditor({
  item: i,
  kind,
  number,
  onSaved,
  readonly,
}: {
  item: Item;
  kind: string;
  number: number;
  onSaved: () => void;
  readonly: boolean;
}) {
  const [verdict, setVerdict] = useState(
      i.verdict === "pending"
        ? i.data.ai_draft?.verdict || "uncertain"
        : i.verdict,
    ),
    [student, setStudent] = useState(i.data.student_answer || ""),
    [explanation, setExplanation] = useState(i.data.explanation || ""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [editingResolved, setEditingResolved] = useState(false);
  const locked = readonly || (i.status === "resolved" && !editingResolved);
  async function save(extra: Record<string, unknown> = {}) {
    setBusy(true);
    setError("");
    try {
      await patch(`/learning/items/${i.id}`, {
        verdict,
        student_answer: student,
        explanation,
        ...extra,
      });
      onSaved();
      setEditingResolved(false);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function explain() {
    setBusy(true); setError("");
    try { await post(`/learning/items/${i.id}/explanation`, {student_answer: student}); onSaved(); }
    catch(e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  return (
    <article className="panel round-question">
      <div className="panel-heading">
        <h2>第{number}题</h2>
        <span
          className={`status status-${i.status === "resolved" ? "completed" : "open"}`}
        >
          {statusLabel[i.status] || i.status}
        </span>
      </div>
      <MathText text={i.data.stem} />
      {i.data.content?.options?.map((s: string, k: number) => (
        <MathText key={k} text={s} />
      ))}
      {i.data.crop_asset_id && (
        <SourceImage id={i.data.crop_asset_id} alt="本卷冻结的打印图像" />
      )}
      <Link
        to={`/questions/${i.question_id}?version=${i.data.version_id || ""}`}
      >
        查看原题与版本 →
      </Link>
      <h3>
        本卷标准答案 ·{" "}
        {i.data.answer_confirmed ? "出卷时已确认" : "出卷时未确认，请人工改判"}
      </h3>
      <MathText text={i.data.answer || (i.data.answer_asset_ids?.length ? "标准答案见下方原图裁片" : i.data.answer_explanation ? "标准答案以所提供解析为准" : "无已确认答案")} />
      {i.data.answer_explanation && <MathText text={i.data.answer_explanation} />}
      {(i.data.answer_asset_ids || []).map((id: string, idx: number) => <SourceImage key={`${id}:${idx}`} id={id} alt={`本卷冻结的答案裁片${idx+1}`} />)}
      {i.data.ai_draft && (
        <Notice>
          AI初判：
          {
            { correct: "正确", wrong: "错误", uncertain: "拿不准" }[
              i.data.ai_draft.verdict as string
            ]
          }
          。你可以修改下面的判定，再确认。
        </Notice>
      )}
      <label>
        本次作答
        <textarea
          className="textarea"
          disabled={locked || busy}
          value={student}
          onChange={(e) => setStudent(e.target.value)}
          rows={2}
        />
      </label>
      <label>
        最终判定（可人工改判）
        <select
          className="select"
          disabled={locked || busy}
          value={verdict}
          onChange={(e) => setVerdict(e.target.value)}
        >
          <option value="uncertain">拿不准 · 待人工改判</option>
          <option value="correct">答案正确</option>
          <option value="wrong">答案错误</option>
        </select>
      </label>
      <label>
        解析或差异说明
        <textarea
          className="textarea"
          disabled={locked || busy}
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
          rows={3}
          placeholder="AI批改差异说明或你核对后记录的解析。"
        />
      </label>
      {!readonly && locked && <button className="button secondary" onClick={() => setEditingResolved(true)}>更正本题人工判定</button>}
      {!locked && (
        <div className="event-actions">
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => save()}
          >
            保存判定
          </button>
          {kind === "error" && verdict === "correct" && (
            <>
              <button
                className="button primary"
                disabled={busy}
                onClick={() => save({ mastered: true })}
              >
                我确认已过手
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => save({ mastered: false })}
              >
                仍未过手 · 次日重做
              </button>
            </>
          )}
          {kind === "error" && verdict === "wrong" && (
            <button className="button secondary" disabled={busy} onClick={explain}>获取本卷错题AI解析</button>
          )}
          {kind === "error" && verdict === "wrong" && (
            <button
              className="button primary"
              disabled={busy || !explanation.trim()}
              onClick={() => save({ learned: true })}
            >
              已学习解析 · 次日重做
            </button>
          )}
        </div>
      )}
      {kind === "error" && verdict === "wrong" && !locked && (
        <p className="muted">
          只有你点击已学习后，才以点击日期的次日为重新推送目标。
        </p>
      )}
      <Notice error={error} />
      {i.data.audit?.length > 0 && (
        <details>
          <summary>人工判定记录（{i.data.audit.length}次）</summary>
          {i.data.audit.map((a: any, k: number) => (
            <p key={k}>
              {a.day_label || a.day} ·{" "}
              {
                { correct: "正确", wrong: "错误", uncertain: "待改判" }[
                  a.verdict as string
                ]
              }
            </p>
          ))}
        </details>
      )}
    </article>
  );
}

export default function RoundPage() {
  const { id } = useParams(),
    [params, setParams] = useSearchParams(),
    { data: r, error, reload } = useData<Round>(`/learning/rounds/${id}`);
  const [busy, setBusy] = useState(false),
    [feedback, setFeedback] = useState(""),
    [file, setFile] = useState<File | null>(null),
    [useAI, setUseAI] = useState(true),
    [reason, setReason] = useState(""),
    [abandon, setAbandon] = useState(false);
  const e =
    r?.events.find((e) => e.id === params.get("event")) ||
    r?.events.find((e) => e.status === "open") ||
    r?.events[0];
  async function run(task: () => Promise<unknown>) {
    setBusy(true);
    setFeedback("");
    try {
      await task();
      await reload();
    } catch (e) {
      setFeedback(message(e));
      await reload();
    } finally {
      setBusy(false);
    }
  }
  async function upload(e: Event) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("purpose", "answer");
    const asset = await api<{ asset_id: string }>("/assets", {
      method: "POST",
      body: form,
    });
    await post(`/learning/events/${e.id}/return`, {
      asset_id: asset.asset_id,
      use_ai: useAI,
    });
  }
  async function download() {
    if (!e) return;
    const response = await fetch(apiUrl(`/learning/events/${e.id}/pdf`));
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error?.message || "PDF生成失败");
    }
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${e.subject}-${r?.kind === "error" ? "错题重做" : "题型重推"}-${e.day_label}-第${e.data.slice}份.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    await reload();
  }
  if (!r || !e)
    return (
      <div className="page">
        <Header title="推送与回收" />
        <Notice error={error} />
        <p>正在读取推送记录…</p>
      </div>
    );
  const items = r.items.filter((i) => i.event_id === e.id),
    isFinal = r.events.every(
      (x) => x.id === e.id || !["open", "planned"].includes(x.status),
    ),
    hasWrong = r.items.some((i) => i.verdict === "wrong"),
    ready = items.length > 0 && items.every((i) => i.status === "resolved"),
    readonly = e.status !== "open" || r.status !== "open";
  const finish = (passed?: boolean) =>
    run(() =>
      post(`/learning/events/${e.id}/action`, { action: "finish", passed }),
    );
  return (
    <div className="page learning-page">
      <Link className="back-button" to="/">
        ← 返回每日安排
      </Link>
      <Header
        title={r.kind === "error" ? "错题重做" : "题型重推"}
        detail={`${r.subject} · 原目标 ${r.target_label} · ${statusLabel[r.status] || r.status}`}
      >
        <button
          className="button primary"
          disabled={busy || e.status === "planned"}
          onClick={() => run(download)}
        >
          下载题目PDF
        </button>
      </Header>
      <Notice error={error || feedback} />
      <div className="toolbar wrap-toolbar">
        {r.events.map((x) => (
          <button
            key={x.id}
            className={`button ${e.id === x.id ? "primary" : "secondary"}`}
            onClick={() => {
              setParams({ event: x.id });
              setFile(null);
              setFeedback("");
            }}
          >
            第{x.data.slice}份 · {x.day_label} · {statusLabel[x.status]}
          </button>
        ))}
      </div>
      {e.status === "planned" && (
        <Notice>这是未来的拆分安排，到安排日期才进入执行事项和周清。</Notice>
      )}
      <Notice>
        {r.kind === "error"
          ? "本轮独立销账。答对仍需要你确认是否过手；答错需要你点击已学习。次日重推另建事件。"
          : "同一题型可能拆成多份PDF。每份做完可销账，整轮完成后只计算一次正确或错误轮次。"}
      </Notice>
      <section className="panel">
        <h2>回收打印稿</h2>
        {e.data.return_assets?.map((aid: string) => (
          <a
            className="button secondary"
            key={aid}
            href={apiUrl(`/assets/${aid}/download`)}
            target="_blank"
            rel="noreferrer"
          >
            查看已回收作答
          </a>
        ))}
        {!readonly && (
          <>
            <label>
              选择这份PDF的手写作答照片
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                disabled={busy}
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={useAI}
                onChange={(e) => setUseAI(e.target.checked)}
                disabled={busy}
              />
              用AI识别并比对本卷答案（结果可人工修改）
            </label>
            <button
              className="button primary"
              disabled={busy || !file}
              onClick={() => run(() => upload(e))}
            >
              {busy ? "正在处理…" : "保存作答并批改"}
            </button>
            <p className="muted">
              每次可追加一张照片。也可关闭AI，保存原稿后逐题人工判定。
            </p>
          </>
        )}
        {e.data.grading_concerns?.length > 0 && (
          <Notice>{e.data.grading_concerns.join("；")}</Notice>
        )}
      </section>
      {items.map((i, k) => (
        <ItemEditor
          key={`${i.id}:${i.status}:${JSON.stringify(i.data.ai_draft || {})}:${i.data.explanation || ''}`}
          item={i}
          kind={r.kind}
          number={k + 1}
          readonly={readonly}
          onSaved={reload}
        />
      ))}
      {!readonly && (
        <section className="panel finish-panel">
          <h2>本份处理完成后销账</h2>
          {r.kind === "type" &&
          isFinal &&
          !hasWrong &&
          !r.data.special_recheck ? (
            <>
              <p>
                整轮全部答对，仍由你确认是否通过。未通过会保持频率，保留连续正确记录，本轮不降频。
              </p>
              <div className="event-actions">
                <button
                  className="button primary"
                  disabled={busy || !ready}
                  onClick={() => finish(true)}
                >
                  我确认本轮通过并销账
                </button>
                <button
                  className="button secondary"
                  disabled={busy || !ready}
                  onClick={() => finish(false)}
                >
                  全部答对，但本轮未通过
                </button>
              </div>
            </>
          ) : (
            <button
              className="button primary"
              disabled={busy || !ready}
              onClick={() => finish()}
            >
              {r.kind === "type" && isFinal && hasWrong
                ? "本轮有错题 · 按未通过销账"
                : "确认本份已完成并销账"}
            </button>
          )}
          {!ready && (
            <p className="muted">仍有题目未完成改判、过手判断或学习确认。</p>
          )}
          <button
            className="link-button danger"
            disabled={busy}
            onClick={() => setAbandon(true)}
          >
            确实做不完 · 记录放弃
          </button>
        </section>
      )}
      {r.status === "completed" && r.kind === "type" && (
        <Notice>
          {r.data.automatic_stop
            ? "停推复检全对，已自动恢复停推。"
            : r.data.has_wrong
              ? "本轮未通过，错题已计入当天对应学科，题型继续推送。"
              : r.data.passed
                ? "本轮已人工确认通过，频率已按设置更新。"
                : "本轮全对但人工未通过，维持频率。"}
        </Notice>
      )}
      {abandon && (
        <div className="modal-backdrop">
          <div className="modal panel">
            <h2>放弃本份推送并留档</h2>
            <p className="muted">
              不计为完成或过手；已处理的内容及原因会保留。
            </p>
            <textarea
              className="textarea"
              placeholder="原因（可选）"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <div className="event-actions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setAbandon(false)}
              >
                取消
              </button>
              <button
                className="button danger"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await post(`/learning/events/${e.id}/action`, {
                      action: "abandon",
                      reason,
                    });
                    setAbandon(false);
                  })
                }
              >
                确认放弃
              </button>
            </div>
            <Notice error={feedback} />
          </div>
        </div>
      )}
    </div>
  );
}
