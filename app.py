
import streamlit as st
import pandas as pd
import numpy as np
import requests
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
    "1+ fallo commesso": ("fouls_committed", 1),
    "2+ falli commessi": ("fouls_committed", 2),
    "3+ falli commessi": ("fouls_committed", 3),
    "1+ fallo subito": ("fouls_drawn", 1),
    "2+ falli subiti": ("fouls_drawn", 2),
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

LEAGUES = {
    "Serie A 🇮🇹": 135,
    "Serie B 🇮🇹": 136,
    "Premier League 🏴": 39,
    "La Liga 🇪🇸": 140,
    "Bundesliga 🇩🇪": 78,
    "Ligue 1 🇫🇷": 61,
}

@st.cache_data(ttl=21600, show_spinner=False)
def get_finished_fixtures(league_id, season):
    data = api_get("fixtures", {
        "league": league_id,
        "season": season,
        "status": "FT",
        "timezone": "Europe/Rome",
    })
    return data.get("response", []), data.get("errors", [])

@st.cache_data(ttl=1800, show_spinner=False)
def get_upcoming_fixtures(league_id, season, days_ahead=14):
    """
    Recupero robusto fixture future:
    1) intervallo esplicito oggi -> +N giorni
    2) fallback automatico con next=30
    3) filtra sempre solo gare non iniziate e realmente future
    """
    tz = ZoneInfo("Europe/Rome")
    now = datetime.now(tz)
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    all_errors = {}

    # Metodo 1: intervallo date esplicito
    data = api_get("fixtures", {
        "league": league_id,
        "season": season,
        "from": date_from,
        "to": date_to,
        "timezone": "Europe/Rome",
    })

    if data.get("errors"):
        all_errors["date_range"] = data.get("errors")

    fixtures = data.get("response") or []

    # Metodo 2: fallback "next"
    if not fixtures:
        fallback = api_get("fixtures", {
            "league": league_id,
            "season": season,
            "next": 30,
            "timezone": "Europe/Rome",
        })

        if fallback.get("errors"):
            all_errors["next"] = fallback.get("errors")

        fixtures = fallback.get("response") or []

    future = []

    for f in fixtures:
        fixture = f.get("fixture", {}) or {}
        status = (fixture.get("status") or {}).get("short")
        dt_raw = fixture.get("date")

        if not dt_raw:
            continue

        dt = pd.to_datetime(dt_raw)

        if dt.tzinfo is None:
            dt = dt.tz_localize("Europe/Rome")
        else:
            dt = dt.tz_convert("Europe/Rome")

        # Solo partite non iniziate e future
        if status in {"NS", "TBD"} and dt.to_pydatetime() > now:
            future.append(f)

    # Deduplica per fixture id
    unique = {}
    for f in future:
        fid = f.get("fixture", {}).get("id")
        unique[fid] = f

    future = list(unique.values())
    future.sort(key=lambda f: pd.to_datetime(f["fixture"]["date"]))

    return future, all_errors

@st.cache_data(ttl=21600, show_spinner=False)
def get_fixture_players(fixture_id):
    data = api_get("fixtures/players", {"fixture": fixture_id})
    return data.get("response", []), data.get("errors", [])

def choose_recent(fixtures_2025, fixtures_2026, matches_per_team):
    all_fixtures = fixtures_2025 + fixtures_2026
    all_fixtures = sorted(
        all_fixtures,
        key=lambda f: pd.to_datetime(f["fixture"]["date"])
    )

    # Cap prudente: circa N gare per squadra.
    # Nei campionati a 18 squadre può includere qualche fixture in più,
    # che migliora il campione senza alterare il calcolo per singolo giocatore.
    target_fixtures = matches_per_team * 10
    return all_fixtures[-target_fixtures:]

def parse_player_rows(fixtures, league_label='Campionato'):
    rows = []
    total = max(len(fixtures), 1)
    progress = st.progress(0, text=f"{league_label}: caricamento statistiche giocatori...")

    for i, f in enumerate(fixtures):
        fixture_id = f["fixture"]["id"]
        date = pd.to_datetime(f["fixture"]["date"]).date().isoformat()
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match = f"{home} - {away}"
        season = f.get("league", {}).get("season")

        blocks, _ = get_fixture_players(fixture_id)

        for block in blocks:
            team_obj = block.get("team", {}) or {}
            team = team_obj.get("name", "")
            team_id = team_obj.get("id")

            home_id = f.get("teams", {}).get("home", {}).get("id")
            away_id = f.get("teams", {}).get("away", {}).get("id")

            opponent = away if team_id == home_id else home
            opponent_id = away_id if team_id == home_id else home_id
            venue = "Casa" if team_id == home_id else "Trasferta"

            for p in block.get("players", []):
                stats_list = p.get("statistics", [])
                if not stats_list:
                    continue

                s = stats_list[0]
                games = s.get("games") or {}
                shots = s.get("shots") or {}
                cards = s.get("cards") or {}
                goals = s.get("goals") or {}
                fouls = s.get("fouls") or {}

                rows.append({
                    "date": date,
                    "season": season,
                    "league": f["league"]["name"],
                    "match": match,
                    "team": team,
                    "team_id": team_id,
                    "opponent": opponent,
                    "opponent_id": opponent_id,
                    "venue": venue,
                    "player_id": p.get("player", {}).get("id"),
                    "player": p.get("player", {}).get("name", ""),
                    "position": games.get("position", ""),
                    "starter": not bool(games.get("substitute", False)),
                    "minutes": games.get("minutes") or 0,
                    "shots_total": shots.get("total") or 0,
                    "shots_on_target": shots.get("on") or 0,
                    "yellow_cards": cards.get("yellow") or 0,
                    "red_cards": cards.get("red") or 0,
                    "fouls_committed": fouls.get("committed") or 0,
                    "fouls_drawn": fouls.get("drawn") or 0,
                    "saves": goals.get("saves") or 0,
                })

        progress.progress((i + 1) / total, text=f"{league_label}: partite analizzate {i+1}/{len(fixtures)}")

    progress.empty()
    return pd.DataFrame(rows)


def window_rate(g, stat, threshold, n, min_minutes):
    x = g[g["minutes"] >= min_minutes].sort_values("date")
    x = x.tail(n)
    used = len(x)
    if used == 0:
        return np.nan, 0, 0
    hits = int((x[stat] >= threshold).sum())
    return hits / used, hits, used

def format_window(rate_value, hits, used, target):
    if used == 0:
        return "—"
    pct = round(rate_value * 100)
    suffix = f"{hits}/{used}"
    if used < target:
        return f"{pct}% ({suffix}; <{target})"
    return f"{pct}% ({suffix})"

def bayes_rate(hits, total, prior_mean, prior_strength=3.0):
    if total <= 0:
        return prior_mean
    return (hits + prior_mean * prior_strength) / (total + prior_strength)

def poisson_at_least(lmbda, threshold):
    """
    Probabilità P(X >= threshold) con X ~ Poisson(lambda).
    Utile come stima di volume per tiri, falli, cartellini e parate.
    """
    lmbda = max(float(lmbda), 0.0)
    threshold = int(threshold)
    if threshold <= 0:
        return 1.0
    cumulative = 0.0
    for k in range(threshold):
        cumulative += math.exp(-lmbda) * (lmbda ** k) / math.factorial(k)
    return float(np.clip(1.0 - cumulative, 0.0, 1.0))

def recency_probability(g, stat, threshold, min_minutes, prior_mean, max_games=15):
    x = g[g["minutes"] >= min_minutes].sort_values("date").tail(max_games).copy()
    n = len(x)
    if n == 0:
        return prior_mean, 0

    outcomes = (x[stat] >= threshold).astype(float).to_numpy()
    weights = np.array([0.90 ** (n - 1 - i) for i in range(n)], dtype=float)

    weighted_hits = float(np.sum(outcomes * weights))
    weighted_total = float(np.sum(weights))
    prior_strength = 3.0

    posterior = (
        weighted_hits + prior_mean * prior_strength
    ) / (weighted_total + prior_strength)

    return float(np.clip(posterior, 0.01, 0.99)), n

def weighted_per90(g, stat, min_minutes, max_games=15):
    x = g[g["minutes"] >= min_minutes].sort_values("date").tail(max_games).copy()
    if x.empty:
        return 0.0

    mins = x["minutes"].clip(lower=1).astype(float).to_numpy()
    vals = x[stat].fillna(0).astype(float).to_numpy()
    per90 = vals * 90.0 / mins

    n = len(x)
    weights = np.array([0.90 ** (n - 1 - i) for i in range(n)], dtype=float)
    return float(np.average(per90, weights=weights))

def contextual_hit_rate(df, stat, threshold, min_minutes, *, opponent=None, venue=None, prior_mean=0.5):
    x = df[df["minutes"] >= min_minutes].copy()

    if opponent is not None:
        x = x[x["opponent"] == opponent]
    if venue is not None and "venue" in x.columns:
        x = x[x["venue"] == venue]

    if x.empty:
        return prior_mean, 0

    hits = int((x[stat] >= threshold).sum())
    return bayes_rate(hits, len(x), prior_mean, prior_strength=5.0), len(x)

def opponent_market_context(df, stat, threshold, min_minutes, next_opponent, league_avg, next_opponent_id=None):
    """
    Misura quanto il prossimo avversario favorisce o limita SPECIFICAMENTE
    il mercato scelto, usando le prestazioni dei giocatori che lo hanno affrontato.

    Per le parate consideriamo solo i portieri per evitare che gli zeri dei
    giocatori di movimento falsino il dato.
    """
    eligible = df[df["minutes"] >= min_minutes].copy()

    if stat == "saves":
        if "position" in eligible.columns:
            eligible = eligible[
                eligible["position"].astype(str).str.upper().isin(["G", "GK", "GOALKEEPER"])
            ]
        # fallback se l'API usa codifiche diverse
        if eligible.empty:
            eligible = df[(df["minutes"] >= min_minutes) & (df["saves"] > 0)].copy()

    if eligible.empty or not next_opponent:
        return league_avg, 1.0, 0, 0.0, 0.0

    if next_opponent_id is not None and "opponent_id" in eligible.columns:
        opp_rows = eligible[
            pd.to_numeric(eligible["opponent_id"], errors="coerce") == int(next_opponent_id)
        ].copy()
    else:
        opp_rows = eligible[eligible["opponent"] == next_opponent].copy()

    league_hit = float((eligible[stat] >= threshold).mean()) if not eligible.empty else league_avg
    league_mean = float(eligible[stat].mean()) if not eligible.empty else 0.0

    if opp_rows.empty:
        return league_hit, 1.0, 0, league_mean, league_mean

    opp_hits = int((opp_rows[stat] >= threshold).sum())
    opp_hit_prob = bayes_rate(
        opp_hits,
        len(opp_rows),
        league_hit,
        prior_strength=6.0,
    )

    opp_mean = float(opp_rows[stat].mean())

    # Fattore di volume: >1 avversario favorevole al mercato, <1 avversario difficile.
    if league_mean > 0:
        volume_factor = float(np.clip(opp_mean / league_mean, 0.70, 1.30))
    else:
        volume_factor = 1.0

    # Smorziamo campioni piccoli.
    sample_conf = min(len(opp_rows) / 40.0, 1.0)
    volume_factor = 1.0 + (volume_factor - 1.0) * sample_conf

    return (
        float(np.clip(opp_hit_prob, 0.01, 0.99)),
        float(np.clip(volume_factor, 0.75, 1.25)),
        int(len(opp_rows)),
        round(opp_mean, 3),
        round(league_mean, 3),
    )


def advanced_probability(df, g, stat, threshold, min_minutes, upcoming, league_avg):
    """
    Modello pre-match contestuale.

    Componenti principali:
      40% forma recente del giocatore
      25% volume atteso per la prossima partita
      15% rendimento casa/trasferta
      20% profilo SPECIFICO del prossimo avversario per quel mercato

    Poi riduce la previsione verso la media di campionato quando il campione
    o la continuità del giocatore sono poco affidabili.
    """
    usable = g[g["minutes"] >= min_minutes].sort_values("date").tail(15).copy()
    if usable.empty:
        return league_avg, {}

    recent_prob, n = recency_probability(
        g, stat, threshold, min_minutes, league_avg, max_games=15
    )

    next_venue = upcoming.get("Casa/Fuori") if upcoming else None
    next_opponent = upcoming.get("Avversario") if upcoming else None
    next_opponent_id = upcoming.get("Avversario ID") if upcoming else None

    # Casa / trasferta del singolo giocatore.
    venue_sample = (
        usable[usable["venue"] == next_venue]
        if next_venue
        else usable.iloc[0:0]
    )
    venue_hits = (
        int((venue_sample[stat] >= threshold).sum())
        if not venue_sample.empty
        else 0
    )
    venue_prob = bayes_rate(
        venue_hits,
        len(venue_sample),
        league_avg,
        prior_strength=4.0,
    )

    # Contesto avversario specifico per il mercato.
    opp_prob, opp_volume_factor, opp_n, opp_mean, league_mean = opponent_market_context(
        df,
        stat,
        threshold,
        min_minutes,
        next_opponent,
        league_avg,
        next_opponent_id=next_opponent_id,
    )

    # Volume recente del giocatore per 90'.
    player_per90 = weighted_per90(g, stat, min_minutes, max_games=15)

    recent5 = usable.tail(5)
    expected_minutes = (
        float(recent5["minutes"].mean())
        if not recent5.empty
        else float(usable["minutes"].mean())
    )
    expected_minutes = float(np.clip(expected_minutes, 20.0, 90.0))

    # Il volume del giocatore viene adattato a quanto il prossimo avversario
    # concede / provoca per QUEL mercato.
    expected_lambda = (
        player_per90
        * (expected_minutes / 90.0)
        * opp_volume_factor
    )
    volume_prob = poisson_at_least(expected_lambda, threshold)

    raw_prob = (
        0.40 * recent_prob
        + 0.25 * volume_prob
        + 0.15 * venue_prob
        + 0.20 * opp_prob
    )

    # Affidabilità del campione del giocatore.
    sample_score = min(len(usable) / 15.0, 1.0)
    minute_score = float(np.clip(expected_minutes / 75.0, 0.45, 1.0))

    if "starter" in usable.columns:
        starter_rate = float(usable.tail(10)["starter"].astype(float).mean())
    else:
        starter_rate = 0.75

    continuity_score = 0.70 + 0.30 * starter_rate
    reliability = float(
        np.clip(sample_score * minute_score * continuity_score, 0.0, 1.0)
    )

    confidence = 0.55 + 0.45 * reliability
    final_prob = confidence * raw_prob + (1.0 - confidence) * league_avg
    final_prob = float(np.clip(final_prob, 0.03, 0.97))

    # Etichetta leggibile dell'effetto avversario.
    if opp_volume_factor <= 0.92:
        opponent_effect = "🔴 Difficile"
    elif opp_volume_factor >= 1.08:
        opponent_effect = "🟢 Favorevole"
    else:
        opponent_effect = "⚪ Neutro"

    details = {
        "Forma recente %": round(recent_prob * 100, 1),
        "Volume %": round(volume_prob * 100, 1),
        "Casa/Trasferta %": round(venue_prob * 100, 1),
        "Avversario %": round(opp_prob * 100, 1),
        "Effetto avversario": opponent_effect,
        "Fattore avversario": round(opp_volume_factor, 2),
        "Media vs avversario": opp_mean,
        "Media campionato": league_mean,
        "Media/90": round(player_per90, 2),
        "Minuti attesi": round(expected_minutes, 1),
        "Titolarità recente %": round(starter_rate * 100, 1),
        "Affidabilità %": round(reliability * 100, 1),
        "Campione avversario": int(opp_n),
    }

    return final_prob, details



def build_upcoming_map(future):
    """
    Prima gara futura per ogni squadra, indicizzata tramite ID API.
    """
    mapping = {}
    ordered = sorted(
        future,
        key=lambda f: pd.to_datetime(f["fixture"]["date"])
    )

    for f in ordered:
        home_obj = f.get("teams", {}).get("home", {}) or {}
        away_obj = f.get("teams", {}).get("away", {}) or {}

        home_id = home_obj.get("id")
        away_id = away_obj.get("id")
        home = home_obj.get("name", "")
        away = away_obj.get("name", "")

        dt = pd.to_datetime(f["fixture"]["date"])
        if dt.tzinfo is not None:
            dt = dt.tz_convert("Europe/Rome")

        if home_id is not None and home_id not in mapping:
            mapping[int(home_id)] = {
                "Avversario": away,
                "Avversario ID": away_id,
                "Casa/Fuori": "Casa",
                "Data prossima": dt.strftime("%d/%m/%Y %H:%M"),
            }

        if away_id is not None and away_id not in mapping:
            mapping[int(away_id)] = {
                "Avversario": home,
                "Avversario ID": home_id,
                "Casa/Fuori": "Trasferta",
                "Data prossima": dt.strftime("%d/%m/%Y %H:%M"),
            }

    return mapping


def recent_sequence(g, column, min_minutes, n=5):
    x = g[g["minutes"] >= min_minutes].sort_values("date").tail(n)
    if x.empty:
        return "—"
    vals = [str(int(v)) for v in x[column].fillna(0).tolist()]
    return " · ".join(vals)


def yellow_sequence(g, min_minutes, n=5):
    return recent_sequence(g, "yellow_cards", min_minutes, n)


def build_rankings(df, market, min_minutes, min_apps, upcoming_map=None):
    if df.empty:
        return pd.DataFrame()

    stat, threshold = MARKETS[market]
    eligible = df[df["minutes"] >= min_minutes]

    if eligible.empty:
        return pd.DataFrame()

    league_avg = float((eligible[stat] >= threshold).mean())
    rows = []
    group_key = "player_id" if "player_id" in df.columns else "player"

    for _, g in df.groupby(group_key, dropna=False):
        usable = g[g["minutes"] >= min_minutes].sort_values("date")
        if len(usable) < min_apps:
            continue

        last = usable.iloc[-1]
        team = last["team"]
        team_id = last.get("team_id")

        upcoming = None
        if upcoming_map is not None and team_id is not None and not pd.isna(team_id):
            upcoming = upcoming_map.get(int(team_id))

        if upcoming_map is not None and upcoming is None:
            continue

        r5, h5, n5 = window_rate(g, stat, threshold, 5, min_minutes)
        r10, h10, n10 = window_rate(g, stat, threshold, 10, min_minutes)
        r15, h15, n15 = window_rate(g, stat, threshold, 15, min_minutes)

        try:
            prob, details = advanced_probability(
                df, g, stat, threshold, min_minutes, upcoming, league_avg
            )
        except Exception:
            # Fallback prudente: non bloccare l'intero campionato se una
            # componente contestuale manca per un singolo giocatore/mercato.
            prob, _ = recency_probability(
                g, stat, threshold, min_minutes, league_avg, max_games=15
            )
            details = {
                "Forma recente %": round(prob * 100, 1),
                "Volume %": np.nan,
                "Casa/Trasferta %": np.nan,
                "Avversario %": np.nan,
                "Effetto avversario": "⚠️ Dato parziale",
                "Fattore avversario": np.nan,
                "Media vs avversario": np.nan,
                "Media campionato": np.nan,
                "Media/90": round(weighted_per90(g, stat, min_minutes, 15), 2),
                "Minuti attesi": round(float(usable.tail(5)["minutes"].mean()), 1),
                "Titolarità recente %": np.nan,
                "Affidabilità %": round(min(len(usable) / 15.0, 1.0) * 100, 1),
                "Campione avversario": 0,
            }

        recent10 = usable.tail(10)
        row = {
            "Giocatore": last["player"],
            "Squadra": team,
            "Ruolo": last["position"],
            "Presenze usate": min(len(usable), 15),
            "Minuti medi": round(recent10["minutes"].mean(), 1),
            "Ultime 5": format_window(r5, h5, n5, 5),
            "Ultime 10": format_window(r10, h10, n10, 10),
            "Ultime 15": format_window(r15, h15, n15, 15),
            "Tiri ultime 5": recent_sequence(g, "shots_total", min_minutes, 5),
            "In porta ultime 5": recent_sequence(g, "shots_on_target", min_minutes, 5),
            "Falli ultime 5": recent_sequence(g, "fouls_committed", min_minutes, 5),
            "Ammonizioni ultime 5": yellow_sequence(g, min_minutes, 5),
            "Prob. stimata": round(prob * 100, 1),
            "Quota equa": round(1.0 / prob, 2) if prob > 0 else np.nan,
            **details,
        }

        if upcoming:
            row["Prossimo avversario"] = upcoming["Avversario"]
            row["Casa/Fuori"] = upcoming["Casa/Fuori"]
            row["Data prossima"] = upcoming["Data prossima"]

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        ["Prob. stimata", "Presenze usate"],
        ascending=[False, False]
    ).reset_index(drop=True)


st.title("⚽ Calcio Stats Analyzer — Europa")
st.caption(
    "Analisi pre-match automatica: Serie A, Serie B, Premier League, "
    "La Liga, Bundesliga e Ligue 1. Cerca le gare da oggi ai successivi "
    "14 giorni, in ora italiana."
)

if not get_key():
    st.error("Chiave API non trovata nei Secrets di Streamlit.")
    st.stop()

with st.sidebar:
    st.header("Filtri")
    market_choice = st.selectbox(
        "Mercato",
        ["Tutti i mercati"] + list(MARKETS.keys()),
        index=0,
    )
    recent_matches = st.slider(
        "Ultime partite per squadra",
        5, 15, 10, 1,
        help="Numero di gare recenti circa per squadra usate per costruire lo storico."
    )
    min_minutes = st.slider("Minuti minimi per presenza", 1, 90, 45)
    min_apps = st.slider("Presenze minime", 2, 15, 5)
    probability_threshold = st.slider("Mostra probabilità da", 50, 100, 70)
    max_signals = st.slider("Numero massimo segnali", 10, 150, 50, 10)
    st.caption("Dati in cache per 6 ore per limitare le richieste API.")

markets_to_scan = list(MARKETS.keys()) if market_choice == "Tutti i mercati" else [market_choice]

all_rankings = []
all_player_data = []
future_rows = []
league_status = []
total_fixtures = 0
current_fixtures_count = 0

status_box = st.empty()

for league_label, league_id in LEAGUES.items():
    status_box.info(f"📡 Analisi {league_label}...")

    try:
        old_fx, err_old = get_finished_fixtures(league_id, HISTORY_SEASON)
        current_fx, err_current = get_finished_fixtures(league_id, CURRENT_SEASON)
        future, future_errors = get_upcoming_fixtures(
            league_id, CURRENT_SEASON, 14
        )

        fixtures = choose_recent(old_fx, current_fx, recent_matches)

        # PRIMA registriamo sempre le prossime partite.
        for f in future:
            fixture_dt = pd.to_datetime(f["fixture"]["date"])
            if fixture_dt.tzinfo is not None:
                fixture_dt = fixture_dt.tz_convert("Europe/Rome")

            today_rome = datetime.now(ZoneInfo("Europe/Rome")).date()
            delta_days = (fixture_dt.date() - today_rome).days
            when_label = (
                "OGGI" if delta_days == 0
                else ("DOMANI" if delta_days == 1 else fixture_dt.strftime("%d/%m"))
            )

            future_rows.append({
                "Quando": when_label,
                "Campionato": league_label,
                "Data": fixture_dt.strftime("%d/%m/%Y %H:%M"),
                "Partita": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                "Giornata": f.get("league", {}).get("round", ""),
            })

        total_fixtures += len(fixtures)
        current_fixtures_count += len([
            f for f in fixtures
            if f.get("league", {}).get("season") == CURRENT_SEASON
        ])

        if not fixtures:
            league_status.append({
                "Campionato": league_label,
                "Stato": "⚠️ Nessuno storico",
                "Nota": f"0 storiche · {len(future)} future",
            })
            continue

        df_league = parse_player_rows(fixtures, league_label=league_label)

        if df_league.empty:
            league_status.append({
                "Campionato": league_label,
                "Stato": "⚠️ Nessuna statistica",
                "Nota": f"{len(fixtures)} storiche · {len(future)} future",
            })
            continue

        df_league["Campionato"] = league_label
        all_player_data.append(df_league)

        upcoming_map = build_upcoming_map(future)

        historical_team_ids = set()
        if "team_id" in df_league.columns:
            historical_team_ids = set(
                pd.to_numeric(df_league["team_id"], errors="coerce")
                .dropna()
                .astype(int)
                .unique()
            )
        matched_teams_count = len(
            historical_team_ids.intersection(set(upcoming_map.keys()))
        )

        market_errors = []

        # Ogni mercato viene calcolato separatamente:
        # un errore non blocca più gli altri.
        for market_name in markets_to_scan:
            try:
                r = build_rankings(
                    df_league,
                    market_name,
                    min_minutes,
                    min_apps,
                    upcoming_map=upcoming_map,
                )
                if not r.empty:
                    r.insert(0, "Mercato", market_name)
                    r.insert(0, "Campionato", league_label)
                    all_rankings.append(r)
            except Exception as market_error:
                market_errors.append(
                    f"{market_name}: {type(market_error).__name__}: {market_error}"
                )

        note = (
            f"{len(fixtures)} storiche · {len(future)} future · "
            f"{matched_teams_count} squadre abbinate"
        )
        if future_errors:
            note += f" · API fixture: {future_errors}"
        if market_errors:
            note += f" · {len(market_errors)} mercati con errore"

        league_status.append({
            "Campionato": league_label,
            "Stato": "✅ OK" if not market_errors else "⚠️ Parziale",
            "Nota": note,
        })

    except Exception as e:
        league_status.append({
            "Campionato": league_label,
            "Stato": "❌ Errore",
            "Nota": f"{type(e).__name__}: {e}",
        })

status_box.empty()

if not all_player_data:
    st.error("Non sono riuscito a recuperare statistiche giocatore dai campionati configurati.")
    if league_status:
        st.dataframe(pd.DataFrame(league_status), use_container_width=True, hide_index=True)
    st.stop()

all_df = pd.concat(all_player_data, ignore_index=True)

if all_rankings:
    ranking = pd.concat(all_rankings, ignore_index=True)
    filtered = ranking[ranking["Prob. stimata"] >= probability_threshold].copy()
    filtered = filtered.sort_values(
        ["Prob. stimata", "Presenze usate"],
        ascending=[False, False]
    ).head(max_signals)
else:
    ranking = pd.DataFrame()
    filtered = pd.DataFrame()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Campionati", len(LEAGUES))
c2.metric("Giocatori analizzati", all_df["player_id"].nunique())
c3.metric(f"Segnali ≥ {probability_threshold}%", len(filtered))
c4.metric("Gare storiche usate", total_fixtures)

st.subheader("🏆 Migliori segnali pre-match d'Europa")

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

    preferred_cols = [
        "Classe",
        "Campionato",
        "Giocatore",
        "Squadra",
        "Prossimo avversario",
        "Casa/Fuori",
        "Data prossima",
        "Mercato",
        "Presenze usate",
        "Minuti medi",
        "Tiri ultime 5",
        "In porta ultime 5",
        "Falli ultime 5",
        "Ammonizioni ultime 5",
        "Ultime 5",
        "Ultime 10",
        "Ultime 15",
        "Prob. stimata",
        "Quota equa",
        "Effetto avversario",
        "Media/90",
        "Minuti attesi",
        "Affidabilità %",
    ]
    cols = [c for c in preferred_cols if c in filtered.columns]
    st.dataframe(
        filtered[cols],
        use_container_width=True,
        hide_index=True,
        height=650,
    )

    with st.expander("🧠 Perché il modello assegna questa probabilità"):
        detail_cols = [
            "Campionato", "Giocatore", "Squadra", "Mercato",
            "Forma recente %", "Volume %", "Casa/Trasferta %",
            "Avversario %", "Effetto avversario", "Fattore avversario",
            "Media vs avversario", "Media campionato",
            "Media/90", "Minuti attesi",
            "Titolarità recente %", "Affidabilità %",
            "Prob. stimata", "Quota equa"
        ]
        detail_cols = [c for c in detail_cols if c in filtered.columns]
        st.dataframe(
            filtered[detail_cols],
            use_container_width=True,
            hide_index=True,
        )
else:
    st.info("Nessun segnale supera i filtri selezionati.")
    st.caption(
        "Se ci sono partite future ma zero segnali, prova temporaneamente "
        "ad abbassare 'Mostra probabilità da' per verificare la distribuzione."
    )

with st.expander("📊 Stato dei campionati analizzati"):
    st.dataframe(pd.DataFrame(league_status), use_container_width=True, hide_index=True)

st.subheader("📅 Prossime partite")

if future_rows:
    future_df = pd.DataFrame(future_rows)
    future_df["_sort"] = pd.to_datetime(
        future_df["Data"], format="%d/%m/%Y %H:%M", errors="coerce"
    )
    future_df = future_df.sort_values("_sort").drop(columns="_sort")
    future_cols = ["Quando", "Campionato", "Data", "Partita", "Giornata"]
    future_cols = [c for c in future_cols if c in future_df.columns]
    st.dataframe(future_df[future_cols], use_container_width=True, hide_index=True)
else:
    st.warning(
        "Nessuna prossima partita trovata. Apri 'Stato dei campionati analizzati' "
        "per vedere se l'API sta restituendo fixture future per ciascuna lega."
    )

st.subheader("👤 Scheda giocatore")

player_options = (
    all_df[["player_id", "player", "team", "Campionato"]]
    .drop_duplicates(subset=["player_id"], keep="last")
    .sort_values("player")
)

if not player_options.empty:
    labels = {
        row.player_id: f"{row.player} — {row.team} — {row.Campionato}"
        for row in player_options.itertuples()
    }

    selected_id = st.selectbox(
        "Giocatore",
        options=list(labels.keys()),
        format_func=lambda x: labels[x],
    )

    g = all_df[all_df["player_id"] == selected_id].sort_values("date", ascending=False)

    player_view = g[[
        "date", "season", "league", "match", "team", "team_id", "opponent", "opponent_id", "venue", "starter", "minutes",
        "shots_total", "shots_on_target",
        "fouls_committed", "fouls_drawn",
        "yellow_cards", "red_cards", "saves"
    ]].copy()

    player_view = player_view.rename(columns={
        "date": "Data",
        "season": "Stagione",
        "league": "Campionato",
        "match": "Partita",
        "team": "Squadra",
        "team_id": "ID squadra",
        "opponent": "Avversario",
        "opponent_id": "ID avversario",
        "venue": "Casa/Trasferta",
        "starter": "Titolare",
        "minutes": "Minuti",
        "shots_total": "Tiri",
        "shots_on_target": "Tiri in porta",
        "fouls_committed": "Falli commessi",
        "fouls_drawn": "Falli subiti",
        "yellow_cards": "Ammonizioni",
        "red_cards": "Espulsioni",
        "saves": "Parate",
    })

    st.dataframe(player_view, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "Analisi esclusivamente pre-match. La probabilità usa al massimo le ultime 15 presenze valide e combina forma recente, "
    "volume per 90 minuti, minuti attesi, continuità/titolarità, casa-trasferta e un profilo "
    "specifico del prossimo avversario per ciascun mercato. Per esempio, una difesa che concede "
    "pochi tiri riduce i mercati tiri, mentre un attacco che costringe i portieri a molte parate "
    "può aumentare i mercati parate. I campioni piccoli vengono corretti verso la media del campionato. "
    "Le percentuali sono stime statistiche, non garanzie di esito. "
    "Tiri, falli, cartellini e parate dipendono dalla copertura API disponibile per la singola gara."
)
