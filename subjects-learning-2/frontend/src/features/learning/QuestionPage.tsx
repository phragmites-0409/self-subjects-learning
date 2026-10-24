import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Question, Node, STEM, SUBJECTS, statusLabel } from "./types";
import AnswerEditor from "./AnswerEditor";
import { TagSelector } from "./KnowledgeControls";
import "./knowledge.css";
import ImageEditor from "./ImageEditor";
import NoteFilter from "./NoteFilter";
import { apiUrl } from "../../api/client";
import { IntakeContext, capturePath, contextFromParams, returnPath } from "./intakeFlow";
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
    [tags, setTags] = useState<string[]>(q.tags),
    [tagOptions, setTagOptions] = useState<string[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [subject, setSubject] = useState(["pending", "unknown"].includes(q.data.subject_source) ? "" : q.subject);
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
        version_id:q.version_id,
        subject,
        content: {
          stem,
          options: options.split("\n").filter(Boolean),
          has_diagram: diagram,
        },
        topic_id: topic || null,
        knowledge_ids: knowledge,
        minutes,
        tags, tag_options: tagOptions,
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
      <h2>2 · 文字校对</h2>
      <label>
        学科（自动识别后可修改）
        <select
          className="select"
          value={subject}
          onChange={(e) => {
            setSubject(e.target.value);
            setTopic("");
            setKnowledge([]);
          }}
        >
          <option value="">尚未识别明确，请选择学科</option>
          {SUBJECTS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <p className="muted">{q.data.subject_source === "auto" ? `自动识别为${q.subject}，可在上方更正。` : q.data.subject_source === "unknown" || q.data.subject_source === "pending" ? "学科尚未识别明确，请选择后保存。" : "已选学科可修改，请核对对应题型。"}</p>
      <label>
        题干
        <textarea
          className="textarea"
          rows={7}
          value={stem}
          onChange={(e) => setStem(e.target.value)}
        />
      </label>
      {!!q.content.inline_images?.length && <p className="muted">[[图块:编号]] 对应原题位置的公式或题图，下方预览会显示图像。可移动占位符，或替换为已校对文字、LaTeX；图块可在第4步单独裁切和清理。</p>}
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
      {q.topic_issue && <p className="kb-inline-issue">有问题：当前题目挂在非叶题型上，可先编辑，归属稍后调整。</p>}
      <details className="classification-fields">
      <summary>归类、标签与用时{q.status === "draft" ? "（入库前请选择题型）" : ""}</summary>
      {q.data.suggested_type && <p className="muted">识别建议题型：{q.data.suggested_type}（请自行选择对应题型）</p>}
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
              {q.topic_issue && topic === q.topic_id && q.subject === subject && <option value={q.topic_id || ""}>{q.question_type}（归属有问题，可暂时保留）</option>}
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
      <TagSelector kind="question" value={tags} onChange={setTags} options={tagOptions} onOptions={setTagOptions} />
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
      </details>
      <Notice error={error} />
      <button className="button primary" disabled={busy || !subject}>
        保存校对、题型与用时
      </button>
    </form>
  );
}

export default function QuestionPage({ onRefresh }: { onRefresh: () => void }) {
  const navigate = useNavigate();
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
    [busy, setBusy] = useState(false), [originalPage,setOriginalPage]=useState(0);
  useEffect(()=>{setOriginalPage(0);},[id]);
  useEffect(() => {
    if (q && ["queued", "running"].includes(q.data.recognition)) {
      const timer = setInterval(reload, 2500);
      return () => clearInterval(timer);
    }
  }, [q?.data.recognition, reload]);
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
  function changeVersion(version?: string) {
    const next = new URLSearchParams(params);
    if (version) next.set("version", version); else next.delete("version");
    setParams(next);
  }
  if (!q)
    return (
      <div className="page">
        <Header title="题目" />
        <Notice error={error} />
        <p>正在读取题目…</p>
      </div>
    );
  const previewCrop = !q.historical || q.data.image_geometry_version_id === q.version_id ? q.data.crop_asset_id : undefined;
  const inlineImages = q.historical ? q.content.inline_images || [] : q.data.inline_images || q.content.inline_images || [];
  const sourcePages: {asset_id:string;filename:string;sha256:string}[] = q.data.source_pages || [];
  const original = sourcePages[originalPage] || sourcePages[0];
  const origin: IntakeContext | undefined = params.has("from") ? contextFromParams(params) : q.data.intake_context;
  const backLabel = origin?.from === "plan" ? "今日安排" : origin?.from === "capture" ? "拍题录入" : "知识库";
  const backPath = origin ? returnPath(origin) : `/knowledge?subject=${encodeURIComponent(q.subject)}`;
  const dailyFinish = origin?.from === "plan" && q.data.intake_context?.from === "plan" && q.data.pending_error && STEM.includes(q.subject) && !q.data.daily_intake_completed && !["pending", "unknown"].includes(q.data.subject_source);
  async function finish(next: boolean, daily = false) {
    if (!q || busy) return;
    setBusy(true); setFeedback("");
    try {
      await post(`/learning/questions/${q.id}/archive`, {finish_daily:daily});
      onRefresh();
      const continued: IntakeContext = {...(origin || {from:"capture"}), subject:q.subject};
      if (origin?.subject !== q.subject) continued.node_id = undefined;
      navigate(next ? capturePath(continued) : backPath);
    } catch (e) {
      const text = message(e); setFeedback(text);
      if (text.includes("题型") || text.includes("学科")) {
        const details = document.querySelector<HTMLDetailsElement>(".classification-fields");
        if (details) details.open=true;
        document.getElementById("question-proofread")?.scrollIntoView({behavior:"smooth"});
      }
    } finally {setBusy(false);}
  }
  return (
    <div className="page learning-page">
      <Link className="back-button" to={backPath}>
        ← 返回{backLabel}
      </Link>
      <Header
        title={`${["pending", "unknown"].includes(q.data.subject_source) ? "学科待识别／选择" : q.subject} · ${q.question_type}`}
        detail={`${q.awaiting_correction ? "待改错 · 尚未开始重推计时" : q.ever_wrong ? (q.mastered ? "已过手的历史错题" : "尚未过手的错题") : "普通题"} · ${q.source_asset_id ? "原件与历史版本均已保存" : "文字稿与历史版本均已保存"}`}
      >
        <button
          className="button secondary"
          disabled={
            busy ||
            q.historical ||
            ["queued", "running"].includes(q.data.recognition)
          }
          onClick={() => document.getElementById("question-proofread")?.scrollIntoView({ behavior: "smooth" })}
        >
          文字校对
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
        {q.awaiting_correction && !q.historical && <button className="button primary" disabled={busy} onClick={() => run(() => post(`/learning/questions/${q.id}/correct`))}>改错</button>}
        <button
          className="button primary"
          disabled={busy || q.historical}
          onClick={() =>
            run(() => post(`/learning/questions/${q.id}/analysis`))
          }
        >
          {busy ? "处理中…" : "请求AI解析（可选）"}
        </button>
      </Header>
      {q.status === "draft" && <Notice>补充答案、选择题型并保存后，在完整预览下方完成入库。AI来源需要确认答案和解析。</Notice>}
      {origin?.subject && origin.subject !== q.subject && q.data.subject_source === "auto" && <Notice>入口为{origin.subject}，实际识别为{q.subject}，请核对学科。每日上传会按保存的学科和错题日期确认。</Notice>}
      <Notice error={error || feedback} />
      {q.content.subject && SUBJECTS.includes(q.content.subject) && q.content.subject !== q.subject && (
        <Notice>
          识别建议学科为{q.content.subject}，当前选择的是{q.subject}。请在“文字校对”中核对学科后选择对应题型。
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
          {q.data.recognition_note && <details><summary>识别与处理提示</summary><p>{q.data.recognition_note}</p>{q.data.recognition_info?.engine === "local" && <p>本地处理 {q.data.recognition_info.seconds} 秒</p>}</details>}
          {!!q.content.formula_audit?.length&&<details><summary>自动公式复核记录 · {q.content.formula_audit.filter(item=>item.accepted).length}/{q.content.formula_audit.length} 块通过</summary><p>这是自动识别时的记录。后续手工校对以上方保存的内容为准。未通过的部分初始保留原位小图，可改为已校对文字。置信度不等于准确率。</p>{q.content.formula_audit.filter(item=>!item.accepted).map((item,i)=><p key={i}>第{item.page||1}张 · {item.source}：{item.reason}</p>)}</details>}
        </Notice>
      )}
      <details className="question-version-history"><summary>查看历史题目版本</summary><div className="toolbar">
        <label>
          查看题目版本
          <select
            className="select"
            value={q.version_id || ""}
            onChange={(e) => {
              changeVersion(e.target.value);
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
      </div></details>
      <div className="question-workflow-grid">
          <section className="panel workflow-step" data-step="1">
            <h2>1 · 原图</h2>
            {sourcePages.length>1 && <label>同题原图（按录入顺序）<select className="select" value={originalPage} onChange={e=>setOriginalPage(Number(e.target.value))}>{sourcePages.map((page,index)=><option value={index} key={index}>第{index+1}张 · {page.filename}</option>)}</select></label>}
            <SourceImage id={original?.asset_id || q.source_asset_id} alt="原始照片" />
            {!q.source_asset_id && <p className="muted">这道题通过文字录入，无原图。</p>}
            {q.source_sha256 && <details><summary>原件校验信息</summary><small className="hash-note">{original?.sha256 || q.source_sha256}</small></details>}
            <NoteFilter q={q} pageIndex={originalPage} onSaved={()=>{reload();onRefresh();}} />
          </section>
          <div id="question-proofread" className="workflow-step" data-step="2">
          {!q.historical && !["queued", "running"].includes(q.data.recognition) ? (
            <QuestionEditor
              key={`${q.id}:${q.version_id}:${q.subject}:${q.data.subject_source}`}
              q={q}
              nodes={knowledge?.items || []}
              onSaved={() => {
                changeVersion();
                reload();
                onRefresh();
              }}
            />
          ) : <section className="panel"><h2>2 · 文字校对</h2>{q.historical ? <><MathText text={q.content.stem || "未保存题干文字"} images={q.content.inline_images} />{q.content.options?.map((text, i) => <MathText key={i} text={text} images={q.content.inline_images} />)}<p className="muted">历史版本只读，返回当前版本后可校对。</p></> : <p className="muted">正在识别原图，完成后可校对文字与学科。</p>}</section>}
          {q.data.recognition_draft && (
            <details className="panel">
              <summary>未覆盖的自动识别草稿</summary>
              {q.data.recognition_draft.subject && <p className="muted">建议学科：{q.data.recognition_draft.subject}；现有学科保留，可在上方修改。</p>}
              <MathText text={q.data.recognition_draft.stem} images={q.data.recognition_draft.inline_images} />
              {q.data.recognition_draft.options?.map((text: string, i: number) => <MathText key={i} text={text} images={q.data.recognition_draft.inline_images} />)}
              {!!q.data.recognition_draft.diagram_regions?.length && <details><summary>核对保留的公式、表格和题图区域（{q.data.recognition_draft.diagram_regions.length}块）</summary><div className="crop-stage note-filter-stage"><img src={apiUrl(`/assets/${q.data.recognition_draft_source || q.source_asset_id}/download`)} alt="识别草稿保留图块范围" />{q.data.recognition_draft.diagram_regions.map((region: {box:number[]},i:number)=><div key={i} className="note-exclusion" style={{left:`${region.box[0]*100}%`,top:`${region.box[1]*100}%`,width:`${(region.box[2]-region.box[0])*100}%`,height:`${(region.box[3]-region.box[1])*100}%`}}>{i+1}</div>)}</div></details>}
              <p className="muted">核对题干、全部选项与裁图后采用。采用会保存题目新版本并更新自动裁图，人工答案和解析保留。</p>
              <button className="button secondary" disabled={busy || q.historical || ["queued", "running"].includes(q.data.recognition)} onClick={() => run(() => post(`/learning/questions/${q.id}/recognition/use-draft`))}>采用已核对的文字与裁图草稿</button>
            </details>
          )}
          </div>
          <div className="workflow-step" data-step="3">
          {!q.historical ? <AnswerEditor q={q} onSaved={() => {reload(); onRefresh();}} /> : <section className="panel"><h2>3 · 录入答案</h2><p className="muted">历史版本只读，返回当前版本后可录入答案。</p></section>}
          {q.data.analysis && (
            <details className="panel">
              <summary>主动请求的AI解析</summary>
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
            </details>
          )}
          </div>
          <section className="panel workflow-step" data-step="4">
            <h2>4 · 图片处理框选</h2>
            {sourcePages.length>1&&<p className="muted">{sourcePages.length}张照片已按顺序拼接成处理稿，跨页图块可在同一画布中框选；各张原图在第一步切换查看。</p>}
            {q.source_asset_id && !q.historical && (
              <ImageEditor
                q={q}
                onSaved={() => {
                  reload();
                  onRefresh();
                }}
              />
            )}
            {(!q.source_asset_id || q.historical) && <p className="muted">{q.historical ? "历史版本只读，返回当前版本后可处理图片。" : "纯文字题目可跳过此步。"}</p>}
          </section>
          <section className="panel workflow-step question-complete-preview" data-step="5">
              <h2>5 · 完整预览</h2>
              <p className="muted">显示已保存的文字、打印题图与答案；校对或修图后请保存，再检查预览。</p>
              <MathText text={q.content.stem || "题干文字尚未整理"} images={inlineImages} />
              {!!inlineImages.length && q.data.image_review_required && <Notice>原位公式和题图待核对；请检查系数、上下标、曲线与笔迹残留，在第4步确认。</Notice>}
              {q.content.options?.filter(text => !(previewCrop && q.data.print_options_embedded && /^\s*\[?[A-H]\]?\s*$/.test(text))).map((text, i) => <MathText key={i} text={text} images={inlineImages} />)}
              {inlineImages.length ? null : previewCrop ? <>
              <h3>打印裁图</h3>{q.data.image_review_required && <Notice>此打印图需核对曲线、标注、选项编号及笔迹残留。确认前不参与新组卷；在图片处理框选中确认。</Notice>}
              <SourceImage id={previewCrop} alt="打印裁图" />
              </> : q.historical ? <Notice>当前裁图未与此历史题干版本绑定，请以对应打印卷为准。</Notice> : q.content.has_diagram && <Notice>此题含图像，请在图片处理框选中保存打印裁图。</Notice>}
              <div className="meta-chips"><span className="meta-chip">{["pending", "unknown"].includes(q.data.subject_source) ? "学科待选择" : q.subject} · {q.question_type} · 预计 {q.minutes} 分钟</span>{q.tags.map(tag => <span className="meta-chip" key={tag}>{tag}</span>)}</div>
              <details className="preview-answer"><summary>{q.historical ? "查看当前保存的答案与解析（历史题干仅供参照）" : "查看已保存答案与解析"} · {q.answer_confirmed ? "已确认" : "尚未确认"}</summary><MathText text={q.answer || "尚未保存文字答案"} /><MathText text={q.data.answer_explanation || ""} />{q.data.answer_asset_ids?.map((aid: string) => <SourceImage key={aid} id={aid} alt="答案照片" />)}</details>
          </section>
      </div>
      {!q.historical && <section className="panel intake-finish"><div><strong>{q.status === "draft" ? "检查预览后完成录入" : "题目已入库"}</strong><p className="muted">{dailyFinish ? `本次明确确认${q.data.intake_day}的${q.subject}上传完成，其他学科仍分别处理。` : "可以继续录入下一题，或返回来源页面。"}</p></div><div className="event-actions">
        {dailyFinish && <button className="button primary" disabled={busy || ["queued", "running"].includes(q.data.recognition)} onClick={() => finish(false,true)}>{q.status === "draft" ? `入库并完成${q.subject}上传` : `完成${q.subject}上传并返回`}</button>}
        {q.status === "draft" ? <><button className={`button ${dailyFinish ? "secondary" : "primary"}`} disabled={busy || ["queued", "running"].includes(q.data.recognition)} onClick={() => finish(false)}>入库并返回{backLabel}</button><button className="button secondary" disabled={busy || ["queued", "running"].includes(q.data.recognition)} onClick={() => finish(true)}>入库并继续录入</button></> : <><Link className="button secondary" to={capturePath({...origin || {from:"capture"},subject:q.subject})}>继续录入</Link><Link className="button secondary" to={backPath}>返回{backLabel}</Link></>}
      </div><Notice error={feedback} /></section>}
      {(q.occurrences?.length || 0) > 0 && <details className="panel"><summary>错题记录与重做目标</summary>{q.occurrences?.map(o => <p key={o.id}>{o.day_label} · {o.target ? `目标 ${o.target}` : "改错后开始计时"} · {statusLabel[o.status] || o.status}</p>)}</details>}
    </div>
  );
}
