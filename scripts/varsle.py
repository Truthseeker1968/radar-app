#!/usr/bin/env python3
"""Sender e-post når nye signaler har oppstått siden forrige kjøring.

Regler for støy: samme signal (instrument+kode) varsles ikke på nytt før det
har vært borte i minst 24 timer, og det sendes maks én e-post per time.
Hemmeligheter leses fra miljøvariabler: GMAIL_USER, GMAIL_APP_PASSWORD, VARSEL_TIL.
"""
import json, os, smtplib, ssl, datetime as dt, pathlib, sys
from email.message import EmailMessage

ROT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROT / "data"
SENDT = DATA / "varsler_sendt.json"
NAA = dt.datetime.now(dt.timezone.utc)

siste = json.loads((DATA / "siste.json").read_text(encoding="utf-8"))
regler = siste["regler"]
hist = json.loads(SENDT.read_text(encoding="utf-8")) if SENDT.exists() else {"signaler": {}, "siste_epost": None}

nye = []
aktive = set()
for r in siste["instrumenter"]:
    for s in r["signaler"]:
        if s["nivaa"] == "info":
            continue  # topp/bunn vises i appen, men sendes ikke på e-post
        n = f"{r['symbol']}:{s['kode']}"
        aktive.add(n)
        sist = hist["signaler"].get(n)
        if sist is None or (NAA - dt.datetime.fromisoformat(sist)).total_seconds() > 24 * 3600:
            nye.append((r, s))
        else:
            hist["signaler"][n] = sist  # behold første observasjon

# glem signaler som ikke lenger er aktive og er eldre enn 24 t
for n, t in list(hist["signaler"].items()):
    if n not in aktive and (NAA - dt.datetime.fromisoformat(t)).total_seconds() > 24 * 3600:
        del hist["signaler"][n]

sperre = False
if hist.get("siste_epost"):
    sperre = (NAA - dt.datetime.fromisoformat(hist["siste_epost"])).total_seconds() < 3600 / regler.get("maks_varsler_per_time", 1)

if not nye:
    print("Ingen nye signaler.")
elif sperre:
    print(f"{len(nye)} nye signaler, men e-post ble sendt for under en time siden. Venter.")
    # rull tilbake tidsstempel så de sendes neste gang
    for r, s in nye:
        hist["signaler"].pop(f"{r['symbol']}:{s['kode']}", None)
else:
    bruker, pw, til = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD"), os.environ.get("VARSEL_TIL")
    if not (bruker and pw and til):
        print("Mangler GMAIL_USER / GMAIL_APP_PASSWORD / VARSEL_TIL – hopper over sending.", file=sys.stderr)
        sendt_ok = False
    else:
        sendt_ok = True
        linjer = []
        for r, s in nye:
            kurs = f"{r['kurs']:,} {r['valuta']}".replace(",", " ") if r.get("kurs") else "–"
            linjer.append(f"{r['navn']} ({r['symbol']})  {kurs}\n    {s['tekst']}\n    Tema: {r['tema']}")
        app = os.environ.get("APP_URL", "")
        tekst = ("Radar-varsel " + NAA.astimezone(dt.timezone(dt.timedelta(hours=2))).strftime("%d.%m.%Y %H:%M") + "\n\n"
                 + "\n\n".join(linjer)
                 + "\n\nDette er regelbaserte observasjoner, ikke kjøps- eller salgsråd. "
                 + "Du vurderer og handler selv i DNB-appen.\n" + (f"\nApp: {app}\n" if app else ""))
        m = EmailMessage()
        m["Subject"] = f"Radar: {len(nye)} nye signaler – " + ", ".join(sorted({r['symbol'] for r, _ in nye}))
        m["From"], m["To"] = bruker, til
        m.set_content(tekst)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
            s.login(bruker, pw)
            s.send_message(m)
        hist["siste_epost"] = NAA.isoformat(timespec="seconds")
        print(f"Sendte e-post med {len(nye)} signaler til {til}.")
    if sendt_ok:
        for r, s in nye:
            hist["signaler"][f"{r['symbol']}:{s['kode']}"] = NAA.isoformat(timespec="seconds")

SENDT.write_text(json.dumps(hist, indent=1), encoding="utf-8")
