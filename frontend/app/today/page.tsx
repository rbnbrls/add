"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Block = { id: string; task_id: string; start_at: string; end_at: string; task_title: string; task_status: string };
type Child = { id: string; title: string; status: "inbox" | "active" | "done" | "archived" };
type Task = { id: string; title: string; description: string | null; status: string; children: Child[] };
type Proposal = { id: string; status: string; items: { id: string; title: string; description: string | null }[] };
type Action = { id: string; text: string; status: string; estimated_minutes: number };
type Session = { session_id: string; action: Action; started_at: string; duration_seconds: number; paused_at: string | null; paused_seconds: number };
type Accountability = { id: string; participant_label: string; status: string };
type Tool = "llm" | "pomodoro" | null;
type BlockChoice = "backlog" | "smaller" | null;

const time = (value: string) => new Date(value).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
const confettiColors = ["#b88945", "#6f8f78", "#c77b68", "#8b7bb5", "#e0b873"];

function playRewardTone(taskComplete = false) {
  if (typeof window === "undefined") return;
  const AudioContextClass = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextClass) return;
  const context = new AudioContextClass();
  const now = context.currentTime;
  const notes = taskComplete ? [523.25, 659.25, 783.99, 1046.5] : [659.25, 783.99];
  notes.forEach((frequency, index) => {
    const oscillator = context.createOscillator(); const gain = context.createGain(); const start = now + index * 0.08;
    oscillator.type = taskComplete ? "triangle" : "sine"; oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, start); gain.gain.exponentialRampToValueAtTime(taskComplete ? 0.14 : 0.09, start + 0.015); gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.2);
    oscillator.connect(gain).connect(context.destination); oscillator.start(start); oscillator.stop(start + 0.22);
  });
  window.setTimeout(() => void context.close(), 700);
}

export default function Today() {
  const router = useRouter();
  const [blocks, setBlocks] = useState<Block[]>([]), [focusId, setFocusId] = useState(""), [task, setTask] = useState<Task | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null), [selectedItemIds, setSelectedItemIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [busyChild, setBusyChild] = useState("");
  const [error, setError] = useState(""), [message, setMessage] = useState("");
  const [toolTarget, setToolTarget] = useState(""), [duration, setDuration] = useState(25), [session, setSession] = useState<Session | null>(null), [remaining, setRemaining] = useState(0);
  const [accountability, setAccountability] = useState<Accountability | null>(null), [buddy, setBuddy] = useState("Focusmate");
  const [activeTool, setActiveTool] = useState<Tool>(null), [childCount, setChildCount] = useState(3), [celebrating, setCelebrating] = useState(false);
  const [blockChoice, setBlockChoice] = useState<BlockChoice>(null), [blockReason, setBlockReason] = useState("too_big"), [smallerTitle, setSmallerTitle] = useState(""), [smallerAction, setSmallerAction] = useState("");

  async function loadBlocks() {
    const response = await fetch(`${API}/api/today-plan?timezone=Europe%2FAmsterdam`);
    if (response.ok) { const next: Block[] = await response.json(); setBlocks(next); if (next.length && (!focusId || !next.some(item => item.task_id === focusId))) setFocusId(next[0].task_id); if (!next.length) { setFocusId(""); setTask(null); } }
    else setError("De planning kon niet worden geladen.");
    setLoading(false);
  }

  async function openFocus(id: string) {
    setFocusId(id); setError("");
    const [taskResponse, proposalResponse] = await Promise.all([fetch(`${API}/api/tasks/${id}`), fetch(`${API}/api/tasks/${id}/decompositions`)]);
    if (!taskResponse.ok) { setError("De taak kon niet worden geopend."); return; }
    const next: Task = await taskResponse.json(); setTask(next); setToolTarget(id); setActiveTool(null);
    if (proposalResponse.ok) { const proposals: Proposal[] = await proposalResponse.json(); const latest = proposals[0] || null; setProposal(latest); setSelectedItemIds(latest?.status === "pending" ? latest.items.map(item => item.id) : []); }
  }

  async function askAssistant() {
    if (!task) return; setBusy(true); setError("");
    const response = await fetch(`${API}/api/tasks/${task.id}/decompositions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ child_count: childCount }) });
    const data = await response.json().catch(() => null);
    if (response.ok) { setProposal(data); setSelectedItemIds(data.items.map((item: { id: string }) => item.id)); setMessage("Voorstel ontvangen. Controleer de volgorde en voeg de stappen toe."); }
    else setError(data?.detail || "De taakassistent is niet beschikbaar.");
    setBusy(false);
  }

  async function approveProposal() {
    if (!proposal || !selectedItemIds.length) return; setBusy(true);
    const response = await fetch(`${API}/api/decompositions/${proposal.id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item_ids: selectedItemIds }) });
    if (response.ok) { setMessage("Subtaken toegevoegd."); await openFocus(focusId); } else setError("Subtaken konden niet worden toegevoegd.");
    setBusy(false);
  }

  async function toggleChild(child: Child) {
    if (!task) return; setBusyChild(child.id); setError("");
    const completingTask = child.status !== "done" && task.children.filter(item => item.id !== child.id).every(item => item.status === "done");
    const response = await fetch(`${API}/api/tasks/${child.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: child.status === "done" ? "inbox" : "done" }) });
    if (response.ok) {
      if (completingTask) {
        playRewardTone(true); setBlocks(current => current.map(block => block.task_id === task.id ? { ...block, task_status: "done" } : block)); setCelebrating(true); window.setTimeout(() => setCelebrating(false), 3500); setMessage("Taak afgerond — goed gedaan!");
      } else if (child.status !== "done") playRewardTone();
      await openFocus(task.id); if (!completingTask) setMessage(child.status === "done" ? "Subtaak weer geopend." : "Subtaak afgerond.");
    } else setError("De subtaak kon niet worden bijgewerkt.");
    setBusyChild("");
  }

  async function completeTask(target: Task = task as Task) {
    if (!target || target.status === "done") return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API}/api/tasks/${target.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "done" }) });
      if (!response.ok) throw new Error("De taak kon niet als gereed worden gemarkeerd.");
      playRewardTone(true); setBlocks(current => current.map(block => block.task_id === target.id ? { ...block, task_status: "done" } : block)); setCelebrating(true); window.setTimeout(() => setCelebrating(false), 3500); setMessage("Taak afgerond — goed gedaan!");
      await openFocus(target.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "De taak kon niet worden afgerond."); }
    setBusy(false);
  }

  async function markBlocked() {
    if (!task || !blockChoice) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API}/api/tasks/${task.id}/block`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: blockReason, resolution: blockChoice, smaller_title: blockChoice === "smaller" ? smallerTitle : undefined, smaller_action: blockChoice === "smaller" ? smallerAction : undefined }) });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || "De blokkade kon niet worden opgeslagen.");
      setMessage(blockChoice === "smaller" ? "De taak is omgezet naar een kleinere stap." : "De taak staat weer in de backlog."); setBlockChoice(null); setSmallerTitle(""); setSmallerAction(""); setTask(null); await loadBlocks();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "De blokkade kon niet worden opgeslagen."); }
    setBusy(false);
  }

  async function getOrCreateAction(target: Task | Child) {
    const response = await fetch(`${API}/api/tasks/${target.id}/actions`); if (!response.ok) throw new Error("Actie kon niet worden geladen.");
    const actions: Action[] = await response.json();
    const ready = actions.find(action => action.status === "ready"); if (ready) return ready;
    if (actions.some(action => action.status === "active")) throw new Error("Er loopt al een sessie voor deze taak.");
    const created = await fetch(`${API}/api/tasks/${target.id}/actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: target.title, estimated_minutes: duration }) });
    if (!created.ok) throw new Error("Actie kon niet worden aangemaakt."); return created.json();
  }

  async function startPomodoro(forAccountability = false) {
    if (!task) return; const target = task.id === toolTarget ? task : task.children.find(child => child.id === toolTarget); if (!target) return;
    setBusy(true); setError("");
    try {
      const action = await getOrCreateAction(target);
      const response = await fetch(`${API}/api/actions/${action.id}/start?duration_seconds=${duration * 60}`, { method: "POST" });
      if (!response.ok) throw new Error("De timer kon niet worden gestart.");
      const next: Session = await response.json(); setSession(next); setRemaining(next.duration_seconds); setMessage(forAccountability ? "Focusmate-sessie gestart." : "Pomodoro gestart.");
      if (forAccountability) {
        const buddyResponse = await fetch(`${API}/api/accountability/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ execution_session_id: next.session_id, participant_label: buddy || "Focusmate" }) });
        if (!buddyResponse.ok) throw new Error("Focusmate-sessie kon niet worden gestart.");
        setAccountability(await buddyResponse.json());
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "De focus-tool kon niet worden gestart."); }
    setBusy(false);
  }

  async function togglePause() { if (!session) return; const path = session.paused_at ? "resume" : "pause"; const response = await fetch(`${API}/api/sessions/${session.session_id}/${path}`, { method: "POST" }); if (response.ok) setSession(await response.json()); }
  async function finishTimer() {
    if (!session || !task) return;
    const target = task.id === toolTarget ? task : task.children.find(child => child.id === toolTarget);
    if (!target) return;
    setBusy(true); setError("");
    try {
      const sessionResponse = await fetch(`${API}/api/sessions/${session.session_id}/finish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ outcome: "done" }) });
      if (!sessionResponse.ok) throw new Error("De pomodoro kon niet worden afgerond.");
      const taskResponse = await fetch(`${API}/api/tasks/${target.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "done" }) });
      if (!taskResponse.ok) throw new Error("De taak kon niet als gereed worden gemarkeerd.");
      playRewardTone(true); setSession(null); setRemaining(0); setBlocks(current => current.map(block => block.task_id === target.id ? { ...block, task_status: "done" } : block)); setTask(current => current && current.id === target.id ? { ...current, status: "done" } : current); setMessage("Taak afgerond — goed gedaan!"); await loadBlocks(); router.push("/today");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "De pomodoro kon niet worden afgerond."); }
    setBusy(false);
  }
  function openFocusmate() { window.open("https://app.focusmate.com/", "_blank", "noopener,noreferrer"); }

  useEffect(() => { void loadBlocks(); }, []);
  useEffect(() => { if (focusId) void openFocus(focusId); }, [focusId]);
  useEffect(() => { if (!session || session.paused_at) return; const timer = window.setInterval(() => { const elapsed = Math.floor((Date.now() - new Date(session.started_at).getTime()) / 1000) - session.paused_seconds; setRemaining(Math.max(0, session.duration_seconds - elapsed)); }, 1000); return () => window.clearInterval(timer); }, [session]);

  if (loading) return <main className="today-shell"><section className="hero"><p className="meta">Vandaag laden…</p></section></main>;
  const doneCount = task?.children.filter(child => child.status === "done").length || 0;
  const targetName = task?.id === toolTarget ? task.title : task?.children.find(child => child.id === toolTarget)?.title;
  const minutes = String(Math.floor(remaining / 60)).padStart(2, "0"), seconds = String(remaining % 60).padStart(2, "0");
  return <><>{celebrating && <div className="task-confetti" aria-hidden="true">{Array.from({ length: 64 }, (_, index) => <i key={index} className="task-confetti-piece" style={{ left: `${(index * 37) % 101}%`, animationDelay: `${(index % 12) * 0.06}s`, backgroundColor: confettiColors[index % confettiColors.length] }} />)}</div>}{session && <div className="pomodoro-fullscreen" role="dialog" aria-modal="true" aria-labelledby="pomodoro-title"><p className="eyebrow">POMODORO · FOCUS</p><h1 id="pomodoro-title">{targetName}</h1><strong className="pomodoro-clock">{minutes}:{seconds}</strong><p className="meta">{session.paused_at ? "Gepauzeerd" : "Blijf bij deze taak."}</p><div className="pomodoro-actions"><button type="button" onClick={() => void togglePause()}>{session.paused_at ? "Hervat" : "Pauze"}</button><button type="button" className="secondary" onClick={() => void finishTimer()}>Taak klaar</button></div></div>}</><main className="today-shell">
    <header><span className="logo">ADD</span><span>Vandaag</span><a className="lab-link" href="/review">Review</a></header>
    <section className="today-intro"><p className="eyebrow">VANDAAG</p><h1>Je geplande taken.</h1><p className="meta">Kies één taak om nu met focus uit te voeren.</p></section>
    {blocks.length === 0 ? <section className="today-empty"><h2>Geen taken gepland.</h2><p className="meta">Er staat vandaag niets op je tijdslijn.</p><a className="primary-link" href="/views?unplanned=true">Bekijk Later</a></section> : <>
      <section className="today-schedule" aria-label="Geplande taken"><div className="today-section-heading"><h2>Tijdslijn</h2><span className="meta">{blocks.length} {blocks.length === 1 ? "taak" : "taken"}</span></div><div className="today-task-list">{blocks.map(block => <button type="button" className={`today-task ${focusId === block.task_id ? "is-focus" : ""} ${block.task_status === "done" ? "is-complete" : ""}`} key={block.id} onClick={() => setFocusId(block.task_id)}><span className="today-task-time">{time(block.start_at)}<small>{time(block.end_at)}</small></span><span className="today-task-copy"><strong>{block.task_title}{block.task_status === "done" && <span className="today-task-check" aria-label="Gereed">✓</span>}</strong>{focusId === block.task_id && <small>{block.task_status === "done" ? "Gereed" : "Focus geselecteerd"}</small>}</span><span className="today-task-arrow" aria-hidden="true">→</span></button>)}</div></section>
      {task && <section className={`today-focus ${task.status === "done" ? "is-complete" : ""}`} aria-labelledby="focus-title">
        <div className="today-section-heading"><div><p className="eyebrow">FOCUS</p><h2 id="focus-title">{task.title}</h2></div><span className="meta">{task.status === "done" ? "Gereed" : `${doneCount}/${task.children.length} subtaken`}</span></div>
        {task.description && <p className="today-focus-description">{task.description}</p>}
        {task.children.length > 0 ? <div className="today-checklist">{task.children.map((child, index) => <label className={`today-check ${child.status === "done" ? "is-done" : ""}`} key={child.id}><input type="checkbox" checked={child.status === "done"} disabled={busyChild === child.id} onChange={() => void toggleChild(child)} /><span><small>Stap {index + 1}</small><strong>{child.title}</strong></span></label>)}</div> : <div className="today-no-subtasks"><p className="meta">Deze taak heeft nog geen subtaken.</p><button type="button" disabled={busy || task.status === "done"} onClick={() => void completeTask()}>{task.status === "done" ? "Taak gereed" : "Taak afronden"}</button></div>}
        <section className="focus-tools" aria-label="Hulpmiddelen voor deze focus"><div className="focus-tool-icons"><button type="button" className={activeTool === "llm" ? "is-active" : ""} aria-label="LLM subtaken openen" aria-expanded={activeTool === "llm"} onClick={() => setActiveTool(activeTool === "llm" ? null : "llm")}><span aria-hidden="true">🧠</span><small>Subtaken</small></button><button type="button" className={activeTool === "pomodoro" ? "is-active" : ""} aria-label="Pomodoro instellen" aria-expanded={activeTool === "pomodoro"} onClick={() => setActiveTool(activeTool === "pomodoro" ? null : "pomodoro")}><span aria-hidden="true">🍅</span><small>Pomodoro</small></button><button type="button" aria-label="Open Focusmate in nieuw tabblad" onClick={openFocusmate}><span aria-hidden="true">👥</span><small>Focusmate</small></button></div>
          {activeTool === "llm" && <div className="focus-tool-panel"><label>Aantal subtaken<select value={childCount} onChange={event => setChildCount(Number(event.target.value))}><option value={2}>2 subtaken</option><option value={3}>3 subtaken</option><option value={4}>4 subtaken</option><option value={5}>5 subtaken</option></select></label><button type="button" className="secondary" disabled={busy || task.status === "done"} onClick={() => void askAssistant()}>Genereer subtaken</button></div>}
          {activeTool === "pomodoro" && <div className="focus-tool-panel"><label>Werk aan<select value={toolTarget} onChange={event => setToolTarget(event.target.value)}><option value={task.id}>{task.title}</option>{task.children.map(child => <option key={child.id} value={child.id}>{child.title}</option>)}</select></label><div className="duration-options">{[15, 25, 50].map(value => <button type="button" key={value} className={duration === value ? "selected" : ""} onClick={() => setDuration(value)}>{value} min</button>)}</div><button type="button" onClick={() => void startPomodoro()} disabled={busy || task.status === "done"} style={{ cursor: busy || task.status === "done" ? "not-allowed" : "pointer" }}>Start timer</button></div>}
        </section>
        <section className="today-stuck" aria-labelledby="stuck-title"><div className="today-stuck-heading"><div><p className="eyebrow">VASTGELOPEN?</p><h3 id="stuck-title">Je hoeft dit niet alleen op te lossen.</h3></div><button type="button" className="quiet" disabled={busy} onClick={() => setBlockChoice(blockChoice ? null : "backlog")} aria-expanded={Boolean(blockChoice)}>Ik zit vast</button></div>{blockChoice && <div className="today-stuck-panel"><label>Wat maakt deze taak lastig?<select value={blockReason} onChange={event => setBlockReason(event.target.value)}><option value="too_big">Te groot of te veel tegelijk</option><option value="unclear">Niet duidelijk wat de eerste stap is</option><option value="missing_info">Informatie of hulpmiddel ontbreekt</option><option value="low_energy">Mijn energie is op</option></select></label><div className="today-stuck-actions"><button type="button" className={blockChoice === "backlog" ? "selected" : "secondary"} disabled={busy} onClick={() => setBlockChoice("backlog")}>Later opnieuw plannen</button><button type="button" className={blockChoice === "smaller" ? "selected" : "secondary"} disabled={busy} onClick={() => setBlockChoice("smaller")}>Kleinere taak kiezen</button></div>{blockChoice === "smaller" && <div className="today-stuck-form"><label>Naam van de kleinere taak<input value={smallerTitle} onChange={event => setSmallerTitle(event.target.value)} placeholder="bijv. Alleen het dossier openen" /></label><label>Eerste concrete stap<input value={smallerAction} onChange={event => setSmallerAction(event.target.value)} placeholder="bijv. Zoek het dossier op" /></label></div>}<button type="button" disabled={busy || (blockChoice === "smaller" && (!smallerTitle.trim() || !smallerAction.trim()))} onClick={() => void markBlocked()}>{busy ? "Opslaan…" : blockChoice === "smaller" ? "Ruil taak in" : "Zet terug naar backlog"}</button></div>}</section>
        {proposal && proposal.status === "pending" && <div className="decomposition-proposal"><p className="eyebrow">VOORSTEL · controleer de volgorde</p><ol>{proposal.items.map(item => <li key={item.id}><label><input type="checkbox" checked={selectedItemIds.includes(item.id)} onChange={() => setSelectedItemIds(current => current.includes(item.id) ? current.filter(id => id !== item.id) : [...current, item.id])} /><span>{item.title}</span></label></li>)}</ol><button type="button" disabled={busy || !selectedItemIds.length} onClick={() => void approveProposal()}>Subtaken toevoegen</button></div>}
      </section>}
    </>}
    {(message || error) && <p className="message">{error || message}</p>}
  </main></>;
}
