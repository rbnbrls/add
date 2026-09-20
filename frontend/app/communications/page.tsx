"use client";
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Tone = "formal" | "informal";
type Mode = "message" | "text";
type TextMode = "rewrite" | "analyze";
type Analysis = { tone: string; emotion: string; directness: string; attention_point: string };

export default function Communications() {
  const [mode, setMode] = useState<Mode>("message");
  const [textMode, setTextMode] = useState<TextMode>("rewrite");
  const [recipient, setRecipient] = useState("mijzelf");
  const [body, setBody] = useState("Ik pak dit vandaag op.");
  const [draft, setDraft] = useState<{ recipient: string; body: string } | null>(null);
  const [text, setText] = useState("");
  const [tone, setTone] = useState<Tone>("formal");
  const [rewrite, setRewrite] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  function clearTextResult() { setRewrite(""); setAnalysis(null); setMessage(""); }

  async function create(e: React.FormEvent) {
    e.preventDefault(); setMessage("");
    const r = await fetch(`${API}/api/mcp/create-message-draft`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ recipient, body }) });
    if (r.ok) { setDraft({ recipient, body }); setMessage("Concept aangemaakt. Controleer de tekst voordat je bevestigt."); }
    else setMessage("Concept maken is niet gelukt.");
  }

  async function confirm() {
    if (!draft) return;
    const r = await fetch(`${API}/api/mcp/send-message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...draft, confirmed: true }) });
    setMessage(r.ok ? "Bericht als verzonden gemarkeerd." : "Verzenden is niet gelukt.");
    if (r.ok) setDraft(null);
  }

  async function assist(e: React.FormEvent) {
    e.preventDefault(); setLoading(true); setMessage(""); setRewrite(""); setAnalysis(null);
    const endpoint = textMode === "rewrite" ? "/api/text/rewrite" : "/api/text/analyze";
    const payload = textMode === "rewrite" ? { text, tone } : { text };
    try {
      const r = await fetch(`${API}${endpoint}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await r.json().catch(() => null);
      if (!r.ok) setMessage(data?.detail || "Teksthulp is tijdelijk niet beschikbaar.");
      else if (textMode === "rewrite") setRewrite(data.text);
      else setAnalysis(data);
    } catch { setMessage("Teksthulp is tijdelijk niet beschikbaar."); }
    finally { setLoading(false); }
  }

  async function copyResult() {
    const value = rewrite || (analysis ? Object.values(analysis).join("\n") : "");
    try { await navigator.clipboard.writeText(value); setMessage("Resultaat gekopieerd."); }
    catch { setMessage("Kopiëren lukt niet in deze browser. Het resultaat blijft zichtbaar."); }
  }

  const hasTextResult = Boolean(rewrite || analysis);
  return <main>
    <header><span className="logo">ADD</span><span>Communicatie</span><a className="lab-link" href="/">← Terug naar NU</a></header>
    <section className="lab-hero"><p className="eyebrow">EXPLICIETE BEVESTIGING</p><h1>Communicatie rustig voorbereiden.</h1><p className="meta">Kies één tekstflow. ADD verstuurt niets zonder dat je een concept controleert en bevestigt.</p><div className="actions" role="group" aria-label="Communicatiemodus"><button className={mode === "message" ? "" : "secondary"} onClick={() => { setMode("message"); clearTextResult(); }}>Berichtconcept</button><button className={mode === "text" ? "" : "secondary"} onClick={() => { setMode("text"); setDraft(null); setMessage(""); }}>Teksthulp</button></div></section>
    {mode === "message" ? <><section className="lab-tools"><form onSubmit={create} className="lab-fields"><label>Ontvanger<input value={recipient} onChange={e => setRecipient(e.target.value)} /></label><label className="lab-wide">Bericht<textarea value={body} onChange={e => setBody(e.target.value)} /></label><button>Concept maken</button></form><p className="message">{message}</p></section>{draft && <section className="suggestion"><p className="eyebrow">CONCEPT</p><h2>Aan: {draft.recipient}</h2><p>{draft.body}</p><div className="actions"><button onClick={confirm}>Bevestig en verzend</button><button className="quiet" onClick={() => setDraft(null)}>Annuleren</button></div></section>}</> : <>
      <section className="lab-tools"><div className="actions" role="group" aria-label="Teksthulptype"><button className={textMode === "rewrite" ? "" : "secondary"} onClick={() => { setTextMode("rewrite"); clearTextResult(); }}>Herschrijven</button><button className={textMode === "analyze" ? "" : "secondary"} onClick={() => { setTextMode("analyze"); clearTextResult(); }}>Toon analyseren</button></div><form onSubmit={assist} className="lab-fields text-assistance-form"><label className="lab-wide">Tekst<textarea required maxLength={4000} value={text} onChange={e => setText(e.target.value)} placeholder="Plak hier de tekst…" /></label>{textMode === "rewrite" && <label>Gewenste toon<select value={tone} onChange={e => setTone(e.target.value as Tone)}><option value="formal">Formeel</option><option value="informal">Informeel</option></select></label>}<button disabled={loading}>{loading ? "Bezig…" : textMode === "rewrite" ? "Herschrijf tekst" : "Analyseer toon"}</button></form>{message && <p className="message">{message}</p>}</section>
      {hasTextResult && <section className="lab-output"><p className="eyebrow">RESULTAAT</p>{rewrite && <p className="text-result">{rewrite}</p>}{analysis && <dl className="analysis-result"><div><dt>Toon</dt><dd>{analysis.tone}</dd></div><div><dt>Emotie</dt><dd>{analysis.emotion}</dd></div><div><dt>Directheid</dt><dd>{analysis.directness}</dd></div><div><dt>Aandachtspunt</dt><dd>{analysis.attention_point}</dd></div></dl>}<div className="actions"><button onClick={copyResult}>Kopiëren</button><button className="quiet" onClick={clearTextResult}>Weggooien</button></div></section>}
    </>}
  </main>;
}
