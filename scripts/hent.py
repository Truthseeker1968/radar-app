#!/usr/bin/env python3
"""Henter kurser for alle instrumenter, beregner signaler og skriver data/siste.json.

Kilder: CoinGecko (krypto, gratis, ingen nøkkel) og Yahoo Finance via yfinance
(aksjer og fond-NAV). Alle regler er deterministiske og forklarbare; ingen
kjøps- eller salgsanbefalinger genereres.
"""
import json, math, time, datetime as dt, pathlib, sys
import requests
import yfinance as yf
import pandas as pd

ROT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROT / "data"
HIST = DATA / "historikk"
HIST.mkdir(exist_ok=True, parents=True)

cfg = json.loads((DATA / "instrumenter.json").read_text(encoding="utf-8"))
REGLER = cfg["regler"]
NAA = dt.datetime.now(dt.timezone.utc)


def rsi(serie: pd.Series, n: int = 14) -> float | None:
    if len(serie) < n + 1:
        return None
    d = serie.diff().dropna()
    opp = d.clip(lower=0).rolling(n).mean()
    ned = (-d.clip(upper=0)).rolling(n).mean()
    rs = opp / ned.replace(0, math.nan)
    v = 100 - 100 / (1 + rs)
    v = v.dropna()
    return round(float(v.iloc[-1]), 1) if len(v) else None


def signaler(close: pd.Series, vol: pd.Series | None, dogn_pct: float | None) -> list[dict]:
    """Returnerer liste av {kode, tekst, nivaa}. nivaa: info | obs | viktig."""
    ut = []
    if dogn_pct is not None and abs(dogn_pct) >= REGLER["dogn_pct"]:
        retning = "opp" if dogn_pct > 0 else "ned"
        ut.append({"kode": "DOGN", "nivaa": "viktig",
                   "tekst": f"Døgnbevegelse {dogn_pct:+.1f} % ({retning}), terskel {REGLER['dogn_pct']} %"})
    if vol is not None and len(vol) >= 31 and vol.iloc[-1] > 0:
        snitt = vol.iloc[-31:-1].mean()
        if snitt > 0 and vol.iloc[-1] >= REGLER["volum_x_snitt30"] * snitt:
            ut.append({"kode": "VOLUM", "nivaa": "obs",
                       "tekst": f"Volum {vol.iloc[-1]/snitt:.1f}× 30-dagers snitt"})
    r = rsi(close)
    if r is not None:
        if r <= REGLER["rsi_lav"]:
            ut.append({"kode": "RSI", "nivaa": "obs", "tekst": f"RSI(14) {r} – oversolgt-sone"})
        elif r >= REGLER["rsi_hoy"]:
            ut.append({"kode": "RSI", "nivaa": "obs", "tekst": f"RSI(14) {r} – overkjøpt-sone"})
    k, l = REGLER["sma_kort"], REGLER["sma_lang"]
    if len(close) >= l + 1:
        sk, sl = close.rolling(k).mean(), close.rolling(l).mean()
        if sk.iloc[-2] <= sl.iloc[-2] and sk.iloc[-1] > sl.iloc[-1]:
            ut.append({"kode": "KRYSS", "nivaa": "viktig", "tekst": f"SMA{k} krysset over SMA{l} (gyllent kryss)"})
        elif sk.iloc[-2] >= sl.iloc[-2] and sk.iloc[-1] < sl.iloc[-1]:
            ut.append({"kode": "KRYSS", "nivaa": "viktig", "tekst": f"SMA{k} krysset under SMA{l} (dødskryss)"})
    n = REGLER["nyhoy_lav_dager"]
    if len(close) >= n:
        vindu = close.iloc[-n:]
        if close.iloc[-1] >= vindu.max():
            ut.append({"kode": "TOPP", "nivaa": "info", "tekst": f"Ny {n}-dagers topp"})
        elif close.iloc[-1] <= vindu.min():
            ut.append({"kode": "BUNN", "nivaa": "info", "tekst": f"Ny {n}-dagers bunn"})
    return ut


def pct(a, b):
    return None if (a is None or b is None or b == 0) else round((a / b - 1) * 100, 2)


def lagre_hist(id_: str, close: pd.Series):
    """Lagrer inntil 400 daglige sluttkurser som [[dato, kurs], ...]."""
    s = close.dropna().iloc[-400:]
    rader = [[str(i.date()), round(float(v), 6)] for i, v in s.items()]
    (HIST / f"{id_.replace('/', '_')}.json").write_text(json.dumps(rader), encoding="utf-8")


# ---------- Krypto (CoinGecko) ----------
def hent_krypto(instr: list[dict]) -> list[dict]:
    if not instr:
        return []
    ids = ",".join(i["id"] for i in instr)
    r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                     params={"ids": ids, "vs_currencies": "usd,nok", "include_24hr_change": "true",
                             "include_24hr_vol": "true", "include_last_updated_at": "true"}, timeout=30)
    r.raise_for_status()
    live = r.json()
    ut = []
    for i in instr:
        p = live.get(i["id"], {})
        rad = {**i, "kurs": p.get("usd"), "kurs_nok": p.get("nok"), "valuta": "USD",
               "dogn_pct": round(p["usd_24h_change"], 2) if p.get("usd_24h_change") is not None else None,
               "volum24": p.get("usd_24h_vol"), "tid": p.get("last_updated_at"), "signaler": [], "feil": None}
        try:
            h = requests.get(f"https://api.coingecko.com/api/v3/coins/{i['id']}/market_chart",
                             params={"vs_currency": "usd", "days": "365", "interval": "daily"}, timeout=30)
            h.raise_for_status()
            hj = h.json()
            idx = pd.to_datetime([x[0] for x in hj["prices"]], unit="ms")
            close = pd.Series([x[1] for x in hj["prices"]], index=idx)
            vol = pd.Series([x[1] for x in hj["total_volumes"]], index=idx)
            rad["uke_pct"] = pct(rad["kurs"], float(close.iloc[-8])) if len(close) > 8 else None
            rad["mnd_pct"] = pct(rad["kurs"], float(close.iloc[-31])) if len(close) > 31 else None
            rad["rsi"] = rsi(close)
            rad["signaler"] = signaler(close, vol, rad["dogn_pct"])
            lagre_hist(i["id"], close)
            time.sleep(2.5)  # CoinGecko gratis: ~30 kall/min
        except Exception as e:  # noqa
            rad["feil"] = f"historikk: {e}"
        ut.append(rad)
    return ut


# ---------- Aksjer og fond (Yahoo) ----------
def hent_yahoo(instr: list[dict]) -> list[dict]:
    ut = []
    for i in instr:
        rad = {**i, "kurs": None, "valuta": None, "dogn_pct": None, "signaler": [], "feil": None}
        try:
            t = yf.Ticker(i["id"])
            df = t.history(period="2y", interval="1d", auto_adjust=False)
            if df.empty:
                raise ValueError("ingen data fra Yahoo for denne tickeren")
            close = df["Close"].dropna()
            vol = df["Volume"] if "Volume" in df else None
            fi = getattr(t, "fast_info", None)
            kurs = float(close.iloc[-1])
            try:
                lp = fi.last_price if fi is not None else None
                if lp and not math.isnan(lp):
                    kurs = float(lp)
            except Exception:
                pass
            rad.update({
                "kurs": round(kurs, 4),
                "valuta": (getattr(fi, "currency", None) or "").upper() or None,
                "dogn_pct": pct(kurs, float(close.iloc[-2])) if len(close) > 1 else None,
                "uke_pct": pct(kurs, float(close.iloc[-6])) if len(close) > 6 else None,
                "mnd_pct": pct(kurs, float(close.iloc[-22])) if len(close) > 22 else None,
                "rsi": rsi(close),
                "tid": int(close.index[-1].timestamp()),
            })
            rad["signaler"] = signaler(close, vol if i["type"] == "aksje" else None, rad["dogn_pct"])
            lagre_hist(i["id"], close)
        except Exception as e:  # noqa
            rad["feil"] = str(e)[:160]
        ut.append(rad)
    return ut


def main():
    alle = cfg["instrumenter"]
    krypto = hent_krypto([i for i in alle if i["type"] == "crypto"])
    yahoo = hent_yahoo([i for i in alle if i["type"] in ("aksje", "fond")])
    rader = krypto + yahoo
    # NOK-kurs for aksjer: hent USDNOK, EURNOK osv. én gang
    fx = {}
    for par in ("USDNOK=X", "EURNOK=X", "JPYNOK=X", "HKDNOK=X"):
        try:
            fx[par[:3]] = round(float(yf.Ticker(par).fast_info.last_price), 4)
        except Exception:
            pass
    fx["NOK"] = 1.0
    for r in rader:
        if r.get("kurs") is not None and r.get("kurs_nok") is None and r.get("valuta") in fx:
            r["kurs_nok"] = round(r["kurs"] * fx[r["valuta"]], 2)
    ut = {"generert": NAA.isoformat(timespec="seconds"), "regler": REGLER, "valutakurser": fx,
          "instrumenter": rader}
    (DATA / "siste.json").write_text(json.dumps(ut, ensure_ascii=False, indent=1), encoding="utf-8")
    n_sig = sum(len(r["signaler"]) for r in rader)
    n_feil = sum(1 for r in rader if r["feil"])
    print(f"OK: {len(rader)} instrumenter, {n_sig} signaler, {n_feil} feil")
    for r in rader:
        if r["feil"]:
            print(f"  FEIL {r['symbol']}: {r['feil']}", file=sys.stderr)


if __name__ == "__main__":
    main()
