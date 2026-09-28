"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Setup() {
  const [step, setStep] = useState(1);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function secureInstallation(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    if (password.length < 10) { setMessage("Gebruik minimaal 10 tekens."); return; }
    if (password !== confirm) { setMessage("De wachtwoorden zijn niet gelijk."); return; }
    setBusy(true);
    try {
      const setup = await fetch(`${API}/api/auth/setup`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
      if (!setup.ok) { const detail = await setup.json().catch(() => null); setMessage(detail?.detail || "De lokale beveiliging kon niet worden ingesteld."); return; }
      const login = await fetch(`${API}/api/auth/login`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
      if (!login.ok) { setMessage("De beveiliging is ingesteld. Open ADD opnieuw om in te loggen."); return; }
      setPassword(""); setConfirm(""); setStep(3);
    } catch { setMessage("De lokale API is niet bereikbaar. Probeer het opnieuw."); }
    finally { setBusy(false); }
  }

  return <main className="security-shell"><header><span className="logo">ADD</span><span>Eerste start</span></header><section className="hero"><p className="eyebrow">ADD-WIZARD · STAP {step} VAN 3</p>{step===1&&<><h1>Rustig beginnen.</h1><p className="meta">Eén korte controle maakt duidelijk of je lokale uitvoering klaarstaat.</p><button onClick={()=>setStep(2)}>Start setup</button></>}{step===2&&<><h1>Beveilig eerst je installatie.</h1><p className="meta">Kies een lokaal wachtwoord. Pas daarna kun je mail en andere integraties koppelen.</p><form className="intake-form" onSubmit={secureInstallation}><label>Wachtwoord<input autoFocus required minLength={10} type="password" value={password} onChange={event=>setPassword(event.target.value)} autoComplete="new-password"/></label><label>Herhaal wachtwoord<input required minLength={10} type="password" value={confirm} onChange={event=>setConfirm(event.target.value)} autoComplete="new-password"/></label><button disabled={busy||!password||!confirm}>{busy?"Beveiliging instellen…":"Wachtwoord instellen"}</button></form><p className="message">{message}</p></>}{step===3&&<><h1>Je installatie is beveiligd.</h1><p className="meta">Je lokale account is klaar. Nu kun je veilig mailboxen en andere integraties verbinden.</p><div className="actions"><a className="primary-link" href="/integrations">Naar integraties</a><a className="secondary-link" href="/">Ga naar NU</a></div></>}</section></main>;
}
