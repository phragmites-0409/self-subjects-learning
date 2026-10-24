export const SUBJECTS = ['数学', '物理', '化学', '生物', '语文', '英语'] as const
export type Subject = (typeof SUBJECTS)[number]

export type SubjectMetadata = {
  label: Subject
  description: string
  scope: string
}

export const SUBJECT_METADATA: Record<Subject, SubjectMetadata> = {
  数学: { label: '数学', description: '函数、几何与代数方法', scope: '高中数学全内容' },
  物理: { label: '物理', description: '力学、电磁学与实验', scope: '高中物理全内容' },
  化学: { label: '化学', description: '反应原理与物质结构', scope: '高中化学全内容' },
  生物: { label: '生物', description: '分子、细胞与生态系统', scope: '高中生物全内容' },
  语文: { label: '语文', description: '阅读、写作与语言文字运用', scope: '高中语文全内容' },
  英语: { label: '英语', description: '高频词汇与语境积累', scope: '知识库仅覆盖单词' },
}

export type NavigationIcon = 'home' | 'capture' | 'knowledge' | 'errors' | 'papers' | 'settings'
export type NavigationItem = {
  to: '/' | '/capture' | '/knowledge' | '/errors' | '/papers' | '/settings'
  label: string
  icon: NavigationIcon
  end?: boolean
}

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  { to: '/', label: '主页', icon: 'home', end: true },
  { to: '/capture', label: '拍题解析', icon: 'capture' },
  { to: '/knowledge', label: '知识库', icon: 'knowledge' },
  { to: '/errors', label: '错题本', icon: 'errors' },
  { to: '/papers', label: '组卷库', icon: 'papers' },
  { to: '/settings', label: '设置', icon: 'settings' },
]

export type Step = { index: number; title: string; content: string; rationale: string }
export type Question = {
  id: string; status: string; subject: Subject; grade: string; question_type: string; difficulty: string
  methods: string[]; knowledge_points: string[]; tags: string[]; version_id?: string; content?: {
    stem?: string; answer?: string; overview?: string; known_conditions?: string[]; target?: string; question_type?: string
    methods?: string[]; knowledge_points?: string[]; solution_steps?: Step[]; common_mistakes?: string[]; uncertainty_notes?: string[]
  }; review?: { status?: string; issues?: string[]; summary?: string }; updated_at: string
}

export type PaperStatus = 'draft' | 'generated'
export const PAPER_STATUS_LABELS: Record<PaperStatus, string> = {
  draft: '草稿',
  generated: '已生成',
}

export type PaperItem = { question_id: string; question_version_id: string; points: number; position: number }
export type Paper = {
  id: string; title: string; subject: Subject; grade: string; total_points: number; status: PaperStatus; items: PaperItem[]
}
export type PaperCreateInput = {
  title: string; subject: Subject; grade: string; items: { question_id: string; points: number }[]
}
