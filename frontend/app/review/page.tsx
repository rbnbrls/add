"use client";
import { useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Suggestion = { id: string; title: string; description: string | null; source_type: string; suggested_next_action: string; suggested_estimated_minutes: number | null };
type Decision = "reject" | "backlog" | "now";

export default function Review() {
  const [item, setItem] = useState<Suggestion | null>(null), [urgent, setUrgent] = useState(false), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [dragX, setDragX] = useState(0);
  const pointerStart = useRef<{ x: number; y: number } | null>(null);

  async function load() {
    setLoading(true); setDragX(0); setUrgent(false);
    const response = await fetch(`${API}/api/inbox/review`);
    setItem(response.ok ? await response.json() : null);
    setLoading(false);
  }

  async function decide(decision: Decision) {
    if (!item || busy) return;
    setBusy(true); setMessage("");
    let response: Response;
    if (decision === "reject") {
      response = await fetch(`${API}/api/mcp/task-suggestions/${item.id}/reject`, { method: "POST" });
    } else if (decision === "backlog") {
      response = await fetch(`${API}/api/mcp/task-suggestions/${item.id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ urgent }) });
    } else {
      const duration = item.suggested_estimated_minutes || 30;
      response = await fetch(`${API}/api/inbox/review/${item.id}/plan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ destination: "today", duration_minutes: duration, urgent: true }) });
    }
    const body = await response.json().catch(() => null);
    if (response.ok) { setMessage(decision === "reject" ? "Niet doen opgeslagen." : decision === "backlog" ? "Opgenomen in Later." : "Voor vandaag ingepland als prioriteit 1."); await load(); }
    else setMessage(body?.detail || "Deze keuze kon niet worden opgeslagen.");
    setBusy(false);
  }

  function pointerDown(event: React.PointerEvent<HTMLElement>) { if (!busy) { pointerStart.current = { x: event.clientX, y: event.clientY }; event.currentTarget.setPointerCapture(event.pointerId); } }
  function pointerMove(event: React.PointerEvent<HTMLElement>) { if (!pointerStart.current || busy) return; setDragX(event.clientX - pointerStart.current.x); }
  function pointerUp(event: React.PointerEvent<HTMLElement>) { if (!pointerStart.current || busy) return; const dx = event.clientX - pointerStart.current.x, dy = event.clientY - pointerStart.current.y; pointerStart.current = null; setDragX(0); if (Math.max(Math.abs(dx), Math.abs(dy)) < 90) return; if (Math.abs(dx) > Math.abs(dy)) void decide(dx < 0 ? "reject" : "backlog"); else if (dy < 0) void decide("now"); }
  useEffect(() => { void load(); }, []);

  const hasDifferentDescription = item?.description?.trim() && item.description.trim() !== item.title.trim();
  return <main className="inbox-review-shell">
    <header><span className="logo">ADD</span><span>Inbox</span></header>
    {loading ? <section className="hero"><p className="meta">Inbox laden…</p></section> : item ? <>
      <section className="inbox-review-intro"><p className="eyebrow">ÉÉN KEUZE</p><h1>Wat wil je hiermee?</h1><p className="meta">Swipe de kaart, of kies één van de drie knoppen.</p></section>
      <section className="inbox-card" style={{ transform: `translate(${dragX}px, ${dragX ? Math.min(5, Math.abs(dragX) / 18) : 0}px) rotate(${dragX / 18}deg)` }} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={() => { pointerStart.current = null; setDragX(0); }}>
        <div className="inbox-card-source">{item.source_type}</div>
        <h2>{item.title}</h2>
        {hasDifferentDescription && <p className="inbox-card-description">{item.description}</p>}
        <p className="inbox-card-action">{item.suggested_next_action}</p>
      </section>
    <section className="inbox-urgent" aria-labelledby="urgent-label"><div><strong id="urgent-label">Is dit urgent?</strong><p className="meta">Urgent werk krijgt prioriteit 1 wanneer je het op NU zet.</p></div><div className="urgent-options" role="radiogroup" aria-label="Urgentie"><button type="button" className={!urgent ? "selected" : ""} aria-pressed={!urgent} onClick={() => setUrgent(false)}>Niet urgent</button><button type="button" className={urgent ? "selected urgent" : ""} aria-pressed={urgent} onClick={() => setUrgent(true)}>Urgent</button></div></section>
      <section className="inbox-actions" aria-label="Inbox-keuzes"><button className="inbox-decision reject" disabled={busy} onClick={() => void decide("reject")}><span aria-hidden="true">×</span><small>Niet doen</small></button><button className="inbox-decision backlog" disabled={busy} onClick={() => void decide("backlog")}><span aria-hidden="true">✓</span><small>Naar Later</small></button><button className="inbox-decision now" disabled={busy} onClick={() => void decide("now")}><span aria-hidden="true">↑</span><small>NU</small></button></section>
      <p className="inbox-hint">← niet doen · → Later · ↑ NU</p>
    </> : <section className="hero inbox-empty"><p className="eyebrow">RUSTIG</p><h1>Inbox leeg.</h1><p className="meta">Er staat niets meer klaar om te beslissen.</p><a className="secondary-link" href="/intake">Nieuwe taak vastleggen</a></section>}
    {message && <p className="message" aria-live="polite">{message}</p>}
  </main>;
}
