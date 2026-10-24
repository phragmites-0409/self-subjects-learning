import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import PapersPage from './PapersPage'
import { Paper, Question, SUBJECTS } from '../../api/types'

const question: Question = {
  id: 'question-1',
  status: 'approved',
  subject: '物理',
  grade: '高一',
  question_type: '函数题',
  difficulty: '中等',
  methods: ['配方法'],
  knowledge_points: ['函数'],
  tags: [],
  updated_at: '2026-09-02T00:00:00Z',
}

const emptyPaperList: Paper[] = []
const jsonResponse = (value: unknown) => ({ ok: true, json: async () => value })

describe('PapersPage subject boundary', () => {
  let requests: { url: string; options: RequestInit }[]

  beforeEach(() => {
    requests = []
    vi.stubGlobal('fetch', vi.fn(async (input: unknown, options: RequestInit = {}) => {
      const url = String(input)
      requests.push({ url, options })
      if (url.endsWith('/papers') && options.method === 'POST') {
        return jsonResponse({ id: 'paper-1', title: '高中专项练习', subject: '物理', grade: '高中', total_points: 5, status: 'generated', items: [] })
      }
      if (url.includes('/papers/paper-1/export')) return jsonResponse({ download_url: '/api/v1/files/paper-1.pdf' })
      throw new Error(`unexpected request: ${url}`)
    }))
    vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('names the board 组卷库 and offers only the six valid subjects', () => {
    render(<MemoryRouter><PapersPage questions={[question]} papers={emptyPaperList} onRefresh={vi.fn()} /></MemoryRouter>)

    expect(screen.getByRole('heading', { name: '组卷库' })).toBeInTheDocument()
    expect(screen.queryByText('试卷归档')).not.toBeInTheDocument()
    expect(Array.from(screen.getByLabelText('试卷学科').querySelectorAll('option')).map(option => option.textContent)).toEqual([...SUBJECTS])
  })

  it('sends the selected valid subject when creating a paper', async () => {
    render(<MemoryRouter><PapersPage questions={[question]} papers={emptyPaperList} onRefresh={vi.fn()} /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('试卷学科'), { target: { value: '物理' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /生成学生版 PDF/ }))

    await waitFor(() => expect(requests.some(request => request.url.endsWith('/papers') && request.options.method === 'POST')).toBe(true))
    const createRequest = requests.find(request => request.url.endsWith('/papers') && request.options.method === 'POST')
    expect(JSON.parse(String(createRequest?.options.body))).toMatchObject({ subject: '物理' })
    expect(await screen.findByText('试卷已生成并保存到组卷库。')).toBeInTheDocument()
  })
})
