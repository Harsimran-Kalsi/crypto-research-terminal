"""Independent six-move Markov micro-price estimator, based on Stoikov (2018).
No reference source is vendored. State discretization and support guards are ours.
"""
import bisect
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

VERSION = 'stoikov-shadow-v1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS shadow_model (
 id TEXT PRIMARY KEY, symbol TEXT NOT NULL, demo INTEGER NOT NULL,
 fitted_at REAL NOT NULL, train_end REAL NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadow_forecast (
 model_id TEXT NOT NULL, quote_id INTEGER NOT NULL, session TEXT NOT NULL,
 at REAL NOT NULL, mid REAL NOT NULL, weighted REAL NOT NULL, micro REAL,
 reason TEXT NOT NULL, PRIMARY KEY(model_id,quote_id));
CREATE TABLE IF NOT EXISTS shadow_score (
 model_id TEXT NOT NULL, quote_id INTEGER NOT NULL, horizon INTEGER NOT NULL,
 target REAL NOT NULL, outcome_quote_id INTEGER NOT NULL,
 PRIMARY KEY(model_id,quote_id,horizon));
CREATE TABLE IF NOT EXISTS shadow_health (
 id INTEGER PRIMARY KEY CHECK(id=1), heartbeat REAL, status TEXT NOT NULL);
'''


def state(model, bid, ask, bq, aq):
    width = (ask-bid)/model['tick']
    if width < .5 or width > model['spread_states']+.25 or bq+aq <= 0:
        return None
    spread = round(width)
    if abs(width-spread) > .25:
        return None
    bucket = min(model['bins']-1, bisect.bisect_right(model['edges'], bq/(bq+aq)))
    return (spread-1)*model['bins']+bucket


def adjustment(q, rewards, moved, moves=6):
    """g1=(I-Q)^-1 r, B=(I-Q)^-1 R; sum(B^k g1,k=0..moves-1)."""
    fundamental = np.eye(len(q))-q
    first = np.linalg.solve(fundamental, rewards)
    b = np.linalg.solve(fundamental, moved)
    total, term = first.copy(), first.copy()
    for _ in range(moves-1):
        term = b@term
        total += term
    return total


def fit(rows, tick=None, bins=6, spread_states=3, min_pairs=100):
    # Rows: session, receipt time, bid, ask, bid size, ask size.
    spreads = [r[3]-r[2] for r in rows if r[3]>r[2]]
    if not spreads:
        raise ValueError('No positive spreads')
    tick = float(tick or min(spreads))
    if not math.isfinite(tick) or tick<=0:
        raise ValueError('Invalid tick')
    # Symmetric training-only quantiles; mirrored transitions use reversed bins.
    imbalance = [r[4]/(r[4]+r[5]) for r in rows if r[4]+r[5]>0]
    edges = np.quantile(imbalance+[1-v for v in imbalance], np.arange(1,bins)/bins).tolist()
    if len(set(edges)) != len(edges):
        raise ValueError('Insufficient imbalance variation')
    model = dict(version=VERSION,tick=tick,bins=bins,spread_states=spread_states,edges=edges,
                 train_end=max(r[1] for r in rows),moves=6)
    n=bins*spread_states
    unchanged, moved, reward = np.zeros((n,n)),np.zeros((n,n)),np.zeros(n)
    counts=np.zeros(n)
    pairs=0
    for a,b in zip(rows,rows[1:]):
        if a[0]!=b[0] or not 0 < b[1]-a[1]<=5:
            continue
        i,j=state(model,*a[2:]),state(model,*b[2:])
        if i is None or j is None:
            continue
        delta=((b[2]+b[3])-(a[2]+a[3]))/(2*tick)
        # Full observed moves retained; unlike reference filtering of large moves.
        for src,dst,change in [(i,j,delta),
                               ((i//bins)*bins+bins-1-i%bins,(j//bins)*bins+bins-1-j%bins,-delta)]:
            counts[src]+=1
            if abs(change)<1e-7:
                unchanged[src,dst]+=1
            else:
                moved[src,dst]+=1
                reward[src]+=change
        pairs+=1
    if pairs<min_pairs:
        raise ValueError('Insufficient supported transitions: %s < %s'%(pairs,min_pairs))
    denominator=np.where(counts>0,counts,1)
    q=unchanged/denominator[:,None]
    r=moved/denominator[:,None]
    radius=float(max(abs(np.linalg.eigvals(q))))
    if radius >= 1-1e-9:
        raise ValueError('Non-absorbing/singular transition system; collect more varied data')
    result=adjustment(q,reward/denominator,r)
    if not np.all(np.isfinite(result)):
        raise ValueError('Nonfinite adjustment')
    model.update(offset_ticks=result.tolist(),counts=counts.tolist(),pairs=pairs,
                 q_spectral_radius=radius,unsupported_states=int(sum(counts<10)))
    return model


def predict(model, bid, ask, bq, aq):
    i=state(model,bid,ask,bq,aq)
    if i is None:
        return None,'ABSTAIN: spread outside fitted state space'
    if model['counts'][i]<10:
        return None,'ABSTAIN: fewer than 10 training transitions in state'
    value=(bid+ask)/2+model['tick']*model['offset_ticks'][i]
    if not math.isfinite(value) or value<=0:
        return None,'ABSTAIN: invalid estimate'
    return value,'SHADOW ONLY: fitted six-price-move estimate'


def grid(rows):
    """Use the last quote of each receipt-time second; do not bridge sessions."""
    selected={}
    for row in rows:
        selected[(row[0],math.floor(row[1]))]=row
    return sorted(selected.values(),key=lambda r:r[1])


def reference(args):
    reports=[]
    for name in ('BAC','CVX'):
        path=Path(args.directory)/(name+'_20110301_20110331.csv')
        raw=path.read_bytes()
        rows=[]
        with path.open() as f:
            reader=csv.reader(f)
            next(reader)  # Author CSV header.
            for fields in reader:
                date,seconds,bid,bq,ask,aq=map(float,fields)
                if 0<bid<ask and bq+aq>0:
                    rows.append((str(date),date*86400+seconds,bid,ask,bq,aq))
        split=int(len(rows)*.8)
        model=fit(rows[:split],tick=.01,bins=10,spread_states=2)
        # Strict future-only three-second diagnostic, never used for fitting.
        test=rows[split:]
        times=[r[1] for r in test]
        errors={k:[] for k in ('mid','weighted','micro')}
        for r in test:
            target=bisect.bisect_left(times,r[1]+3)
            if target>=len(test) or test[target][0]!=r[0] or times[target]-r[1]>8:
                continue
            micro,_=predict(model,*r[2:])
            if micro is None:
                continue
            mid=(r[2]+r[3])/2
            weighted=(r[3]*r[4]+r[2]*r[5])/(r[4]+r[5])
            future=(test[target][2]+test[target][3])/2
            for k,p in [('mid',mid),('weighted',weighted),('micro',micro)]:
                errors[k].append(((p-future)/mid*10000)**2)
        reports.append(dict(symbol=name,sha256=hashlib.sha256(raw).hexdigest(),rows=len(rows),
                            train=len(rows[:split]),test=len(test),pairs=model['pairs'],
                            scored=len(errors['micro']),mse_bps2={k:float(np.mean(v)) if v else None for k,v in errors.items()},
                            model=model))
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(version=VERSION,reference=reports,
        note='Independent method check on author sample. Adapted discretization/full moves; not exact notebook or published results replication.'),indent=2)+'\n')
    print('Reference diagnostics:',output)
    for r in reports:
        print(r['symbol'],'scored',r['scored'],'MSE',r['mse_bps2'])


def setup(db):
    db.executescript(SCHEMA)


def calibrate(db,symbol,demo):
    rows=db.execute('SELECT session,received,bid,ask,bid_qty,ask_qty FROM quotes '
                    'WHERE symbol=? AND session LIKE ? ORDER BY received,id',
                    (symbol,'demo-%' if demo else 'live-%')).fetchall()
    # Freeze once on historical grid; forecasts must arrive strictly after train_end.
    model=fit(grid(rows))
    model.update(symbol=symbol,demo=demo,source_sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
    encoded=json.dumps(model,sort_keys=True)
    key=hashlib.sha256(encoded.encode()).hexdigest()[:16]
    with db:
        db.execute('INSERT OR IGNORE INTO shadow_model VALUES(?,?,?,?,?,?)',
                   (key,symbol,int(demo),time.time(),model['train_end'],encoded))
    return key,model


def shadow_step(db,key,model,now=None):
    now=time.time() if now is None else now
    row=db.execute('SELECT id,session,received,bid,ask,bid_qty,ask_qty FROM quotes '
                   'WHERE symbol=? AND session LIKE ? ORDER BY id DESC LIMIT 1',
                   (model['symbol'],'demo-%' if model['demo'] else 'live-%')).fetchone()
    status='WAITING FOR NEW DATA'
    with db:
        if row:
            qid,session,ts,bid,ask,bq,aq=row
            if 0<=now-ts<=5 and ts>model['train_end']:
                micro,reason=predict(model,bid,ask,bq,aq)
                mid=(bid+ask)/2
                weighted=(ask*bq+bid*aq)/(bq+aq)
                # At most one forecast per second; no retrospective backfill on restart.
                previous=db.execute('SELECT MAX(at) FROM shadow_forecast WHERE model_id=?',(key,)).fetchone()[0]
                if previous is None or ts-previous>=1:
                    db.execute('INSERT OR IGNORE INTO shadow_forecast VALUES(?,?,?,?,?,?,?,?)',
                               (key,qid,session,ts,mid,weighted,micro,reason))
                status=reason
            elif now-ts>5 or now<ts:
                status='STALE: NO NEW FORECASTS'
        # Resolve to the first quote at/after target, never across gaps/sessions.
        for qid,session,ts in db.execute('SELECT quote_id,session,at FROM shadow_forecast '
                                       'WHERE model_id=? AND at>=? AND at<=?',(key,now-180,now-3)).fetchall():
            for h in (3,15,60):
                if ts+h>now:
                    continue
                if db.execute('SELECT 1 FROM shadow_score WHERE model_id=? AND quote_id=? AND horizon=?',(key,qid,h)).fetchone():
                    continue
                target=db.execute('SELECT id,received,bid,ask FROM quotes WHERE session=? AND symbol=? '
                                  'AND received>=? AND received<=? ORDER BY received,id LIMIT 1',
                                  (session,model['symbol'],ts+h,ts+h+5)).fetchone()
                if not target:
                    continue
                stamps=[ts]+[r[0] for r in db.execute('SELECT received FROM quotes WHERE session=? AND symbol=? '
                                                     'AND received>? AND received<=? ORDER BY received,id',
                                                     (session,model['symbol'],ts,target[1]))]
                if any(b-a>5 for a,b in zip(stamps,stamps[1:])):
                    continue
                db.execute('INSERT OR IGNORE INTO shadow_score VALUES(?,?,?,?,?)',
                           (key,qid,h,(target[2]+target[3])/2,target[0]))
        db.execute('INSERT OR REPLACE INTO shadow_health VALUES(1,?,?)',(now,status))


def run_shadow(args):
    from .cli import connect
    db=connect(args.db);setup(db)
    try:
        row=db.execute('SELECT id,payload FROM shadow_model WHERE symbol=? AND demo=? ORDER BY fitted_at DESC LIMIT 1',
                       (args.symbol,int(args.demo))).fetchone()
        if row:
            key,encoded=row;model=json.loads(encoded)
        else:
            key,model=calibrate(db,args.symbol,args.demo)
        print('SHADOW ONLY model',key,'pairs',model['pairs'],'frozen at',model['train_end'],flush=True)
        deadline=time.monotonic()+args.seconds if args.seconds else float('inf')
        while time.monotonic()<deadline:
            shadow_step(db,key,model)
            time.sleep(1)
    finally:
        db.close()


def panel(db,symbol,demo):
    from rich.panel import Panel
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='shadow_model'").fetchone():
        return Panel('Run quant shadow to calibrate and start prospective monitoring.',title='MICRO-PRICE / SHADOW')
    row=db.execute('SELECT id,payload FROM shadow_model WHERE symbol=? AND demo=? ORDER BY fitted_at DESC LIMIT 1',
                   (symbol,int(demo))).fetchone()
    if not row:
        return Panel('No fitted model for this symbol/mode.',title='MICRO-PRICE / SHADOW')
    key,encoded=row;model=json.loads(encoded)
    health=db.execute('SELECT heartbeat,status FROM shadow_health WHERE id=1').fetchone()
    active=bool(health and 0<=time.time()-health[0]<4)
    text='Stoikov-style fitted state-transition estimator · model %s\n'%key
    text+='FROZEN TRAINING: %s transitions · prospective shadow only\n'%model['pairs']
    text+='WORKER %s · %s\n'%('ACTIVE' if active else 'STOPPED / STALE',health[1] if health else 'waiting')
    latest=db.execute('SELECT at,mid,weighted,micro,reason FROM shadow_forecast WHERE model_id=? ORDER BY at DESC LIMIT 1',(key,)).fetchone()
    if latest:
        ts,mid,weighted,micro,reason=latest
        text+='MID $%.4f | WEIGHTED $%.4f | FITTED %s\n'%(mid,weighted,'$%.4f'%micro if micro is not None else 'ABSTAIN')
        text+='FORECAST AGE %.1fs · %s\n'%(max(0,time.time()-ts),reason)
    text+='FORWARD MSE (bps²): horizon / n / midpoint / weighted / fitted\n'
    for h in (3,15,60):
        values=db.execute('SELECT f.mid,f.weighted,f.micro,s.target FROM shadow_score s JOIN shadow_forecast f '
                          'ON f.model_id=s.model_id AND f.quote_id=s.quote_id WHERE s.model_id=? AND s.horizon=? '
                          'AND f.micro IS NOT NULL',(key,h)).fetchall()
        if values:
            mse=[sum(((r[i]-r[3])/r[0]*10000)**2 for r in values)/len(values) for i in range(3)]
            text+='%2ss / %s / %.5f / %.5f / %.5f\n'%(h,len(values),*mse)
        else:
            text+='%2ss / waiting for matured forecasts\n'%h
    text+='No orders · no fixed-clock forecast implied by six moves · CatBoost remains offline.'
    return Panel(text,title='FITTED MICRO-PRICE / LIVE SHADOW',border_style='cyan')
