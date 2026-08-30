"use client";

import { FormEvent, useState } from "react";
import { askQuestion, AskResponse } from "./ask-api";

const examples = ["查询齐鑫涛最近一个月业绩", "今年各区域销售额表现如何？", "哪些产品的增长最快？"];

export default function AnalyticsPage() {
  const [question, setQuestion] = useState(examples[0]);
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const value = question.trim();
    if (!value || busy) return;
    setSubmittedQuestion(value);
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await askQuestion(value));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "请求失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <aside className={sidebarOpen ? "side" : "side shut"}>
        <div className="brand"><span>数</span><strong>知数</strong></div>
        <button className="new" onClick={() => { setQuestion(""); setSubmittedQuestion(""); setResult(null); }}>＋ <span>新建问数</span></button>
        <nav>
          <small>工作台</small><button className="active">⌁ <span>智能问数</span></button><button>▥ <span>数据看板</span></button><button>◇ <span>指标中心</span></button>
          <small>示例问题</small>{examples.map(item => <button className="history" key={item} onClick={() => setQuestion(item)}>{item}</button>)}
        </nav>
        <div className="bottom"><div className="user"><b>本地</b><span><strong>开发调试</strong><small>Local environment</small></span></div></div>
      </aside>
      <section className="workspace">
        <header><button onClick={() => setSidebarOpen(!sidebarOpen)}>☰</button><span>智能问数　/　本地联调</span><div><i />后端服务 127.0.0.1:8000</div></header>
        <div className="content">
          <section className="welcome"><div><small>AI DATA ANALYST</small><h1>你好<br /><em>今天想了解什么？</em></h1><p>先解析用户意图，再检索业务知识，生成并校验 SQL。</p></div><div className="orb">✦</div></section>
          <form className="ask" onSubmit={submit}>
            <div><span>✦</span><textarea aria-label="输入数据问题" value={question} onChange={event => setQuestion(event.target.value)} placeholder="输入你想了解的数据问题…" onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} /><button disabled={!question.trim() || busy}>{busy ? "···" : "↑"}</button></div>
            <footer><span>试试这样问</span>{examples.map(item => <button type="button" key={item} onClick={() => setQuestion(item)}>{item}</button>)}<small>Enter 发送</small></footer>
          </form>
          {submittedQuestion && <section className="result">
            <div className="question"><b>问</b><div><small>你的问题</small><h2>{submittedQuestion}</h2></div></div>
            <div className="response"><b className="ai">✦</b><div>
              <div className="answer-head"><p><strong>知数 AI</strong>{result && <span>状态：{result.status} · 置信度：{Math.round(result.confidence * 100)}%</span>}</p></div>
              {busy && <p className="summary muted">正在解析意图并执行工作流…</p>}
              {error && <div className="message error">{error}</div>}
              {result && <><p className="summary">{result.answer}</p>{result.sql && <article className="sql-card"><header>生成的 SQL</header><pre>{result.sql}</pre></article>}<div className="source">请求 ID：{result.request_id}</div></>}
            </div></div>
          </section>}
        </div>
      </section>
    </main>
  );
}
