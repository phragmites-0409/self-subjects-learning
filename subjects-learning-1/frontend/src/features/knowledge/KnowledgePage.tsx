import { BookOpen, Search, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SUBJECTS, SUBJECT_METADATA, Subject } from '../../api/types'

export default function KnowledgePage() {
  const [activeSubject, setActiveSubject] = useState<Subject>('数学')
  const navigate = useNavigate()
  const subject = SUBJECT_METADATA[activeSubject]

  return (
    <div className="page subject-page knowledge-page">
      <header className="subpage-header">
        <div>
          <p className="eyebrow">KNOWLEDGE LIBRARY</p>
          <h1>知识库</h1>
          <p className="muted">按学科整理概念、题型与解题方法。</p>
        </div>
        <span className="pill light-pill">高中六科</span>
      </header>

      <SubjectTabs activeSubject={activeSubject} onChange={setActiveSubject} />

      <section className="subject-intro panel">
        <div className="subject-icon"><BookOpen size={22} /></div>
        <div>
          <p className="eyebrow">{subject.label} KNOWLEDGE SPACE</p>
          <h2>{subject.description}</h2>
          <p>{subject.scope}</p>
        </div>
      </section>

      <section className="subject-empty panel">
        <div className="empty-illustration"><Search size={24} /></div>
        <h2>知识条目正在积累</h2>
        <p>确认题目后，相关的知识点和解题方法会沉淀到{activeSubject}知识库。</p>
        <button className="button primary" onClick={() => navigate('/capture')}>
          <Sparkles size={16} />去拍一道题
        </button>
      </section>
    </div>
  )
}

function SubjectTabs({ activeSubject, onChange }: { activeSubject: Subject; onChange: (subject: Subject) => void }) {
  return (
    <div className="subject-tabs" role="tablist" aria-label="选择学科">
      {SUBJECTS.map(subject => (
        <button
          key={subject}
          type="button"
          role="tab"
          aria-selected={activeSubject === subject}
          className={activeSubject === subject ? 'subject-tab active' : 'subject-tab'}
          onClick={() => onChange(subject)}
        >
          {subject}
        </button>
      ))}
    </div>
  )
}
