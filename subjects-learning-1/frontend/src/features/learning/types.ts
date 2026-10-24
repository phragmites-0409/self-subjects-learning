export const STEM = ["数学", "物理", "化学", "生物"];
export const SUBJECTS = [...STEM, "语文", "英语"];
export type Event = {
  id: string;
  kind: string;
  subject: string;
  title: string;
  day: string;
  day_label: string;
  week: string;
  status: string;
  minutes: number;
  deadline_label: string;
  data: Record<string, any>;
};
export type Node = {
  id: string;
  name: string;
  subject: string;
  kind: string;
  parent_id: string | null;
  summary: string;
  active: boolean;
  cadence: number | null;
  target_label: string | null;
  mastery: { total: number; mastered: number; ratio: number | null } | null;
  data: Record<string, any>;
};
export type Question = {
  id: string;
  subject: string;
  question_type: string;
  status: string;
  tags: string[];
  content: { stem?: string; options?: string[]; has_diagram?: boolean; subject?: string };
  version_id: string;
  source_asset_id: string | null;
  source_sha256: string | null;
  topic_id: string | null;
  minutes: number;
  answer: string;
  answer_confirmed: boolean;
  ever_wrong: boolean;
  mastered: boolean;
  data: Record<string, any>;
  historical?: boolean;
  versions?: { id: string; number: number; source: string }[];
  occurrences?: {
    id: string;
    day_label: string;
    target: string;
    status: string;
  }[];
};
export type Item = {
  id: string;
  question_id: string;
  event_id: string;
  position: number;
  verdict: string;
  status: string;
  data: Record<string, any>;
};
export type Round = {
  id: string;
  kind: string;
  subject: string;
  topic_id: string | null;
  target_label: string;
  status: string;
  data: Record<string, any>;
  items: Item[];
  events: Event[];
};
export type Preferences = {
  redo_days: number;
  mastery_threshold: number;
  daily_minutes: number;
  priority_enabled: boolean;
  priority_subjects: string[];
  correct_rounds: number;
  wrong_rounds: number;
  type_min_questions: number;
  default_question_minutes: number;
  auto_recognize: boolean;
};
export type Report = {
  week: string;
  label: string;
  completed: Event[];
  unfinished: Event[];
  abandoned: Event[];
  events: Event[];
  carried: string[];
};
export type Dashboard = {
  day: string;
  day_label: string;
  week_end_label: string;
  preferences: Preferences;
  minutes: number;
  maximum: number;
  events: Event[];
  upcoming: Event[];
  uploads: Event[];
  pending_errors: number;
  pending_minutes: number;
  reports: Report[];
  plan_notes: string[];
  waiting_topics: { id: string; name: string }[];
};

export function dateLabel(value: string) {
  const d = new Date(`${value.slice(0, 10)}T12:00:00`);
  return `${d.getMonth() + 1}月${d.getDate()}日（星期${"日一二三四五六"[d.getDay()]}）`;
}
export function localDay() {
  return new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}
export const statusLabel: Record<string, string> = {
  open: "待处理",
  planned: "未来安排",
  completed: "已完成",
  abandoned: "已放弃",
  pending: "待处理",
  assigned: "已安排",
  processed: "本轮已处理",
  mastered: "已过手",
  corrected: "已人工纠正",
  resolved: "已处理",
  judged: "待过手或学习确认",
};
