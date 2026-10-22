import React, { Component, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, AlertTriangle, Box, CheckCircle2, Clock3, Github, LoaderCircle, Play, Radar, Search, ShieldCheck, XCircle } from 'lucide-react';
import './styles.css';

const API = `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api`;
const tasks = [
  'Analyze this repository and prepare it for CI/CD.',
  'Find and diagnose test failures.',
];
const severityClass = { high: 'danger', medium: 'warning', low: 'quiet' };

class AppErrorBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) return <div className="runtime-error"><AlertTriangle size={28}/><h1>Dashboard failed to render</h1><p>{this.state.error.message}</p><button className="primary" onClick={() => window.location.reload()}>Reload dashboard</button></div>;
    return this.props.children;
  }
}

function readableError(error) {
  try { const body = JSON.parse(error); return body.detail?.message || body.message || error; } catch { return error || 'Could not reach the backend.'; }
}

function App() {
  const [path, setPath] = useState('');
  const [task, setTask] = useState(tasks[0]);
  const [run, setRun] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [githubQuery, setGithubQuery] = useState('');
  const [githubRepos, setGithubRepos] = useState([]);
  const [githubMessage, setGithubMessage] = useState('');
  const [searchingGithub, setSearchingGithub] = useState(false);
  const [tab, setTab] = useState('overview');
  const runId = useRef(null);

  useEffect(() => {
    if (!runId.current || !run || ['completed', 'failed', 'timed_out'].includes(run.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/agent/runs/${runId.current}`);
        if (!response.ok) throw new Error(await response.text());
        setRun(await response.json());
      } catch (err) { setError(readableError(err.message)); }
    }, 650);
    return () => window.clearInterval(timer);
  }, [run?.status]);

  async function analyzeRepository() {
    setStarting(true); setError(''); setRun(null); runId.current = null;
    try {
      const response = await fetch(`${API}/agent/run`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path, task}) });
      if (!response.ok) throw new Error(await response.text());
      const started = await response.json();
      runId.current = started.agent_run_id;
      setRun(started); setTab('activity');
    } catch (err) { setError(readableError(err.message)); }
    finally { setStarting(false); }
  }

  async function findGithubRepositories() {
    setSearchingGithub(true); setGithubMessage(''); setError('');
    try {
      const response = await fetch(`${API}/github/repositories?query=${encodeURIComponent(githubQuery)}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail?.message || 'GitHub search failed.');
      setGithubRepos(result.repositories || []);
      setGithubMessage(result.message || `${result.repositories.length} repositories found.`);
    } catch (err) { setGithubMessage(readableError(err.message)); setGithubRepos([]); }
    finally { setSearchingGithub(false); }
  }

  async function applyProposal(proposal) {
    setError('');
    try {
      const response = await fetch(`${API}/agent/runs/${run.agent_run_id}/proposals/${encodeURIComponent(proposal.proposal_id)}/apply`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({approved: true}) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail?.message || 'Could not apply this proposal.');
      setRun(previous => ({...previous, proposed_files: previous.proposed_files.map(file => file.proposal_id === proposal.proposal_id ? {...file, applied_at: new Date().toISOString()} : file), actions: [...previous.actions, {at: new Date().toISOString(), state: 'success', message: `Applied approved change to ${proposal.path}`, tool: 'apply_proposal'}]}));
    } catch (err) { setError(readableError(err.message)); }
  }

  const isWorking = starting || run?.status === 'queued' || run?.status === 'running';
  return <div className="app">
    <header><div className="brand"><div className="mark"><Radar size={21}/></div><div><strong>AI DevOps Agent</strong><span>Repository intelligence workspace</span></div></div><div className="secure"><ShieldCheck size={16}/> approval-gated operations</div></header>
    <main>
      <section className="hero"><div><p className="eyebrow">DEVOPS CONTROL PLANE / 01</p><h1>Make the repository<br/><em>explain itself.</em></h1><p className="sub">Inspect structure, execute verified tests, and turn findings into reviewable engineering changes.</p></div><div className="signal"><span className={`pulse ${isWorking ? 'working' : ''}`}></span><span>{isWorking ? 'Agent running' : 'Agent ready'}</span></div></section>
      <section className="inputbar"><div className="inputwrap"><label>Repository path or GitHub URL</label><input value={path} onChange={e => setPath(e.target.value)} placeholder="C:\\projects\\your-repository or https://github.com/owner/repo" /></div><div className="taskwrap"><label>Agent task</label><select value={task} onChange={e => setTask(e.target.value)}><option value={tasks[0]}>Prepare for CI/CD</option><option value={tasks[1]}>Diagnose test failures</option></select></div><button className="primary" onClick={analyzeRepository} disabled={!path || isWorking}>{starting ? <LoaderCircle className="spin" size={17}/> : <Play size={17}/>} {isWorking ? 'Running agent' : 'Analyze Repository'}</button></section>
      <section className="github-picker"><div className="github-title"><Github size={18}/><div><strong>Choose a GitHub repository</strong><span>Search public repositories or list repos from the configured GitHub account.</span></div></div><div className="github-search"><input value={githubQuery} onChange={e => setGithubQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && findGithubRepositories()} placeholder="Search by repository or owner (blank lists your repos when configured)"/><button className="secondary" onClick={findGithubRepositories} disabled={searchingGithub}>{searchingGithub ? <LoaderCircle className="spin" size={15}/> : <Search size={15}/>} Find repositories</button></div>{githubMessage && <p className="github-message">{githubMessage}</p>}{githubRepos.length > 0 && <div className="repo-results">{githubRepos.map(repo => <button key={repo.url} onClick={() => {setPath(repo.url);setGithubMessage(`${repo.name} selected. Analyze it when you’re ready.`)}}><strong>{repo.name}</strong><span>{repo.description || 'No description'}{repo.private ? ' · Private' : ''}</span></button>)}</div>}</section>
      {error && <div className="error"><AlertTriangle size={17}/>{error}</div>}
      {run && <><AgentRunPanel run={run}/><nav className="tabs">{[['overview','Overview'],['activity',`Agent activity ${run.actions.length}`],['issues',`Issues ${run.issues.length}`],['tests','Test results'],['cicd','CI/CD proposals']].map(([id,label]) => <button className={tab === id ? 'active' : ''} onClick={() => setTab(id)} key={id}>{label}</button>)}</nav><Dashboard tab={tab} run={run} onApplyProposal={applyProposal}/></>}
      {!run && !error && <div className="empty"><Box size={34}/><h2>Connect a repository to begin</h2><p>The agent will inspect manifests, identify the stack, run its actual test command, and produce a reviewable report.</p></div>}
    </main>
  </div>;
}

function AgentRunPanel({run}) {
  const status = run.status.replace('_', ' ');
  return <section className="runpanel"><div className="runhead"><div><p className="eyebrow">AGENT RUN</p><h2>{status}</h2></div><span className={`runstatus ${run.status}`}>{run.status === 'running' || run.status === 'queued' ? <LoaderCircle className="spin" size={14}/> : run.status === 'completed' ? <CheckCircle2 size={14}/> : <XCircle size={14}/>} {status}</span></div><div className="rungrid"><RunItem label="Run ID" value={run.agent_run_id}/><RunItem label="Repository" value={run.repository}/><RunItem label="Current task" value={run.task}/><RunItem label="Duration" value={`${run.duration_seconds || 0}s`}/><RunItem label="Tools used" value={run.tools_used.length ? run.tools_used.join(', ') : 'Awaiting execution'}/><RunItem label="Tests" value={run.test_results ? `${run.test_summary.passed} passed / ${run.test_summary.failed} failed` : 'Not executed yet'}/><RunItem label="Issues found" value={String(run.issues.length)}/><RunItem label="Files proposed" value={run.proposed_files.length ? run.proposed_files.map(file => file.path).join(', ') : 'None'}/></div>{run.error && <div className="error"><AlertTriangle size={16}/>{run.error.code}: {run.error.message}</div>}</section>;
}
function RunItem({label, value}) { return <div className="runitem"><span>{label}</span><strong title={value}>{value}</strong></div>; }

function Dashboard({ tab, run, onApplyProposal }) {
  const report = run.report;
  if (tab === 'activity') return <Panel title="Agent activity"><div className="timeline">{run.actions.length ? run.actions.map((action, i) => <div className={`event ${action.state}`} key={`${action.at}-${i}`}><span className="eventdot">{action.state === 'success' ? <CheckCircle2 size={14}/> : action.state === 'error' ? <XCircle size={14}/> : action.state === 'waiting' ? <Clock3 size={14}/> : <Activity size={14}/>}</span><span>{action.message}{action.tool && <small className="toolname">{action.tool}</small>}</span><small>{new Date(action.at).toLocaleTimeString()}</small></div>) : <p className="muted">The backend has accepted the run; waiting for the first factual action.</p>}</div></Panel>;
  if (tab === 'issues') return <Panel title="Detected issues"><div className="issues">{run.issues.length ? run.issues.map(issue => <article className="issue" key={`${issue.issue}-${issue.file}`}><div className={`tag ${severityClass[issue.severity]}`}>{issue.severity}</div><div><h3>{issue.issue}</h3><p>{issue.explanation}</p><small>{issue.file || 'repository'} · Suggested fix: {issue.suggested_fix}</small></div></article>) : run.status === 'completed' ? <div className="success"><CheckCircle2/> No issues detected in the inspected surface.</div> : <p className="muted">Issue detection is still running.</p>}</div></Panel>;
  if (tab === 'tests') return <Panel title="Test execution">{run.test_results ? <pre className="code">{JSON.stringify(run.test_results, null, 2)}</pre> : <p className="muted">No test output is available yet. The panel will only show backend execution results.</p>}</Panel>;
  if (tab === 'cicd') return <Panel title="Review proposed changes">{run.proposed_files.length ? run.proposed_files.map(file => <div className="proposal" key={file.proposal_id}><div className="proposal-head"><div><span className="filepill">{file.path}</span><p className="proposal-reason">{file.reason}</p></div>{file.applied_at ? <span className="applied"><CheckCircle2 size={15}/> Applied</span> : <button className="approve" onClick={() => onApplyProposal(file)}>Approve and apply</button>}</div><pre className="code diff">{file.diff || '(No changes)'}</pre></div>) : <p className="muted">No file changes have been proposed yet.</p>}</Panel>;
  if (!report) return <Panel title="Repository overview"><p className="muted">Repository inspection is in progress.</p></Panel>;
  return <><div className="stats"><Stat label="Detected stack" value={report.language}/><Stat label="Framework" value={report.framework}/><Stat label="Files inspected" value={report.file_count}/><Stat label="Issues found" value={run.issues.length}/></div><div className="grid"><Panel title="Repository overview"><div className="overview"><div><span className="big">{report.name}</span><span className="path">{report.path}</span></div><div className="filegrid">{Object.entries(report.important_files).map(([file, found]) => <span className={found ? 'found' : ''} key={file}>{found ? <CheckCircle2 size={14}/> : <AlertTriangle size={14}/>} {file}</span>)}</div></div></Panel><Panel title="Final diagnosis"><p className="diagnosis">{run.diagnosis || 'The agent is gathering evidence.'}</p><div className="summary"><div className="donut">{run.issues.length}<small>issues</small></div><div><p><b>{run.test_summary.passed}</b> tests passed</p><p><b>{run.test_summary.failed}</b> tests failed</p><p><b>{run.tools_used.length}</b> tools executed</p></div></div></Panel></div></>;
}
function Panel({title, children}) { return <section className="panel"><div className="panelhead"><h2>{title}</h2><span>BACKEND DATA</span></div>{children}</section>; }
function Stat({label,value}) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div>; }
const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('React root element was not found');
createRoot(rootElement).render(<AppErrorBoundary><App /></AppErrorBoundary>);
