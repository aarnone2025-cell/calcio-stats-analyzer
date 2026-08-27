import streamlit as st
import pandas as pd
import numpy as np
import requests

st.set_page_config(page_title="Calcio Stats Analyzer", page_icon="⚽", layout="wide")
BASE_URL = "https://v3.football.api-sports.io"

MARKETS = {
    "1+ tiro": ("shots_total", 1),
    "2+ tiri": ("shots_total", 2),
    "3+ tiri": ("shots_total", 3),
    "1+ tiro in porta": ("shots_on_target", 1),
    "2+ tiri in porta": ("shots_on_target", 2),
    "Ammonito": ("yellow_cards", 1),
    "3+ parate": ("saves", 3),
    "4+ parate": ("saves", 4),
    "5+ parate": ("saves", 5),
}

def get_key():
    try:
        return st.secrets["API_FOOTBALL_KEY"]
    except Exception:
        return None

@st.cache_data(ttl=21600, show_spinner=False)
def api_get(endpoint, params):
    key = get_key()
    r = requests.get(
        f"{BASE_URL}/{endpoint}",
        headers={"x-apisports-key": key},
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=21600, show_spinner=False)
def get_leagues():
    data = api_get("leagues", {"country": "Italy", "current": "true"})
    found = {}
    for item in data.get("response", []):
        name = item.get("league", {}).get("name", "")
        if name not in ("Serie A", "Serie B"):
            continue
        current = next((s for s in item.get("seasons", []) if s.get("current")), None)
        if current:
            found[name] = {"id": item["league"]["id"], "season": 2024}
    return found, data.get("errors", [])

@st.cache_data(ttl=21600, show_spinner=False)
def get_fixtures(league_id, season, last_n):
    data = api_get("fixtures", {
        "league": league_id,
        "season": season,
        "status": "FT",
        "timezone": "Europe/Rome",
    })
    fixtures = data.get("response", [])
    return fixtures[-last_n:], data.get("errors", [])

@st.cache_data(ttl=21600, show_spinner=False)
def get_next(league_id, season):
    data = api_get("fixtures", {
        "league": league_id,
        "season": season,
        "next": 10,
        "timezone": "Europe/Rome",
    })
    return data.get("response", [])

@st.cache_data(ttl=21600, show_spinner=False)
def get_players(fixture_id):
    data = api_get("fixtures/players", {"fixture": fixture_id})
    return data.get("response", []), data.get("errors", [])

def parse_rows(fixtures):
    rows = []
    bar = st.progress(0, text="Caricamento statistiche giocatori...")
    total = max(len(fixtures), 1)

    for i, f in enumerate(fixtures):
        fid = f["fixture"]["id"]
        date = pd.to_datetime(f["fixture"]["date"]).date().isoformat()
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match = f"{home} - {away}"

        blocks, _ = get_players(fid)
        for block in blocks:
            team = block.get("team", {}).get("name", "")
            opponent = away if team == home else home
            for p in block.get("players", []):
                stats = p.get("statistics", [])
                if not stats:
                    continue
                s = stats[0]
                games = s.get("games") or {}
                shots = s.get("shots") or {}
                cards = s.get("cards") or {}
                goals = s.get("goals") or {}
                rows.append({
                    "date": date,
                    "league": f["league"]["name"],
                    "match": match,
                    "team": team,
                    "opponent": opponent,
                    "player": p.get("player", {}).get("name", ""),
                    "position": games.get("position", ""),
                    "minutes": games.get("minutes") or 0,
                    "shots_total": shots.get("total") or 0,
                    "shots_on_target": shots.get("on") or 0,
                    "yellow_cards": cards.get("yellow") or 0,
                    "red_cards": cards.get("red") or 0,
                    "saves": goals.get("saves") or 0,
                })
        bar.progress((i + 1) / total, text=f"Partite analizzate: {i+1}/{len(fixtures)}")
    bar.empty()
    return pd.DataFrame(rows)

def rate(g, stat, threshold, n, min_minutes):
    x = g[g["minutes"] >= min_minutes].sort_values("date")
    if n:
        x = x.tail(n)
    if len(x) == 0:
        return np.nan
    return (x[stat] >= threshold).mean()

def rankings(df, market, min_minutes, min_apps):
    stat, threshold = MARKETS[market]
    rows = []
    if df.empty:
        return pd.DataFrame()
    league_avg = (df[stat] >= threshold).mean()

    for player, g in df.groupby("player"):
        usable = g[g["minutes"] >= min_minutes].sort_values("date")
        if len(usable) < min_apps:
            continue
        r5 = rate(g, stat, threshold, 5, min_minutes)
        r10 = rate(g, stat, threshold, 10, min_minutes)
        rp = rate(g, stat, threshold, None, min_minutes)
        vals, weights = [], []
        for v, w in [(r5, .45), (r10, .30), (rp, .25)]:
            if not np.isnan(v):
                vals.append(v); weights.append(w)
        raw = np.average(vals, weights=weights)
        strength = min(len(usable) / 15.0, 1.0)
        prob = raw * strength + league_avg * (1 - strength)
        last = usable.iloc[-1]
        rows.append({
            "Giocatore": player,
            "Squadra": last["team"],
            "Ruolo": last["position"],
            "Presenze usate": len(usable),
            "Minuti medi": round(usable.tail(10)["minutes"].mean(), 1),
            "Ultime 5": round(r5 * 100, 1),
            "Ultime 10": round(r10 * 100, 1),
            "Periodo": round(rp * 100, 1),
            "Prob. stimata": round(prob * 100, 1),
            "Quota equa": round(1 / prob, 2) if prob > 0 else np.nan,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["Prob. stimata", "Presenze usate"], ascending=[False, False])
    return out

st.title("⚽ Calcio Stats Analyzer")
st.caption("Dati reali API-Football — Serie A e Serie B")

if not get_key():
    st.error("Chiave API non trovata nei Secrets di Streamlit.")
    st.stop()

with st.spinner("Connessione ad API-Football..."):
    leagues, errors = get_leagues()

if errors:
    st.error(f"Errore API: {errors}")
    st.stop()

if not leagues:
    st.error("Non trovo Serie A o Serie B tra le competizioni italiane correnti.")
    st.stop()

with st.sidebar:
    st.header("Filtri")
    league_name = st.selectbox("Campionato", [x for x in ["Serie A", "Serie B"] if x in leagues])
    last_n = st.slider("Partite recenti da analizzare", 5, 20, 10, 5)
    market = st.selectbox("Mercato", list(MARKETS.keys()))
    min_minutes = st.slider("Minuti minimi", 1, 90, 45)
    min_apps = st.slider("Presenze minime", 2, 10, 3)
    threshold = st.slider("Mostra probabilità da", 50, 100, 70)
    st.caption("Cache di 6 ore per ridurre il consumo della quota API.")

cfg = leagues[league_name]
st.info(f"📡 {league_name} — stagione {cfg['season']}")

with st.spinner("Scarico le partite concluse..."):
    fixtures, errors = get_fixtures(cfg["id"], cfg["season"], last_n)

if errors:
    st.error(f"Errore partite: {errors}")
    st.stop()

if not fixtures:
    st.warning("Nessuna partita conclusa trovata.")
    st.stop()

df = parse_rows(fixtures)
if df.empty:
    st.warning("Le partite sono state trovate, ma l'API non ha restituito statistiche giocatore per queste gare.")
    st.stop()

ranking = rankings(df, market, min_minutes, min_apps)
filtered = ranking[ranking["Prob. stimata"] >= threshold].copy() if not ranking.empty else ranking

c1, c2, c3 = st.columns(3)
c1.metric("Giocatori analizzati", df["player"].nunique())
c2.metric(f"Segnali ≥ {threshold}%", len(filtered))
c3.metric("Partite analizzate", len(fixtures))

st.subheader(f"🏆 TOP — {market}")
if not filtered.empty:
    def cls(p):
        if p >= 85: return "🟢 Molto alta"
        if p >= 75: return "🟡 Alta"
        if p >= 65: return "⚪ Media"
        return "🔴 Bassa"
    filtered.insert(0, "Classe", filtered["Prob. stimata"].map(cls))
    st.dataframe(filtered, use_container_width=True, hide_index=True)
else:
    st.info("Nessun giocatore supera i filtri selezionati.")

st.subheader("📅 Prossime partite")
future = get_next(cfg["id"], cfg["season"])
future_rows = [{
    "Data": pd.to_datetime(f["fixture"]["date"]).strftime("%d/%m/%Y %H:%M"),
    "Partita": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}"
} for f in future]
if future_rows:
    st.dataframe(pd.DataFrame(future_rows), use_container_width=True, hide_index=True)

st.subheader("👤 Scheda giocatore")
players = sorted(df["player"].dropna().unique())
if players:
    player = st.selectbox("Giocatore", players)
    g = df[df["player"] == player].sort_values("date", ascending=False)
    st.dataframe(g[[
        "date","match","team","opponent","minutes",
        "shots_total","shots_on_target","yellow_cards","red_cards","saves"
    ]], use_container_width=True, hide_index=True)

st.divider()
st.caption("Le percentuali sono stime statistiche, non garanzie. Prima dell'uso con quote reali il modello va validato su un campione storico più ampio.")
