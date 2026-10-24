import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import HomePage from './HomePage'
import { Paper, PaperStatus } from '../../api/types'

const paper = (id: string, status: PaperStatus): Paper => ({
  id,
  title: `${id}试卷`,
  subject: '数学',
  grade: '高中',
  total_points: 10,
  status,
  items: [],
})

describe('HomePage paper summary', () => {
  it('counts only generated papers and renders each paper state', () => {
    render(<MemoryRouter><HomePage questions={[]} papers={[paper('generated', 'generated'), paper('draft', 'draft')]} /></MemoryRouter>)

    const generatedStat = screen.getByText('已生成试卷').closest('.stat-card')
    expect(generatedStat).toHaveTextContent('1')
    expect(screen.getByText('已生成')).toBeInTheDocument()
    expect(screen.getByText('草稿')).toBeInTheDocument()
  })
})
