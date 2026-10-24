import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, BookOpen } from "lucide-react";
import {
  Header,
  Notice,
  Tabs,
  MathText,
  message,
  patch,
  post,
  useData,
} from "./shared";
import { Node, Question, SUBJECTS, STEM } from "./types";

function NodeEditor({ node, onSaved }: { node: Node; onSaved: () => void }) {
  const [name, setName] = useState(node.name),
    [summary, setSummary] = useState(node.summary || ""),
    [method, setMethod] = useState(node.data.method || ""),
    [notes, setNotes] = useState(node.data.notes || ""),
    [pain, setPain] = useState(node.data.pain_points || ""),
    [tags, setTags] = useState((node.data.tags || []).join("，")),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function save() {
    setBusy(true);
    setError("");
    try {
      await patch(`/learning/knowledge/${node.id}`, {
        name,
        summary,
        method,
        notes,
        pain_points: pain,
        tags: tags
          .split(/[,，]/)
          .map((s: string) => s.trim())
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
    <details className="node-editor">
      <summary>编辑名称、材料与个人记录</summary>
      <label>
        名称
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        {node.kind === "type" ? "题型说明" : "知识或记录正文"}
        <textarea
          className="textarea"
          rows={5}
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
        />
      </label>
      {node.kind === "type" && (
        <>
          <label>
            题型方法
            <textarea
              className="textarea"
              rows={5}
              value={method}
              onChange={(e) => setMethod(e.target.value)}
            />
          </label>
          <label>
            学习笔记
            <textarea
              className="textarea"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          <label>
            个人痛点
            <textarea
              className="textarea"
              value={pain}
              onChange={(e) => setPain(e.target.value)}
            />
          </label>
          <label>
            标签（逗号分隔）
            <input
              className="input"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              list="topic-tags"
            />
            <datalist id="topic-tags">
              <option value="校外" />
            </datalist>
            <small>校外标签不参与题型推送，其他标签按普通标签管理。</small>
          </label>
        </>
      )}
      <Notice error={error} />
      <button className="button primary" disabled={busy} onClick={save}>
        保存材料
      </button>
    </details>
  );
}

export default function KnowledgePage() {
  const {
    data: knowledge,
    error,
    reload,
  } = useData<{ items: Node[] }>("/learning/knowledge");
  const [subject, setSubject] = useState("数学"),
    [branch, setBranch] = useState("type"),
    [selected, setSelected] = useState(""),
    [filter, setFilter] = useState(""),
    [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [adding, setAdding] = useState(false),
    [name, setName] = useState(""),
    [parent, setParent] = useState(""),
    [feedback, setFeedback] = useState(""),
    [busy, setBusy] = useState(false);
  const {
    data: questions,
    error: qerror,
    reload: qreload,
  } = useData<{ items: Question[]; total: number }>(
    `/learning/questions?subject=${encodeURIComponent(subject)}&topic_id=${selected && branch === "type" ? selected : ""}&knowledge_id=${selected && branch === "knowledge" ? selected : ""}&q=${encodeURIComponent(search)}&filter=${filter}&offset=${offset}&limit=100`,
  );
  useEffect(() => {
    setSelected("");
    setOffset(0);
    setBranch(STEM.includes(subject) ? "type" : "record");
  }, [subject]);
  const nodes = (knowledge?.items || []).filter(
    (n) =>
      n.subject === subject &&
      (branch === "record"
        ? ["record", "composition_category"].includes(n.kind)
        : n.kind === branch),
  );
  const node = nodes.find((n) => n.id === selected);
  const byParent = (
    pid: string | null,
    depth = 0,
  ): { node: Node; depth: number }[] =>
    depth > 50
      ? []
      : nodes
          .filter((n) => n.parent_id === pid)
          .flatMap((n) => [{ node: n, depth }, ...byParent(n.id, depth + 1)]);
  async function add() {
    setBusy(true);
    setFeedback("");
    try {
      const n = await post<Node>("/learning/knowledge", {
        subject,
        kind: branch,
        name,
        parent_id: parent || null,
      });
      setSelected(n.id);
      setAdding(false);
      setName("");
      await reload();
    } catch (e) {
      setFeedback(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page learning-page">
      <Header
        title="知识库"
        detail="知识点与题型分别组织；错题、普通题和过手题在同一题库中查找。"
      >
        <Link className="button primary" to={`/capture?subject=${subject}`}>
          <Plus size={15} />
          录入题目
        </Link>
        <Link className="button secondary" to="/answer-bank">答案库</Link>
      </Header>
      <Notice error={error || qerror || feedback} />
      <Tabs values={SUBJECTS} value={subject} onChange={setSubject} />
      <div className="toolbar">
        {STEM.includes(subject) && (
          <Tabs
            values={["题型", "知识点"]}
            value={branch === "type" ? "题型" : "知识点"}
            onChange={(v) => {
              setBranch(v === "题型" ? "type" : "knowledge");
              setSelected("");
              setOffset(0);
            }}
          />
        )}
        <button
          className="button secondary"
          onClick={() => {
            setAdding(true);
            setParent(selected);
            setFeedback("");
          }}
        >
          <Plus size={15} />
          新建
          {branch === "type"
            ? "题型"
            : branch === "knowledge"
              ? "知识点"
              : "记录分类"}
        </button>
      </div>
      <div className="knowledge-layout">
        <aside className="panel tree-panel">
          <button
            className={`tree-node ${!selected ? "active" : ""}`}
            onClick={() => {
              setSelected("");
              setOffset(0);
            }}
          >
            <BookOpen size={15} />
            全部{subject}题目与分类
          </button>
          {byParent(null).map(({ node: n, depth }) => (
            <button
              key={n.id}
              className={`tree-node ${selected === n.id ? "active" : ""}`}
              style={{ paddingLeft: 12 + depth * 18 }}
              onClick={() => {
                setSelected(n.id);
                setOffset(0);
              }}
            >
              {n.name}
              {n.data.suspect && (
                <span className="dot-warning" title="可能有问题" />
              )}
            </button>
          ))}
          {!nodes.length && (
            <p className="muted">先建立题型；拍题草稿选择题型后才能正式入库。</p>
          )}
        </aside>
        <div className="knowledge-main">
          {node && (
            <section className="panel">
              <h2>{node.name}</h2>
              {node.kind === "type" && (
                <>
                  <div className="meta-chips">
                    <span className="meta-chip">
                      {node.active
                        ? `${node.cadence}天推送`
                        : "尚未启用或已停推"}
                    </span>
                    <span className="meta-chip">
                      历史错题过手 {node.mastery?.mastered}/
                      {node.mastery?.total}
                      {node.mastery?.ratio !== null &&
                        ` · ${node.mastery?.ratio}%`}
                    </span>
                    {node.target_label && (
                      <span className="meta-chip">
                        目标 {node.target_label}
                      </span>
                    )}
                    {node.data.suspect && (
                      <span className="meta-chip warning-chip">可能有问题</span>
                    )}
                    {(node.data.tags || []).map((t: string) => (
                      <span className="meta-chip" key={t}>
                        {t}
                      </span>
                    ))}
                  </div>
                  <p className="muted">
                    连续正确 {node.data.correct_streak || 0} 轮 · 连续错误{" "}
                    {node.data.wrong_streak || 0} 轮
                  </p>
                </>
              )}
              {node.summary && (
                <>
                  <h3>内容</h3>
                  <MathText text={node.summary} />
                </>
              )}
              {node.data.method && (
                <>
                  <h3>题型方法</h3>
                  <MathText text={node.data.method} />
                </>
              )}
              {node.data.notes && (
                <>
                  <h3>学习笔记</h3>
                  <MathText text={node.data.notes} />
                </>
              )}
              {node.data.pain_points && (
                <>
                  <h3>个人痛点</h3>
                  <MathText text={node.data.pain_points} />
                </>
              )}
              <NodeEditor
                key={node.id}
                node={node}
                onSaved={() => {
                  reload();
                  qreload();
                }}
              />
            </section>
          )}
          <section className="panel">
            <div className="panel-heading">
              <h2>{node?.kind === "type" ? "关联题目" : "本学科题目"}</h2>
              <span className="muted">共 {questions?.total || 0} 题</span>
            </div>
            <div className="toolbar wrap-toolbar">
              <input
                aria-label="搜索题目"
                className="input"
                placeholder="搜题干、标签或题型"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                }}
              />
              <select
                aria-label="题目状态"
                className="select"
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="">全部题目</option>
                <option value="unmastered">尚未过手的错题</option>
                <option value="mastered">已过手的历史错题</option>
                <option value="ordinary">普通题</option>
                <option value="unassigned">尚未归类</option>
              </select>
            </div>
            {(questions?.items || []).map((q) => (
              <Link
                key={q.id}
                className="knowledge-question"
                to={`/questions/${q.id}`}
              >
                <div>
                  <strong>
                    {q.content.stem?.slice(0, 100) || "原图题目 · 待校对文字"}
                  </strong>
                  <small>
                    {q.question_type} · {q.minutes}分钟 ·{" "}
                    {q.ever_wrong
                      ? q.mastered
                        ? "已过手"
                        : "尚未过手"
                      : "普通题"}
                    {q.tags.length > 0 && ` · ${q.tags.join("、")}`}
                  </small>
                </div>
                <span>查看 →</span>
              </Link>
            ))}
            {!questions?.items.length && (
              <div className="empty-state">这个范围还没有题目。</div>
            )}
            <div className="event-actions">
              <button
                className="button secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 100))}
              >
                上一页
              </button>
              <button
                className="button secondary"
                disabled={offset + 100 >= (questions?.total || 0)}
                onClick={() => setOffset(offset + 100)}
              >
                下一页
              </button>
            </div>
          </section>
        </div>
      </div>
      {adding && (
        <div className="modal-backdrop">
          <form
            className="modal panel"
            onSubmit={(e) => {
              e.preventDefault();
              add();
            }}
          >
            <h2>
              新建
              {branch === "type"
                ? "题型"
                : branch === "knowledge"
                  ? "知识点"
                  : "记录分类"}
            </h2>
            <label>
              名称
              <input
                className="input"
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              上级分类
              <select
                className="select"
                value={parent}
                onChange={(e) => setParent(e.target.value)}
              >
                <option value="">根分类</option>
                {nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name}
                  </option>
                ))}
              </select>
            </label>
            <Notice error={feedback} />
            <div className="event-actions">
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={() => setAdding(false)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                保存
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
