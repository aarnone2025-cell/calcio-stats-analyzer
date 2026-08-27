
# Calcio Stats Analyzer — MVP

Prima versione per analizzare statistiche per giocatore e individuare frequenze elevate.

## Mercati inclusi
- 1+, 2+, 3+ tiri
- 1+, 2+ tiri in porta
- ammonizione
- 3+, 4+, 5+ parate

## Avvio
1. Installa Python 3.11+.
2. Apri il terminale nella cartella.
3. Esegui: `pip install -r requirements.txt`
4. Esegui: `streamlit run app.py`

## Formato CSV richiesto
Una riga = un giocatore in una partita.

Colonne:
date, league, match, team, opponent, player, position, minutes,
shots_total, shots_on_target, yellow_cards, red_cards, saves

## Stima iniziale
- Ultime 5: peso 45%
- Ultime 10: peso 30%
- Stagione: peso 25%
- Correzione verso la media quando il campione è piccolo

## Prossima fase
Collegamento API-Football:
- fixtures
- fixtures/players
- fixtures/events
- lineups
- injuries
- odds

Per i dati reali serve una API key personale e la copertura deve essere disponibile per lega/stagione.
