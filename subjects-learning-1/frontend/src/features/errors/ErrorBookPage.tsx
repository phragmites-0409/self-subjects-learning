import { ClipboardCheck, RotateCcw, Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { SUBJECTS, SUBJECT_METADATA, Subject } from '../../api/types'
import { useState } from 'react'

export default function ErrorBookPage() {
  const [activeSubject, setActiveSubject] = useState<Subject>('数学')
  const navigate = useNavigate()
  const subject = SUBJECT_METADATA[activeSubject]

  return (
    <div className="page subject-page error-book-page">
      <header className="subpage-header">
        <div>
          <p className="eyebrow">ERROR REVIEW</p>
          <h1>错题本</h1>
          <p className="muted">把暂时不会的题留下来，按学科安排下一次复盘。</p>
        </div>
        <span className="pill light-pill">高中六科</span>
      </header>

      <div className="subject-tabs" role="tablist" aria-label="选择错题学科">
        {SUBJECTS.map(subjectName => (
          <button
            key={subjectName}
            type="button"
            role="tab"
            aria-selected={activeSubject === subjectName}
            className={activeSubject === subjectName ? 'subject-tab active' : 'subject-tab'}
            onClick={() => setActiveSubject(subjectName)}
          >
            {subjectName}
          </button>
        ))}
      </div>

      <section className="review-summary panel">
        <div className="subject-icon"><ClipboardCheck size={22} /></div>
        <div>
          <p className="eyebrow">{subject.label} REVIEW SPACE</p>
          <h2>还没有待复盘的错题</h2>
          <p>在题目解析后标记需要巩固的内容，这里会按学科保留复习线索。</p>
        </div>
      </section>

      <section className="subject-empty panel">
        <div className="empty-illustration"><RotateCcw size={24} /></div>
        <h2>从一道不确定的题开始</h2>
        <p>拍题并完成解析后，你可以把易错点加入{activeSubject}错题本。</p>
        <button className="button primary" onClick={() => navigate('/capture')}>
          <Sparkles size={16} />去拍一道题
        </button>
      </section>
    </div>
  )
}
