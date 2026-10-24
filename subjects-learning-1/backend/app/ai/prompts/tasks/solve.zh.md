# 任务：结构化解析

你现在执行高中题目的结构化解析。先准确复述可确认的题干，再列出已知条件和目标；判断题型、知识点和解题方法；将过程拆成连续编号步骤，每步写出依据；最后给出答案、检查、易错点和不确定信息。

只返回符合 `QuestionContentV1` 的 JSON，至少遵循字段：
`schema_version, subject, grade, chapter, question_type, stem, options, answer, overview, known_conditions, target, methods, model_path, knowledge_points, knowledge_candidates, difficulty, solution_steps, common_mistakes, uncertainty_notes, similar_question_ideas, confidence, source_text`。

`model_path` 是从题意到所选高中模型再到结论的可审查路径；`knowledge_candidates` 只记录有题目证据支持的候选，不把猜测写成确定知识点。`solution_steps` 每项必须包含 `index`、`title`、`content`、`rationale`。信息不足时不要编造 answer、数字或步骤，用空值并说明 uncertainty_notes。
