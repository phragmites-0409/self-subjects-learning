import { api } from "../../api/client";
import { post } from "./shared";
import { Question, SUBJECTS, localDay } from "./types";

export type IntakeContext = {
  from: "capture" | "knowledge" | "plan";
  subject?: string;
  branch?: string;
  node_id?: string;
  day?: string;
};

export function contextFromParams(params: URLSearchParams): IntakeContext {
  return {
    from: params.get("from") === "knowledge" ? "knowledge" : params.get("from") === "plan" ? "plan" : "capture",
    subject: SUBJECTS.includes(params.get("subject") || "") ? params.get("subject")! : undefined,
    branch: params.get("branch") || undefined,
    node_id: params.get("node") || undefined,
    day: params.get("day") || undefined,
  };
}

export function capturePath(context: IntakeContext): string {
  const params = new URLSearchParams({ from: context.from });
  if (context.subject) params.set("subject", context.subject);
  if (context.branch) params.set("branch", context.branch);
  if (context.node_id) params.set("node", context.node_id);
  if (context.day) params.set("day", context.day);
  return `/capture?${params}`;
}

export function questionPath(id: string, context?: IntakeContext): string {
  const query = context ? new URL(capturePath(context), "http://local").search : "";
  return `/questions/${encodeURIComponent(id)}${query}`;
}

export function returnPath(context?: IntakeContext): string {
  if (context?.from === "plan") return "/#daily-uploads";
  if (context?.from === "knowledge") {
    const params = new URLSearchParams();
    if (context.subject) params.set("subject", context.subject);
    if (context.branch) params.set("branch", context.branch);
    if (context.node_id) params.set("node", context.node_id);
    return `/knowledge?${params}`;
  }
  return "/capture";
}

export async function uploadQuestion(input: File | File[], text = ""): Promise<string> {
  const files = Array.isArray(input) ? input : [input];
  if (!files.length || files.length > 8) throw new Error("同一道题请选择1至8张照片");
  const form = new FormData();
  files.forEach(file => form.append(files.length===1 ? "file" : "files", file));
  form.append("text", text);
  const uploaded = await api<{ question_id: string }>(files.length===1 ? "/assets" : "/learning/intake/photos", { method: "POST", body: form });
  return uploaded.question_id;
}

export function createIntake(context: IntakeContext, input: { question_id?: string; text?: string; subject?: string; is_error?: boolean; day?: string }) {
  return post<Question>("/learning/intake", {
    ...input,
    subject: input.subject || "",
    is_error: input.is_error ?? true,
    day: input.day || context.day || localDay(),
    context,
  });
}
