# 六科高中学习系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有本地 FastAPI + React 项目上完成六门高中学科学习主链，提供主页、拍题解答、知识库、错题本、组卷库和设置六个板块；暂不实现每日错题、考情统计、课外内容。

**Architecture:** 保留现有轻量单体结构。FastAPI 继续作为本地服务和 DeepSeek AI Gateway，SQLite 保存元数据、关系与查询字段，本地压缩对象保存完整题目解析与对话；React/Vite 负责六板块界面。题目是唯一的可复用内容源，错题本通过关联记录引用题目版本，组卷库固定题目版本快照。未来开发板只使用受限 API，不直接访问文件或 API Key。

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, httpx, Pillow, ReportLab; React, TypeScript, Vite, React Router, lucide-react.

**Spec:** `C:\Users\ASUS\.claude\plans\cached-wiggling-taco.md`；英语补充规格：`docs/superpowers/specs/2026-09-02-english-composition-vocabulary-design.md`（本次范围以用户 2026-09-02 的六板块及英语补充要求为准；每日错题、考情统计、课外内容明确排除）

## Global Constraints

- 仅支持高中数学、物理、化学、生物、语文、英语六门；普通高中英语题可以解析，英语知识库只沉淀作文素材，单词使用独立词库和过关系统。
- 单词库分为后续文本导入的高考考纲 3500 词和拍照/手动查词产生的日常词汇；查询结果须由用户选择后才能入库。
- 单词过关使用规则匹配；匹配失败由用户裁决，用户认可答案保存为绑定具体义项的个人别名；逐义项模式按词性分组且同词性义项无序匹配。
- 每日单词任务与未来每日错题复用通用调度模型；本轮仅启用单词任务，支持后端常驻定时通知和启动补推，不实现每日错题页面或推送。
- 所有题目识别、分类、解析、思路引导、对话和知识抽取由外部 AI 完成；本地服务负责中转、提示词约束、结构校验、存储和展示。
- DeepSeek API Key 只能由后端读取，不得返回浏览器或设备。
- 正式解析前必须执行信息完整性/高中范围判定；信息不足不得伪造条件或直接标记为可归档。
- 用户可修改 AI 推荐的学科、题型、模型、知识点和标签；AI 建议未经用户确认不得破坏知识树。
- 数据库保存轻量元数据和关系，完整解析/对话/导入内容压缩保存；图片和 PDF 不放入数据库。
- 顶层用户板块只包括主页、拍题解答、知识库、错题本、组卷库、设置；不添加每日错题、考情统计、课外内容入口。
- 现有项目没有 Git 基线；每个任务结束仍需运行对应测试并记录验证结果，不执行不可逆的外部发布操作。

---

## 文件与边界

### 后端

- `backend/app/db/models.py`：扩展知识节点、知识内容、题目关联、错题记录及标签关系；保留现有题目版本、试卷版本和设备模型。
- `backend/app/ai/schemas.py`：增加六科枚举/结构化知识映射、错题元数据和对话显示 DTO；继续复用现有 `QuestionContentV1`、`PreflightResult`、`ReviewResult`。
- `backend/app/ai/prompts.py`：保留兼容导出，组合全局高中策略、普通学科任务与英语作文/单词专项任务；普通英语题不得被误拒绝。
- `backend/app/ai/prompts/`：保存版本化中文策略，普通英语题、英语作文素材、单词识别/查词使用彼此隔离的任务提示词。
- `backend/app/ai/gateway.py`：统一生成 AI 请求、执行信息完整性判定、解析/复核、题型/模型/知识节点建议和题内对话；记录 AI Run 用量/延迟。
- `backend/app/ai/validator.py`：复用并加强 JSON 提取、有限修复和 Pydantic 校验。
- `backend/app/modules/knowledge/`：知识节点、关系树、预置数据、搜索、导入建议和题目关联服务。
- `backend/app/modules/errors/`：错题本加入/修改/筛选/删除服务；加入日期按日期存储和展示。
- `backend/app/modules/questions/`、`backend/app/modules/conversations/`：扩展题目确认、完整内容读取、题内对话上下文、幂等和版本操作。
- `backend/app/modules/papers/`、`backend/app/documents/pdf_service.py`：复用现有组卷与 PDF 能力，增加学科筛选、题目版本固定和学生版/答案版/解析版输出。
- `backend/app/api/v1/knowledge.py`、`errors.py`、`questions.py`、`conversations.py`、`papers.py`、`settings.py`：提供页面和未来设备可复用的稳定 DTO；不暴露管理配置和试卷给设备 scope。
- `backend/app/seed/knowledge.py`：六科最小预置知识树；英语种子只包含作文素材分类，不把单词建成知识节点。
- `backend/app/modules/vocabulary/`：单词、义项、个人别名、导入、查词、每日会话、匹配和调度服务。
- `backend/app/modules/composition/`：英语作文素材的增删改查、导入建议与确认服务。
- `tests/`：单元、API 和闭环测试，全部使用临时 SQLite、本地对象目录和 Fake Provider。

### 前端

- `frontend/src/app/App.tsx`：六个板块导航、路由和主页数据装配；不渲染三个暂缓板块。
- `frontend/src/features/home/`：拍题窗口、快速入口、最近题目和每日错题占位不实现（可显示功能尚未启用）。
- `frontend/src/features/capture/`：拍照/上传、任务阶段、结构化解析、知识关联、加入错题本、题内追问。
- `frontend/src/features/knowledge/`：学科切换、关系树、节点详情、搜索、预置/题目导入/外部导入确认；英语页提供作文素材、单词库、单词过关子页签。
- `frontend/src/features/vocabulary/`：3500 词预览/确认导入、日常查词/拍照、词条详情、两种过关模式、人工裁决和今日任务。
- `frontend/src/features/home/`：除拍题和现有快速入口外，增加单词库与今日单词过关卡片。
- `frontend/src/features/errors/`：错题列表、日期/题型/学科/标签筛选、详情、编辑标签和跳转题目对话。
- `frontend/src/features/papers/`：按学科选题、筛选、排序、分值、版本确认和 PDF 生成状态。
- `frontend/src/features/settings/`：DeepSeek 模型、解析模式、存储和未来设备配对设置。
- `frontend/src/api/client.ts`、`types.ts`：集中类型和错误处理；不在组件中拼接 API Key。
- `frontend/src/components/RichContent.tsx`（必要时）：统一 Markdown/GFM/KaTeX 渲染，题干、步骤、答案、对话和知识内容复用。

---

## Task 1: 固化六板块壳层和领域常量

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/styles/global.css`
- Create: `frontend/src/features/home/HomePage.tsx`
- Create: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Create: `frontend/src/features/errors/ErrorBookPage.tsx`
- Test: `frontend/src/app/App.test.tsx`（若当前前端无测试配置，则在 Task 1 中添加 Vitest 最小配置）

**Interfaces:**
- Produces routes `/`, `/capture`, `/knowledge`, `/errors`, `/papers`, `/settings`。
- Produces `Subject = '数学' | '物理' | '化学' | '生物' | '语文' | '英语'` and shared navigation metadata.

- [ ] **Step 1: Write the failing route test**

```tsx
it('exposes exactly the six active study sections', () => {
  render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
  expect(screen.getByText('知识库')).toBeInTheDocument()
  expect(screen.getByText('错题本')).toBeInTheDocument()
  expect(screen.getByText('组卷库')).toBeInTheDocument()
  expect(screen.queryByText('每日错题')).not.toBeInTheDocument()
  expect(screen.queryByText('考情统计')).not.toBeInTheDocument()
  expect(screen.queryByText('课外内容')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd frontend; npm test -- --run src/app/App.test.tsx`
Expected: FAIL because the current navigation has only the old five routes and no test runner/page components.

- [ ] **Step 3: Implement the shell and shared subject constants**

Update `App.tsx` to import the six route pages, replace “总览/题目归档/试卷归档” user-facing labels with “主页/知识库/错题本/组卷库”, retain `/capture`, `/papers`, `/settings`, and remove any links to deferred sections. Add a `Subject` union and shared subject metadata in `types.ts`. Build HomePage with the required capture card, quick links, and recent question/paper panels; build initial KnowledgePage and ErrorBookPage empty states with subject tabs so later tasks have stable route boundaries.

- [ ] **Step 4: Run the focused test and build**

Run: `cd frontend; npm test -- --run src/app/App.test.tsx; npm run build`
Expected: PASS and a successful Vite/TypeScript build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
 git commit -m "feat: add six-subject study workspace shell"
```

---

## Task 2: Extend the domain model for knowledge and error-book records

**Files:**
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/session.py`
- Create: `backend/app/modules/knowledge/schemas.py`
- Create: `backend/app/modules/errors/schemas.py`
- Test: `tests/test_domain_models.py`

**Interfaces:**
- `KnowledgeNode(id, subject, parent_id, name, kind, summary, sort_order, status)`.
- `KnowledgeEdge(id, source_id, target_id, relation)`.
- `KnowledgeContent(id, node_id, title, content_storage_key, source, content_hash)`.
- `QuestionKnowledge(question_id, node_id, relation, confidence, source)`.
- `ErrorEntry(id, question_id, added_date, subject, question_type, tags_json, error_reason, status, note)`.
- `ErrorReview(id, error_entry_id, reviewed_date, result, note)` reserved for future review screens but no Daily Mistake scheduler.
- Pydantic schemas validate subjects to the six-value allow-list and English knowledge kind to `word`.

- [ ] **Step 1: Write failing model/schema tests**

```python
def test_error_entry_stores_date_without_time_and_subject_is_restricted(db):
    entry = ErrorEntry(question_id='q1', added_date=date(2026, 9, 2), subject='数学', question_type='函数')
    db.add(entry); db.commit(); db.refresh(entry)
    assert entry.added_date.isoformat() == '2026-09-02'

def test_english_knowledge_rejects_non_word_kind():
    with pytest.raises(ValidationError):
        KnowledgeNodeCreate(subject='英语', name='时态', kind='grammar')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_domain_models.py -q`
Expected: FAIL because the new tables and schemas do not exist.

- [ ] **Step 3: Implement models and initialization**

Add SQLAlchemy tables, indexes on subject/date/type/status, foreign keys with cascade behavior, and SQLite initialization/migration logic compatible with the existing `Base.metadata.create_all` startup. Store full content through the existing local object store; model fields retain only storage keys and hashes. Add schema validators for the six subjects. The original Task 2 English word-only constraint was implemented at that time but is explicitly superseded by Task 3A/3B: English Knowledge becomes composition-only and words move to their own tables.

- [ ] **Step 4: Run focused and existing backend tests**

Run: `pytest tests/test_domain_models.py -q; pytest -q`
Expected: PASS without breaking existing question/paper tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db
 git add backend/app/modules/knowledge backend/app/modules/errors tests/test_domain_models.py
 git commit -m "feat: add knowledge graph and error book models"
```

---

## Task 3: Build versioned subject prompts and AI output contracts

**Files:**
- Modify: `backend/app/ai/schemas.py`
- Modify: `backend/app/ai/prompts.py`
- Create: `backend/app/ai/prompt_registry.py`
- Create: `backend/app/ai/prompts/policy.zh.md`
- Create: `backend/app/ai/prompts/subjects/{math,physics,chemistry,biology,chinese,english_words}.zh.md`
- Create: `backend/app/ai/prompts/tasks/{preflight,solve,review,chat,knowledge_import}.zh.md`
- Modify: `backend/app/ai/validator.py`
- Test: `tests/test_ai_contracts.py`

**Interfaces:**
- `PromptRegistry.get(task: str, subject: str | None = None) -> PromptBundle(version: str, system: str)`.
- `QuestionContentV1` gains `model_path`, `knowledge_candidates`, and `uncertainty_notes` while remaining backward-compatible.
- `KnowledgeMappingResult(nodes: list[KnowledgeSuggestion], edges: list[KnowledgeRelationSuggestion])`.
- `PreflightResult` supports `not_supported` and `uncertain` decisions.

- [ ] **Step 1: Write failing contract and prompt tests**

```python
def test_english_prompt_is_word_only():
    bundle = get_prompt_registry().get('solve', '英语')
    assert '单词' in bundle.system
    assert '语法' in bundle.system

def test_preflight_rejects_unknown_subject_decision():
    result = PreflightResult.model_validate({'decision':'not_supported','is_high_school':False,'recognized_text':'','concerns':[],'missing_information':[],'suggestion':'仅支持高中六科'})
    assert result.decision == 'not_supported'
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_ai_contracts.py -q`
Expected: FAIL because PromptRegistry and new schema fields are absent.

- [ ] **Step 3: Implement prompt registry and contracts**

Create a cached registry with policy → subject → task composition, a stable policy version, Chinese-first fallback, and explicit prompt-injection boundary around user text. Add subject-specific instructions: mathematics models/formulas, physics derivations/conditions, chemistry properties/experiments/industrial process/textbook, biology textbook/models, Chinese poetry/reading/idioms/composition/language use, and English words only. Extend validators to extract fenced JSON, remove `<think>` wrappers, attempt at most one safe repair, then run Pydantic validation; never fabricate missing answer fields.

- [ ] **Step 4: Run tests and lint**

Run: `pytest tests/test_ai_contracts.py -q; ruff check backend/app/ai`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai tests/test_ai_contracts.py
 git commit -m "feat: add versioned six-subject AI contracts"
```

---

## Task 3A: Supersede the English prompt and knowledge constraints

**Files:**
- Modify: `backend/app/ai/prompt_registry.py`
- Modify: `backend/app/ai/prompts/subjects/english_words.zh.md`
- Create: `backend/app/ai/prompts/subjects/english_question.zh.md`
- Create: `backend/app/ai/prompts/tasks/english_composition.zh.md`
- Create: `backend/app/ai/prompts/tasks/vocabulary_extract.zh.md`
- Create: `backend/app/ai/prompts/tasks/vocabulary_lookup.zh.md`
- Modify: `backend/app/ai/schemas.py`
- Modify: `backend/app/modules/knowledge/schemas.py`
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_english_policy.py`

**Interfaces:**
- `PromptRegistry.get('solve', '英语')` handles ordinary high-school English questions.
- `PromptRegistry.get('english_composition', '英语')` permits composition material only.
- `PromptRegistry.get('vocabulary_extract'|'vocabulary_lookup', '英语')` permits word extraction/lookup only.
- English `KnowledgeNode.kind` accepts only `composition_category`, `phrase`, `sentence_pattern`, `viewpoint`, `material`, `sample_excerpt`; words are no longer knowledge nodes.

- [ ] Write tests proving ordinary English questions are not rejected, vocabulary prompts cannot create grammar/reading knowledge nodes, and the database rejects English knowledge kind `word`/`grammar` while accepting composition kinds.
- [ ] Run `pytest backend/tests/test_english_policy.py -q` and confirm it fails under the superseded word-only implementation.
- [ ] Implement task-specific prompt composition, new output schemas for composition suggestions and vocabulary lookup/extraction, and replace the SQLite English-kind CHECK. Because `create_all` cannot alter an existing CHECK, add an idempotent SQLite migration that rebuilds `knowledge_nodes` while preserving valid rows and reports legacy word rows for migration into the vocabulary table in Task 3B.
- [ ] Run `pytest backend/tests/test_english_policy.py -q; pytest backend/tests -q; ruff check backend/app/ai backend/app/modules/knowledge backend/app/db`.
- [ ] Record changed files and exact results in `task-3a-report.md`; no Git commit is available.

---

## Task 3B: Add composition, vocabulary, and study-schedule persistence

**Files:**
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/session.py`
- Create: `backend/app/modules/composition/schemas.py`
- Create: `backend/app/modules/vocabulary/schemas.py`
- Create: `backend/app/modules/study/schemas.py`
- Test: `backend/tests/test_vocabulary_models.py`

**Interfaces:**
- `EnglishCompositionMaterial` stores English content, Chinese note, material type, themes/tags, source, date, favorite, and optional compressed object reference.
- `Word` stores `word`, normalized lemma, source membership, created/review dates, status, correct/wrong counts.
- `WordSense` stores part of speech, standard/normalized Chinese meaning, order, source, enabled.
- `AcceptedAlias` binds one enabled normalized user answer to one sense and never overwrites the standard meaning.
- `VocabularyImport` and `VocabularyImportError` store preview/commit status and bad lines.
- `VocabularySettings`, `VocabularySession`, `VocabularySessionItem`, `VocabularyAttempt`, `StudySchedule`, and `DailyStudyTask` provide daily passage state without implementing daily-error review.

- [ ] Write failing temporary-SQLite tests for unique normalized words/senses/aliases, source merge, composition-kind allow-list, daily 1–200 limit, one vocabulary task per date, and cascades.
- [ ] Run `pytest backend/tests/test_vocabulary_models.py -q` and verify RED.
- [ ] Implement indexed SQLAlchemy models, six-subject-compatible checks, date-only scheduling, immutable standard meanings, and idempotent migration of any legacy English word knowledge nodes into Word/WordSense where the row has usable word/meaning content; keep unresolved legacy rows in a migration report rather than dropping them silently.
- [ ] Run focused/backend tests and Ruff.
- [ ] Append exact output to `task-3b-report.md`; no Git commit.

---

## Task 3C: Implement composition CRUD, 3500-word import, and AI lookup

**Files:**
- Create: `backend/app/modules/composition/service.py`
- Create: `backend/app/api/v1/composition.py`
- Create: `backend/app/modules/vocabulary/importer.py`
- Create: `backend/app/modules/vocabulary/service.py`
- Create: `backend/app/api/v1/vocabulary.py`
- Modify: `backend/app/ai/gateway.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_composition_vocabulary_api.py`

**Interfaces:**
- Composition routes: list/search/create/update/delete and AI proposal/apply confirmation.
- `POST /api/v1/vocabulary/imports/preview` accepts text or safe uploaded TXT/MD/CSV/JSON and returns parsed rows/errors without persistence.
- `POST /api/v1/vocabulary/imports/{id}/commit` applies the stable preview idempotently.
- `POST /api/v1/vocabulary/lookup` accepts a word or image asset and returns candidates/lemma/senses/context meaning without saving.
- `POST /api/v1/vocabulary/words` saves selected or edited senses; duplicates merge source to `both`.

- [ ] Write failing API tests for composition CRUD/proposal confirmation, accepted import formats, duplicate rules, malformed-row isolation, lookup-without-save, selected-sense save, and prompt-injection boundaries on image/OCR text.
- [ ] Run the focused test and verify RED.
- [ ] Implement deterministic import parsing and preview hashes; AI is used only for image candidate extraction/word lookup, while persistence remains an explicit user action. Save images/results through the existing local object store, never in SQLite; reject unsafe paths and unsupported MIME/size.
- [ ] Run focused/backend tests and Ruff.
- [ ] Write `task-3c-report.md` with red/green evidence and concerns; no Git commit.

---

## Task 3D: Implement rule matching and vocabulary-passage sessions

**Files:**
- Create: `backend/app/modules/vocabulary/normalization.py`
- Create: `backend/app/modules/vocabulary/matcher.py`
- Create: `backend/app/modules/vocabulary/practice.py`
- Extend: `backend/app/api/v1/vocabulary.py`
- Test: `backend/tests/test_vocabulary_practice.py`

**Interfaces:**
- `normalize_chinese_answer(text: str) -> str` normalizes whitespace and common punctuation without semantic guessing.
- `match_any_sense(word_id, answer) -> MatchResult` checks enabled standard senses and aliases.
- `match_all_senses(word_id, answers_by_pos) -> GroupMatchResult` performs one-to-one maximum matching within each part-of-speech group; order is irrelevant within the group.
- A failed attempt returns standard meanings and a pending adjudication token; `POST /attempts/{id}/adjudicate` accepts correct/incorrect, and correct creates a sense-bound personal alias.

- [ ] Write failing tests for punctuation/spacing normalization, aliases, any-sense mode, same-POS reversed order, duplicate answers not satisfying two senses, distinct POS separation, incorrect answers, and alias reuse after user adjudication.
- [ ] Run focused tests and verify RED.
- [ ] Implement deterministic bipartite matching, immutable session item ordering, attempt persistence, counter updates and idempotent adjudication. Never use AI to grade answers.
- [ ] Run focused/backend tests and Ruff.
- [ ] Write `task-3d-report.md`; no Git commit.

---

## Task 3E: Add vocabulary daily scheduling, notification boundary, and UI

**Files:**
- Create: `backend/app/modules/study/scheduler.py`
- Create: `backend/app/modules/study/notifications.py`
- Create: `backend/app/api/v1/study.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/home/HomePage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Create: `frontend/src/features/vocabulary/VocabularyLibrary.tsx`
- Create: `frontend/src/features/vocabulary/VocabularyLookup.tsx`
- Create: `frontend/src/features/vocabulary/VocabularyImport.tsx`
- Create: `frontend/src/features/vocabulary/VocabularyPractice.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Test: `backend/tests/test_vocabulary_schedule.py`
- Test: `frontend/src/features/vocabulary/VocabularyPractice.test.tsx`

**Interfaces:**
- `ensure_daily_task(local_date) -> DailyStudyTask` is idempotent and fixes that day's selected words.
- Startup catch-up creates a missing due task; an in-process scheduler creates due tasks while running.
- `NotificationBackend.notify(title, body)` has a no-op fallback; notification failure never loses a task.
- Study routes expose settings, today's task/progress, start/resume, answer and adjudicate.
- English knowledge UI has composition/material, vocabulary and passage tabs; home has Vocabulary and Today's Passage quick cards.

- [ ] Write failing scheduler tests with a fake clock and fake notifier for due generation, startup catch-up, one task/day, daily limit/source/order rules, notification failure, and no daily-error tasks. Write UI tests for two modes, POS labels, same-POS unordered inputs, failed-match adjudication and alias confirmation.
- [ ] Run focused backend/frontend tests and verify RED.
- [ ] Implement the reusable schedule core with only `task_type='vocabulary'` enabled. Add a Windows notification adapter only behind the interface and retain no-op fallback. Build the English sub-tabs, import/lookup/library/practice pages, home cards and settings controls; do not add a seventh top-level navigation item.
- [ ] Run focused tests, full backend/frontend tests, Ruff and production build.
- [ ] Write `task-3e-report.md`; no Git commit.

---

## Task 4: Refactor AI Gateway into a staged, auditable question pipeline

**Files:**
- Modify: `backend/app/ai/gateway.py`
- Modify: `backend/app/ai/providers/deepseek.py`
- Modify: `backend/app/modules/jobs/service.py`
- Create: `backend/app/ai/runtime.py`
- Create: `backend/app/ai/usage.py`
- Modify: `backend/app/api/v1/questions.py`
- Test: `tests/test_ai_pipeline.py`

**Interfaces:**
- `QuestionAIRuntime.run(question_id: str, text: str, image_bytes: bytes | None, mode: Literal['quick','rigorous']) -> AsyncIterator[AIEvent]`.
- `AIEvent(type: Literal['preflight','recognizing','analyzing','mapping','reviewing','completed','failed'], seq: int, progress: int, payload: dict)`.
- `AIGateway.map_knowledge(content, subject) -> KnowledgeMappingResult`.
- `AIGateway.chat(content, history, question, summary='') -> ChatAnswer`.

- [ ] **Step 1: Write failing Fake Provider pipeline tests**

```python
@pytest.mark.asyncio
async def test_pipeline_stops_when_preflight_needs_more_info(fake_provider, client):
    fake_provider.preflight_result = {'decision':'needs_more_info','is_high_school':True,'recognized_text':'x','concerns':['图形缺失'],'missing_information':['几何图'],'suggestion':'补拍'}
    events = [event async for event in runtime.run('q1', '', None, 'quick')]
    assert [event.type for event in events] == ['preflight', 'failed']
    assert events[-1].payload['code'] == 'needs_more_info'

def test_ai_run_records_usage_and_policy_version(...):
    assert run.purpose == 'parse_question'
    assert run.policy_version
    assert run.latency_ms is not None
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_ai_pipeline.py -q`
Expected: FAIL because staged runtime/events and usage recording do not exist.

- [ ] **Step 3: Implement the staged runtime**

Keep network calls outside DB transactions. Start a Job as queued/running, emit sequenced events for preflight → recognition/parse → classification/knowledge mapping → review, and finish/fail atomically. Return explicit non-archive outcomes for `needs_more_info`, `not_supported`, and `uncertain`; only approved review results can set question status to `approved`. Record model, policy version, input hash, usage, latency and error code in `AIRun`; never log prompt secrets or API keys. Keep a demo provider path when no API key is configured.

- [ ] **Step 4: Verify normal, malformed, timeout and review-failure paths**

Run: `pytest tests/test_ai_pipeline.py -q; pytest -q`
Expected: PASS; existing upload/parse behavior remains compatible.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai backend/app/modules/jobs backend/app/api/v1/questions.py tests/test_ai_pipeline.py
 git commit -m "feat: add staged auditable AI question runtime"
```

---

## Task 5: Implement knowledge tree, six subject seed data, and controlled imports

**Files:**
- Create: `backend/app/modules/knowledge/service.py`
- Create: `backend/app/modules/knowledge/router.py`
- Create: `backend/app/seed/knowledge.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/ai/gateway.py`
- Test: `tests/test_knowledge_api.py`

**Interfaces:**
- `KnowledgeService.list_nodes(subject: str, parent_id: str | None, search: str = '') -> list[KnowledgeNodeDTO]`.
- `KnowledgeService.get_tree(subject: str) -> KnowledgeTreeDTO`.
- `KnowledgeService.create_import_proposal(source_type, subject, content) -> ImportProposalDTO`.
- `KnowledgeService.apply_import(proposal_id, decisions) -> ImportResultDTO`.
- Routes: `GET /api/v1/knowledge`, `GET /api/v1/knowledge/tree`, `GET /api/v1/knowledge/{id}`, `POST /api/v1/knowledge/import/proposals`, `POST /api/v1/knowledge/import/{id}/apply`, `POST /api/v1/knowledge/questions/{question_id}/link`.

- [ ] **Step 1: Write failing API tests**

```python
def test_each_subject_has_seed_tree(client):
    for subject in ('数学','物理','化学','生物','语文','英语'):
        response = client.get('/api/v1/knowledge/tree', params={'subject': subject})
        assert response.status_code == 200
        assert response.json()['subject'] == subject
        assert response.json()['nodes']

def test_english_seed_contains_words_only(client):
    payload = client.get('/api/v1/knowledge/tree', params={'subject':'英语'}).json()
    assert all(node['kind'] == 'word' for node in payload['nodes'])
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_knowledge_api.py -q`
Expected: FAIL because routes, seed data and service do not exist.

- [ ] **Step 3: Implement tree and import confirmation flow**

Seed idempotently with subject roots and minimal useful nodes. Use `parent_id` plus explicit edges for model relationships. Keep seed text compact and expandable. AI import returns proposals only; the apply endpoint requires explicit per-node decisions (`merge`, `create`, `tag_only`, `ignore`). Link questions by IDs and confidence/source, without copying full question text into knowledge records. Support external Markdown/TXT/JSON input through local object storage, rejecting unsafe paths.

- [ ] **Step 4: Run API, persistence and English restrictions tests**

Run: `pytest tests/test_knowledge_api.py -q; pytest -q`
Expected: PASS and seed remains idempotent across app restarts.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/knowledge backend/app/seed backend/app/api/v1/router.py tests/test_knowledge_api.py
 git commit -m "feat: add six-subject knowledge tree"
```

---

## Task 6: Implement the error book and question confirmation workflow

**Files:**
- Create: `backend/app/modules/errors/service.py`
- Create: `backend/app/modules/errors/router.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/modules/questions/service.py`
- Modify: `backend/app/api/v1/questions.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/features/errors/ErrorBookPage.tsx`
- Modify: `frontend/src/features/capture/CapturePage.tsx`
- Modify: `frontend/src/features/questions/QuestionDetailPage.tsx`
- Test: `tests/test_error_book_api.py`

**Interfaces:**
- `POST /api/v1/errors` accepts `{question_id, question_type?, tags?, error_reason?, note?}` and records `added_date` as local calendar date.
- `GET /api/v1/errors` accepts `subject`, `added_from`, `added_to`, `question_type`, `tag`, `status`, `search`, `limit`, `offset`.
- `PATCH /api/v1/errors/{id}` updates manual labels/status/note; `DELETE` removes only the error-book association.
- `GET /api/v1/errors/{id}` returns question detail, approved version, AI/manual label sources, added date, and linked conversation summary.
- `POST /api/v1/questions/{id}/confirm` creates an immutable approved version from user-confirmed fields.

- [ ] **Step 1: Write failing API tests**

```python
def test_add_error_book_entry_records_local_date(client, question):
    response = client.post('/api/v1/errors', json={'question_id': question.id, 'question_type':'函数','tags':['待复习']})
    assert response.status_code == 201
    assert response.json()['added_date'] == date.today().isoformat()
    assert response.json()['question_type_source'] == 'manual'

def test_error_book_filters_by_subject_type_and_date(client):
    response = client.get('/api/v1/errors', params={'subject':'数学','question_type':'函数','added_from':'2026-09-01','added_to':'2026-09-02'})
    assert response.status_code == 200
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `pytest tests/test_error_book_api.py -q`
Expected: FAIL because error routes and confirmation endpoint do not exist.

- [ ] **Step 3: Implement services and UI workflow**

Add the association service with AI labels as suggestions and explicit manual override metadata. The Capture page shows `加入错题本` only after a question has usable content; it pre-fills AI subject/type/method tags and allows edits before POST. The error book lists by date and tags, displays date only, and links into question detail. Question confirmation copies normalized content to a new version, preserving the original AI output and invalidating no historical paper version. Use existing conversation ownership checks.

- [ ] **Step 4: Verify API and browser build**

Run: `pytest tests/test_error_book_api.py -q; pytest -q; cd frontend; npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/errors backend/app/modules/questions backend/app/api/v1 frontend/src tests/test_error_book_api.py
 git commit -m "feat: add editable error book workflow"
```

---

## Task 7: Add robust question-internal conversation and rich content rendering

**Files:**
- Modify: `backend/app/modules/conversations/service.py`
- Modify: `backend/app/ai/gateway.py`
- Modify: `backend/app/api/v1/conversations.py`
- Create: `frontend/src/components/RichContent.tsx`
- Create: `frontend/src/features/conversations/QuestionChat.tsx`
- Modify: `frontend/src/features/questions/QuestionDetailPage.tsx`
- Modify: `frontend/src/features/capture/CapturePage.tsx`
- Modify: `frontend/package.json`
- Test: `tests/test_question_conversation.py`
- Test: `frontend/src/components/RichContent.test.tsx`

**Interfaces:**
- `ConversationService.send(question_id, text, conversation_id=None, client_request_id=None, mode='explain') -> ConversationDTO`.
- Context sent to AI includes approved/current question version, image reference, knowledge paths, compact summary, and recent 4–8 message window.
- `RichContent` accepts `{content: string, enableMath?: boolean, compact?: boolean}` and renders Markdown/GFM/KaTeX safely.

- [ ] **Step 1: Write failing conversation and renderer tests**

```python
@pytest.mark.asyncio
async def test_duplicate_client_request_is_idempotent(...):
    first = await service.send('q1', '为什么第二步？', client_request_id='r1')
    second = await service.send('q1', '为什么第二步？', client_request_id='r1')
    assert first['assistant_message_id'] == second['assistant_message_id']

def test_rich_content_renders_math_delimiter():
    render(<RichContent content={'content': '面积为 $S=\\pi r^2$'} />)
    expect(screen.getByText(/S/)).toBeInTheDocument()
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `pytest tests/test_question_conversation.py -q; cd frontend; npm test -- --run src/components/RichContent.test.tsx`
Expected: FAIL because summary/idempotency context and RichContent dependencies do not exist.

- [ ] **Step 3: Implement bounded context and UI**

Use the current question's approved version as primary context; include only recent messages and a bounded summary. On long conversations, update the summary and retain the most recent window. Honor `client_request_id` before making an AI call. Preserve question text and answer as immutable unless the explicit confirmation endpoint is used. Add Markdown/GFM/KaTeX dependencies and normalize common `$`, `$$`, `\\(`, `\\[` delimiters based on the DeepTutor renderer pattern; do not execute HTML or arbitrary code. The question detail page shows step-by-step content, related knowledge paths, and a persistent question chat.

- [ ] **Step 4: Verify tests and build**

Run: `pytest tests/test_question_conversation.py -q; cd frontend; npm test -- --run src/components/RichContent.test.tsx; npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/conversations backend/app/ai backend/app/api/v1/conversations.py frontend tests/test_question_conversation.py
 git commit -m "feat: add grounded question chat and rich content"
```

---

## Task 8: Complete subject-aware paper library and immutable PDF exports

**Files:**
- Modify: `backend/app/modules/papers/schemas.py`
- Modify: `backend/app/modules/papers/service.py`
- Modify: `backend/app/api/v1/papers.py`
- Modify: `backend/app/documents/pdf_service.py`
- Modify: `frontend/src/features/papers/PapersPage.tsx`
- Modify: `frontend/src/api/types.ts`
- Test: `tests/test_papers_workflow.py`

**Interfaces:**
- `GET /api/v1/papers/candidates` filters `subject`, `grade`, `question_type`, `knowledge_node_id`, `method`, `difficulty`, `error_only`.
- `POST /api/v1/papers` accepts title, subject, grade, items `{question_id, question_version_id, position, points, section_name}`.
- `POST /api/v1/papers/{id}/generate` accepts `formats: ['student','answer','analysis']` and returns a job ID.
- PDF output is stored as local assets and remains linked to fixed `question_version_id` values.

- [ ] **Step 1: Write failing snapshot/version tests**

```python
def test_old_paper_uses_fixed_question_version_after_question_edit(client, paper, question):
    old_pdf = client.post(f'/api/v1/papers/{paper.id}/generate', json={'formats':['student']}).json()
    client.post(f'/api/v1/questions/{question.id}/confirm', json={'stem':'新版题干'})
    new_pdf = client.get(f'/api/v1/papers/{paper.id}').json()
    assert new_pdf['items'][0]['question_version_id'] == paper.items[0].question_version_id
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_papers_workflow.py -q`
Expected: FAIL because candidate filters/formats and fixed version export are incomplete.

- [ ] **Step 3: Implement subject filters, ordering and PDF formats**

Keep question text out of paper duplication; validate every item version belongs to its question. Generate student, answer and optional analysis HTML/PDF from the fixed version content, with Chinese font fallback, safe image paths, page-break rules and math content prepared by the shared renderer/template. Return explicit queued/processing/completed/failed status and do not block forever in an HTTP request.

- [ ] **Step 4: Verify PDF and frontend behavior**

Run: `pytest tests/test_papers_workflow.py -q; pytest -q; cd frontend; npm run build`
Expected: PASS; generated assets exist and old paper content remains stable after edits.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/papers backend/app/documents frontend/src/features/papers frontend/src/api/types.ts tests/test_papers_workflow.py
 git commit -m "feat: add subject-aware versioned paper exports"
```

---

## Task 9: Finish settings, local storage maintenance, and future device boundary

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/app/api/v1/settings.py`
- Modify: `backend/app/api/v1/device.py`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `tests/test_settings_device_boundary.py`
- Create: `scripts/check-data.ps1`

**Interfaces:**
- Settings supports DeepSeek text/vision model, base URL, parse mode, AI review toggle, image retention, compression and local data path; secret values are write-only.
- Device API exposes only `device:question:read`, `device:question:write`, `device:chat:write`, `device:knowledge:read`; it never exposes paper/PDF/settings/prompt/backup routes.
- `GET /api/v1/device/questions/{id}/display?step=1` returns bounded display DTO with `schema_version`, `revision`, `step_index`, `total_steps`.

- [ ] **Step 1: Write failing boundary tests**

```python
def test_device_token_cannot_access_papers(client, device_token):
    response = client.get('/api/v1/papers', headers={'Authorization': f'Bearer {device_token}'})
    assert response.status_code in (401, 403)

def test_settings_never_returns_api_key(client):
    payload = client.get('/api/v1/settings').json()
    assert 'DEEPSEEK_API_KEY' not in payload
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_settings_device_boundary.py -q`
Expected: FAIL because the current settings/device routes are not fully scope-aware.

- [ ] **Step 3: Implement settings and maintenance**

Add write-only secret handling, test-connection endpoint that does not persist failed configuration, local date/time settings, object integrity/cleanup checks, compressed-content maintenance and an export/backup command that excludes secrets. Apply scope checks on the server, not just navigation. Keep default bind `127.0.0.1`; expose LAN/VPN only through explicit configuration.

- [ ] **Step 4: Verify security and clean-data checks**

Run: `pytest tests/test_settings_device_boundary.py -q; pytest -q; powershell -ExecutionPolicy Bypass -File scripts/check-data.ps1`
Expected: PASS; script reports no broken object references in a clean test data directory.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core backend/app/api/v1/settings.py backend/app/api/v1/device.py frontend/src/features/settings frontend/src/api/client.ts tests/test_settings_device_boundary.py scripts/check-data.ps1
 git commit -m "feat: harden local settings and device boundary"
```

---

## Task 10: End-to-end six-board acceptance and regression verification

**Files:**
- Create: `tests/test_six_subject_flow.py`
- Create: `frontend/src/app/navigation.test.tsx`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `scripts/dev.ps1` only if startup needs correction

**Interfaces:**
- Acceptance flow: capture → preflight → parse/review → confirm → knowledge link → error-book add/filter → question chat → paper candidate/select/generate.
- Startup remains `scripts/dev.ps1`; no Supabase or server database required.

- [ ] **Step 1: Add a Fake Provider full-loop test**

```python
def test_six_subject_capture_to_paper_flow(app_client, fake_provider):
    for subject in ('数学','物理','化学','生物','语文','英语'):
        question = upload_and_parse(app_client, subject=subject)
        assert question['subject'] == subject
        app_client.post(f"/api/v1/questions/{question['id']}/confirm", json={})
        app_client.post('/api/v1/errors', json={'question_id': question['id']})
    assert app_client.get('/api/v1/errors', params={'subject':'数学'}).status_code == 200
    paper = create_paper_from_candidates(app_client, subject='数学')
    assert generate_student_pdf(app_client, paper)['status'] in ('queued','completed')
```

- [ ] **Step 2: Run focused test and frontend navigation test**

Run: `pytest tests/test_six_subject_flow.py -q; cd frontend; npm test -- --run src/app/navigation.test.tsx`
Expected: FAIL until all preceding API contracts and routes are wired.

- [ ] **Step 3: Update startup documentation and implement only discovered wiring fixes**

Document six active sections, exact local startup, demo mode, DeepSeek text/vision configuration, local SQLite/object storage, and explicitly state that Daily Mistakes, Exam Statistics and External Content are not yet implemented. Do not add those navigation entries or speculative APIs. Fix only integration issues proven by the failing acceptance test.

- [ ] **Step 4: Run the complete verification matrix**

Run:

```powershell
py -m pip install -e ".[dev]"
pytest -q
cd frontend
npm run build
```

Then run the app with `scripts/dev.ps1`, verify `GET /api/v1/health`, open the six routes, upload one demo image without an API key, and if credentials are available run one real DeepSeek high-school sample. Confirm no key appears in browser network payloads or logs and verify the generated PDF opens.

Expected: all automated tests/builds pass; local app starts; six active boards are reachable; deferred boards remain absent; data survives restart.

- [ ] **Step 5: Commit final acceptance updates**

```bash
git add README.md .env.example scripts tests frontend/src
 git commit -m "test: verify six-subject local study workflow"
```

---

## Verification Checklist

- [ ] Six active navigation boards are present; three deferred boards are absent.
- [ ] Each of the six subjects has a knowledge root; English knowledge contains composition material only, while words live in the separate vocabulary store.
- [ ] A photo/text input cannot proceed to formal parsing when preflight reports missing information or unsupported scope.
- [ ] AI output is structurally validated, marked uncertain when necessary, and auditable by policy/model/usage fields.
- [ ] User confirmation is required before a question becomes an approved reusable version.
- [ ] Error-book records show only the added calendar date and can be filtered by subject/type/tag/date.
- [ ] Question-internal chat is grounded in the selected question and idempotent under client retries.
- [ ] Rich content displays Markdown and high-school formulas safely.
- [ ] Paper candidates filter by subject and fixed version IDs; old papers do not change after question edits.
- [ ] Student, answer and optional analysis PDF generation has explicit status and local asset output.
- [ ] Device-scoped credentials cannot access papers, PDFs, prompts, settings or backups.
- [ ] Default local deployment needs no Supabase or database server and preserves data after restart.
- [ ] Ordinary high-school English questions remain solvable; only confirmed composition material enters English Knowledge.
- [ ] The vocabulary store supports 3500-word preview/commit import, daily photo/manual lookup, selected save, standard senses and removable personal aliases.
- [ ] Vocabulary passage supports any-sense and POS-grouped all-senses modes; same-POS answers are order-independent and duplicate answers cannot satisfy multiple senses.
- [ ] Failed rule matches expose standard meanings for user adjudication; accepted answers become sense-bound aliases and match automatically later.
- [ ] A fixed daily vocabulary task is generated at the configured local time or caught up on startup, and home shows its progress without adding a seventh navigation board.
