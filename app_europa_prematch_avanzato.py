
import streamlit as st
import pandas as pd
import numpy as np
import requests
import math

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
            team = block.get("team", {}).get("name", "")
            opponent = away if team == home else home
            venue = "Casa" if team == home else "Trasferta"

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
                    "opponent": opponent,
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

def advanced_probability(df, g, stat, threshold, min_minutes, upcoming, league_avg):
    """
    Modello pre-match trasparente.

    Componenti:
      45% forma recente / hit-rate regolarizzato
      25% volume statistico atteso (per 90 + minuti attesi + avversario)
      15% split casa/trasferta
      15% quanto l'avversario concede storicamente

    La previsione finale viene poi ridotta verso la media campionato quando
    campione, minuti o continuità da titolare sono poco affidabili.
    """
    usable = g[g["minutes"] >= min_minutes].sort_values("date").tail(15).copy()
    if usable.empty:
        return league_avg, {}

    recent_prob, n = recency_probability(
        g, stat, threshold, min_minutes, league_avg, max_games=15
    )

    next_venue = upcoming.get("Casa/Fuori") if upcoming else None
    next_opponent = upcoming.get("Avversario") if upcoming else None

    # Split personale casa/trasferta, con prior verso la media campionato.
    venue_sample = usable[usable["venue"] == next_venue] if next_venue else usable.iloc[0:0]
    venue_hits = int((venue_sample[stat] >= threshold).sum()) if not venue_sample.empty else 0
    venue_prob = bayes_rate(
        venue_hits, len(venue_sample), league_avg, prior_strength=4.0
    )

    # Quanto il prossimo avversario ha concesso a tutti i giocatori affrontati.
    opp_prob, opp_n = contextual_hit_rate(
        df, stat, threshold, min_minutes,
        opponent=next_opponent,
        prior_mean=league_avg,
    )

    # Volume per 90 del giocatore.
    player_per90 = weighted_per90(g, stat, min_minutes, max_games=15)

    recent5 = usable.tail(5)
    expected_minutes = float(recent5["minutes"].mean()) if not recent5.empty else float(usable["minutes"].mean())
    expected_minutes = float(np.clip(expected_minutes, 20.0, 90.0))

    # Fattore volume concesso dall'avversario.
    league_eligible = df[df["minutes"] >= min_minutes].copy()
    league_mean_stat = float(league_eligible[stat].mean()) if not league_eligible.empty else 0.0

    opp_rows = league_eligible[league_eligible["opponent"] == next_opponent] if next_opponent else league_eligible.iloc[0:0]
    opp_mean_stat = float(opp_rows[stat].mean()) if not opp_rows.empty else league_mean_stat

    if league_mean_stat > 0:
        opp_volume_factor = float(np.clip(opp_mean_stat / league_mean_stat, 0.75, 1.25))
    else:
        opp_volume_factor = 1.0

    expected_lambda = player_per90 * (expected_minutes / 90.0) * opp_volume_factor
    volume_prob = poisson_at_least(expected_lambda, threshold)

    raw_prob = (
        0.45 * recent_prob
        + 0.25 * volume_prob
        + 0.15 * venue_prob
        + 0.15 * opp_prob
    )

    # Affidabilità del campione.
    sample_score = min(len(usable) / 15.0, 1.0)
    minute_score = float(np.clip(expected_minutes / 75.0, 0.45, 1.0))

    if "starter" in usable.columns:
        starter_rate = float(usable.tail(10)["starter"].astype(float).mean())
    else:
        starter_rate = 0.75

    continuity_score = 0.70 + 0.30 * starter_rate
    reliability = float(np.clip(sample_score * minute_score * continuity_score, 0.0, 1.0))

    # Con campioni piccoli si torna prudentemente verso la media del campionato.
    confidence = 0.55 + 0.45 * reliability
    final_prob = confidence * raw_prob + (1.0 - confidence) * league_avg
    final_prob = float(np.clip(final_prob, 0.03, 0.97))

    details = {
        "Forma recente %": round(recent_prob * 100, 1),
        "Volume %": round(volume_prob * 100, 1),
        "Casa/Trasferta %": round(venue_prob * 100, 1),
        "Avversario %": round(opp_prob * 100, 1),
        "Media/90": round(player_per90, 2),
        "Minuti attesi": round(expected_minutes, 1),
        "Titolarità recente %": round(starter_rate * 100, 1),
        "Affidabilità %": round(reliability * 100, 1),
        "Campione avversario": int(opp_n),
    }

    return final_prob, details

def build_upcoming_map(future):
    mapping = {}
    for f in future:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        dt = pd.to_datetime(f["fixture"]["date"])
        mapping[home] = {
            "Avversario": away,
            "Casa/Fuori": "Casa",
            "Data prossima": dt.strftime("%d/%m/%Y %H:%M"),
        }
        mapping[away] = {
            "Avversario": home,
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
        upcoming = (upcoming_map or {}).get(team)

        if upcoming_map is not None and upcoming is None:
            continue

        r5, h5, n5 = window_rate(g, stat, threshold, 5, min_minutes)
        r10, h10, n10 = window_rate(g, stat, threshold, 10, min_minutes)
        r15, h15, n15 = window_rate(g, stat, threshold, 15, min_minutes)

        prob, details = advanced_probability(
            df, g, stat, threshold, min_minutes, upcoming, league_avg
        )

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
    "La Liga, Bundesliga e Ligue 1"
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
        future, future_errors = get_upcoming_fixtures(league_id, CURRENT_SEASON, 20)

        if err_old or err_current:
            league_status.append({
                "Campionato": league_label,
                "Stato": "⚠️ Parziale",
                "Nota": str(err_old or err_current),
            })

        fixtures = choose_recent(old_fx, current_fx, recent_matches)

        if not fixtures:
            league_status.append({
                "Campionato": league_label,
                "Stato": "⚠️ Nessun dato",
                "Nota": "Nessuna partita conclusa trovata",
            })
            continue

        df_league = parse_player_rows(fixtures, league_label=league_label)
        if df_league.empty:
            league_status.append({
                "Campionato": league_label,
                "Stato": "⚠️ Nessuna statistica",
                "Nota": "Statistiche giocatore non disponibili",
            })
            continue

        df_league["Campionato"] = league_label
        all_player_data.append(df_league)

        upcoming_map = build_upcoming_map(future)

        for market_name in markets_to_scan:
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

        for f in future:
            future_rows.append({
                "Campionato": league_label,
                "Data": pd.to_datetime(f["fixture"]["date"]).strftime("%d/%m/%Y %H:%M"),
                "Partita": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                "Giornata": f.get("league", {}).get("round", ""),
            })

        total_fixtures += len(fixtures)
        current_fixtures_count += len([
            f for f in fixtures
            if f.get("league", {}).get("season") == CURRENT_SEASON
        ])

        league_status.append({
            "Campionato": league_label,
            "Stato": "✅ OK",
            "Nota": f"{len(fixtures)} gare analizzate",
        })

    except Exception as e:
        league_status.append({
            "Campionato": league_label,
            "Stato": "❌ Errore",
            "Nota": str(e),
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
c4.metric("Gare analizzate", total_fixtures)

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
            "Avversario %", "Media/90", "Minuti attesi",
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

with st.expander("📊 Stato dei campionati analizzati"):
    st.dataframe(pd.DataFrame(league_status), use_container_width=True, hide_index=True)

st.subheader("📅 Prossime partite")

if future_rows:
    future_df = pd.DataFrame(future_rows)
    future_df["_sort"] = pd.to_datetime(
        future_df["Data"], format="%d/%m/%Y %H:%M", errors="coerce"
    )
    future_df = future_df.sort_values("_sort").drop(columns="_sort")
    st.dataframe(future_df, use_container_width=True, hide_index=True)
else:
    st.info("Nessuna prossima partita trovata.")

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
        "date", "season", "league", "match", "team", "opponent", "venue", "starter", "minutes",
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
        "opponent": "Avversario",
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
    "volume per 90 minuti, minuti attesi, continuità/titolarità, casa-trasferta e dati concessi "
    "dal prossimo avversario. I campioni piccoli vengono corretti verso la media del campionato. "
    "Le percentuali sono stime statistiche, non garanzie di esito. "
    "Tiri, falli, cartellini e parate dipendono dalla copertura API disponibile per la singola gara."
)
