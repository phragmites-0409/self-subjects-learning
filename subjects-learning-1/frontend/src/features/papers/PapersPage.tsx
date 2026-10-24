import { useMemo, useState } from 'react'
import { Download, FileStack, LoaderCircle, Plus } from 'lucide-react'
import { api, apiUrl } from '../../api/client'
import {
  PAPER_STATUS_LABELS,
  Paper,
  PaperCreateInput,
  Question,
  SUBJECTS,
  Subject,
} from '../../api/types'

type PapersPageProps = {
  questions: Question[]
  papers: Paper[]
  onRefresh: () => void
}

export default function PapersPage({ questions, papers, onRefresh }: PapersPageProps) {
  const [selected, setSelected] = useState<string[]>([])
  const [title, setTitle] = useState('高中专项练习')
  const [subject, setSubject] = useState<Subject>(SUBJECTS[0])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const available = useMemo(
    () => questions.filter(question => question.status === 'approved' && question.subject === subject),
    [questions, subject],
  )

  const changeSubject = (nextSubject: Subject) => {
    setSubject(nextSubject)
    setSelected([])
    setMessage('')
  }

  const toggle = (id: string) => {
    setSelected(previous => previous.includes(id)
      ? previous.filter(item => item !== id)
      : [...previous, id])
  }

  const create = async () => {
    if (!selected.length) {
      setMessage('请至少选择一道已确认题目。')
      return
    }

    const payload: PaperCreateInput = {
      title,
      subject,
      grade: '高中',
      items: selected.map(question_id => ({ question_id, points: 5 })),
    }

    setBusy(true)
    try {
      const paper = await api<Paper>('/papers', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      const exported = await api<{ download_url: string }>(`/papers/${paper.id}/export?include_answers=false`, {
        method: 'POST',
      })
      window.open(apiUrl(exported.download_url.replace('/api/v1', '')), '_blank')
      setMessage('试卷已生成并保存到组卷库。')
      setSelected([])
      onRefresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '生成失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="subpage-header">
        <div>
          <p className="eyebrow">PAPER LIBRARY</p>
          <h1>组卷库</h1>
          <p className="muted">从已确认题目中挑选，生成可以直接使用的练习卷。</p>
        </div>
      </div>
      <div className="paper-builder">
        <section className="detail-panel">
          <div className="panel-label"><Plus size={15} />新建试卷</div>
          <label className="field-label">
            试卷名称
            <input className="input" value={title} onChange={event => setTitle(event.target.value)} />
          </label>
          <label className="field-label">
            试卷学科
            <select
              className="select"
              value={subject}
              onChange={event => changeSubject(event.target.value as Subject)}
            >
              {SUBJECTS.map(item => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <h3>可用题目（{available.length}）</h3>
          <div className="select-question-list">
            {available.map(question => (
              <label className={`select-question ${selected.includes(question.id) ? 'selected' : ''}`} key={question.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(question.id)}
                  onChange={() => toggle(question.id)}
                />
                <div>
                  <strong>{question.question_type}</strong>
                  <span>{question.subject} · {question.methods?.slice(0, 2).join(' / ') || '待分类'}</span>
                </div>
              </label>
            ))}
            {!available.length && (
              <div className="empty-state"><FileStack size={20} /><span>先确认几道本学科题目，才能开始组卷。</span></div>
            )}
          </div>
          <button className="button primary full-button" onClick={create} disabled={busy}>
            {busy ? <LoaderCircle className="spin" size={16} /> : <Download size={16} />}
            生成学生版 PDF（{selected.length} 题）
          </button>
          {message && <div className="result-message success">{message}</div>}
        </section>
        <section className="detail-panel paper-history">
          <div className="panel-label"><FileStack size={15} />历史试卷</div>
          {papers.map(paper => (
            <div className="history-row" key={paper.id}>
              <div>
                <strong>{paper.title}</strong>
                <span>{paper.items.length} 道题 · {paper.total_points} 分</span>
              </div>
              <span className={`status status-${paper.status}`}>{PAPER_STATUS_LABELS[paper.status]}</span>
            </div>
          ))}
          {!papers.length && (
            <div className="empty-state"><FileStack size={20} /><span>生成的试卷会显示在这里。</span></div>
          )}
        </section>
      </div>
    </div>
  )
}
