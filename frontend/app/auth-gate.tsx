"use client";
import { useEffect, useState } from "react";
const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
export default function AuthGate({children}:{children:React.ReactNode}){const[ready,setReady]=useState(false),[required,setRequired]=useState(false),[authenticated,setAuthenticated]=useState(true),[password,setPassword]=useState(""),[error,setError]=useState("");
 useEffect(()=>{const original=window.fetch.bind(window);window.fetch=((input:RequestInfo|URL,init:RequestInit={})=>original(input,{...init,credentials:init.credentials||"include"})) as typeof window.fetch;const timeout=window.setTimeout(()=>setReady(true),1500);fetch(`${API}/api/auth/status`,{credentials:"include"}).then(r=>r.json()).then(d=>{setRequired(d.enabled);setAuthenticated(d.authenticated);setReady(true)}).catch(()=>setReady(true));return()=>window.clearTimeout(timeout)},[]);
 async function login(e:React.FormEvent){e.preventDefault();setError("");const r=await fetch(`${API}/api/auth/login`,{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify({password})});if(r.ok){setAuthenticated(true);setPassword("")}else setError("Wachtwoord klopt niet.")}
 if(!ready)return <main className="security-shell"><section className="hero"><p className="meta">Lokale sessie controleren…</p></section></main>;
 if(required&&!authenticated)return <main className="security-shell"><section className="hero"><p className="eyebrow">LOKALE LOGIN</p><h1>Welkom terug.</h1><p className="meta">Ontgrendel ADD om verder te gaan.</p><form className="intake-form" onSubmit={login}><label>Wachtwoord<input autoFocus type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password"/></label><button>Ontgrendelen</button></form><p className="message">{error}</p></section></main>;
 return <>{children}</>;
}
