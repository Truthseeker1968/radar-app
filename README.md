# Radar – kurser og signaler

Daglig kurs- og signallag over Teknologiradarens temaer: kvantesikker krypto (XRP, XLM, ALGO, QRL), SMR, fusjon, kvante, KI-medisin, Oslo Børs og DNB-fond.

Hvert 5. minutt henter GitHub Actions kurser (CoinGecko, Yahoo Finance), beregner regelbaserte signaler og sender e-post ved nye. Appen på GitHub Pages leser `data/siste.json`.

Ingen kjøps- eller salgsråd. Regler og instrumentliste i `data/instrumenter.json`.

## Oppsett

1. Settings → Pages → Source: `main`, mappe `/ (root)`.
2. Settings → Secrets and variables → Actions → New repository secret:
   `GMAIL_USER` (Gmail-adressen som sender), `GMAIL_APP_PASSWORD` (app-passord fra Google-kontoen, krever totrinnsverifisering), `VARSEL_TIL` (mottaker).
3. Actions → «Overvåk og varsle» → Run workflow for første kjøring.

Lokalt: `pip install -r requirements.txt && python scripts/hent.py`.
