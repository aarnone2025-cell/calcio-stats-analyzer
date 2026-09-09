
import streamlit as st
import pandas as pd
import numpy as np
import requests
import math
import re
import unicodedata
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
def get_odds_bets():
    """Elenco ufficiale dei mercati pre-match disponibili nel catalogo Odds."""
    return api_get("odds/bets", {})


@st.cache_data(ttl=21600, show_spinner=False)
def get_odds_bookmakers():
    """Elenco dei bookmaker disponibili nel catalogo Odds di API-Football."""
    return api_get("odds/bookmakers", {})


# Player props pre-match che ci interessano.
# Gli ID possono avere varianti Home/Away o duplicati nel catalogo;
# per il test reale filtriamo anche per nome per essere robusti.
PLAYER_PROP_BET_IDS = {
    102, 240, 241, 242, 251, 264, 265,
    266, 267, 268, 269, 270, 271, 274, 275, 276, 277,
}

PLAYER_PROP_PATTERNS = (
    "player shots",
    "player shots on target",
    "player to be booked",
    "player fouls committed",
    "goalkeeper saves",
)


@st.cache_data(ttl=10800, show_spinner=False)
def get_fixture_odds(fixture_id):
    """Quote pre-match per una singola fixture. Cache 3 ore come update dell'endpoint Odds."""
    return api_get("odds", {"fixture": int(fixture_id)})


def is_relevant_player_prop(bet_id, bet_name):
    name = str(bet_name or "").strip().lower()
    if int(bet_id or -1) in PLAYER_PROP_BET_IDS:
        return True
    return any(p in name for p in PLAYER_PROP_PATTERNS)




def human_market(bet_name):
    """Etichetta leggibile del player prop, senza esporre i nomi tecnici API."""
    n = str(bet_name or "").lower()
    if "booked" in n:
        return "Cartellino giallo"
    if "fouls committed" in n:
        return "Falli commessi"
    if "goalkeeper saves" in n:
        return "Parate"
    if "shots on target" in n:
        return "Tiri in porta"
    if "player shots" in n:
        return "Tiri"
    return str(bet_name or "Altro")


def split_player_and_line(value, bet_name):
    """Separa il nome giocatore dall'eventuale soglia numerica codificata nel value API."""
    raw = str(value or "").strip()
    player = raw
    threshold = None
    m = re.match(r"^(.*?)\s+-\s+(\d+(?:[.,]\d+)?)$", raw)
    if m:
        player = m.group(1).strip()
        try:
            threshold = float(m.group(2).replace(",", "."))
        except Exception:
            threshold = None

    market = human_market(bet_name)
    if market == "Cartellino giallo":
        giocata = "Ammonito"
    elif threshold is None:
        giocata = market
    else:
        t = int(threshold) if float(threshold).is_integer() else threshold
        if market == "Tiri":
            giocata = f"{t}+ tiri"
        elif market == "Tiri in porta":
            giocata = f"{t}+ tiri in porta"
        elif market == "Falli commessi":
            giocata = f"{t}+ falli commessi"
        elif market == "Parate":
            giocata = f"{t}+ parate"
        else:
            giocata = f"{market} - {t}"
    return player, threshold, giocata


def parse_fixture_odds(odds_json, league_label=None):
    """Normalizza la risposta /odds in righe bookmaker/mercato/valore/quota."""
    rows = []
    response = odds_json.get("response") or []

    for item in response:
        fixture = item.get("fixture") or {}
        league = item.get("league") or {}
        fixture_id = fixture.get("id")
        fixture_date = fixture.get("date")
        update = item.get("update")

        for bm in item.get("bookmakers") or []:
            bookmaker_id = bm.get("id")
            bookmaker_name = bm.get("name")

            for bet in bm.get("bets") or []:
                bet_id = bet.get("id")
                bet_name = bet.get("name")
                if not is_relevant_player_prop(bet_id, bet_name):
                    continue

                for val in bet.get("values") or []:
                    odd_raw = val.get("odd")
                    try:
                        odd = float(str(odd_raw).replace(",", "."))
                    except Exception:
                        odd = np.nan

                    implied = round(100 / odd, 1) if pd.notna(odd) and odd > 0 else np.nan
                    player_name, threshold, play_label = split_player_and_line(val.get("value"), bet_name)
                    rows.append({
                        "Campionato": league_label or league.get("name", ""),
                        "Fixture ID": fixture_id,
                        "Data quota": fixture_date,
                        "Bookmaker ID": bookmaker_id,
                        "Bookmaker": bookmaker_name,
                        "Bet ID": bet_id,
                        "Mercato API": bet_name,
                        "Valore API": val.get("value"),
                        "Tipo mercato": human_market(bet_name),
                        "Giocatore": player_name,
                        "Soglia": threshold,
                        "Giocata": play_label,
                        "Quota": odd,
                        "Prob. implicita %": implied,
                        "Ultimo update": update,
                    })

    return rows

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


@st.cache_data(ttl=1800, show_spinner=False)
def get_league_standings(league_id, season):
    """Classifica corrente, usata solo come contesto aggiuntivo del modello."""
    data = api_get("standings", {
        "league": int(league_id),
        "season": int(season),
    })
    rows = []
    response = data.get("response") or []
    if not response:
        return rows, data.get("errors", [])

    groups = response[0].get("league", {}).get("standings") or []
    for group in groups:
        for r in group:
            team = r.get("team") or {}
            all_stats = r.get("all") or {}
            rows.append({
                "team_id": team.get("id"),
                "team": team.get("name", ""),
                "rank": r.get("rank"),
                "points": r.get("points"),
                "goalsDiff": r.get("goalsDiff"),
                "played": all_stats.get("played"),
                "win": all_stats.get("win"),
                "draw": all_stats.get("draw"),
                "lose": all_stats.get("lose"),
                "form": r.get("form"),
                "description": r.get("description"),
            })
    return rows, data.get("errors", [])


def standings_lookup(rows):
    return {r.get("team_id"): r for r in rows if r.get("team_id") is not None}


def automatic_match_context(fixture, standings_rows):
    """
    Contesto prudente: classifica, giornata e differenza punti.
    Non trasforma mai 'deve vincere' in una certezza.
    """
    league = fixture.get("league") or {}
    round_name = str(league.get("round") or "")
    home = fixture.get("teams", {}).get("home", {}) or {}
    away = fixture.get("teams", {}).get("away", {}) or {}
    lookup = standings_lookup(standings_rows)

    h = lookup.get(home.get("id"), {})
    a = lookup.get(away.get("id"), {})

    notes = []
    if round_name:
        notes.append(round_name)

    hr, ar = h.get("rank"), a.get("rank")
    hp, ap = h.get("points"), a.get("points")
    played = max(h.get("played") or 0, a.get("played") or 0)

    if hr and ar:
        notes.append(f"classifica {home.get('name','')} #{hr} – {away.get('name','')} #{ar}")
    if hp is not None and ap is not None:
        diff = hp - ap
        if abs(diff) >= 8:
            leader = home.get("name","") if diff > 0 else away.get("name","")
            notes.append(f"vantaggio punti netto per {leader}")

    # euristica molto prudente: segnala solo fasi avanzate, non presume l'obbligo.
    if played >= 30:
        notes.append("fase avanzata del campionato: motivazioni di classifica più rilevanti")

    return " · ".join(notes) if notes else "Contesto standard", h, a


CONTEXT_LEVELS = [
    "Neutro",
    "Molto motivata",
    "Deve vincere / risultato necessario",
    "Turnover probabile",
    "Obiettivo già quasi acquisito",
]


def context_factor(label):
    """
    Correttivo volutamente piccolo: il contesto non deve dominare i dati.
    """
    return {
        "Neutro": 1.000,
        "Molto motivata": 1.020,
        "Deve vincere / risultato necessario": 1.035,
        "Turnover probabile": 0.955,
        "Obiettivo già quasi acquisito": 0.975,
    }.get(str(label), 1.0)


def apply_manual_match_context(pred_df, context_df):
    if pred_df.empty or context_df.empty:
        return pred_df.copy()

    out = pred_df.copy()
    ctx = context_df.set_index("Fixture ID")

    for idx, row in out.iterrows():
        fid = row.get("Fixture ID")
        if fid not in ctx.index:
            continue

        crow = ctx.loc[fid]
        hf = context_factor(crow.get("Contesto casa", "Neutro"))
        af = context_factor(crow.get("Contesto trasferta", "Neutro"))

        lh = float(row["xG casa modello"]) * hf
        la = float(row["xG trasferta modello"]) * af

        probs = poisson_extra_markets(lh, la)
        for m in ["1", "X", "2", "1X", "X2", "GOL", "NO GOL"]:
            p = probs[m]
            out.at[idx, f"Prob. {m} %"] = round(p * 100, 1)
            out.at[idx, f"Quota equa {m}"] = round(1 / p, 2) if p > 0 else np.nan

        out.at[idx, "xG casa modello"] = round(lh, 2)
        out.at[idx, "xG trasferta modello"] = round(la, 2)
        out.at[idx, "Contesto casa"] = crow.get("Contesto casa", "Neutro")
        out.at[idx, "Contesto trasferta"] = crow.get("Contesto trasferta", "Neutro")
        out.at[idx, "Nota contesto"] = crow.get("Nota contesto", "")

    return out


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
                "Fixture ID": f.get("fixture", {}).get("id"),
                "Partita": f"{home} - {away}",
            }

        if away_id is not None and away_id not in mapping:
            mapping[int(away_id)] = {
                "Avversario": home,
                "Avversario ID": home_id,
                "Casa/Fuori": "Trasferta",
                "Data prossima": dt.strftime("%d/%m/%Y %H:%M"),
                "Fixture ID": f.get("fixture", {}).get("id"),
                "Partita": f"{home} - {away}",
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
            row["Fixture ID"] = upcoming.get("Fixture ID")
            row["Partita"] = upcoming.get("Partita", "")

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        ["Prob. stimata", "Presenze usate"],
        ascending=[False, False]
    ).reset_index(drop=True)



def normalize_name(name):
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\\s+", " ", s).strip()

def player_match_score(model_name, odds_name):
    a = normalize_name(model_name)
    b = normalize_name(odds_name)
    if not a or not b:
        return 0
    if a == b:
        return 100
    at, bt = a.split(), b.split()
    if at[-1] == bt[-1]:
        if at[0] == bt[0]:
            return 98
        if at[0][0] == bt[0][0]:
            return 96
        return 88
    if a in b or b in a:
        return 92
    overlap = len(set(at) & set(bt))
    return 60 + 10 * overlap if overlap else 0

def model_market_to_odds(market_name):
    return {
        "1+ tiro": ("Tiri", 1.0),
        "2+ tiri": ("Tiri", 2.0),
        "3+ tiri": ("Tiri", 3.0),
        "1+ tiro in porta": ("Tiri in porta", 1.0),
        "2+ tiri in porta": ("Tiri in porta", 2.0),
        "Ammonito": ("Cartellino giallo", None),
        "1+ fallo commesso": ("Falli commessi", 1.0),
        "2+ falli commessi": ("Falli commessi", 2.0),
        "3+ falli commessi": ("Falli commessi", 3.0),
        "3+ parate": ("Parate", 3.0),
        "4+ parate": ("Parate", 4.0),
        "5+ parate": ("Parate", 5.0),
    }.get(str(market_name), (None, None))

def add_real_odds_to_signals(signals_df):
    if signals_df.empty or "Fixture ID" not in signals_df.columns:
        return signals_df.copy(), []
    work = signals_df.copy()
    work["Bookmaker"] = "—"
    work["Quota reale"] = np.nan
    work["Prob. bookmaker %"] = np.nan
    work["Edge p.p."] = np.nan
    work["Value %"] = np.nan
    work["VALUE"] = "—"

    fixture_ids = pd.to_numeric(work["Fixture ID"], errors="coerce").dropna().astype(int).unique().tolist()
    odds_rows, errors = [], []
    for fid in fixture_ids:
        try:
            data = get_fixture_odds(fid)
            odds_rows.extend(parse_fixture_odds(data))
        except Exception as exc:
            errors.append({"Fixture ID": fid, "Errore": f"{type(exc).__name__}: {exc}"})

    if not odds_rows:
        return work, errors

    odds_df = pd.DataFrame(odds_rows)
    odds_df["Fixture ID"] = pd.to_numeric(odds_df["Fixture ID"], errors="coerce")
    odds_df["Soglia"] = pd.to_numeric(odds_df["Soglia"], errors="coerce")
    odds_df["Quota"] = pd.to_numeric(odds_df["Quota"], errors="coerce")

    for idx, row in work.iterrows():
        fid = pd.to_numeric(pd.Series([row.get("Fixture ID")]), errors="coerce").iloc[0]
        market_type, threshold = model_market_to_odds(row.get("Mercato"))
        if pd.isna(fid) or market_type is None:
            continue

        cand = odds_df[
            (odds_df["Fixture ID"] == fid) &
            (odds_df["Tipo mercato"] == market_type)
        ].copy()

        if market_type != "Cartellino giallo":
            cand = cand[np.isclose(cand["Soglia"], threshold, equal_nan=False)]

        if cand.empty:
            continue

        cand["Name score"] = cand["Giocatore"].map(lambda x: player_match_score(row.get("Giocatore"), x))
        cand = cand[cand["Name score"] >= 88]
        if cand.empty:
            continue

        qrow = cand.sort_values(["Quota", "Name score"], ascending=[False, False]).iloc[0]
        q = float(qrow["Quota"])
        if not np.isfinite(q) or q <= 0:
            continue

        p_book = 100.0 / q
        p_model = float(row["Prob. stimata"])
        edge_pp = p_model - p_book
        value_pct = ((p_model / 100.0) * q - 1.0) * 100.0

        work.at[idx, "Bookmaker"] = str(qrow.get("Bookmaker", "—"))
        work.at[idx, "Quota reale"] = round(q, 2)
        work.at[idx, "Prob. bookmaker %"] = round(p_book, 1)
        work.at[idx, "Edge p.p."] = round(edge_pp, 1)
        work.at[idx, "Value %"] = round(value_pct, 1)

        if value_pct >= 10:
            work.at[idx, "VALUE"] = "🟢 Forte"
        elif value_pct >= 3:
            work.at[idx, "VALUE"] = "🟡 Sì"
        elif value_pct > 0:
            work.at[idx, "VALUE"] = "⚪ Minimo"
        else:
            work.at[idx, "VALUE"] = "🔴 No"
    return work, errors



def _weighted_mean(values, decay=0.88):
    vals = [float(v) for v in values if pd.notna(v)]
    if not vals:
        return np.nan
    n = len(vals)
    w = np.array([decay ** (n - 1 - i) for i in range(n)], dtype=float)
    return float(np.average(np.array(vals, dtype=float), weights=w))


def league_goal_baselines(fixtures):
    hg, ag = [], []
    for f in fixtures:
        goals = f.get("goals", {}) or {}
        h = goals.get("home")
        a = goals.get("away")
        if h is None or a is None:
            continue
        hg.append(float(h))
        ag.append(float(a))
    return (
        float(np.mean(hg)) if hg else 1.45,
        float(np.mean(ag)) if ag else 1.15,
    )


def team_form_metrics(fixtures, team_id, venue=None, n=10):
    rows = []
    for f in fixtures:
        home_id = f.get("teams", {}).get("home", {}).get("id")
        away_id = f.get("teams", {}).get("away", {}).get("id")
        if team_id not in (home_id, away_id):
            continue

        is_home = team_id == home_id
        this_venue = "Casa" if is_home else "Trasferta"
        if venue and this_venue != venue:
            continue

        goals = f.get("goals", {}) or {}
        gh, ga = goals.get("home"), goals.get("away")
        if gh is None or ga is None:
            continue

        gf = float(gh if is_home else ga)
        gc = float(ga if is_home else gh)
        pts = 3.0 if gf > gc else (1.0 if gf == gc else 0.0)
        dt = pd.to_datetime(f.get("fixture", {}).get("date"), errors="coerce")
        rows.append((dt, gf, gc, pts))

    if not rows:
        return {"gf": np.nan, "ga": np.nan, "ppg": np.nan, "n": 0}

    rows = sorted(rows, key=lambda x: x[0])[-n:]
    return {
        "gf": _weighted_mean([r[1] for r in rows]),
        "ga": _weighted_mean([r[2] for r in rows]),
        "ppg": _weighted_mean([r[3] for r in rows]),
        "n": len(rows),
    }


def player_team_factor(df_league, team_id):
    """
    Fattore giocatori 0.88-1.12.
    Usa statistiche realmente prodotte dai giocatori: tiri in porta/tiri per partita
    e continuità del nucleo con più minuti nelle gare recenti.
    """
    t = df_league[df_league["team_id"] == team_id].copy()
    if t.empty:
        return 1.0, 50.0, 50.0

    t["date"] = pd.to_datetime(t["date"], errors="coerce")
    team_match = (
        t.groupby("date", as_index=False)
        .agg(
            shots=("shots_total", "sum"),
            sot=("shots_on_target", "sum"),
            total_minutes=("minutes", "sum"),
        )
        .sort_values("date")
    )

    league_match = (
        df_league.groupby(["team_id", "date"], as_index=False)
        .agg(sot=("shots_on_target", "sum"))
    )
    league_sot = float(league_match["sot"].mean()) if not league_match.empty else 4.0
    recent = team_match.tail(5)
    recent_sot = float(recent["sot"].mean()) if not recent.empty else league_sot
    shooting_ratio = np.clip(recent_sot / max(league_sot, 0.5), 0.70, 1.35)

    # Continuità: quanti dei 8 giocatori con più minuti recenti compaiono nell'ultima gara.
    last_dates = sorted(t["date"].dropna().unique())[-5:]
    recent_players = t[t["date"].isin(last_dates)]
    core = (
        recent_players.groupby("player_id")["minutes"].sum()
        .sort_values(ascending=False)
        .head(8)
        .index
    )
    latest_date = t["date"].max()
    latest_ids = set(t[(t["date"] == latest_date) & (t["minutes"] > 0)]["player_id"].dropna())
    continuity = len(set(core) & latest_ids) / max(len(core), 1)

    factor = 1.0 + 0.10 * (shooting_ratio - 1.0) + 0.05 * (continuity - 0.75)
    factor = float(np.clip(factor, 0.88, 1.12))
    return factor, round(shooting_ratio * 100, 1), round(continuity * 100, 1)


def poisson_1x2(lambda_home, lambda_away, max_goals=8):
    ph = [math.exp(-lambda_home) * lambda_home**k / math.factorial(k) for k in range(max_goals + 1)]
    pa = [math.exp(-lambda_away) * lambda_away**k / math.factorial(k) for k in range(max_goals + 1)]
    p1 = px = p2 = 0.0
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            p = pi * pj
            if i > j:
                p1 += p
            elif i == j:
                px += p
            else:
                p2 += p
    total = p1 + px + p2
    if total <= 0:
        return 1/3, 1/3, 1/3
    return p1/total, px/total, p2/total


def predict_match_1x2(fixtures, df_league, future_fixture):
    home = future_fixture.get("teams", {}).get("home", {}) or {}
    away = future_fixture.get("teams", {}).get("away", {}) or {}
    hid, aid = home.get("id"), away.get("id")
    if hid is None or aid is None:
        return None

    base_h, base_a = league_goal_baselines(fixtures)

    h_all = team_form_metrics(fixtures, hid, None, 10)
    a_all = team_form_metrics(fixtures, aid, None, 10)
    h_home = team_form_metrics(fixtures, hid, "Casa", 6)
    a_away = team_form_metrics(fixtures, aid, "Trasferta", 6)

    def blend(primary, fallback, key, default):
        p = primary.get(key)
        f = fallback.get(key)
        if pd.notna(p) and primary.get("n", 0) >= 3:
            return 0.65 * p + 0.35 * (f if pd.notna(f) else default)
        return f if pd.notna(f) else default

    h_gf = blend(h_home, h_all, "gf", base_h)
    h_ga = blend(h_home, h_all, "ga", base_a)
    a_gf = blend(a_away, a_all, "gf", base_a)
    a_ga = blend(a_away, a_all, "ga", base_h)

    h_attack = np.clip(h_gf / max(base_h, 0.35), 0.55, 1.75)
    h_defweak = np.clip(h_ga / max(base_a, 0.35), 0.55, 1.75)
    a_attack = np.clip(a_gf / max(base_a, 0.35), 0.55, 1.75)
    a_defweak = np.clip(a_ga / max(base_h, 0.35), 0.55, 1.75)

    h_player, h_shoot, h_cont = player_team_factor(df_league, hid)
    a_player, a_shoot, a_cont = player_team_factor(df_league, aid)

    # Forma punti come correttivo leggero.
    h_ppg = h_all["ppg"] if pd.notna(h_all["ppg"]) else 1.4
    a_ppg = a_all["ppg"] if pd.notna(a_all["ppg"]) else 1.4
    h_form = float(np.clip((h_ppg / 1.4) ** 0.10, 0.90, 1.10))
    a_form = float(np.clip((a_ppg / 1.4) ** 0.10, 0.90, 1.10))

    lam_h = base_h * math.sqrt(h_attack * a_defweak) * h_player * h_form
    lam_a = base_a * math.sqrt(a_attack * h_defweak) * a_player * a_form
    lam_h = float(np.clip(lam_h, 0.25, 3.50))
    lam_a = float(np.clip(lam_a, 0.20, 3.25))

    p1, px, p2 = poisson_1x2(lam_h, lam_a)
    dt = pd.to_datetime(future_fixture.get("fixture", {}).get("date"))
    if dt.tzinfo is not None:
        dt = dt.tz_convert("Europe/Rome")

    return {
        "Fixture ID": future_fixture.get("fixture", {}).get("id"),
        "Partita": f"{home.get('name','')} - {away.get('name','')}",
        "Data": dt.strftime("%d/%m/%Y %H:%M"),
        "Casa": home.get("name", ""),
        "Trasferta": away.get("name", ""),
        "Prob. 1 %": round(p1 * 100, 1),
        "Prob. X %": round(px * 100, 1),
        "Prob. 2 %": round(p2 * 100, 1),
        "Quota equa 1": round(1/p1, 2) if p1 > 0 else np.nan,
        "Quota equa X": round(1/px, 2) if px > 0 else np.nan,
        "Quota equa 2": round(1/p2, 2) if p2 > 0 else np.nan,
        "xG casa modello": round(lam_h, 2),
        "xG trasferta modello": round(lam_a, 2),
        "Forma casa PPG": round(h_ppg, 2),
        "Forma trasferta PPG": round(a_ppg, 2),
        "Fattore giocatori casa": round(h_player, 3),
        "Fattore giocatori trasferta": round(a_player, 3),
        "Tiri-porta giocatori casa idx": h_shoot,
        "Tiri-porta giocatori trasferta idx": a_shoot,
        "Continuità nucleo casa %": h_cont,
        "Continuità nucleo trasferta %": a_cont,
    }


def extract_1x2_odds(odds_json):
    rows = []
    for item in odds_json.get("response") or []:
        for book in item.get("bookmakers") or []:
            bname = book.get("name", "")
            for bet in book.get("bets") or []:
                bet_name = str(bet.get("name", "")).strip().lower()
                bet_id = bet.get("id")
                if not (
                    bet_id == 1
                    or "match winner" in bet_name
                    or bet_name in {"1x2", "winner"}
                ):
                    continue
                for v in bet.get("values") or []:
                    raw = str(v.get("value", "")).strip().lower()
                    odd = v.get("odd")
                    try:
                        odd = float(odd)
                    except Exception:
                        continue
                    outcome = None
                    if raw in {"home", "1"}:
                        outcome = "1"
                    elif raw in {"draw", "x"}:
                        outcome = "X"
                    elif raw in {"away", "2"}:
                        outcome = "2"
                    if outcome:
                        rows.append({"Bookmaker": bname, "Esito": outcome, "Quota": odd})
    return pd.DataFrame(rows)


def attach_1x2_real_odds(pred_df):
    if pred_df.empty:
        return pred_df.copy(), []
    out = pred_df.copy()
    for c in ["Quota reale 1", "Quota reale X", "Quota reale 2"]:
        out[c] = np.nan
    for c in ["Bookmaker 1", "Bookmaker X", "Bookmaker 2"]:
        out[c] = "—"

    errors = []
    for idx, row in out.iterrows():
        fid = row.get("Fixture ID")
        try:
            od = extract_1x2_odds(get_fixture_odds(fid))
        except Exception as exc:
            errors.append({"Partita": row.get("Partita"), "Errore": str(exc)})
            continue
        if od.empty:
            continue
        for outcome in ["1", "X", "2"]:
            x = od[od["Esito"] == outcome].sort_values("Quota", ascending=False)
            if not x.empty:
                best = x.iloc[0]
                out.at[idx, f"Quota reale {outcome}"] = round(float(best["Quota"]), 2)
                out.at[idx, f"Bookmaker {outcome}"] = str(best["Bookmaker"])
    return out, errors



def poisson_extra_markets(lambda_home, lambda_away, max_goals=8):
    ph = [math.exp(-lambda_home) * lambda_home**k / math.factorial(k) for k in range(max_goals + 1)]
    pa = [math.exp(-lambda_away) * lambda_away**k / math.factorial(k) for k in range(max_goals + 1)]

    p1 = px = p2 = pgg = 0.0
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            p = pi * pj
            if i > j:
                p1 += p
            elif i == j:
                px += p
            else:
                p2 += p
            if i >= 1 and j >= 1:
                pgg += p

    total = p1 + px + p2
    if total <= 0:
        p1 = px = p2 = 1/3
    else:
        p1, px, p2 = p1/total, px/total, p2/total

    p1x = min(1.0, p1 + px)
    px2 = min(1.0, px + p2)
    p12 = min(1.0, p1 + p2)
    png = max(0.0, 1.0 - pgg)

    return {
        "1": p1, "X": px, "2": p2,
        "1X": p1x, "X2": px2, "12": p12,
        "GOL": pgg, "NO GOL": png,
    }


def enrich_extra_markets(pred_df):
    if pred_df.empty:
        return pred_df.copy()

    out = pred_df.copy()
    market_names = ["1", "X", "2", "1X", "X2", "GOL", "NO GOL"]

    for idx, row in out.iterrows():
        lh = float(row["xG casa modello"])
        la = float(row["xG trasferta modello"])
        probs = poisson_extra_markets(lh, la)

        for m in market_names:
            p = probs[m]
            out.at[idx, f"Prob. {m} %"] = round(p * 100, 1)
            out.at[idx, f"Quota equa {m}"] = round(1 / p, 2) if p > 0 else np.nan

    return out


def build_manual_odds_table(pred_df):
    rows = []
    markets = ["1", "X", "2", "1X", "X2", "GOL", "NO GOL"]

    for _, r in pred_df.iterrows():
        for market in markets:
            prob_col = f"Prob. {market} %"
            fair_col = f"Quota equa {market}"
            if prob_col not in r or fair_col not in r:
                continue

            # Pre-fill 1/X/2 with API real odds when available. Others start blank
            # because user said current feed can be wrong/incomplete.
            q = np.nan
            bookmaker = ""
            if market in {"1", "X", "2"}:
                q_api = r.get(f"Quota reale {market}")
                if pd.notna(q_api):
                    q = float(q_api)
                    bookmaker = str(r.get(f"Bookmaker {market}", ""))

            rows.append({
                "Campionato": r.get("Campionato", ""),
                "Data": r.get("Data", ""),
                "Partita": r.get("Partita", ""),
                "Mercato": market,
                "Prob. modello %": float(r.get(prob_col, np.nan)),
                "Quota equa": float(r.get(fair_col, np.nan)),
                "Quota bookmaker": q,
                "Bookmaker / sito": bookmaker,
            })

    return pd.DataFrame(rows)


def evaluate_manual_odds(odds_df):
    if odds_df.empty:
        return odds_df.copy()

    out = odds_df.copy()
    out["Quota bookmaker"] = pd.to_numeric(out["Quota bookmaker"], errors="coerce")
    out["Prob. modello %"] = pd.to_numeric(out["Prob. modello %"], errors="coerce")

    out["Prob. implicita %"] = np.where(
        out["Quota bookmaker"] > 0,
        100.0 / out["Quota bookmaker"],
        np.nan,
    )
    out["Edge p.p."] = out["Prob. modello %"] - out["Prob. implicita %"]
    out["Value %"] = (
        (out["Prob. modello %"] / 100.0) * out["Quota bookmaker"] - 1.0
    ) * 100.0

    def flag(v):
        if pd.isna(v):
            return "—"
        if v >= 10:
            return "🟢 Forte"
        if v >= 3:
            return "🟡 Interessante"
        if v > 0:
            return "⚪ Minimo"
        return "🔴 No"

    out["Conviene?"] = out["Value %"].map(flag)

    for c in ["Prob. implicita %", "Edge p.p.", "Value %"]:
        out[c] = out[c].round(1)

    return out


def make_coupon_from_manual_odds(evaluated_df, mode="Alta probabilità", legs=5, min_probability=70):
    if evaluated_df.empty:
        return pd.DataFrame(), {}

    # Primary objective: maximize reliability. Quote/value are secondary.
    mode_bonus = {
        "Alta probabilità": {"min_value": -20.0, "min_odd": 1.01, "prob_weight": 4.0, "value_weight": 0.10},
        "Prudente": {"min_value": -8.0, "min_odd": 1.05, "prob_weight": 3.2, "value_weight": 0.16},
        "Equilibrata": {"min_value": -2.0, "min_odd": 1.10, "prob_weight": 2.4, "value_weight": 0.30},
        "Alta quota": {"min_value": 2.0, "min_odd": 1.35, "prob_weight": 1.5, "value_weight": 0.55},
    }[mode]

    c = evaluated_df.copy()
    c["Quota bookmaker"] = pd.to_numeric(c["Quota bookmaker"], errors="coerce")
    c["Prob. modello %"] = pd.to_numeric(c["Prob. modello %"], errors="coerce")
    c["Value %"] = pd.to_numeric(c["Value %"], errors="coerce")

    c = c[
        c["Quota bookmaker"].notna()
        & (c["Quota bookmaker"] >= mode_bonus["min_odd"])
        & (c["Prob. modello %"] >= float(min_probability))
        & (c["Value %"].fillna(-999) >= mode_bonus["min_value"])
    ].copy()

    if c.empty:
        return pd.DataFrame(), {}

    p = c["Prob. modello %"] / 100.0
    value_component = c["Value %"].fillna(0) / 100.0

    # Reliability dominates. A 1.25 @ 85% can rank above a 1.60 @ 68%.
    c["_score"] = (
        mode_bonus["prob_weight"] * p
        + mode_bonus["value_weight"] * value_component
        + 0.05 * np.log(c["Quota bookmaker"].clip(lower=1.01))
    )

    # Only one selection per fixture.
    c = c.sort_values(
        ["_score", "Prob. modello %", "Value %"],
        ascending=[False, False, False]
    ).drop_duplicates("Partita")

    # Do not force a fixed number: stop adding events when reliability drops too much.
    selected = []
    running_joint = 1.0
    best_prob = float(c["Prob. modello %"].max()) if not c.empty else 0.0
    for _, row in c.iterrows():
        if len(selected) >= int(legs):
            break
        row_p = float(row["Prob. modello %"]) / 100.0

        # In Alta probabilità mode, avoid padding the coupon with clearly weaker picks.
        if mode == "Alta probabilità" and selected:
            if float(row["Prob. modello %"]) < max(float(min_probability), best_prob - 10.0):
                continue

        selected.append(row)
        running_joint *= row_p

    if not selected:
        return pd.DataFrame(), {}

    c = pd.DataFrame(selected).copy()
    total_odd = float(np.prod(c["Quota bookmaker"]))
    joint_p = float(np.prod(c["Prob. modello %"] / 100.0))

    view = c[
        [
            "Campionato", "Data", "Partita", "Mercato",
            "Prob. modello %", "Quota equa", "Quota bookmaker",
            "Bookmaker / sito", "Prob. implicita %", "Edge p.p.",
            "Value %", "Conviene?"
        ]
    ].copy()

    summary = {
        "N. eventi": len(view),
        "Quota totale": round(total_odd, 2),
        "Prob. combinata approx %": round(joint_p * 100, 2),
        "Prob. media eventi %": round(float(view["Prob. modello %"].mean()), 1),
    }
    return view, summary



def make_coupon(pred_df, mode="Equilibrata", legs=5):
    if pred_df.empty:
        return pd.DataFrame(), {}

    params = {
        "Alta probabilità": {"min_p": 0.70, "max_p": 0.98, "min_odd": 1.01},
        "Prudente": {"min_p": 0.62, "max_p": 0.90, "min_odd": 1.20},
        "Equilibrata": {"min_p": 0.54, "max_p": 0.84, "min_odd": 1.35},
        "Alta quota": {"min_p": 0.43, "max_p": 0.76, "min_odd": 1.55},
    }.get(mode, {"min_p": 0.70, "max_p": 0.98, "min_odd": 1.01})

    candidates = []
    for _, r in pred_df.iterrows():
        for outcome in ["1", "X", "2"]:
            p = float(r[f"Prob. {outcome} %"]) / 100.0
            real_odd = r.get(f"Quota reale {outcome}")
            fair = r.get(f"Quota equa {outcome}")
            odd = float(real_odd) if pd.notna(real_odd) else float(fair)
            is_real = pd.notna(real_odd)
            if p < params["min_p"] or p > params["max_p"] or odd < params["min_odd"]:
                continue
            ev = p * odd - 1.0 if is_real else 0.0
            # Favorisce probabilità + quota, e se disponibile value reale.
            score = (p ** 1.35) * math.log(max(odd, 1.01)) + max(ev, -0.20) * 0.65
            candidates.append({
                "Partita": r["Partita"],
                "Data": r["Data"],
                "Esito": outcome,
                "Prob. modello %": round(p*100, 1),
                "Quota": round(odd, 2),
                "Quota reale?": "Sì" if is_real else "No (equa)",
                "Bookmaker": r.get(f"Bookmaker {outcome}", "—") if is_real else "—",
                "Value %": round(ev*100, 1) if is_real else np.nan,
                "_score": score,
            })

    if not candidates:
        return pd.DataFrame(), {}

    cdf = pd.DataFrame(candidates).sort_values("_score", ascending=False)
    # una sola selezione per partita
    cdf = cdf.drop_duplicates("Partita").head(int(legs)).copy()
    cdf = cdf.drop(columns="_score")

    total_odd = float(np.prod(cdf["Quota"])) if not cdf.empty else np.nan
    joint_p = float(np.prod(cdf["Prob. modello %"] / 100.0)) if not cdf.empty else np.nan
    summary = {
        "Quota totale": round(total_odd, 2) if pd.notna(total_odd) else np.nan,
        "Prob. combinata approx %": round(joint_p * 100, 2) if pd.notna(joint_p) else np.nan,
        "N. eventi": len(cdf),
    }
    return cdf, summary


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
    st.divider()
    st.subheader("Quote API")
    show_odds_catalog = st.toggle(
        "Mostra mercati e bookmaker API",
        value=False,
        help="Apre il catalogo ufficiale Odds senza modificare le probabilità del modello.",
    )
    test_real_player_odds = st.toggle(
        "Testa quote REALI player props",
        value=False,
        help=(
            "Interroga le prossime partite e mostra le quote pre-match realmente presenti "
            "per tiri giocatore, tiri in porta e cartellino."
        ),
    )
    odds_fixture_limit = st.slider(
        "Partite da testare per campionato",
        1, 10, 3, 1,
        disabled=not test_real_player_odds,
        help="Ogni partita testata usa circa una chiamata all'endpoint /odds.",
    )
    st.divider()
    st.subheader("Pronostici partite")
    enable_match_model = st.toggle(
        "🏆 Calcola 1X2 e schedina",
        value=True,
        help="Stima 1/X/2 usando forma squadra, casa/trasferta e fattore giocatori.",
    )
    match_model_limit = st.slider(
        "Partite per campionato",
        1, 8, 4, 1,
        disabled=not enable_match_model,
    )
    coupon_mode = st.selectbox(
        "Tipo schedina",
        ["Alta probabilità", "Prudente", "Equilibrata", "Alta quota"],
        index=0,
        disabled=not enable_match_model,
    )
    min_coupon_probability = st.slider(
        "Probabilità minima singolo evento",
        50, 90, 70, 1,
        disabled=not enable_match_model,
        help="La schedina preferirà eventi sopra questa probabilità, anche se la quota è bassa.",
    )
    coupon_legs = st.slider(
        "Numero massimo di eventi",
        2, 8, 5, 1,
        disabled=not enable_match_model,
    )

markets_to_scan = list(MARKETS.keys()) if market_choice == "Tutti i mercati" else [market_choice]

if show_odds_catalog:
    st.subheader("🔎 Mercati quote disponibili su API-Football")
    st.caption(
        "Questa sezione legge direttamente il catalogo Odds dell'API. "
        "Ci serve per verificare se esistono player props come tiri, tiri in porta e cartellini giocatore."
    )

    try:
        bets_data = get_odds_bets()
        bet_errors = bets_data.get("errors") or []
        bets = bets_data.get("response") or []

        if bet_errors:
            st.warning(f"API /odds/bets ha restituito: {bet_errors}")

        if bets:
            bets_df = pd.DataFrame(bets)
            # Normalizza i nomi più comuni della risposta API.
            rename_map = {}
            for c in bets_df.columns:
                lc = str(c).lower()
                if lc == "id":
                    rename_map[c] = "ID"
                elif lc == "name":
                    rename_map[c] = "Mercato API"
            bets_df = bets_df.rename(columns=rename_map)

            if "Mercato API" in bets_df.columns:
                names = bets_df["Mercato API"].astype(str)
                player_prop_mask = names.str.contains(
                    r"player|shot|shots|card|cards|booking|booked",
                    case=False,
                    regex=True,
                    na=False,
                )
                props_df = bets_df[player_prop_mask].copy()

                st.markdown("**Mercati potenzialmente utili al nostro modello**")
                if not props_df.empty:
                    st.dataframe(props_df, use_container_width=True, hide_index=True)
                else:
                    st.warning(
                        "Nel catalogo /odds/bets non risultano mercati con nomi contenenti "
                        "Player, Shot, Card o Booking. Questo indica che i player props che ci servono "
                        "potrebbero non essere disponibili nell'endpoint Odds standard."
                    )

                with st.expander("📋 Vedi tutti i mercati Odds API"):
                    st.dataframe(bets_df, use_container_width=True, hide_index=True, height=500)
            else:
                st.dataframe(bets_df, use_container_width=True, hide_index=True)
        else:
            st.info("L'API non ha restituito mercati da /odds/bets.")

        bookmakers_data = get_odds_bookmakers()
        bookmaker_errors = bookmakers_data.get("errors") or []
        bookmakers = bookmakers_data.get("response") or []

        if bookmaker_errors:
            st.warning(f"API /odds/bookmakers ha restituito: {bookmaker_errors}")

        with st.expander("🏦 Bookmaker disponibili nell'API"):
            if bookmakers:
                book_df = pd.DataFrame(bookmakers)
                book_df = book_df.rename(columns={"id": "ID", "name": "Bookmaker"})
                st.dataframe(book_df, use_container_width=True, hide_index=True, height=400)
            else:
                st.info("Nessun bookmaker restituito dall'endpoint /odds/bookmakers.")

    except Exception as odds_error:
        st.error(
            "Non riesco a leggere il catalogo Odds. "
            f"Errore: {type(odds_error).__name__}: {odds_error}"
        )

    st.divider()

all_rankings = []
all_player_data = []
future_rows = []
league_status = []
real_odds_rows = []
real_odds_errors = []
match_prediction_rows = []
match_prediction_errors = []
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

        # Test quote pre-match reali: una chiamata /odds per fixture, solo se richiesto.
        if test_real_player_odds and future:
            for odds_fx in future[:odds_fixture_limit]:
                fid = odds_fx.get("fixture", {}).get("id")
                home_name = odds_fx.get("teams", {}).get("home", {}).get("name", "")
                away_name = odds_fx.get("teams", {}).get("away", {}).get("name", "")
                fixture_label = f"{home_name} - {away_name}"
                try:
                    odds_json = get_fixture_odds(fid)
                    if odds_json.get("errors"):
                        real_odds_errors.append({
                            "Campionato": league_label,
                            "Partita": fixture_label,
                            "Fixture ID": fid,
                            "Errore": str(odds_json.get("errors")),
                        })
                    parsed = parse_fixture_odds(odds_json, league_label=league_label)
                    for rr in parsed:
                        rr["Partita"] = fixture_label
                    real_odds_rows.extend(parsed)
                except Exception as odds_e:
                    real_odds_errors.append({
                        "Campionato": league_label,
                        "Partita": fixture_label,
                        "Fixture ID": fid,
                        "Errore": f"{type(odds_e).__name__}: {odds_e}",
                    })

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

        if enable_match_model and future:
            try:
                standings_rows, standings_errors = get_league_standings(league_id, CURRENT_SEASON)
            except Exception:
                standings_rows, standings_errors = [], []

            for ff in future[:match_model_limit]:
                try:
                    pred = predict_match_1x2(fixtures, df_league, ff)
                    if pred:
                        auto_ctx, hs, aws = automatic_match_context(ff, standings_rows)
                        pred["Campionato"] = league_label
                        pred["Contesto automatico"] = auto_ctx
                        pred["Pos. casa"] = hs.get("rank")
                        pred["Punti casa"] = hs.get("points")
                        pred["Pos. trasferta"] = aws.get("rank")
                        pred["Punti trasferta"] = aws.get("points")
                        match_prediction_rows.append(pred)
                except Exception as pred_e:
                    match_prediction_errors.append({
                        "Campionato": league_label,
                        "Partita": f"{ff.get('teams',{}).get('home',{}).get('name','')} - {ff.get('teams',{}).get('away',{}).get('name','')}",
                        "Errore": f"{type(pred_e).__name__}: {pred_e}",
                    })

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

top_odds_errors = []
if not filtered.empty:
    filtered, top_odds_errors = add_real_odds_to_signals(filtered)

if test_real_player_odds:
    st.subheader("💶 Test quote REALI player props")
    st.caption(
        "Quote pre-match restituite realmente da API-Football per le prossime gare testate. "
        "Qui NON stiamo ancora confrontando la quota col modello: prima verifichiamo copertura, "
        "bookmaker, nomi giocatore e linee disponibili."
    )

    if real_odds_rows:
        odds_df = pd.DataFrame(real_odds_rows)
        # Formatta data in ora italiana quando disponibile.
        if "Data quota" in odds_df.columns:
            def _fmt_odds_date(x):
                try:
                    dt = pd.to_datetime(x)
                    if dt.tzinfo is not None:
                        dt = dt.tz_convert("Europe/Rome")
                    return dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    return str(x or "")
            odds_df["Data partita"] = odds_df["Data quota"].map(_fmt_odds_date)

        # Tabella leggibile: niente ID tecnici o campi API grezzi nella vista principale.
        odds_df = odds_df.sort_values(
            ["Campionato", "Partita", "Tipo mercato", "Giocatore", "Soglia", "Quota"],
            ascending=[True, True, True, True, True, False],
            na_position="last",
        )

        st.success(
            f"Trovate {len(odds_df)} righe quota player props su "
            f"{odds_df['Fixture ID'].nunique()} partite e "
            f"{odds_df['Bookmaker'].nunique()} bookmaker."
        )
        st.caption(
            "Ora la tabella mostra direttamente giocatore, giocata e sito bookmaker. "
            "Gli ID tecnici API sono nascosti perché non servono alla lettura."
        )

        preferred_odds_cols = [
            "Campionato", "Data partita", "Partita",
            "Giocatore", "Giocata", "Bookmaker",
            "Quota", "Prob. implicita %", "Ultimo update",
        ]
        st.dataframe(
            odds_df[[c for c in preferred_odds_cols if c in odds_df.columns]],
            use_container_width=True, hide_index=True, height=600,
        )

        # Vista miglior quota per ogni partita/mercato/valore.
        best = (
            odds_df.dropna(subset=["Quota"])
            .sort_values("Quota", ascending=False)
            .drop_duplicates(subset=["Fixture ID", "Tipo mercato", "Giocatore", "Soglia"], keep="first")
        )
        with st.expander("🏆 Migliore quota trovata per ogni linea"):
            best_cols = [
                "Campionato", "Partita", "Giocatore", "Giocata",
                "Bookmaker", "Quota", "Prob. implicita %",
            ]
            st.dataframe(
                best[[c for c in best_cols if c in best.columns]],
                use_container_width=True, hide_index=True, height=500,
            )
    else:
        st.warning(
            "Nessuna quota player props trovata nelle partite testate. "
            "Questo può significare che le quote non sono ancora pubblicate, che il bookmaker "
            "non offre quei mercati su quelle gare o che la copertura API è assente per quel match."
        )

    if real_odds_errors:
        with st.expander("⚠️ Errori/risposte API durante il test quote"):
            st.dataframe(pd.DataFrame(real_odds_errors), use_container_width=True, hide_index=True)

    st.info(
        "Nota: la probabilità implicita è 1/quota e include il margine del bookmaker. "
        "Non è ancora il nostro 'edge'. Il confronto con Prob. stimata/Quota equa sarà il passo successivo "
        "dopo aver verificato che i valori API identificano bene giocatore e linea."
    )
    st.divider()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Campionati", len(LEAGUES))
c2.metric("Giocatori analizzati", all_df["player_id"].nunique())
c3.metric(f"Segnali ≥ {probability_threshold}%", len(filtered))
c4.metric("Gare storiche usate", total_fixtures)

if not filtered.empty:
    real_count = int(pd.to_numeric(filtered["Quota reale"], errors="coerce").notna().sum()) if "Quota reale" in filtered.columns else 0
    st.caption(
        f"💶 Quote reali abbinate automaticamente: {real_count}/{len(filtered)} segnali. "
        "Per ogni segnale viene mostrata la migliore quota disponibile trovata nell'API."
    )
    if top_odds_errors:
        with st.expander("⚠️ Errori nel collegamento delle quote"):
            st.dataframe(pd.DataFrame(top_odds_errors), use_container_width=True, hide_index=True)

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
        "Bookmaker",
        "Quota reale",
        "Prob. bookmaker %",
        "Edge p.p.",
        "Value %",
        "VALUE",
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
            "Prob. stimata", "Quota equa", "Bookmaker", "Quota reale",
            "Prob. bookmaker %", "Edge p.p.", "Value %", "VALUE"
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


st.divider()
st.subheader("🏟️ Pronostici partite 1X2 & Schedina")

if enable_match_model and match_prediction_rows:
    match_pred_df = pd.DataFrame(match_prediction_rows)
    match_pred_df = enrich_extra_markets(match_pred_df)
    match_pred_df["_sort"] = pd.to_datetime(
        match_pred_df["Data"], format="%d/%m/%Y %H:%M", errors="coerce"
    )
    match_pred_df = match_pred_df.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)

    st.markdown("### 🔥 Contesto e motivazioni della partita")
    st.caption(
        "La classifica viene letta automaticamente. Se sai che una squadra deve vincere per qualificarsi, "
        "ha turnover o una motivazione particolare, puoi indicarlo qui. Il correttivo resta volutamente piccolo "
        "per non trasformare una motivazione in una falsa certezza."
    )

    context_table = match_pred_df[
        [
            "Fixture ID", "Campionato", "Data", "Partita",
            "Contesto automatico", "Pos. casa", "Punti casa",
            "Pos. trasferta", "Punti trasferta"
        ]
    ].copy()
    context_table["Contesto casa"] = "Neutro"
    context_table["Contesto trasferta"] = "Neutro"
    context_table["Nota contesto"] = ""

    edited_context = st.data_editor(
        context_table,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Fixture ID": st.column_config.NumberColumn(disabled=True),
            "Campionato": st.column_config.TextColumn(disabled=True),
            "Data": st.column_config.TextColumn(disabled=True),
            "Partita": st.column_config.TextColumn(disabled=True),
            "Contesto automatico": st.column_config.TextColumn(disabled=True, width="large"),
            "Pos. casa": st.column_config.NumberColumn(disabled=True),
            "Punti casa": st.column_config.NumberColumn(disabled=True),
            "Pos. trasferta": st.column_config.NumberColumn(disabled=True),
            "Punti trasferta": st.column_config.NumberColumn(disabled=True),
            "Contesto casa": st.column_config.SelectboxColumn(
                options=CONTEXT_LEVELS,
                required=True,
                help="Es. deve vincere per passare il turno, turnover, motivazione alta."
            ),
            "Contesto trasferta": st.column_config.SelectboxColumn(
                options=CONTEXT_LEVELS,
                required=True
            ),
            "Nota contesto": st.column_config.TextColumn(
                help="Es. ritorno playoff: deve vincere; salvezza; qualificazione già acquisita."
            ),
        },
        key="match_context_editor",
    )

    match_pred_df = apply_manual_match_context(match_pred_df, edited_context)

    with st.spinner("💶 Cerco le migliori quote 1X2 disponibili..."):
        match_pred_df, match_odds_errors = attach_1x2_real_odds(match_pred_df)

    # Miglior esito modello
    probs = match_pred_df[["Prob. 1 %", "Prob. X %", "Prob. 2 %"]].to_numpy()
    outcomes = np.array(["1", "X", "2"])
    best_idx = np.argmax(probs, axis=1)
    match_pred_df["Pronostico"] = outcomes[best_idx]
    match_pred_df["Prob. pronostico %"] = probs[np.arange(len(probs)), best_idx]

    st.caption(
        "Il modello combina forma recente, rendimento casa/trasferta, gol fatti/subiti, classifica, "
        "fattore giocatori e contesto/motivazioni. Il contesto modifica il modello solo in modo contenuto: "
        "una squadra obbligata a vincere non viene mai trattata come vincente certa."
    )

    view_cols = [
        "Campionato", "Data", "Partita", "Contesto automatico",
        "Pronostico", "Prob. pronostico %",
        "Prob. 1 %", "Prob. X %", "Prob. 2 %",
        "Prob. 1X %", "Prob. X2 %", "Prob. GOL %", "Prob. NO GOL %",
        "Quota equa 1X", "Quota equa X2", "Quota equa GOL", "Quota equa NO GOL",
        "Quota equa 1", "Quota reale 1", "Bookmaker 1",
        "Quota equa X", "Quota reale X", "Bookmaker X",
        "Quota equa 2", "Quota reale 2", "Bookmaker 2",
        "xG casa modello", "xG trasferta modello",
    ]
    view_cols = [c for c in view_cols if c in match_pred_df.columns]
    st.dataframe(match_pred_df[view_cols], use_container_width=True, hide_index=True, height=520)

    st.info(
        "🎯 Criterio attuale: prima affidabilità, poi quota. "
        "Una giocata a quota 1.25–1.35 può essere selezionata se la probabilità stimata è alta. "
        "Il programma non è obbligato a raggiungere una quota totale minima."
    )

    st.markdown("### ✍️ Quote bookmaker modificabili")
    st.caption(
        "Puoi correggere manualmente le quote e indicare il sito/bookmaker. "
        "La valutazione si aggiorna usando la probabilità del modello. "
        "Per 1/X/2 provo a precompilare la quota API quando disponibile; 1X, X2, GOL e NO GOL puoi inserirli tu."
    )

    manual_odds = build_manual_odds_table(match_pred_df)

    edited_odds = st.data_editor(
        manual_odds,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Campionato": st.column_config.TextColumn(disabled=True),
            "Data": st.column_config.TextColumn(disabled=True),
            "Partita": st.column_config.TextColumn(disabled=True),
            "Mercato": st.column_config.TextColumn(disabled=True),
            "Prob. modello %": st.column_config.NumberColumn(format="%.1f", disabled=True),
            "Quota equa": st.column_config.NumberColumn(format="%.2f", disabled=True),
            "Quota bookmaker": st.column_config.NumberColumn(
                min_value=1.01, step=0.01, format="%.2f",
                help="Inserisci qui la quota che vedi sul bookmaker."
            ),
            "Bookmaker / sito": st.column_config.TextColumn(
                help="Es. Bet365, Snai, Eurobet, Sisal..."
            ),
        },
        key="manual_odds_editor",
    )

    evaluated_odds = evaluate_manual_odds(edited_odds)

    st.markdown("### 📊 Vale la pena?")
    with_quotes = evaluated_odds[evaluated_odds["Quota bookmaker"].notna()].copy()

    if with_quotes.empty:
        st.info("Inserisci almeno una quota bookmaker nella tabella sopra.")
    else:
        with_quotes = with_quotes.sort_values(["Value %", "Prob. modello %"], ascending=False)
        st.dataframe(
            with_quotes[
                [
                    "Campionato", "Partita", "Mercato", "Prob. modello %",
                    "Quota equa", "Quota bookmaker", "Bookmaker / sito",
                    "Prob. implicita %", "Edge p.p.", "Value %", "Conviene?"
                ]
            ],
            use_container_width=True,
            hide_index=True,
            height=430,
        )

    coupon_df, coupon_summary = make_coupon_from_manual_odds(
        evaluated_odds,
        coupon_mode,
        coupon_legs,
        min_coupon_probability,
    )

    st.markdown(f"### 🎟️ Schedina suggerita — {coupon_mode}")
    if not coupon_df.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Eventi scelti", coupon_summary.get("N. eventi", 0))
        m2.metric("Quota totale", coupon_summary.get("Quota totale", "—"))
        m3.metric(
            "Prob. combinata approx",
            f"{coupon_summary.get('Prob. combinata approx %', 0):.2f}%"
        )
        m4.metric(
            "Prob. media eventi",
            f"{coupon_summary.get('Prob. media eventi %', 0):.1f}%"
        )
        st.dataframe(coupon_df, use_container_width=True, hide_index=True)
        st.caption(
            "Priorità alla probabilità, non al raggiungimento di una quota obiettivo: "
            "se il modello trova pochi eventi davvero forti, può proporre una schedina più corta. "
            "La probabilità combinata resta un'approssimazione e non rende l'esito certo."
        )
    else:
        st.info(
            "Non ci sono abbastanza eventi sopra la probabilità minima scelta con le quote inserite. "
            "Meglio nessuna selezione che aggiungere eventi deboli solo per alzare la quota."
        )

    with st.expander("🧠 Dettagli forza squadre e giocatori"):
        detail = [
            "Campionato", "Partita", "Contesto automatico",
            "Contesto casa", "Contesto trasferta", "Nota contesto",
            "Pos. casa", "Punti casa", "Pos. trasferta", "Punti trasferta",
            "Forma casa PPG", "Forma trasferta PPG",
            "Fattore giocatori casa", "Fattore giocatori trasferta",
            "Tiri-porta giocatori casa idx", "Tiri-porta giocatori trasferta idx",
            "Continuità nucleo casa %", "Continuità nucleo trasferta %",
            "xG casa modello", "xG trasferta modello",
        ]
        st.dataframe(match_pred_df[detail], use_container_width=True, hide_index=True)

    errs = match_prediction_errors + match_odds_errors
    if errs:
        with st.expander("⚠️ Partite/quote non elaborate"):
            st.dataframe(pd.DataFrame(errs), use_container_width=True, hide_index=True)
elif enable_match_model:
    st.info("Nessun pronostico 1X2 disponibile con le partite future attuali.")


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
