# 任务：题目前置判定

你现在执行题目前置判定。检查待分析数据是否属于高中六科、题干是否完整，以及选项、公式、表格和图形信息是否足够。

`decision` 只能是：
- `ready`：科目受支持且当前信息足以进入解析；
- `needs_more_info`：属于支持范围，但缺少明确的题干、条件或图像信息；
- `not_supported`：不是高中六科或超出高中范围；英语阅读、语法、完形、翻译和作文等高中题型属于支持范围。
- `uncertain`：证据不足，暂时不能可靠判断；保守地列出原因。

保留旧客户端可能发送的 `not_high_school` 兼容值时，不要把它当成新的推荐值。只返回符合 `PreflightResult` 的 JSON：
`{"schema_version":"preflight-v1","decision":"ready|needs_more_info|not_supported|uncertain","is_high_school":true,"missing_information":[],"concerns":[],"recognized_text":"","suggestion":""}`。
