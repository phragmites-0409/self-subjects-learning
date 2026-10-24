import { useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ImagePlus, LoaderCircle } from "lucide-react";
import { Header, Notice, message, useData } from "./shared";
import { SUBJECTS, STEM, localDay, Question } from "./types";
import CaptureEntry from "./CaptureEntry";
import { contextFromParams, createIntake, returnPath, uploadQuestion } from "./intakeFlow";
import QuestionPhotos, {photoKey} from "./QuestionPhotos";

export default function CapturePage({ onCreated }: { onCreated: () => void }) {
  const { data: drafts } = useData<{items: Question[]}>("/learning/questions?filter=draft");
  const [params] = useSearchParams(),
    navigate = useNavigate();
  const context = contextFromParams(params), more = useRef<HTMLDetailsElement>(null);
  const [subject, setSubject] = useState(""),
    [files, setFiles] = useState<File[]>([]),
    [text, setText] = useState(""),
    [isError, setIsError] = useState(true),
    [day, setDay] = useState(context.day || localDay()),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [staged, setStaged] = useState<{
    name: string;
    question_id: string;
  } | null>(null);
  async function submit() {
    setBusy(true);
    setError("");
    try {
      let qid =
        staged?.name === photoKey(files)
          ? staged.question_id
          : undefined;
      if (files.length && !qid) {
        qid = await uploadQuestion(files, text);
        setStaged({
          name: photoKey(files),
          question_id: qid,
        });
      }
      const result = await createIntake(context, {
        question_id: qid,
        subject,
        text,
        is_error: (!subject || STEM.includes(subject)) && isError,
        day,
      });
      onCreated();
      navigate(`/questions/${result.id}`);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page learning-page">
      <Header
        title="拍题录入"
        detail="原图 → 文字校对 → 录入答案 → 图片处理框选 → 完整预览。学科自动识别，可随时更正。"
      ><Link to="/answer-bank" className="button secondary">管理整页答案库</Link></Header>
      <Notice error={error} />
      {context.from !== "capture" && <Link className="back-button" to={returnPath(context)}>← 返回{context.from === "plan" ? "今日安排" : "知识库"}</Link>}
      <section className="panel capture-start">
        <h2>选图后直接进入校对</h2>
        <p className="muted">{context.subject ? `当前从${context.subject}${context.from === "plan" ? "今日安排" : "知识库"}进入，` : ""}学科仍自动识别。题型、答案和裁图在下一页完成。</p>
        <CaptureEntry context={context} onCreated={onCreated} onMore={() => { if (more.current) {more.current.open=true;more.current.scrollIntoView({behavior:"smooth"});} }} />
      </section>
      <details ref={more} className="panel capture-more">
        <summary>文字录入与更多设置</summary>
          <label>
            学科（默认自动识别）
            <select
              className="select"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              <option value="">自动识别，之后可修改</option>
              {SUBJECTS.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="file-zone">
            <ImagePlus size={28} />
            <strong>{files.length ? `已选${files.length}张同题照片` : "选择题目照片（可多选）"}</strong>
            <span>JPG、PNG、WebP，每张最多10 MB，同题最多8张；可继续添加，也可以只填文字。</span>
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              disabled={busy}
              onChange={(e) => {
                const next=[...files,...Array.from(e.target.files||[])];
                if(next.length>8){setError("同一道题最多8张照片");return;}setFiles(next);setError("");e.target.value="";
                setStaged(null);
              }}
            />
          </label>
          <QuestionPhotos files={files} onChange={setFiles} busy={busy} />
          <label>
            题目文字或识别提示（可不填）
            <textarea
              className="textarea"
              rows={7}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="可粘贴题目文字，公式可使用 $...$ 或 \\( ... \\)。"
            />
          </label>
          {(!subject || STEM.includes(subject)) && (
            <>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={isError}
                  onChange={(e) => setIsError(e.target.checked)}
                />
                这是需要记录的错题（适用于数学、物理、化学、生物）
              </label>
              {isError && (
                <label>
                  错题日期
                  <input
                    className="input"
                    type="date"
                    value={day}
                    max={localDay()}
                    onChange={(e) => setDay(e.target.value)}
                  />
                </label>
              )}
            </>
          )}
          <button
            className="button primary"
            disabled={busy || (!files.length && !text.trim())}
            onClick={submit}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <ImagePlus size={16} />
            )}
            保存草稿并继续
          </button>
      </details>
        <details className="panel">
          <summary>录入说明与识别设置</summary>
          <p>
            原始照片按原字节保存。旋转显示、缩略图和裁切都是派生版本，原件可随时打开核对。
          </p>
          <p>
            默认在本机提取文字和图形区域、清理红色笔迹并增强图像，无需调用收费图片识别API。黑色笔迹覆盖印刷内容时保留，请核对公式、图形及选项编号，也可以手动调整裁图。
          </p>
          <p>
            手动输入／拍照、答案库提取、AI作答三种答案来源任选。人工提供的内容视为已确认；AI须给出答案与解析，并由你确认。选择题型后才可正式入库，草稿不参与重做或组卷。
          </p>
          <Link to="/settings" className="button secondary">
            设置图片识别与笔迹处理
          </Link>
        </details>
      {(drafts?.items.length || 0) > 0 && <section className="panel"><h2>继续未完成的录入</h2>{drafts?.items.map(q => <Link className="knowledge-question" key={q.id} to={`/questions/${q.id}`}><div><strong>{q.content.stem?.slice(0,100) || "图片草稿 · 待整理"}</strong><small>{["pending", "unknown"].includes(q.data.subject_source) ? "学科待识别／选择" : q.subject} · {q.question_type} · 待完成入库</small></div><span>继续 →</span></Link>)}</section>}
    </div>
  );
}
