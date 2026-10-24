import { useState } from "react";
import ReviewSettings from "./ReviewSettings";
import CloudCatalog from "./CloudCatalog";
import { useAccount } from "../../features/accounts/AuthGate";
import { Preferences, STEM } from "./types";
import { Header, Notice, patch, useData, message } from "./shared";

type Settings = {
  preferences: Preferences;
  recognition: { mode: "local" | "api"; ink: "off" | "red" | "red_blue"; pencil: "off" | "gentle" | "balanced" | "strong"; formula: boolean; structured_formula?:boolean; formula_threshold?:number;document_ocr_ready?:boolean; ready: boolean; formula_ready: boolean; available: boolean; message: string };
  ai: {
    configured: boolean;
    base_url: string;
    model: string;
    vision_model: string;
  };
};
function Editor({ data }: { data: Settings }) {
  const [p, setP] = useState(data.preferences),
    [recognition, setRecognition] = useState(data.recognition),
    [key, setKey] = useState(""),
    [base, setBase] = useState(data.ai.base_url),
    [model, setModel] = useState(data.ai.model),
    [vision, setVision] = useState(data.ai.vision_model),
    [configured, setConfigured] = useState(data.ai.configured),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("");
  const number = (
    name: keyof Preferences,
    title: string,
    min: number,
    max: number,
    step = 1,
  ) => (
    <label key={name}>
      {title}
      <input
        className="input"
        type="number"
        min={min}
        max={max}
        step={step}
        value={Number(p[name])}
        onChange={(e) => setP({ ...p, [name]: Number(e.target.value) })}
      />
    </label>
  );
  async function save(aiOnly = false) {
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const r = await patch<Settings>(
        "/learning/settings",
        aiOnly
          ? {
              ai: {
                base_url: base,
                model,
                vision_model: vision,
                ...(key ? { key } : {}),
              },
            }
          : { preferences: p },
      );
      setP(r.preferences);
      setConfigured(r.ai.configured);
      setKey("");
      setSaved(
        aiOnly ? "AI设置已保存" : "学习规则已保存，影响后续尚未生成的安排",
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function saveRecognition() {
    setBusy(true); setError(""); setSaved("");
    try {
      const result = await patch<Settings>("/learning/settings", { recognition: { mode: recognition.mode, ink: recognition.ink, formula: recognition.formula, pencil: recognition.pencil, structured_formula:!!recognition.structured_formula,formula_threshold:recognition.formula_threshold??.985 } });
      setRecognition(result.recognition);
      setSaved("图片识别设置已保存，影响下一次识别");
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return (
    <>
      <Notice error={error} />
      {saved && <Notice>{saved}</Notice>}
      <section className="panel">
        <h2>图片识别与笔迹处理</h2>
        <p>{recognition.message}</p>
        <label>识别方式<select className="select" value={recognition.mode} onChange={e => setRecognition({ ...recognition, mode: e.target.value as "local" | "api" })}>
          <option value="local">本地识别（默认，无API调用费）</option><option value="api">外部AI识别（使用下方服务，会产生调用费用）</option>
        </select></label>
        <p className="muted">题目文字、答案照片和答案页索引使用所选方式。本地识别失败时保留原件，提示核对；AI解题、解析和批改仍由你主动请求。</p>
        {recognition.mode === "local" && <>
          <label>题目照片的笔迹颜色<select className="select" value={recognition.ink} onChange={e => setRecognition({ ...recognition, ink: e.target.value as "off" | "red" | "red_blue" })}>
            <option value="red">清理红色笔迹</option><option value="red_blue">清理红色和蓝色笔迹</option><option value="off">保留全部颜色（原题含彩色标注时选择）</option>
          </select></label>
          <label>铅笔与背景处理<select className="select" value={recognition.pencil} onChange={e => setRecognition({ ...recognition, pencil: e.target.value as "off" | "gentle" | "balanced" | "strong" })}><option value="balanced">标准减淡（默认）</option><option value="gentle">轻度减淡</option><option value="strong">强度减淡（须核对浅色印刷线）</option><option value="off">关闭（彩色原题或保留灰线）</option></select></label>
          <p className="muted">铅笔按灰度减淡，深色和重叠笔迹可在题图工具中局部涂抹。强度处理可能影响浅色印刷线；曲线、虚线与选项编号须核对并确认打印图。人工答案照片始终保留笔迹。</p>
          <label className="check-label"><input type="checkbox" checked={!!recognition.structured_formula} onChange={e=>setRecognition({...recognition,structured_formula:e.target.checked})}/>高精度公式与化学式转录（本地 AI 辅助）</label>
          <label>公式自动采用的置信门槛<input className="input" type="number" min=".98" max=".999" step=".001" value={recognition.formula_threshold??.985} onChange={e=>setRecognition({...recognition,formula_threshold:Number(e.target.value)})}/></label>
          <p className="muted">按字框裁出公式，比较原始与光照归一化两种视图，再复核数字、物态和符号。通过的内容转为可编辑公式；未通过的部分保留原位小图。模型置信度不代表准确率，仍须校对。全程在本机处理，无外部调用费。{!recognition.document_ocr_ready&&'本地文档模型尚未安装。'}</p>
          <label className="check-label"><input type="checkbox" checked={recognition.formula} onChange={e => setRecognition({ ...recognition, formula: e.target.checked })} />旧版独立公式模型（实验选项，默认关闭）</label>
          <p className="muted">默认使用普通OCR文字与原图。公式模型对字体、大小写及上下标敏感，启用后也需核对，并可能增加耗时。</p>
          {!recognition.formula_ready && recognition.formula && <p className="muted">公式模型尚未准备好，暂保留普通识别文字及原图供核对。</p>}
        </>}
        <button className="button primary" disabled={busy} onClick={saveRecognition}>保存图片识别设置</button>
      </section>
      <div className="content-grid">
        <section className="panel">
          <h2>学习规则与每日体量</h2>
          {number("redo_days", "首次错题重做目标间隔（天）", 1, 365)}
          <label className="check-label"><input type="checkbox" checked={!!p.type_review_enabled} onChange={e => setP({ ...p, type_review_enabled: e.target.checked })} />启用题型定期重推（选用，默认关闭）</label>
          {number(
            "mastery_threshold",
            "题型启用的历史错题过手阈值（%）",
            1,
            100,
          )}
          {number("daily_minutes", "四科每日正常预计用时（分钟）", 1, 600, 1)}
          <p className="muted">
            必要时最高 {Math.round(p.daily_minutes * 1.2 * 100) / 100}{" "}
            分钟，硬上限为正常预算的120%。单题可以另改预计时间。
          </p>
          {number(
            "default_question_minutes",
            "新题默认预计用时（分钟）",
            0.5,
            120,
            0.5,
          )}
          {number("correct_rounds", "连续正确几轮后降频", 1, 20)}
          {number("wrong_rounds", "连续错误几轮后升频", 1, 20)}
          {number(
            "type_min_questions",
            "题型一轮最少几题（不足则不推）",
            1,
            50,
          )}
          <label className="check-label">
            <input
              type="checkbox"
              checked={p.priority_enabled}
              onChange={(e) =>
                setP({ ...p, priority_enabled: e.target.checked })
              }
            />
            排不开时优先指定学科
          </label>
          <div className="check-grid">
            {STEM.map((s) => (
              <label className="check-label" key={s}>
                <input
                  type="checkbox"
                  checked={p.priority_subjects.includes(s)}
                  onChange={(e) =>
                    setP({
                      ...p,
                      priority_subjects: e.target.checked
                        ? [...p.priority_subjects, s]
                        : p.priority_subjects.filter((x) => x !== s),
                    })
                  }
                />
                {s}
              </label>
            ))}
          </div>
          <label className="check-label">
            <input
              type="checkbox"
              checked={p.auto_recognize}
              onChange={(e) => setP({ ...p, auto_recognize: e.target.checked })}
            />
            拍题后自动识别原题文字（解析始终由你选择）
          </label>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => save()}
          >
            保存学习设置
          </button>
        </section>
        <section className="panel">
          <h2>AI解题、解析与批改 · {configured ? "已配置密钥" : "尚未配置"}</h2>
          <p className="muted">
            兼容Chat
            Completions的服务；图像模型需要支持视觉输入。密钥保存在本机，不回传到界面。
          </p>
          <label>
            API地址
            <input
              className="input"
              value={base}
              onChange={(e) => setBase(e.target.value)}
            />
          </label>
          <label>
            文本模型
            <input
              className="input"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </label>
          <label>
            视觉模型
            <input
              className="input"
              value={vision}
              onChange={(e) => setVision(e.target.value)}
            />
          </label>
          <label>
            API密钥
            <input
              className="input"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={configured ? "留空保留现有密钥" : "填写你的密钥"}
            />
          </label>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => save(true)}
          >
            保存AI设置
          </button>
          <p>
            本地图片识别无需AI密钥。AI密钥用于主动请求的解题、解析、批改及选择外部识别时的图片处理。
          </p>
        </section>
      </div>
      <ReviewSettings />
    </>
  );
}
export default function SettingsPage() {
  const account = useAccount();
  const { data, error } = useData<Settings>("/learning/settings");
  return (
    <div className="page learning-page">
      <Header
        title="设置"
        detail="按账号保存本机学习数据；已经生成的试卷、答案基准及周报告保留原样。"
      />
      <Notice error={error} />
      {data ? <Editor data={data} /> : <p>正在读取设置…</p>}
      {account.user && <CloudCatalog />}
    </div>
  );
}
