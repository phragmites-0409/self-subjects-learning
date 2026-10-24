"""Conservative subject suggestions from recognized text, with no remote calls."""

import re


TERMS = {
    "数学": ("函数", "方程", "不等式", "数列", "导数", "积分", "概率", "椭圆", "抛物线", "双曲线", "复数", "三角函数", "集合", "向量", "定义域", "值域", "单调", "极值", "几何", "直线", "圆锥曲线", "斜率", "三角形", "矩阵"),
    "物理": ("电场", "电势", "等势", "电荷", "电流", "电压", "电阻", "磁场", "磁感", "粒子", "电子", "质点", "小球", "机械能", "动能", "势能", "摩擦", "弹簧", "加速度", "牛顿", "匀速", "匀变速", "重力", "动量", "波长", "振动", "简谐", "横波", "纵波", "波形", "周期", "透镜", "折射", "热力学", "光电效应"),
    "化学": ("化学", "氧化", "还原", "溶液", "溶质", "溶剂", "电解", "电极", "化合物", "催化", "反应速率", "化学平衡", "离子", "分子", "原子", "元素", "沉淀", "摩尔", "有机", "烷", "烯", "苯", "乙醇", "盐酸", "硫酸", "氢氧化", "酸碱", "酯化"),
    "生物": ("细胞", "遗传", "基因", "染色体", "蛋白质", "核酸", "光合作用", "呼吸作用", "有丝分裂", "减数分裂", "生态", "食物链", "种群", "群落", "抗体", "免疫", "神经", "激素", "酶", "孟德尔", "性状", "转录", "翻译", "DNA", "RNA"),
    "语文": ("文言", "古诗", "诗歌", "诗句", "诗人", "文学", "修辞", "成语", "病句", "字音", "字形", "汉字", "散文", "小说", "论述类", "实用类", "现代文", "语言文字运用", "默写", "句式", "作者", "段落", "文中", "加点字", "加点词"),
    "英语": ("完形填空", "语法填空", "英语", "读后续写", "七选五", "定语从句", "非谓语", "过去分词", "过去完成时", "短文改错"),
}


def detect_subject(stem: str, options=None) -> dict:
    text = "\n".join([stem or "", *(options or [])])
    scores = {subject: sum(bool(re.search(re.escape(term), text, re.I)) for term in terms)
              for subject, terms in TERMS.items()}
    # English question prose is stronger evidence than isolated formula symbols.
    words = re.findall(r"\b[a-zA-Z]{2,}\b", text)
    common_words = {"the", "a", "an", "is", "are", "of", "and", "to", "in", "for", "with", "which", "what", "choose", "following", "read", "from", "that", "have", "be", "was", "by"}
    if len(words) >= 8 and len(set(word.lower() for word in words) & common_words) >= 3 and len(re.findall(r"[\u4e00-\u9fff]", text)) < len(words) * 2:
        scores["英语"] += 4
    if re.search(r"\b(?:NaOH|H2SO4|HCl|NaCl|CuSO4|CH3COOH)\b", text):
        scores["化学"] += 2
    if re.search(r"(?:[xy]\s*[+−=]|[xy]\s*\^\s*\d|\\(?:sin|cos|log|frac))", text):
        scores["数学"] += 1
    if re.search(r"[xy].*=[^=]", text) and not re.search(r"[\u4e00-\u9fff]", text):
        scores["数学"] += 2
    ranked = sorted(scores, key=scores.get, reverse=True)
    best, second = ranked[:2]
    # Abstain on weak or tied evidence instead of labeling every photo as math.
    subject = best if scores[best] >= 2 and scores[best] > scores[second] else ""
    return {"subject": subject, "engine": "local-text", "scores": scores}
