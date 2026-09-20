"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TIMEZONE = "Europe/Amsterdam";
const START_HOUR = 7;
const END_HOUR = 23;
const SLOT_MINUTES = 30;
const SLOT_HEIGHT = 32;

type Task = { id: string; title: string; description: string | null; deadline: string | null; planned_at: string | null; priority: "high" | "medium" | "low"; status: string; source_type: string; created_at: string };
type Block = { id: string; task_id: string; start_at: string; end_at: string; task_title: string };
type ResizeState = { block: Block; initialY: number; originalDuration: number };
type StartDragState = { block: Block; initialY: number };

function localDayStart(offset = 0) { const now = new Date(); return new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset, 0, 0, 0, 0); }
function planningDateKey(offset = 0) { const parts = new Intl.DateTimeFormat("en-CA", { timeZone: TIMEZONE, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date()); const year = Number(parts.find(part => part.type === "year")?.value); const month = Number(parts.find(part => part.type === "month")?.value); const day = Number(parts.find(part => part.type === "day")?.value); const target = new Date(Date.UTC(year, month - 1, day + offset)); return target.toISOString().slice(0, 10); }
function slotDate(index: number, offset = 0) { const day = localDayStart(offset); day.setHours(START_HOUR, index * SLOT_MINUTES, 0, 0); return day; }
function isoForSlot(index: number, offset = 0) { return slotDate(index, offset).toISOString(); }
function formatTime(value: string | Date) { return new Date(value).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" }); }
function formatDeadline(value: string | null) { return value ? new Date(value).toLocaleDateString("nl-NL", { day: "numeric", month: "short" }) : "Geen deadline"; }
function duration(block: Block) { return Math.max(SLOT_MINUTES, Math.round((new Date(block.end_at).getTime() - new Date(block.start_at).getTime()) / 60000)); }
async function planningError(response: Response, fallback: string) {
  const body = await response.json().catch(() => null) as { detail?: string } | null;
  if (body?.detail === "start_at cannot be in the past") return "Kies een tijdstip vanaf nu; eerdere momenten zijn voorbij.";
  if (body?.detail === "plan block overlaps an existing block") return "Dit tijdstip overlapt met een andere taak.";
  return body?.detail || fallback;
}

export default function Views() {
  const [dayOffset, setDayOffset] = useState(0), [dayReady, setDayReady] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]), [blocks, setBlocks] = useState<Block[]>([]);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [error, setError] = useState("");
  const [editingDeadline, setEditingDeadline] = useState<string | null>(null);
  const [resizeState, setResizeState] = useState<ResizeState | null>(null);
  const [startDragState, setStartDragState] = useState<StartDragState | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const nowIndicatorRef = useRef<HTMLDivElement | null>(null);
  const pendingSchedules = useRef(new Set<string>());

  const load = useCallback(async () => {
    setLoading(true); setError("");
    const requestedOffset = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("day") === "tomorrow" ? 1 : dayOffset;
    const day = planningDateKey(requestedOffset);
    const [taskResponse, blockResponse] = await Promise.all([fetch(`${API}/api/tasks`, { cache: "no-store" }), fetch(`${API}/api/today-plan?day=${day}&timezone=${TIMEZONE}`, { cache: "no-store" })]);
    if (!taskResponse.ok || !blockResponse.ok) { setError("Later kon niet worden geladen."); setLoading(false); return; }
    const allTasks: Task[] = await taskResponse.json();
    setTasks(allTasks.filter((task) => task.status === "active" && !task.planned_at));
    setBlocks(await blockResponse.json()); setLoading(false);
  }, [dayOffset]);
  useEffect(() => { setDayOffset(new URLSearchParams(window.location.search).get("day") === "tomorrow" ? 1 : 0); setDayReady(true); }, []);
  useEffect(() => { if (dayReady) void load(); }, [dayReady, dayOffset, load]);

  const urgentTasks = useMemo(() => tasks.filter((task) => task.priority === "high"), [tasks]);
  const normalTasks = useMemo(() => tasks.filter((task) => task.priority !== "high"), [tasks]);
  function sortTasks(items: Task[]) { return [...items].sort((a, b) => { if (a.deadline && b.deadline) return new Date(a.deadline).getTime() - new Date(b.deadline).getTime(); if (a.deadline) return -1; if (b.deadline) return 1; return new Date(b.created_at).getTime() - new Date(a.created_at).getTime(); }); }

  async function updateTask(taskId: string, payload: { priority?: "high" | "medium"; deadline?: string | null }) {
    setBusy(true); setError(""); const response = await fetch(`${API}/api/tasks/${taskId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!response.ok) { setError("Taak kon niet worden bijgewerkt."); setBusy(false); return; } setMessage("Bijgewerkt."); await load(); setBusy(false);
  }

  async function scheduleTask(taskId: string, slotIndex: number) {
    if (pendingSchedules.current.has(taskId)) return;
    if (!blocks.some((block) => block.task_id === taskId) && blocks.length >= 3) { setError("Plan maximaal drie taken voor vandaag."); return; }
    const startAt = isoForSlot(slotIndex, dayOffset); const end = new Date(startAt); end.setMinutes(end.getMinutes() + 60);
    if (blocks.some((block) => new Date(block.start_at) < end && new Date(block.end_at) > new Date(startAt))) { setError("Dit tijdslot is al bezet."); return; }
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return;
    const temporaryId = `pending-${taskId}-${Date.now()}`;
    const optimisticBlock: Block = { id: temporaryId, task_id: task.id, start_at: startAt, end_at: end.toISOString(), task_title: task.title };
    pendingSchedules.current.add(taskId);
    setError(""); setMessage("Taak gepland."); setBusy(true);
    setTasks((current) => current.filter((item) => item.id !== taskId));
    setBlocks((current) => [...current, optimisticBlock].sort((a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime()));
    try {
      const response = await fetch(`${API}/api/plan-blocks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_id: taskId, start_at: startAt, end_at: end.toISOString() }) });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "Taak kon niet worden ingepland.");
      const saved: Block = await response.json();
      setBlocks((current) => current.map((block) => block.id === temporaryId ? saved : block));
    } catch (scheduleError) {
      setBlocks((current) => current.filter((block) => block.id !== temporaryId));
      setTasks((current) => [...current, task]);
      setError(scheduleError instanceof Error ? scheduleError.message : "Taak kon niet worden ingepland."); setMessage("");
    } finally {
      pendingSchedules.current.delete(taskId); setBusy(false);
    }
  }
  async function finishResize() {
    if (!resizeState) return; const state = resizeState; setResizeState(null);
    const y = (window as Window & { __addLastPointerY?: number }).__addLastPointerY; const deltaSlots = y == null ? 0 : Math.round((y - state.initialY) / SLOT_HEIGHT); const nextDuration = Math.max(SLOT_MINUTES, state.originalDuration + deltaSlots * SLOT_MINUTES);
    if (nextDuration === state.originalDuration) return;
    const response = await fetch(`${API}/api/tasks/${state.block.task_id}/replan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ destination: "at", start_at: state.block.start_at, duration_minutes: nextDuration }) });
    if (!response.ok) { setError(await planningError(response, "De duur kon niet worden aangepast.")); return; } setMessage("Duur aangepast."); await load();
  }
  useEffect(() => { if (!resizeState) return; const move = (event: PointerEvent) => { (window as Window & { __addLastPointerY?: number }).__addLastPointerY = event.clientY; }; const up = () => { void finishResize(); }; window.addEventListener("pointermove", move); window.addEventListener("pointerup", up, { once: true }); return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); }; }, [resizeState]);

  async function finishStartDrag() {
    if (!startDragState) return;
    const state = startDragState;
    const y = (window as Window & { __addStartPointerY?: number }).__addStartPointerY;
    const deltaSlots = y == null ? 0 : Math.round((y - state.initialY) / SLOT_HEIGHT);
    const start = new Date(state.block.start_at);
    start.setMinutes(start.getMinutes() + deltaSlots * SLOT_MINUTES);
    const startAt = start.toISOString();
    setStartDragState(null);
    if (deltaSlots === 0) return;
    if (start.getTime() < Date.now()) {
      setBlocks((current) => current.map((block) => block.id === state.block.id ? state.block : block));
      setError("Kies een tijdstip vanaf nu; eerdere momenten zijn voorbij.");
      return;
    }
    const response = await fetch(`${API}/api/tasks/${state.block.task_id}/replan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ destination: "at", start_at: startAt, duration_minutes: duration(state.block) }) });
    if (!response.ok) {
      setBlocks((current) => current.map((block) => block.id === state.block.id ? state.block : block));
      setError(await planningError(response, "De starttijd kon niet worden aangepast."));
      return;
    }
    setMessage("Starttijd aangepast.");
  }
  useEffect(() => {
    if (!startDragState) return;
    const move = (event: PointerEvent) => {
      (window as Window & { __addStartPointerY?: number }).__addStartPointerY = event.clientY;
      const deltaSlots = Math.round((event.clientY - startDragState.initialY) / SLOT_HEIGHT);
      const start = new Date(startDragState.block.start_at);
      start.setMinutes(start.getMinutes() + deltaSlots * SLOT_MINUTES);
      const end = new Date(start);
      end.setMinutes(end.getMinutes() + duration(startDragState.block));
      setBlocks((current) => current.map((block) => block.id === startDragState.block.id ? { ...block, start_at: start.toISOString(), end_at: end.toISOString() } : block));
    };
    const up = () => { void finishStartDrag(); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up, { once: true });
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [startDragState]);

  async function moveBlock(block: Block, slotIndex: number) {
    const startAt = isoForSlot(slotIndex, dayOffset);
    const response = await fetch(`${API}/api/tasks/${block.task_id}/replan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ destination: "at", start_at: startAt, duration_minutes: duration(block) }) });
    if (!response.ok) { setError(await planningError(response, "De taak kon niet worden verplaatst.")); return; }
    setMessage("Starttijd aangepast."); await load();
  }
  async function returnToBacklog(block: Block) {
    const response = await fetch(`${API}/api/tasks/${block.task_id}/replan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ destination: "inbox" }) });
    if (!response.ok) { setError("De taak kon niet terug naar Later."); return; }
    setMessage("Taak teruggezet naar Later."); await load();
  }
  function handleDayDrop(event: React.DragEvent, slotIndex: number) {
    event.preventDefault(); const value = event.dataTransfer.getData("text/plain");
    if (value.startsWith("move:")) { const block = blocks.find((item) => item.id === value.slice(5)); if (block) void moveBlock(block, slotIndex); return; }
    if (value) void scheduleTask(value, slotIndex);
  }
  function handleBacklogDrop(event: React.DragEvent) {
    event.preventDefault(); const value = event.dataTransfer.getData("text/plain");
    if (value.startsWith("move:")) { const block = blocks.find((item) => item.id === value.slice(5)); if (block) void returnToBacklog(block); }
  }
  const now = new Date(), dayStart = localDayStart(dayOffset), nowMinutes = (now.getTime() - dayStart.getTime()) / 60000, nowTop = ((nowMinutes - START_HOUR * 60) / SLOT_MINUTES) * SLOT_HEIGHT;
  useEffect(() => {
    if (!dayReady || loading || dayOffset !== 0) return;
    const timeline = timelineRef.current;
    if (timeline && nowTop >= 0) timeline.scrollTop = Math.max(0, nowTop - 12);
  }, [dayReady, dayOffset, loading, blocks.length, nowTop]);
  function renderBacklog(items: Task[], label: string, urgent: boolean) { return <section className="later-backlog-group" aria-labelledby={`later-${urgent ? "urgent" : "normal"}`}><div className="later-group-heading"><div><p className="eyebrow">{urgent ? "EERST KIJKEN" : "DAARNA"}</p><h2 id={`later-${urgent ? "urgent" : "normal"}`}>{label}</h2></div><span className="later-group-count">{items.length}</span></div>{sortTasks(items).map((task) => <article className="later-task" key={task.id} draggable onDragStart={(event) => event.dataTransfer.setData("text/plain", task.id)}><div className="later-task-select"><a className="later-task-title" href={`/task/${task.id}`}><span><strong>{task.title}</strong><small>{task.deadline ? `Deadline ${formatDeadline(task.deadline)}` : "Geen deadline"}</small></span></a></div><div className="later-task-controls"><label className="later-deadline"><span className="sr-only">Deadline voor {task.title}</span>{task.deadline || editingDeadline === task.id ? <input type="date" disabled={busy} autoFocus={!task.deadline} value={task.deadline ? task.deadline.slice(0, 10) : ""} onChange={(event) => void updateTask(task.id, { deadline: event.target.value ? new Date(`${event.target.value}T23:59:00`).toISOString() : null })} onBlur={() => { if (!task.deadline) setEditingDeadline(null); }} /> : <button type="button" className="later-deadline-add" onClick={() => setEditingDeadline(task.id)}>+ Deadline</button>}</label><button type="button" disabled={busy} className={`later-urgent-toggle ${task.priority === "high" ? "is-urgent" : ""}`} onClick={() => void updateTask(task.id, { priority: task.priority === "high" ? "medium" : "high" })} aria-label={`${task.priority === "high" ? "Maak niet urgent" : "Maak urgent"}: ${task.title}`} aria-pressed={task.priority === "high"}>{task.priority === "high" ? "Urgent" : "Normaal"}</button></div><div className="later-task-drag" title="Sleep naar een tijdslot vandaag" aria-hidden="true">⋮⋮</div></article>)}{!items.length && <p className="meta later-empty-group">Geen taken hier.</p>}</section>; }

  const dayLabel = dayOffset === 1 ? "morgen" : "vandaag";
  return <main className="later-shell"><header><span className="logo">ADD</span><span>Later</span><a className="lab-link" href="/overview">Overzicht</a></header><section className="later-intro"><p className="eyebrow">WORKFLOW · LATER</p><h1>Kies wat {dayLabel} past.</h1><p className="meta">Kies maximaal drie taken uit je backlog en sleep ze naar een rustig moment {dayLabel}.</p><div className="later-progress" aria-live="polite"><strong>{blocks.length}</strong><span>taken gepland {dayLabel}</span></div></section><div className="later-workspace"><section className="later-backlog" aria-labelledby="backlog-title" onDragOver={(event) => event.preventDefault()} onDrop={handleBacklogDrop}><div className="later-section-heading"><div><p className="eyebrow">BACKLOG</p><h2 id="backlog-title">Wat wil je gaan doen?</h2></div><span className="meta">urgent en daarna deadline</span></div>{loading ? <p className="meta">Backlog laden…</p> : tasks.length ? <>{renderBacklog(urgentTasks, "Urgent", true)}{renderBacklog(normalTasks, "Niet urgent", false)}</> : <div className="later-empty"><h3>Je backlog is leeg.</h3><p className="meta">Nieuwe taken komen vanuit je Inbox hier terecht.</p><a className="secondary-link" href="/review">Naar Inbox</a></div>}</section><section className="later-day" aria-labelledby="day-title"><div className="later-section-heading"><div><p className="eyebrow">{dayOffset === 1 ? "MORGEN" : "VANDAAG"}</p><h2 id="day-title">Sleep naar een moment</h2></div><span className="meta">blokken van 1 uur</span></div><div ref={timelineRef} className="day-timeline" style={{ "--slot-height": `${SLOT_HEIGHT}px` } as React.CSSProperties}>{Array.from({ length: (END_HOUR - START_HOUR) * 2 }, (_, index) => <div className="day-slot" key={index} onDragOver={(event) => event.preventDefault()} onDrop={(event) => handleDayDrop(event, index)}><time>{index % 2 === 0 ? `${String(START_HOUR + index / 2).padStart(2, "0")}:00` : ""}</time><div className="day-slot-line" /></div>)}{dayOffset === 0 && nowTop >= 0 && nowTop <= (END_HOUR - START_HOUR) * 2 * SLOT_HEIGHT && <div ref={nowIndicatorRef} className="now-indicator" style={{ top: nowTop }}><span>nu</span></div>}{blocks.map((block) => { const start = new Date(block.start_at); const top = (((start.getHours() * 60 + start.getMinutes()) - START_HOUR * 60) / SLOT_MINUTES) * SLOT_HEIGHT; const height = (duration(block) / SLOT_MINUTES) * SLOT_HEIGHT; return <article className="planned-block" key={block.id} style={{ top, height }}><button className="start-time-handle" type="button" onPointerDown={(event) => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); (window as Window & { __addStartPointerY?: number }).__addStartPointerY = event.clientY; setStartDragState({ block, initialY: event.clientY }); }} aria-label={`Verplaats starttijd van ${block.task_title}`}>↕</button><div className="planned-block-head" draggable onDragStart={(event) => event.dataTransfer.setData("text/plain", `move:${block.id}`)}><a className="planned-block-title" href={`/task/${block.task_id}`}>{block.task_title}</a><small>{formatTime(block.start_at)}–{formatTime(block.end_at)}</small></div><button className="resize-handle" type="button" onPointerDown={(event) => { event.preventDefault(); (event.currentTarget as HTMLButtonElement).setPointerCapture(event.pointerId); (window as Window & { __addLastPointerY?: number }).__addLastPointerY = event.clientY; setResizeState({ block, initialY: event.clientY, originalDuration: duration(block) }); }} aria-label={`Pas duur aan van ${block.task_title}`}>↕</button></article>; })}</div><p className="later-timeline-hint">Sleep de rechterbovenhoek van een kaart om de starttijd per 30 minuten te verschuiven. Sleep de onderkant om de duur aan te passen.</p></section></div><p className="message">{error || message}</p><p className="later-footer"><a href="/today">Volledige dagplanning openen</a></p></main>;
}
