import { ChangeEvent, useRef, useState } from 'react'
import { Camera, CheckCircle2, ImagePlus, LoaderCircle, RotateCcw, Sparkles, Upload } from 'lucide-react'
import { api, apiUrl } from '../../api/client'
import { Question } from '../../api/types'

export default function CapturePage({ onCreated }: { onCreated: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [text, setText] = useState('')
  const [questionId, setQuestionId] = useState('')
  const [result, setResult] = useState<Question | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  const selectFile = (next: File | undefined) => {
    if (!next) return
    setFile(next); setPreview(URL.createObjectURL(next)); setResult(null); setQuestionId(''); setMessage('')
  }
  const onFile = (event: ChangeEvent<HTMLInputElement>) => selectFile(event.target.files?.[0])
  const upload = async () => {
    if (!file && !text.trim()) { setMessage('请先拍照、上传图片或粘贴题目文字。'); return }
    setLoading(true); setMessage('正在上传并检查题目信息…')
    try {
      let id = questionId
      if (!id) {
        if (!file) throw new Error('当前需要一张题目图片，请选择图片后再试。')
        const form = new FormData(); form.append('file', file); form.append('text', text)
        const uploaded = await api<{question_id: string}>('/assets', { method: 'POST', body: form }); id = uploaded.question_id; setQuestionId(id)
      }
      setMessage('AI 正在分析并复核，请稍候…')
      await api(`/questions/${id}/parse`, { method: 'POST', body: JSON.stringify({ text }) })
      const detail = await api<Question>(`/questions/${id}`)
      setResult(detail); setMessage(detail.status === 'approved' ? '解析完成，已通过 AI 复核。' : '解析完成，请确认 AI 标记的不确定信息。'); onCreated()
    } catch (e) { setMessage(e instanceof Error ? e.message : '处理失败') }
    finally { setLoading(false) }
  }
  return <div className="page"><div className="subpage-header"><div><p className="eyebrow">CAPTURE & UNDERSTAND</p><h1>拍题解析</h1></div><span className="pill light-pill">高中题目 · AI 中转</span></div>
    <div className="capture-layout"><section className="capture-card"><div className={`drop-zone ${preview ? 'has-preview' : ''}`} onClick={() => inputRef.current?.click()}>{preview ? <img src={preview} alt="题目预览"/> : <><div className="upload-icon"><Camera size={25}/></div><strong>拍照或上传题目</strong><span>支持 JPG、PNG、WebP，建议保证题干和图形完整</span><button className="button secondary" onClick={e => { e.stopPropagation(); inputRef.current?.click() }}><ImagePlus size={15}/>选择图片</button></>}</div><input ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden onChange={onFile}/>{preview && <button className="reset-file" onClick={() => { setFile(null); setPreview(''); setQuestionId(''); setResult(null) }}><RotateCcw size={13}/>重新选择</button>}<label className="field-label">补充题目文字（可选）<textarea className="textarea" value={text} onChange={e => setText(e.target.value)} placeholder="如果图片中有不清楚的公式，可以在这里补充…"/></label><button className="button primary analyze-button" disabled={loading} onClick={upload}>{loading ? <LoaderCircle className="spin" size={16}/> : <Sparkles size={16}/>} {loading ? 'AI 处理中…' : '开始 AI 分析'}</button>{message && <div className={`result-message ${result ? 'success' : ''}`}>{result ? <CheckCircle2 size={16}/> : <Upload size={16}/>}<span>{message}</span></div>}</section>
      <section className="guide-card"><div className="guide-head"><Sparkles size={18}/><div><strong>AI 分析流程</strong><span>每一步都可追溯、可确认</span></div></div><div className="guide-list"><Guide n="01" title="完整性判定" text="先检查是否为高中题目，以及题干、公式和图形是否完整。"/><Guide n="02" title="结构化解析" text="识别题型与方法，将解题过程拆分为清晰的步骤。"/><Guide n="03" title="复核与归档" text="AI 复核后，你可以确认分类并继续追问。"/></div><div className="guide-note">提示：AI 是学习助手。遇到标记为“不确定”的信息，请先检查原题再归档。</div></section></div>
    {result && <AnalysisPreview question={result}/>}</div>
}
function Guide({ n, title, text }: { n: string; title: string; text: string }) { return <div className="guide-step"><b>{n}</b><div><strong>{title}</strong><p>{text}</p></div></div> }
function AnalysisPreview({ question }: { question: Question }) { const c = question.content || {}; return <section className="analysis-preview"><div className="analysis-title"><div><p className="eyebrow">ANALYSIS RESULT</p><h2>{c.question_type || question.question_type}</h2></div><span className={`status status-${question.status}`}>{question.status === 'approved' ? 'AI 复核通过' : '需要确认'}</span></div><div className="meta-chips"><span className="meta-chip">{question.subject}</span><span className="meta-chip">{question.grade}</span><span className="meta-chip">{question.difficulty}</span>{(question.methods || []).map(m => <span key={m} className="meta-chip">{m}</span>)}</div><div className="analysis-columns"><div><h3>识别出的题目</h3><div className="question-stem">{c.stem || '暂无题干'}</div><h3>解题概览</h3><p className="body-copy">{c.overview || '暂无概览'}</p></div><div><h3>分步解析</h3>{(c.solution_steps || []).map(step => <div className="step" key={step.index}><strong>Step {step.index} · {step.title}</strong><p>{step.content}</p>{step.rationale && <small>依据：{step.rationale}</small>}</div>)}</div></div>{(c.uncertainty_notes || []).length > 0 && <div className="notice">需要留意：{c.uncertainty_notes?.join('；')}</div>}</section> }
