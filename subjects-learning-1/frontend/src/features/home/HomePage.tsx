import { BookOpen, FileStack, ImagePlus, Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { PAPER_STATUS_LABELS, Paper, Question } from '../../api/types'

type HomePageProps = {
  questions: Question[]
  papers: Paper[]
}

export default function HomePage({ questions, papers }: HomePageProps) {
  const navigate = useNavigate()
  const approvedQuestions = questions.filter(question => question.status === 'approved').length
  const generatedPapers = papers.filter(paper => paper.status === 'generated').length

  return (
    <div className="page home-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">PERSONAL STUDY WORKSPACE</p>
          <h1>今天，攻克一道题。</h1>
          <p className="muted">把不确定交给 AI，把清晰的思路留在自己的学习空间里。</p>
        </div>
        <button className="button primary" onClick={() => navigate('/capture')}>
          <Sparkles size={17} />开始拍题
        </button>
      </header>

      <section className="hero-card home-capture-card">
        <div>
          <span className="pill">CAPTURE · UNDERSTAND · KEEP</span>
          <h2>从一张照片开始，<br /><span>让解题思路变得可见。</span></h2>
          <p>上传题目图片或补充文字，获得结构化的分步解析，并在确认后沉淀到你的学习资料中。</p>
          <button className="text-button" onClick={() => navigate('/capture')}>上传一道题 <span>→</span></button>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="visual-card">
            <Sparkles size={22} />
            <strong>AI 学习流程</strong>
            <span>识别 · 解析 · 归档</span>
            <small>从看懂一道题开始</small>
          </div>
        </div>
      </section>

      <section className="stats-grid" aria-label="学习空间概览">
        <Stat label="已收录题目" value={questions.length} note="持续积累" />
        <Stat label="已确认解析" value={approvedQuestions} note="可用于组卷" />
        <Stat label="已生成试卷" value={generatedPapers} note="本地保存" />
      </section>

      <section className="quick-links" aria-label="快捷入口">
        <button className="quick-link" onClick={() => navigate('/capture')}>
          <span className="quick-link-icon"><ImagePlus size={18} /></span>
          <span><strong>拍题解析</strong><small>上传新题，开始理解</small></span>
          <span className="row-arrow">→</span>
        </button>
        <button className="quick-link" onClick={() => navigate('/knowledge')}>
          <span className="quick-link-icon"><BookOpen size={18} /></span>
          <span><strong>浏览知识体系</strong><small>按学科整理方法与概念</small></span>
          <span className="row-arrow">→</span>
        </button>
        <button className="quick-link" onClick={() => navigate('/errors')}>
          <span className="quick-link-icon"><Sparkles size={18} /></span>
          <span><strong>复盘错题</strong><small>回看仍需巩固的题目</small></span>
          <span className="row-arrow">→</span>
        </button>
      </section>

      <section className="content-grid home-content-grid">
        <div className="panel">
          <div className="panel-heading">
            <div><p className="eyebrow">RECENT QUESTIONS</p><h3>最近题目</h3></div>
            <button className="link-button" onClick={() => navigate('/knowledge')}>进入知识库 →</button>
          </div>
          {questions.slice(0, 4).map(question => (
            <button className="question-row" key={question.id} onClick={() => navigate(`/questions/${question.id}`)}>
              <div className="question-icon"><BookOpen size={17} /></div>
              <div className="row-copy">
                <strong>{question.question_type || '待分类题目'}</strong>
                <span>{question.subject} · {question.grade} · {question.methods?.slice(0, 2).join(' / ') || '待 AI 判断'}</span>
              </div>
              <span className={`status status-${question.status}`}>{question.status === 'approved' ? '已确认' : '待复核'}</span>
              <span className="row-arrow">→</span>
            </button>
          ))}
          {!questions.length && <EmptyState icon={<BookOpen size={22} />} text="还没有题目，拍下第一道题吧。" />}
        </div>

        <div className="panel recent-papers-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">RECENT PAPERS</p><h3>最近试卷</h3></div>
            <button className="link-button" onClick={() => navigate('/papers')}>进入组卷库 →</button>
          </div>
          {papers.slice(0, 3).map(paper => (
            <div className="history-row" key={paper.id}>
              <div><strong>{paper.title}</strong><span>{paper.items.length} 道题 · {paper.total_points} 分</span></div>
              <span className={`status status-${paper.status}`}>{PAPER_STATUS_LABELS[paper.status]}</span>
            </div>
          ))}
          {!papers.length && <EmptyState icon={<FileStack size={22} />} text="生成的试卷会显示在这里。" />}
        </div>
      </section>
    </div>
  )
}

function Stat({ label, value, note }: { label: string; value: number; note: string }) {
  return <div className="stat-card"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>
}

function EmptyState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return <div className="empty-state">{icon}<span>{text}</span></div>
}
