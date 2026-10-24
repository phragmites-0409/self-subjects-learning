import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ImagePlus, LoaderCircle } from "lucide-react";
import { api } from "../../api/client";
import { Header, Notice, message, post, useData } from "./shared";
import { SUBJECTS, STEM, localDay, Question } from "./types";

export default function CapturePage({ onCreated }: { onCreated: () => void }) {
  const { data: drafts } = useData<{items: Question[]}>("/learning/questions?filter=draft");
  const [params] = useSearchParams(),
    navigate = useNavigate();
  const [subject, setSubject] = useState(params.get("subject") || "数学"),
    [file, setFile] = useState<File | null>(null),
    [text, setText] = useState(""),
    [isError, setIsError] = useState(true),
    [day, setDay] = useState(localDay()),
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
        staged?.name === `${file?.name}:${file?.lastModified}`
          ? staged.question_id
          : undefined;
      if (file && !qid) {
        const form = new FormData();
        form.append("file", file);
        form.append("text", text);
        const uploaded = await api<{ question_id: string }>("/assets", {
          method: "POST",
          body: form,
        });
        qid = uploaded.question_id;
        setStaged({
          name: `${file.name}:${file.lastModified}`,
          question_id: qid,
        });
      }
      const result = await post<Question>("/learning/intake", {
        question_id: qid,
        subject,
        text,
        is_error: STEM.includes(subject) && isError,
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
        detail="图片整理 → 补充答案解析 → 选择题型、设置标签与用时 → 正式入库。"
      ><Link to="/answer-bank" className="button secondary">管理整页答案库</Link></Header>
      <ol className="intake-steps"><li className="active">整理题目</li><li>补充答案解析</li><li>归类与用时</li><li>正式入库</li></ol>
      <Notice error={error} />
      <div className="content-grid">
        <section className="panel">
          <label>
            学科
            <select
              className="select"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              {SUBJECTS.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="file-zone">
            <ImagePlus size={28} />
            <strong>{file?.name || "选择题目照片"}</strong>
            <span>JPG、PNG、WebP，最多10 MB；也可以只填文字。</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              disabled={busy}
              onChange={(e) => {
                setFile(e.target.files?.[0] || null);
                setStaged(null);
              }}
            />
          </label>
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
          {STEM.includes(subject) && (
            <>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={isError}
                  onChange={(e) => setIsError(e.target.checked)}
                />
                这是需要记录的错题
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
            disabled={busy || (!file && !text.trim())}
            onClick={submit}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <ImagePlus size={16} />
            )}
            保存草稿并继续
          </button>
        </section>
        <section className="panel accent-panel">
          <h2>自动整理题面</h2>
          <p>
            原始照片按原字节保存。旋转显示、缩略图和裁切都是派生版本，原件可随时打开核对。
          </p>
          <p>
            自动分离题干与示意图，清理可独立辨认的手写笔记，并增强图像。示意图保留完整标注；被笔记遮挡且无法辨认的条件会提示核对，也可以手动调整裁图。
          </p>
          <p>
            手动输入／拍照、答案库提取、AI作答三种答案来源任选。人工提供的内容视为已确认；AI须给出答案与解析，并由你确认。选择题型后才可正式入库，草稿不参与重做或组卷。
          </p>
          <Link to="/settings" className="button secondary">
            设置AI识别
          </Link>
        </section>
      </div>
      {(drafts?.items.length || 0) > 0 && <section className="panel"><h2>继续未完成的录入</h2>{drafts?.items.map(q => <Link className="knowledge-question" key={q.id} to={`/questions/${q.id}`}><div><strong>{q.content.stem?.slice(0,100) || "图片草稿 · 待整理"}</strong><small>{q.subject} · {q.question_type} · 待完成入库</small></div><span>继续 →</span></Link>)}</section>}
    </div>
  );
}
