import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { apiUrl } from "../../api/client";
import { Question, Node, STEM, SUBJECTS, statusLabel } from "./types";
import AnswerEditor from "./AnswerEditor";
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

function CropEditor({ q, onSaved }: { q: Question; onSaved: () => void }) {
  const [box, setBox] = useState([0, 0, 1, 1]),
    [dragging, setDragging] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const origin = useRef([0, 0]);
  const location = (e: React.PointerEvent<HTMLImageElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    ];
  };
  async function save() {
    setBusy(true);
    setError("");
    try {
      await post(`/learning/questions/${q.id}/crop`, {
        left: box[0],
        top: box[1],
        right: box[2],
        bottom: box[3],
      });
      onSaved();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  if (!q.source_asset_id) return null;
  return (
    <details className="crop-editor">
      <summary>框选打印图像（原件不变）</summary>
      <p className="muted">
        自动分离后的示意图可在下方查看。需要调整时，拖动框选完整示意图及所有标注，避开答案和笔记；手动裁图始终取自原件。
      </p>
      <div className="crop-stage">
        <img
          src={apiUrl(`/assets/${q.source_asset_id}/download`)}
          alt="用于框选的原题图像"
          draggable={false}
          onPointerDown={(e) => {
            origin.current = location(e);
            setBox([...origin.current, ...origin.current]);
            setDragging(true);
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (dragging) {
              const p = location(e);
              setBox([
                Math.min(origin.current[0], p[0]),
                Math.min(origin.current[1], p[1]),
                Math.max(origin.current[0], p[0]),
                Math.max(origin.current[1], p[1]),
              ]);
            }
          }}
          onPointerUp={() => setDragging(false)}
        />
        <div
          className="crop-rectangle"
          style={{
            left: `${box[0] * 100}%`,
            top: `${box[1] * 100}%`,
            width: `${(box[2] - box[0]) * 100}%`,
            height: `${(box[3] - box[1]) * 100}%`,
          }}
        />
      </div>
      <div className="event-actions">
        <button
          className="button secondary"
          onClick={() => setBox([0, 0, 1, 1])}
        >
          选择整图
        </button>
        <button
          className="button primary"
          disabled={busy || box[2] <= box[0] || box[3] <= box[1]}
          onClick={save}
        >
          保存打印裁图
        </button>
      </div>
      <Notice error={error} />
    </details>
  );
}

function QuestionEditor({
  q,
  nodes,
  onSaved,
}: {
  q: Question;
  nodes: Node[];
  onSaved: () => void;
}) {
  const [stem, setStem] = useState(q.content.stem || ""),
    [options, setOptions] = useState((q.content.options || []).join("\n")),
    [diagram, setDiagram] = useState(!!q.content.has_diagram),
    [topic, setTopic] = useState(q.topic_id || ""),
    [knowledge, setKnowledge] = useState<string[]>(q.data.knowledge_ids || []),
    [minutes, setMinutes] = useState(q.minutes),
    [tags, setTags] = useState(q.tags.join("，")),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [subject, setSubject] = useState(q.subject);
  const [estimate, setEstimate] = useState<{minutes: number; reason: string} | null>(q.data.time_estimate || null), [estimating, setEstimating] = useState(false);
  async function estimateTime() {
    setEstimating(true); setError("");
    try { const result = await post<Question>(`/learning/questions/${q.id}/estimate`); setEstimate(result.data.time_estimate); }
    catch (e) { setError(message(e)); } finally { setEstimating(false); }
  }
  const types = nodes.filter(
      (n) =>
        n.kind === "type" &&
        n.subject === subject &&
        !nodes.some((c) => c.parent_id === n.id),
    ),
    points = nodes.filter(
      (n) => n.kind === "knowledge" && n.subject === subject,
    );
  async function save() {
    setBusy(true);
    setError("");
    try {
      await patch(`/learning/questions/${q.id}`, {
        subject,
        content: {
          stem,
          options: options.split("\n").filter(Boolean),
          has_diagram: diagram,
        },
        topic_id: topic || null,
        knowledge_ids: knowledge,
        minutes,
        tags: tags
          .split(/[,，]/)
          .map((s) => s.trim())
          .filter(Boolean),
      });
      onSaved();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="panel question-editor"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <h2>校对与归类</h2>
      <label>
        学科
        <select
          className="select"
          value={subject}
          onChange={(e) => {
            setSubject(e.target.value);
            setTopic("");
            setKnowledge([]);
          }}
        >
          {SUBJECTS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <label>
        题干
        <textarea
          className="textarea"
          rows={7}
          value={stem}
          onChange={(e) => setStem(e.target.value)}
        />
      </label>
      <label>
        选项（每行一项）
        <textarea
          className="textarea"
          rows={3}
          value={options}
          onChange={(e) => setOptions(e.target.value)}
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={diagram}
          onChange={(e) => setDiagram(e.target.checked)}
        />
        题目含图像，需要打印裁图
      </label>
      {STEM.includes(subject) && (
        <>
          <label>
            主题型（单个叶子节点）
            <select
              className="select"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            >
              <option value="">{q.status === "draft" ? "请选择题型（正式入库必填）" : "暂不归类"}</option>
              {types.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </select>
          </label>
          <div className="form-label">关联知识点（可多选）</div>
          <div className="check-grid">
            {points.map((n) => (
              <label className="check-label" key={n.id}>
                <input
                  type="checkbox"
                  checked={knowledge.includes(n.id)}
                  onChange={(e) =>
                    setKnowledge(
                      e.target.checked
                        ? [...knowledge, n.id]
                        : knowledge.filter((id) => id !== n.id),
                    )
                  }
                />
                {n.name}
              </label>
            ))}
            {!points.length && (
              <p className="muted">可以到知识库建立知识点，稍后关联。</p>
            )}
          </div>
        </>
      )}
      <label>
        题目标签（逗号分隔）
        <input
          className="input"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="重点题，难题，模板题"
        />
      </label>
      <label>
        预计做题时间（分钟）
        <input
          className="input"
          type="number"
          min="0.5"
          max="600"
          step="0.5"
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
        />
      </label>
      <div className="event-actions"><button type="button" className="button secondary" disabled={busy || estimating} onClick={estimateTime}>{estimating ? "正在预估…" : "AI预估用时（可选）"}</button>
      {estimate && <button type="button" className="button secondary" onClick={() => setMinutes(estimate.minutes)}>采用建议：{estimate.minutes}分钟</button>}</div>
      {estimate && <p className="muted">AI预估依据：{estimate.reason}。正式用时以上方输入值为准。</p>}
      <Notice error={error} />
      <button className="button primary" disabled={busy}>
        保存校对、题型与用时
      </button>
    </form>
  );
}

export default function QuestionPage({ onRefresh }: { onRefresh: () => void }) {
  const { id } = useParams(),
    [params, setParams] = useSearchParams();
  const {
      data: q,
      error,
      reload,
    } = useData<Question>(
      `/learning/questions/${id}${params.get("version") ? `?version=${params.get("version")}` : ""}`,
    ),
    { data: knowledge } = useData<{ items: Node[] }>("/learning/knowledge");
  const [feedback, setFeedback] = useState(""),
    [busy, setBusy] = useState(false),
    [editing, setEditing] = useState(false);
  useEffect(() => {
    if (q && !editing && ["queued", "running"].includes(q.data.recognition)) {
      const timer = setInterval(reload, 2500);
      return () => clearInterval(timer);
    }
  }, [q?.data.recognition, editing, reload]);
  async function run(task: () => Promise<unknown>) {
    setBusy(true);
    setFeedback("");
    try {
      await task();
      await reload();
      onRefresh();
    } catch (e) {
      setFeedback(message(e));
    } finally {
      setBusy(false);
    }
  }
  if (!q)
    return (
      <div className="page">
        <Header title="题目" />
        <Notice error={error} />
        <p>正在读取题目…</p>
      </div>
    );
  return (
    <div className="page learning-page">
      <Link className="back-button" to="/knowledge">
        ← 返回知识库
      </Link>
      <Header
        title={`${q.subject} · ${q.question_type}`}
        detail={`${q.ever_wrong ? (q.mastered ? "已过手的历史错题" : "尚未过手的错题") : "普通题"} · ${q.source_asset_id ? "原件与历史版本均已保存" : "文字稿与历史版本均已保存"}`}
      >
        <button
          className="button secondary"
          disabled={
            busy ||
            q.historical ||
            ["queued", "running"].includes(q.data.recognition)
          }
          onClick={() => setEditing(!editing)}
        >
          {editing ? "关闭编辑" : "校对与归类"}
        </button>
        {STEM.includes(q.subject) && q.status !== "draft" && (
          <button
            className="button secondary"
            disabled={busy || q.historical}
            onClick={() => run(() => post(`/learning/questions/${q.id}/error`))}
          >
            记录为当日错题
          </button>
        )}
        <button
          className="button primary"
          disabled={busy}
          onClick={() =>
            run(() => post(`/learning/questions/${q.id}/analysis`))
          }
        >
          {busy ? "处理中…" : "请求AI解析（可选）"}
        </button>
        {q.status === "draft" && <button className="button primary" disabled={busy || q.historical || ["queued", "running"].includes(q.data.recognition)} onClick={() => run(() => post(`/learning/questions/${q.id}/archive`))}>完成并正式入库</button>}
      </Header>
      {q.status === "draft" && <Notice>当前为待完成草稿，不在知识库或组卷中显示。补充答案、选择题型并保存后，点击“完成并正式入库”。AI来源还需要确认答案和解析。</Notice>}
      <Notice error={error || feedback} />
      {q.content.subject && SUBJECTS.includes(q.content.subject) && q.content.subject !== q.subject && (
        <Notice>
          AI识别学科为{q.content.subject}，当前选择的是{q.subject}。请在“校对与归类”中核对学科后选择对应题型。
        </Notice>
      )}
      {q.data.recognition && (
        <Notice>
          {
            {
              queued: "图片等待识别",
              running: "正在识别文字并分离示意图，草稿已保存",
              completed: "文字识别已完成，请核对公式与图形",
              failed: "自动识别失败，原件已经保存",
              manual: q.source_asset_id
                ? "原件已保存，可手动填写文字"
                : "文字稿已保存",
              review: "识别结果作为草稿保留",
            }[q.data.recognition as string]
          }
          {q.data.recognition_note && ` · ${q.data.recognition_note}`}
          {q.source_asset_id &&
            !["queued", "running"].includes(q.data.recognition) && (
              <button
                className="link-button"
                disabled={busy}
                onClick={() =>
                  run(() => post(`/learning/questions/${q.id}/recognize`))
                }
              >
                重新识别
              </button>
            )}
        </Notice>
      )}
      <div className="toolbar">
        <label>
          查看题目版本
          <select
            className="select"
            value={q.version_id || ""}
            onChange={(e) => {
              setEditing(false);
              setParams({ version: e.target.value });
            }}
          >
            {q.versions?.map((v) => (
              <option value={v.id} key={v.id}>
                版本{v.number} ·{" "}
                {v.source === "user" ? "用户或整理稿" : v.source}
              </option>
            ))}
          </select>
        </label>
        {q.historical && (
          <Notice>
            正在查看打印卷对应的历史题干。返回当前版本后可以编辑。
          </Notice>
        )}
      </div>
      <div className="question-core-grid">
        <div>
          <section className="panel">
            <h2>原题文字</h2>
            <MathText
              text={q.content.stem || "文字尚未整理，请核对原图后补充。"}
            />
            {q.content.options?.map((s, i) => (
              <MathText key={i} text={s} />
            ))}
            <div className="meta-chips">
              <span className="meta-chip">预计 {q.minutes} 分钟</span>
              {q.tags.map((t) => (
                <span className="meta-chip" key={t}>
                  {t}
                </span>
              ))}
            </div>
            {q.data.suggested_type && (
              <p className="muted">
                AI建议题型：{q.data.suggested_type}（尚未自动归类）
              </p>
            )}
            {q.content.has_diagram && !q.data.crop_asset_id && (
              <Notice>
                此题含图像。请框选打印裁图后参与推送，确保标注完整并避开笔记。
              </Notice>
            )}
            <h3>标准答案 · {q.answer_confirmed ? "用户已确认" : "尚未确认"}</h3>
            <MathText
              text={q.answer || "可以填写标准答案；AI解析给出的答案仅作草稿。"}
            />
          </section>
          {!q.historical && <AnswerEditor q={q} onSaved={() => {reload(); onRefresh();}} />}
          {(editing || q.status === "draft") && !q.historical && !["queued", "running"].includes(q.data.recognition) && (
            <QuestionEditor
              key={`${q.id}:${q.version_id}`}
              q={q}
              nodes={knowledge?.items || []}
              onSaved={() => {
                setEditing(false);
                setParams({});
                reload();
                onRefresh();
              }}
            />
          )}
          {q.data.analysis && (
            <section className="panel">
              <h2>主动请求的AI解析</h2>
              <MathText text={q.data.analysis.explanation} />
              <h3>答案建议（未作为标准答案确认）</h3>
              <MathText text={q.data.analysis.answer_draft} />
              {q.data.analysis.concerns?.length > 0 && (
                <Notice>{q.data.analysis.concerns.join("；")}</Notice>
              )}
              {q.data.analysis.answer_draft && (
                <button
                  className="button secondary"
                  disabled={busy || q.historical}
                  onClick={() =>
                    run(() =>
                      post(`/learning/questions/${q.id}/answer/use-ai`),
                    )
                  }
                >
                  将答案和解析填入待确认内容
                </button>
              )}
            </section>
          )}
          {q.data.recognition_draft && (
            <details className="panel">
              <summary>未覆盖的AI识别草稿</summary>
              <MathText text={q.data.recognition_draft.stem} />
            </details>
          )}
          {(q.occurrences?.length || 0) > 0 && (
            <section className="panel">
              <h2>错题记录与重做目标</h2>
              {q.occurrences?.map((o) => (
                <p key={o.id}>
                  {o.day_label} · 目标 {o.target} ·{" "}
                  {statusLabel[o.status] || o.status}
                </p>
              ))}
            </section>
          )}
        </div>
        <aside>
          {q.data.processed_asset_id && <section className="panel"><h2>清理与增强稿</h2><SourceImage id={q.data.processed_asset_id} alt="清理笔记并增强后的题目" /><p className="muted">整理稿为副本，下方保留原始照片供核对。</p></section>}
          <section className="panel">
            <h2>原始照片</h2>
            <SourceImage id={q.source_asset_id} />
            {q.source_sha256 && (
              <small className="hash-note">原件校验：{q.source_sha256}</small>
            )}
            {!q.source_asset_id && (
              <p className="muted">这道题通过文字录入。</p>
            )}
            {q.source_asset_id && !q.historical && (
              <CropEditor
                q={q}
                onSaved={() => {
                  reload();
                  onRefresh();
                }}
              />
            )}
          </section>
          {q.data.crop_asset_id && (
            <section className="panel">
              <h2>打印裁图</h2>
              <SourceImage id={q.data.crop_asset_id} alt="打印裁图" />
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
