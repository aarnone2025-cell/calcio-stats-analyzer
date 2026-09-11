import streamlit as st
import pandas as pd
import numpy as np
import requests, math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title='Schedina Calcio', page_icon='🎟️', layout='wide')
BASE_URL='https://v3.football.api-sports.io'
HISTORY_SEASON=2025
CURRENT_SEASON=2026
LEAGUES={'Serie A 🇮🇹':135,'Serie B 🇮🇹':136,'Premier League 🏴':39,'La Liga 🇪🇸':140,'Bundesliga 🇩🇪':78,'Ligue 1 🇫🇷':61}

def get_key():
    try: return st.secrets['API_FOOTBALL_KEY']
    except Exception: return None

@st.cache_data(ttl=21600, show_spinner=False)
def api_get(endpoint, params):
    r=requests.get(f'{BASE_URL}/{endpoint}',headers={'x-apisports-key':get_key()},params=params,timeout=30)
    r.raise_for_status(); return r.json()

@st.cache_data(ttl=21600, show_spinner=False)
def get_finished(league, season):
    return api_get('fixtures',{'league':league,'season':season,'status':'FT','timezone':'Europe/Rome'}).get('response',[])

@st.cache_data(ttl=1800, show_spinner=False)
def get_upcoming(league, season, days=7):
    tz=ZoneInfo('Europe/Rome'); now=datetime.now(tz)
    data=api_get('fixtures',{'league':league,'season':season,'from':now.strftime('%Y-%m-%d'),'to':(now+timedelta(days=days)).strftime('%Y-%m-%d'),'timezone':'Europe/Rome'})
    fixtures=data.get('response') or []
    if not fixtures:
        fixtures=api_get('fixtures',{'league':league,'season':season,'next':30,'timezone':'Europe/Rome'}).get('response') or []
    out=[]
    for f in fixtures:
        fx=f.get('fixture') or {}; status=(fx.get('status') or {}).get('short'); raw=fx.get('date')
        if not raw: continue
        dt=pd.to_datetime(raw); dt=dt.tz_localize('Europe/Rome') if dt.tzinfo is None else dt.tz_convert('Europe/Rome')
        if status in {'NS','TBD'} and dt.to_pydatetime()>now: out.append(f)
    out=list({f['fixture']['id']:f for f in out}.values()); out.sort(key=lambda f: pd.to_datetime(f['fixture']['date']))
    return out

@st.cache_data(ttl=1800, show_spinner=False)
def get_standings(league, season):
    data=api_get('standings',{'league':league,'season':season}); resp=data.get('response') or []; rows=[]
    if resp:
        for group in resp[0].get('league',{}).get('standings') or []:
            for r in group:
                t=r.get('team') or {}; a=r.get('all') or {}
                rows.append({'team_id':t.get('id'),'team':t.get('name',''),'rank':r.get('rank'),'points':r.get('points'),'played':a.get('played'),'form':r.get('form')})
    return rows

def weighted_mean(vals, decay=.88):
    vals=[float(v) for v in vals if v is not None and pd.notna(v)]
    if not vals: return np.nan
    n=len(vals); w=np.array([decay**(n-1-i) for i in range(n)],float)
    return float(np.average(np.array(vals),weights=w))

def league_baseline(fixtures):
    hg=[]; ag=[]
    for f in fixtures:
        g=f.get('goals') or {}; h,a=g.get('home'),g.get('away')
        if h is not None and a is not None: hg.append(float(h)); ag.append(float(a))
    return (float(np.mean(hg)) if hg else 1.45, float(np.mean(ag)) if ag else 1.15)

def team_metrics(fixtures, team_id, venue=None, n=10):
    rows=[]
    for f in fixtures:
        teams=f.get('teams') or {}; hid=(teams.get('home') or {}).get('id'); aid=(teams.get('away') or {}).get('id')
        if team_id not in {hid,aid}: continue
        is_home=team_id==hid; v='Casa' if is_home else 'Trasferta'
        if venue and v!=venue: continue
        g=f.get('goals') or {}; gh,ga=g.get('home'),g.get('away')
        if gh is None or ga is None: continue
        gf=float(gh if is_home else ga); gc=float(ga if is_home else gh); pts=3.0 if gf>gc else (1.0 if gf==gc else 0.0)
        rows.append((pd.to_datetime(f['fixture']['date']),gf,gc,pts))
    rows=sorted(rows,key=lambda x:x[0])[-n:]
    if not rows: return {'gf':np.nan,'ga':np.nan,'ppg':np.nan,'n':0}
    return {'gf':weighted_mean([r[1] for r in rows]),'ga':weighted_mean([r[2] for r in rows]),'ppg':weighted_mean([r[3] for r in rows]),'n':len(rows)}

def blend(primary,fallback,key,default):
    p=primary.get(key); f=fallback.get(key)
    if pd.notna(p) and primary.get('n',0)>=3: return .65*p+.35*(f if pd.notna(f) else default)
    return f if pd.notna(f) else default

def poisson_matrix(lh,la,max_goals=8):
    ph=[math.exp(-lh)*lh**k/math.factorial(k) for k in range(max_goals+1)]
    pa=[math.exp(-la)*la**k/math.factorial(k) for k in range(max_goals+1)]
    m=np.outer(ph,pa); return m/m.sum()

def market_probs(lh,la):
    m=poisson_matrix(lh,la); p1=float(np.tril(m,-1).sum()); px=float(np.trace(m)); p2=float(np.triu(m,1).sum())
    gg=sum(float(m[i,j]) for i in range(1,m.shape[0]) for j in range(1,m.shape[1])); totals={}
    for i in range(m.shape[0]):
        for j in range(m.shape[1]): totals[i+j]=totals.get(i+j,0)+float(m[i,j])
    probs={'1':p1,'X':px,'2':p2,'1X':p1+px,'X2':px+p2,'12':p1+p2,'GOL':gg,'NO GOL':1-gg,
           'Over 1.5':sum(v for k,v in totals.items() if k>=2),'Under 1.5':sum(v for k,v in totals.items() if k<=1),
           'Over 2.5':sum(v for k,v in totals.items() if k>=3),'Under 2.5':sum(v for k,v in totals.items() if k<=2),
           'Over 3.5':sum(v for k,v in totals.items() if k>=4),'Under 3.5':sum(v for k,v in totals.items() if k<=3)}
    return probs,m

def top_scores(m,n=3):
    rows=[(float(m[i,j]),f'{i}-{j}') for i in range(m.shape[0]) for j in range(m.shape[1])]
    rows.sort(reverse=True); return rows[:n]

def predict(fixture,history,standings,league_name):
    teams=fixture.get('teams') or {}; home=teams.get('home') or {}; away=teams.get('away') or {}; hid,aid=home.get('id'),away.get('id')
    if not hid or not aid: return None
    bh,ba=league_baseline(history); ha=team_metrics(history,hid,None,10); aa=team_metrics(history,aid,None,10); hh=team_metrics(history,hid,'Casa',6); aw=team_metrics(history,aid,'Trasferta',6)
    hgf=blend(hh,ha,'gf',bh); hga=blend(hh,ha,'ga',ba); agf=blend(aw,aa,'gf',ba); aga=blend(aw,aa,'ga',bh)
    h_att=np.clip(hgf/max(bh,.35),.55,1.75); h_def=np.clip(hga/max(ba,.35),.55,1.75); a_att=np.clip(agf/max(ba,.35),.55,1.75); a_def=np.clip(aga/max(bh,.35),.55,1.75)
    hppg=ha['ppg'] if pd.notna(ha['ppg']) else 1.4; appg=aa['ppg'] if pd.notna(aa['ppg']) else 1.4
    lh=float(np.clip(bh*math.sqrt(h_att*a_def)*np.clip((hppg/1.4)**.10,.90,1.10),.20,3.50)); la=float(np.clip(ba*math.sqrt(a_att*h_def)*np.clip((appg/1.4)**.10,.90,1.10),.20,3.25))
    probs,m=market_probs(lh,la); scores=top_scores(m,3)
    penalty={'1X':.015,'X2':.015,'12':.02,'Under 3.5':.03,'Over 1.5':.03}
    rec=sorted([(min(p,.90)-penalty.get(k,0),p,k) for k,p in probs.items()],reverse=True)[0]; _,rp,rm=rec
    sm={r['team_id']:r for r in standings if r.get('team_id') is not None}; hs,as_=sm.get(hid,{}),sm.get(aid,{})
    reasons=[]
    if hppg>=appg+.45: reasons.append(f"forma recente migliore {home.get('name')} ({hppg:.2f} vs {appg:.2f} punti/gara)")
    elif appg>=hppg+.45: reasons.append(f"forma recente migliore {away.get('name')} ({appg:.2f} vs {hppg:.2f} punti/gara)")
    else: reasons.append('forma recente abbastanza equilibrata')
    if hs.get('rank') and as_.get('rank'): reasons.append(f"classifica: {home.get('name')} #{hs.get('rank')}, {away.get('name')} #{as_.get('rank')}")
    if rm in {'1','1X'}: reasons.append(f'vantaggio casa e xG modello {lh:.2f}-{la:.2f}')
    elif rm in {'2','X2'}: reasons.append(f'profilo trasferta favorevole e xG modello {lh:.2f}-{la:.2f}')
    elif 'Over' in rm: reasons.append(f'totale gol atteso {lh+la:.2f}')
    elif 'Under' in rm: reasons.append(f'totale gol atteso contenuto {lh+la:.2f}')
    elif rm=='GOL': reasons.append('buona probabilità che segnino entrambe')
    elif rm=='NO GOL': reasons.append('buona probabilità che almeno una resti a zero')
    dt=pd.to_datetime(fixture['fixture']['date']); dt=dt.tz_convert('Europe/Rome') if dt.tzinfo is not None else dt
    return {'Campionato':league_name,'Data':dt.strftime('%d/%m/%Y %H:%M'),'Partita':f"{home.get('name')} - {away.get('name')}",'Giocata consigliata':rm,'Probabilità %':round(rp*100,1),'Quota equa':round(1/rp,2),'Perché':' · '.join(reasons),'xG modello':f'{lh:.2f} - {la:.2f}',
            'Risultato esatto 1':scores[0][1],'Prob. risultato 1 %':round(scores[0][0]*100,1),'Risultato esatto 2':scores[1][1],'Prob. risultato 2 %':round(scores[1][0]*100,1),'Risultato esatto 3':scores[2][1],'Prob. risultato 3 %':round(scores[2][0]*100,1)}

def evaluate_quotes(df):
    out=df.copy(); out['Quota inserita']=pd.to_numeric(out['Quota inserita'],errors='coerce')
    out['Prob. implicita %']=np.where(out['Quota inserita']>1,100/out['Quota inserita'],np.nan)
    out['Edge p.p.']=out['Probabilità %']-out['Prob. implicita %']; out['Value %']=((out['Probabilità %']/100)*out['Quota inserita']-1)*100
    def verdict(r):
        if pd.isna(r['Quota inserita']): return 'Inserisci quota'
        if r['Probabilità %']>=75 and r['Value %']>=-8: return '🟢 Buona per multipla'
        if r['Probabilità %']>=68 and r['Value %']>=0: return '🟢 Interessante'
        if r['Probabilità %']>=65 and r['Value %']>=-5: return '🟡 Valutabile'
        return '🔴 Meglio evitare'
    out['Valutazione']=out.apply(verdict,axis=1)
    for c in ['Prob. implicita %','Edge p.p.','Value %']: out[c]=out[c].round(1)
    return out

def build_coupon(df,max_events,min_prob):
    c=df[df['Quota inserita'].notna() & (df['Quota inserita']>1) & (df['Probabilità %']>=min_prob) & (~df['Valutazione'].str.contains('evitare',case=False,na=False))].copy()
    if c.empty: return pd.DataFrame(),{}
    c['_score']=4*(c['Probabilità %']/100)+.15*(c['Value %'].fillna(0)/100)+.03*np.log(c['Quota inserita'])
    c=c.sort_values(['_score','Probabilità %'],ascending=False).head(max_events)
    view=c[['Campionato','Data','Partita','Giocata consigliata','Probabilità %','Quota inserita','Perché','Valutazione']].copy()
    return view,{'eventi':len(view),'quota_totale':round(float(np.prod(c['Quota inserita'])),2),'prob_media':round(float(view['Probabilità %'].mean()),1),'prob_combinata':round(float(np.prod(view['Probabilità %']/100))*100,2)}

st.title('🎟️ Schedina Calcio — solo partite')
st.caption('Niente giocatori: solo pronostici di partita, motivazione della scelta, quote inserite da te e 3 risultati esatti più probabili.')
if not get_key(): st.error('API_FOOTBALL_KEY non trovata nei Secrets di Streamlit.'); st.stop()

with st.sidebar:
    st.header('Impostazioni')
    days=st.slider('Giorni futuri da analizzare',1,14,7)
    per_league=st.slider('Partite per campionato',1,10,5)
    min_prob=st.slider('Probabilità minima per la schedina',55,90,70)
    max_events=st.slider('Numero massimo eventi',2,8,5)
    st.caption('Se ci sono pochi eventi forti, la schedina resta più corta: non forza il moltiplicatore.')

pred=[]; errors=[]
with st.spinner('Analizzo le prossime partite...'):
    for lname,lid in LEAGUES.items():
        try:
            history=sorted(get_finished(lid,HISTORY_SEASON)+get_finished(lid,CURRENT_SEASON),key=lambda f:pd.to_datetime(f['fixture']['date']))[-220:]
            upcoming=get_upcoming(lid,CURRENT_SEASON,days); standings=get_standings(lid,CURRENT_SEASON)
            for f in upcoming[:per_league]:
                try:
                    r=predict(f,history,standings,lname)
                    if r: pred.append(r)
                except Exception as e: errors.append({'Campionato':lname,'Partita':f.get('fixture',{}).get('id'),'Errore':str(e)})
        except Exception as e: errors.append({'Campionato':lname,'Errore':str(e)})

if not pred:
    st.warning('Nessuna partita futura trovata con i filtri attuali.')
    if errors:
        with st.expander('Dettagli errori'): st.dataframe(pd.DataFrame(errors),use_container_width=True,hide_index=True)
    st.stop()

pred_df=pd.DataFrame(pred); pred_df['_dt']=pd.to_datetime(pred_df['Data'],format='%d/%m/%Y %H:%M',errors='coerce'); pred_df=pred_df.sort_values(['_dt','Probabilità %'],ascending=[True,False]).drop(columns='_dt')

st.subheader('✅ Pronostici consigliati e perché')
cols=['Campionato','Data','Partita','Giocata consigliata','Probabilità %','Quota equa','Perché','xG modello','Risultato esatto 1','Prob. risultato 1 %','Risultato esatto 2','Prob. risultato 2 %','Risultato esatto 3','Prob. risultato 3 %']
st.dataframe(pred_df[cols],use_container_width=True,hide_index=True,height=560)

st.subheader('✍️ Inserisci tu le quote')
q=pred_df[['Campionato','Data','Partita','Giocata consigliata','Probabilità %','Quota equa','Perché']].copy(); q['Quota inserita']=np.nan; q['Bookmaker / sito']=''
edited=st.data_editor(q,use_container_width=True,hide_index=True,num_rows='fixed',column_config={
    'Campionato':st.column_config.TextColumn(disabled=True),'Data':st.column_config.TextColumn(disabled=True),'Partita':st.column_config.TextColumn(disabled=True),'Giocata consigliata':st.column_config.TextColumn(disabled=True),
    'Probabilità %':st.column_config.NumberColumn(format='%.1f',disabled=True),'Quota equa':st.column_config.NumberColumn(format='%.2f',disabled=True),'Perché':st.column_config.TextColumn(disabled=True,width='large'),
    'Quota inserita':st.column_config.NumberColumn(min_value=1.01,step=.01,format='%.2f'),'Bookmaker / sito':st.column_config.TextColumn()},key='manual_quotes')

eval_df=evaluate_quotes(edited); withq=eval_df[eval_df['Quota inserita'].notna()].copy()
st.subheader('🧮 Valutazione delle tue quote')
if withq.empty: st.info('Inserisci almeno una quota sopra: il calcolo si aggiorna automaticamente.')
else: st.dataframe(withq[['Partita','Giocata consigliata','Probabilità %','Quota equa','Quota inserita','Prob. implicita %','Edge p.p.','Value %','Valutazione']].sort_values(['Probabilità %','Value %'],ascending=False),use_container_width=True,hide_index=True)

coupon,summary=build_coupon(eval_df,max_events,min_prob)
st.subheader('🎟️ Schedina consigliata')
if coupon.empty:
    st.info('Dopo aver inserito le quote, qui comparirà solo la combinazione degli eventi più affidabili. Non è obbligatorio raggiungere una quota minima.')
else:
    a,b,c,d=st.columns(4); a.metric('Eventi',summary['eventi']); b.metric('Quota totale',summary['quota_totale']); c.metric('Prob. media eventi',f"{summary['prob_media']:.1f}%"); d.metric('Prob. combinata approx',f"{summary['prob_combinata']:.2f}%")
    st.dataframe(coupon,use_container_width=True,hide_index=True)
    st.caption('La probabilità combinata è un’approssimazione; non garantisce l’esito della multipla.')

if errors:
    with st.expander('⚠️ Eventuali campionati non caricati'): st.dataframe(pd.DataFrame(errors),use_container_width=True,hide_index=True)
