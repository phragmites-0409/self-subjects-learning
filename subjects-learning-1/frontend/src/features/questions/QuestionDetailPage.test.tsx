import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QuestionDetailPage from './QuestionDetailPage'

const question = {
  id: 'question-1',
  status: 'approved',
  subject: '数学' as const,
  grade: '高一',
  question_type: '函数题',
  difficulty: '中等',
  methods: [],
  knowledge_points: [],
  tags: [],
  updated_at: '2026-09-02T00:00:00Z',
  content: { stem: '求函数值。', question_type: '函数题' },
}

const jsonResponse = (value: unknown) => ({ ok: true, json: async () => value })

function LocationProbe() {
  return <output data-testid="location"><LocationPath /></output>
}

function LocationPath() {
  return useLocation().pathname
}

describe('QuestionDetailPage navigation', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.endsWith('/questions/question-1')) return jsonResponse(question)
      if (url.endsWith('/questions/question-1/conversations')) return jsonResponse({ items: [] })
      throw new Error(`unexpected request: ${url}`)
    }))
  })

  it('returns to a valid study route instead of the removed questions route', async () => {
    render(
      <MemoryRouter initialEntries={['/questions/question-1']}>
        <Routes>
          <Route path="/questions/:id" element={<QuestionDetailPage onRefresh={vi.fn()} />} />
          <Route path="/knowledge" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: /返回知识库/ }))

    expect(screen.getByTestId('location')).toHaveTextContent('/knowledge')
  })
})
