import { useState } from "react";
import { Preferences, STEM } from "./types";
import { Header, Notice, patch, useData, message } from "./shared";

type Settings = {
  preferences: Preferences;
  ai: {
    configured: boolean;
    base_url: string;
    model: string;
    vision_model: string;
  };
};
function Editor({ data }: { data: Settings }) {
  const [p, setP] = useState(data.preferences),
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
  return (
    <>
      <Notice error={error} />
      {saved && <Notice>{saved}</Notice>}
      <div className="content-grid">
        <section className="panel">
          <h2>学习规则与每日体量</h2>
          {number("redo_days", "首次错题重做目标间隔（天）", 1, 365)}
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
          <h2>AI服务 · {configured ? "已配置密钥" : "尚未配置"}</h2>
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
            未配置AI也可手工校对、确认答案、人工批改，并使用排期、重做、题型检测和周报告。
          </p>
        </section>
      </div>
    </>
  );
}
export default function SettingsPage() {
  const { data, error } = useData<Settings>("/learning/settings");
  return (
    <div className="page learning-page">
      <Header
        title="设置"
        detail="单机单人使用；已经生成的试卷、答案基准及周报告保留原样。"
      />
      <Notice error={error} />
      {data ? <Editor data={data} /> : <p>正在读取设置…</p>}
    </div>
  );
}
