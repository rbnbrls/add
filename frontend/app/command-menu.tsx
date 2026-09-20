"use client";
import { useEffect, useState } from "react";

export default function CommandMenu(){
 const[open,setOpen]=useState(false);
 useEffect(()=>{const onKey=(event:KeyboardEvent)=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==="k"){event.preventDefault();setOpen(value=>!value)}if(event.key==="Escape")setOpen(false)};window.addEventListener("keydown",onKey);return()=>window.removeEventListener("keydown",onKey)},[]);
 return <>{open&&<div className="command-backdrop" role="presentation" onClick={()=>setOpen(false)}><section className="command-menu" role="dialog" aria-modal="true" aria-label="Command menu" onClick={event=>event.stopPropagation()}><div className="pending-heading"><h2>Command menu</h2><button className="quiet" onClick={()=>setOpen(false)}>Sluiten</button></div><p className="meta">Kies een ingang voor de volgende stap.</p><nav className="command-links" aria-label="Snelle commando's"><a className="primary-link" href="/intake?quick=1">Snel vastleggen</a><a href="/review">Review openen</a><a href="/">Volgende actie</a><a href="/execute">Start uitvoeren</a></nav></section></div>}<button className="command-trigger quiet" aria-keyshortcuts="Control+K Meta+K" onClick={()=>setOpen(true)}>⌘K Command menu</button></>;
}
