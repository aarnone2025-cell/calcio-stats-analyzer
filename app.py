
import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path

st.set_page_config(page_title="Calcio Stats Analyzer", page_icon="⚽", layout="wide")

REQUIRED = [
    "date","league","match","team","opponent","player","position","minutes",
    "shots_total","shots_on_target","yellow_cards","red_cards","saves"
]

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

def load_data(uploaded=None):
    if uploaded is not None:
        df = pd.read_csv(uploaded)
    else:
        p = Path(__file__).parent / "sample_matches.csv"
        df = pd.read_csv(p)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        st.error("Colonne mancanti: " + ", ".join(missing))
        st.stop()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    numeric = ["minutes","shots_total","shots_on_target","yellow_cards","red_cards","saves"]
    for c in numeric:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df.dropna(subset=["date"]).sort_values("date")

def rate_for(g, stat, threshold, n=None, min_minutes=1):
    x = g[g["minutes"] >= min_minutes].sort_values("date")
    if n:
        x = x.tail(n)
    if len(x) == 0:
        return np.nan, 0
    return (x[stat] >= threshold).mean(), len(x)

def build_rankings(df, market, min_minutes, min_apps, odds=None):
    stat, threshold = MARKETS[market]
    rows = []
    league_avg = (df[stat] >= threshold).mean() if len(df) else 0

    for player, g in df.groupby("player", sort=False):
        g = g.sort_values("date")
        usable = g[g["minutes"] >= min_minutes]
        if len(usable) < min_apps:
            continue

        r5, n5 = rate_for(g, stat, threshold, 5, min_minutes)
        r10, n10 = rate_for(g, stat, threshold, 10, min_minutes)
        rs, ns = rate_for(g, stat, threshold, None, min_minutes)

        vals, weights = [], []
        for val, w in [(r5, 0.45), (r10, 0.30), (rs, 0.25)]:
            if not np.isnan(val):
                vals.append(val)
                weights.append(w)
        raw = np.average(vals, weights=weights) if vals else np.nan

        sample_strength = min(ns / 15.0, 1.0)
        prob = raw * sample_strength + league_avg * (1 - sample_strength)

        last = usable.iloc[-1]
        avg_minutes = usable.tail(10)["minutes"].mean()

        row = {
            "Giocatore": player,
            "Squadra": last["team"],
            "Ruolo": last["position"],
            "Campionato": last["league"],
            "Presenze usate": int(ns),
            "Minuti medi": round(avg_minutes, 1),
            "Ultime 5": round(r5 * 100, 1) if not np.isnan(r5) else np.nan,
            "Ultime 10": round(r10 * 100, 1) if not np.isnan(r10) else np.nan,
            "Stagione": round(rs * 100, 1) if not np.isnan(rs) else np.nan,
            "Prob. stimata": round(prob * 100, 1),
            "Quota equa": round(1 / prob, 2) if prob > 0 else np.nan,
        }
        if odds is not None and odds > 1:
            implied = 1 / odds
            row["Quota inserita"] = odds
            row["Prob. quota"] = round(implied * 100, 1)
            row["Edge"] = round((prob - implied) * 100, 1)
        rows.append(row)

    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["Prob. stimata","Presenze usate"], ascending=[False,False])
    return out

st.title("⚽ Calcio Stats Analyzer")
st.caption("MVP per Serie A / Serie B — tiri, tiri in porta, cartellini e parate.")

with st.sidebar:
    st.header("Dati")
    uploaded = st.file_uploader("Carica CSV statistiche partita/giocatore", type=["csv"])
    st.caption("Se non carichi nulla viene usato il file dimostrativo incluso.")

df = load_data(uploaded)

with st.sidebar:
    leagues = sorted(df["league"].dropna().unique().tolist())
    selected_leagues = st.multiselect("Campionato", leagues, default=leagues)
    market = st.selectbox("Mercato", list(MARKETS.keys()))
    min_minutes = st.slider("Minuti minimi per contare una presenza", 1, 90, 45)
    min_apps = st.slider("Presenze minime", 2, 20, 5)
    threshold_prob = st.slider("Mostra probabilità da", 50, 100, 75)
    use_odds = st.checkbox("Confronta con una quota")
    odds = st.number_input("Quota bookmaker", min_value=1.01, max_value=20.0, value=1.50, step=0.01) if use_odds else None

fdf = df[df["league"].isin(selected_leagues)] if selected_leagues else df.iloc[0:0]
ranking = build_rankings(fdf, market, min_minutes, min_apps, odds)
filtered = ranking[ranking["Prob. stimata"] >= threshold_prob].copy() if len(ranking) else ranking

c1, c2, c3 = st.columns(3)
c1.metric("Giocatori analizzati", len(ranking))
c2.metric(f"Segnali ≥ {threshold_prob}%", len(filtered))
if len(filtered):
    c3.metric("Probabilità massima", f'{filtered["Prob. stimata"].max():.1f}%')
else:
    c3.metric("Probabilità massima", "—")

st.subheader(f"TOP — {market}")
if len(filtered):
    def label(p):
        if p >= 85: return "🟢 Molto alta"
        if p >= 75: return "🟡 Alta"
        if p >= 65: return "⚪ Media"
        return "🔴 Bassa"
    filtered.insert(0, "Classe", filtered["Prob. stimata"].map(label))
    st.dataframe(filtered, use_container_width=True, hide_index=True)
else:
    st.info("Nessun giocatore supera i filtri selezionati.")

st.subheader("Scheda giocatore")
players = sorted(fdf["player"].unique().tolist())
if players:
    player = st.selectbox("Giocatore", players)
    g = fdf[fdf["player"] == player].sort_values("date", ascending=False).copy()
    st.dataframe(
        g[["date","league","match","team","opponent","minutes","shots_total",
           "shots_on_target","yellow_cards","red_cards","saves"]],
        use_container_width=True, hide_index=True
    )

st.divider()
st.caption(
    "Nota: la probabilità è una stima statistica, non una garanzia. "
    "La prima versione usa frequenze pesate e una correzione per campioni piccoli. "
    "Per uso reale va validata su dati storici fuori campione e confrontata con quote specifiche per mercato."
)
