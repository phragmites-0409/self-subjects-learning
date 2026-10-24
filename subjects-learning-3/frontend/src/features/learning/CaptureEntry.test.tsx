import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import CaptureEntry from "./CaptureEntry";

afterEach(() => {cleanup();vi.unstubAllGlobals();});
const response = (value: unknown, ok=true) => ({ok, json:async()=>value});
function renderEntry() {
  render(<MemoryRouter><Routes><Route path="/" element={<CaptureEntry context={{from:"plan",subject:"数学",day:"2026-10-14"}} />} /><Route path="/questions/:id" element={<p>已进入校对</p>} /></Routes></MemoryRouter>);
}

it("one photo selection enters proofreading with automatic subject and retained daily context", async () => {
  const fetch = vi.fn(async (url: string, _options?: RequestInit) => response(url.endsWith("/assets") ? {question_id:"q1"} : {id:"q1"}));
  vi.stubGlobal("fetch",fetch);renderEntry();
  fireEvent.change(screen.getByLabelText("拍题录入照片"), {target:{files:[new File(["photo"],"q.png",{type:"image/png"})]}});
  await screen.findByText("已进入校对");
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toMatchObject({question_id:"q1",subject:"",is_error:true,day:"2026-10-14",context:{from:"plan",subject:"数学"}});
  expect(fetch.mock.calls.every(call => !/analysis|archive|parse/.test(String(call[0])))).toBe(true);
});

it("multiple photos wait for order confirmation and upload as one question", async () => {
  const fetch=vi.fn(async (url: string,_options?:RequestInit)=>response(url.endsWith("/intake/photos")?{question_id:"q1"}:{id:"q1"}));
  vi.stubGlobal("fetch",fetch);renderEntry();
  const first=new File(["first"],"first.png",{type:"image/png"}),second=new File(["second"],"second.png",{type:"image/png"});
  fireEvent.change(screen.getByLabelText("拍题录入照片"),{target:{files:[first,second]}});
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"第2张前移"}));
  fireEvent.click(screen.getByRole("button",{name:"按此顺序录入同一道题"}));
  await screen.findByText("已进入校对");
  expect(fetch).toHaveBeenCalledTimes(2);
  const form=fetch.mock.calls[0][1]?.body as FormData;
  expect(form.getAll("files").map(file=>(file as File).name)).toEqual(["second.png","first.png"]);
  expect(String(fetch.mock.calls[0][0])).toContain("/intake/photos");
});

it("a failed intake retries the existing uploaded draft instead of uploading the photo twice", async () => {
  let attempts=0;
  const fetch=vi.fn(async (url: string,_options?:RequestInit) => {
    if (url.endsWith("/assets")) return response({question_id:"q1"});
    attempts++;
    return attempts===1 ? response({error:{message:"暂时无法保存，请重试"}},false) : response({id:"q1"});
  });
  vi.stubGlobal("fetch",fetch);renderEntry();
  const photo=new File(["photo"],"q.png",{type:"image/png"});
  fireEvent.change(screen.getByLabelText("拍题录入照片"),{target:{files:[photo]}});
  await screen.findByText("暂时无法保存，请重试");
  await waitFor(()=>expect(screen.getByRole("button",{name:"拍题录入"})).toBeEnabled());
  fireEvent.change(screen.getByLabelText("拍题录入照片"),{target:{files:[photo]}});
  await screen.findByText("已进入校对");
  expect(fetch.mock.calls.filter(call => String(call[0]).endsWith("/assets"))).toHaveLength(1);
});

it("finishing a background upload does not move the user away from a page they chose", async () => {
  let resolveUpload!: (result: ReturnType<typeof response>) => void;
  const fetch=vi.fn(async (url: string) => url.endsWith("/assets") ? new Promise<ReturnType<typeof response>>(resolve=>{resolveUpload=resolve;}) : response({id:"q1"}));
  vi.stubGlobal("fetch",fetch);
  render(<MemoryRouter><Routes><Route path="/" element={<><Link to="/other">查看知识库</Link><CaptureEntry context={{from:"capture"}} /></>} /><Route path="/other" element={<p>知识库页面</p>} /><Route path="/questions/:id" element={<p>已进入校对</p>} /></Routes></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("拍题录入照片"),{target:{files:[new File(["photo"],"q.png",{type:"image/png"})]}});
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("link",{name:"查看知识库"}));
  resolveUpload(response({question_id:"q1"}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  expect(screen.getByText("知识库页面")).toBeInTheDocument();
  expect(screen.queryByText("已进入校对")).not.toBeInTheDocument();
});
