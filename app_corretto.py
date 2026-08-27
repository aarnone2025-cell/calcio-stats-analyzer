
import streamlit as st
import pandas as pd
import numpy as np
import requests

st.set_page_config(page_title="Calcio Stats Analyzer", page_icon="⚽", layout="wide")
BASE_URL = "https://v3.football.api-sports.io"

HISTORY_SEASON = 2025
CURRENT_SEASON = 2026

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
    r = requests.get(
        f"{BASE_URL}/{endpoint}",
        headers={"x-apisports-key": get_key()},
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=21600, show_spinner=False)
def get_league_ids():
    data = api_get("leagues", {"country": "Italy"})
    found = {}
    for item in data.get("response", []):
        name = item.get("league", {}).get("name", "")
        if name in ("Serie A", "Serie B"):
            found[name] = item.get("league", {}).get("id")
    return found, data.get("errors", [])

@st.cache_data(ttl=21600, show_spinner=False)
def get_finished_fixtures(league_id, season):
    data = api_get("fixtures", {
        "league": league_id,
        "season": season,
        "status": "FT",
        "timezone": "Europe/Rome",
    })
    return data.get("response", []), data.get("errors", [])

@st.cache_data(ttl=21600, show_spinner=False)
def get_upcoming_fixtures(league_id, season, n=20):
    data = api_get("fixtures", {
        "league": league_id,
        "season": season,
        "next": n,
        "timezone": "Europe/Rome",
    })
    return data.get("response", []), data.get("errors", [])

@st.cache_data(ttl=21600, show_spinner=False)
def get_fixture_players(fixture_id):
    data = api_get("fixtures/players", {"fixture": fixture_id})
    return data.get("response", []), data.get("errors", [])

def choose_recent(fixtures_2025, fixtures_2026, matches_per_team):
    # Serie A/B hanno normalmente 10 gare per turno (20 squadre).
    # Per avere circa N partite recenti PER SQUADRA servono circa N*10 fixture totali.
    all_fixtures = fixtures_2025 + fixtures_2026
    all_fixtures = sorted(
        all_fixtures,
        key=lambda f: pd.to_datetime(f["fixture"]["date"])
    )
    target_fixtures = matches_per_team * 10
    return all_fixtures[-target_fixtures:]

def parse_player_rows(fixtures):
    rows = []
    total = max(len(fixtures), 1)
    progress = st.progress(0, text="Caricamento statistiche giocatori...")

    for i, f in enumerate(fixtures):
        fixture_id = f["fixture"]["id"]
        date = pd.to_datetime(f["fixture"]["date"]).date().isoformat()
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match = f"{home} - {away}"
        season = f.get("league", {}).get("season")

        blocks, _ = get_fixture_players(fixture_id)

        for block in blocks:
            team = block.get("team", {}).get("name", "")
            opponent = away if team == home else home

            for p in block.get("players", []):
                stats_list = p.get("statistics", [])
                if not stats_list:
                    continue

                s = stats_list[0]
                games = s.get("games") or {}
                shots = s.get("shots") or {}
                cards = s.get("cards") or {}
                goals = s.get("goals") or {}

                rows.append({
                    "date": date,
                    "season": season,
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

        progress.progress((i + 1) / total, text=f"Partite analizzate: {i+1}/{len(fixtures)}")

    progress.empty()
    return pd.DataFrame(rows)

def rate(g, stat, threshold, n, min_minutes):
    x = g[g["minutes"] >= min_minutes].sort_values("date")
    if n:
        x = x.tail(n)
    if len(x) == 0:
        return np.nan
    return (x[stat] >= threshold).mean()

def build_rankings(df, market, min_minutes, min_apps):
    if df.empty:
        return pd.DataFrame()

    stat, threshold = MARKETS[market]
    rows = []
    league_avg = (df[stat] >= threshold).mean()

    for player, g in df.groupby("player"):
        usable = g[g["minutes"] >= min_minutes].sort_values("date")
        if len(usable) < min_apps:
            continue

        r5 = rate(g, stat, threshold, 5, min_minutes)
        r10 = rate(g, stat, threshold, 10, min_minutes)
        r15 = rate(g, stat, threshold, 15, min_minutes)
        rall = rate(g, stat, threshold, None, min_minutes)

        vals, weights = [], []
        for v, w in [(r5, 0.40), (r10, 0.30), (r15, 0.20), (rall, 0.10)]:
            if not np.isnan(v):
                vals.append(v)
                weights.append(w)

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
            "Ultime 5": round(r5 * 100, 1) if not np.isnan(r5) else np.nan,
            "Ultime 10": round(r10 * 100, 1) if not np.isnan(r10) else np.nan,
            "Ultime 15": round(r15 * 100, 1) if not np.isnan(r15) else np.nan,
            "Periodo totale": round(rall * 100, 1),
            "Prob. stimata": round(prob * 100, 1),
            "Quota equa": round(1 / prob, 2) if prob > 0 else np.nan,
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["Prob. stimata", "Presenze usate"], ascending=[False, False])
    return out

st.title("⚽ Calcio Stats Analyzer")
st.caption("Serie A e Serie B — forma 2025/26 + stagione corrente 2026/27")

if not get_key():
    st.error("Chiave API non trovata nei Secrets di Streamlit.")
    st.stop()

with st.spinner("Connessione ad API-Football..."):
    league_ids, errors = get_league_ids()

if errors:
    st.error(f"Errore API: {errors}")
    st.stop()

available = [x for x in ["Serie A", "Serie B"] if x in league_ids]
if not available:
    st.error("Non trovo Serie A o Serie B.")
    st.stop()

with st.sidebar:
    st.header("Filtri")
    league_name = st.selectbox("Campionato", available)
    recent_matches = st.slider(
        "Ultime partite per squadra",
        5, 15, 10, 1,
        help="10 significa circa le ultime 10 gare di ogni squadra, non 10 gare totali del campionato."
    )
    market = st.selectbox("Mercato", list(MARKETS.keys()))
    min_minutes = st.slider("Minuti minimi per presenza", 1, 90, 45)
    min_apps = st.slider("Presenze minime", 2, 15, 3)
    threshold = st.slider("Mostra probabilità da", 50, 100, 70)
    st.caption("Dati in cache per 6 ore per limitare le richieste API.")

league_id = league_ids[league_name]

st.info(
    f"📡 {league_name} — storico {HISTORY_SEASON}/26 + stagione corrente {CURRENT_SEASON}/27"
)

with st.spinner("Recupero partite 2025/26 e 2026/27..."):
    old_fx, err_old = get_finished_fixtures(league_id, HISTORY_SEASON)
    current_fx, err_current = get_finished_fixtures(league_id, CURRENT_SEASON)

if err_old:
    st.warning(f"Avviso storico 2025: {err_old}")
if err_current:
    st.warning(f"Avviso stagione 2026: {err_current}")

fixtures = choose_recent(old_fx, current_fx, recent_matches)

if not fixtures:
    st.warning("Nessuna partita conclusa trovata.")
    st.stop()

df = parse_player_rows(fixtures)
if df.empty:
    st.warning("Le partite sono state trovate ma non sono disponibili statistiche giocatore.")
    st.stop()

ranking = build_rankings(df, market, min_minutes, min_apps)
filtered = ranking[ranking["Prob. stimata"] >= threshold].copy() if not ranking.empty else ranking

c1, c2, c3, c4 = st.columns(4)
c1.metric("Giocatori analizzati", df["player"].nunique())
c2.metric(f"Segnali ≥ {threshold}%", len(filtered))
c3.metric("Gare di campionato analizzate", len(fixtures))
c4.metric("Gare 2026/27 incluse", len([f for f in fixtures if f.get("league", {}).get("season") == CURRENT_SEASON]))

st.subheader(f"🏆 TOP — {market}")

if not filtered.empty:
    def cls(p):
        if p >= 85:
            return "🟢 Molto alta"
        if p >= 75:
            return "🟡 Alta"
        if p >= 65:
            return "⚪ Media"
        return "🔴 Bassa"
    filtered.insert(0, "Classe", filtered["Prob. stimata"].map(cls))
    st.dataframe(filtered, use_container_width=True, hide_index=True)
else:
    st.info("Nessun giocatore supera i filtri selezionati.")

st.subheader("📅 Prossime partite — stagione 2026/27")

future, future_errors = get_upcoming_fixtures(league_id, CURRENT_SEASON, 20)
if future_errors:
    st.warning(f"Errore prossime partite: {future_errors}")

future_rows = [{
    "Data": pd.to_datetime(f["fixture"]["date"]).strftime("%d/%m/%Y %H:%M"),
    "Partita": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
    "Giornata": f.get("league", {}).get("round", "")
} for f in future]

if future_rows:
    st.dataframe(pd.DataFrame(future_rows), use_container_width=True, hide_index=True)
else:
    st.info("Nessuna prossima partita trovata per la stagione 2026/27.")

st.subheader("👤 Scheda giocatore")

players = sorted(df["player"].dropna().unique())
if players:
    player = st.selectbox("Giocatore", players)
    g = df[df["player"] == player].sort_values("date", ascending=False)
    st.dataframe(
        g[[
            "date", "season", "match", "team", "opponent", "minutes",
            "shots_total", "shots_on_target", "yellow_cards",
            "red_cards", "saves"
        ]],
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.caption(
    "La stima usa la forma recente attraversando la fine della stagione 2025/26 "
    "e l'inizio della 2026/27. Le percentuali sono stime statistiche e non garantiscono un esito."
)
