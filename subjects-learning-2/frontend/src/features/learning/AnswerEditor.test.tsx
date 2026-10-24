import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import AnswerEditor from "./AnswerEditor";
import { Question } from "./types";

const question: Question = {id:"q1",subject:"数学",question_type:"方程",status:"draft",tags:[],content:{stem:"x+1=2"},version_id:"v1",source_asset_id:null,source_sha256:null,topic_id:"t1",minutes:8,answer:"",answer_confirmed:false,ever_wrong:false,mastered:false,data:{}};
const response = (data: unknown) => ({ok:true,json:async () => data});
afterEach(() => {cleanup();vi.unstubAllGlobals();});
const renderEditor = (q=question) => render(<MemoryRouter><AnswerEditor q={q} onSaved={() => {}} /></MemoryRouter>);

describe("answer-source decisions", () => {
  it("offers exactly three sources and accepts manual answer without a confirmation checkbox or AI", async () => {
    const fetch=vi.fn(async (_url: string, _options?: RequestInit) => response({...question,answer:"1",answer_confirmed:true,data:{answer_source:"manual"}}));vi.stubGlobal("fetch",fetch);
    renderEditor();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("人工答案"),{target:{value:"1"}});
    fireEvent.click(screen.getByRole("button",{name:"保存人工答案"}));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(String(fetch.mock.calls[0][0])).toContain("/learning/questions/q1/answer");
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toMatchObject({source:"manual",answer:"1",explanation:""});
  });
  it("manual explanation alone can be saved", async () => {
    vi.stubGlobal("fetch",vi.fn(async () => response(question)));
    renderEditor();
    fireEvent.change(screen.getByLabelText("人工解析（可选）"),{target:{value:"等式两边减去1"}});
    expect(screen.getByRole("button",{name:"保存人工答案"})).toBeEnabled();
  });
  it("AI draft exposes an unchecked explicit confirmation and sends only that decision", async () => {
    const fetch=vi.fn(async (_url: string,_options?:RequestInit) => response(question));vi.stubGlobal("fetch",fetch);
    renderEditor({...question,answer:"1",data:{answer_source:"ai",answer_explanation:"两边减一"}});
    const confirmation=screen.getByRole("checkbox",{name:"我已核对AI答案和解析"});
    expect(confirmation).not.toBeChecked();
    fireEvent.click(confirmation);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({answer_confirmed:true});
  });
  it("requests complete AI analysis then adopts it without confirming automatically", async () => {
    const fetch=vi.fn(async (_url: string,_options?:RequestInit) => response(question));vi.stubGlobal("fetch",fetch);
    renderEditor();
    fireEvent.click(screen.getByRole("radio",{name:"AI作答，人工确认"}));
    fireEvent.click(screen.getByRole("button",{name:"生成答案和解析"}));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(String(fetch.mock.calls[0][0])).toContain("/analysis");
    expect(String(fetch.mock.calls[1][0])).toContain("/answer/use-ai");
    expect(fetch.mock.calls.every(call => !String(call[1]?.body).includes('"answer_confirmed":true'))).toBe(true);
  });
  it("bank lookup presents candidates and only crops after choosing one", async () => {
    const match={document_id:"d1",book:"练习册",edition:"2026",chapter:"第一章",number:"2",filename:"整页.pdf",entries:[{page_number:1,answer:"B",explanation:"解析",asset_id:"a1"}]};
    const fetch=vi.fn(async (url: string,_options?:RequestInit) => response(url.includes("/lookup") ? {items:[match]} : question));vi.stubGlobal("fetch",fetch);
    renderEditor();
    fireEvent.click(screen.getByRole("radio",{name:"从答案库提取"}));
    fireEvent.change(screen.getByLabelText("资料名"),{target:{value:"练习册"}});
    fireEvent.change(screen.getByLabelText("题号"),{target:{value:"2"}});
    fireEvent.click(screen.getByRole("button",{name:"查找答案"}));
    const apply=await screen.findByRole("button",{name:"提取此答案并自动裁切"});
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(apply);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(String(fetch.mock.calls[1][0])).toContain("/answer-bank/apply/q1");
    expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({document_id:"d1",chapter:"第一章",number:"2"});
  });
});
