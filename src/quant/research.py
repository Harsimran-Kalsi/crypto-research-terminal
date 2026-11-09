"""Paper-inspired adaptation v1. Read-only snapshots; never changes a trading account."""
import bisect
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import time

VERSION = 'microstructure-v1'
HORIZONS = (3, 15, 60)
FEATURES = ('imbalance', 'spread_bps', 'microprice_offset_bps', 'momentum_5s_bps',
            'volatility_30s_bps', 'signed_volume_10s', 'trade_imbalance_10s',
            'buy_vwap_offset_bps', 'sell_vwap_offset_bps', 'buy_present', 'sell_present')


def snapshot(path):
    source = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
    db = sqlite3.connect(':memory:')
    source.backup(db)
    source.close()
    return db


def load(db, symbol, demo=False):
    prefix = 'demo-%' if demo else 'live-%'
    quotes = db.execute('SELECT session,received,bid,ask,bid_qty,ask_qty FROM quotes '
                        'WHERE symbol=? AND session LIKE ? ORDER BY received,id', (symbol, prefix)).fetchall()
    trades = defaultdict(list)
    seen = set()
    audit = dict(raw_quotes=len(quotes), updates=0, duplicate_trades=0, snapshots_excluded=0,
                 trade_id_gaps=0, invalid_trades=0)
    previous = {}
    for session, received, payload in db.execute('SELECT session,received,payload FROM events '
                                                "WHERE channel='trade' AND session LIKE ? ORDER BY received,id", (prefix,)):
        message = json.loads(payload)
        if message.get('type') != 'update':
            audit['snapshots_excluded'] += 1
            continue
        for trade in message.get('data', []):
            if trade.get('symbol') != symbol:
                continue
            key = (symbol, trade['trade_id'])
            if key in seen:
                audit['duplicate_trades'] += 1
                continue
            seen.add(key)
            qty, price, side = trade.get('qty'), trade.get('price'), trade.get('side')
            if (side not in ('buy', 'sell') or not isinstance(qty, (int,float))
                    or not isinstance(price, (int,float)) or not math.isfinite(qty)
                    or not math.isfinite(price) or min(qty,price) <= 0):
                audit['invalid_trades'] += 1
                continue
            last = previous.get(session)
            if last is not None and trade['trade_id'] != last+1:
                audit['trade_id_gaps'] += 1
            previous[session] = trade['trade_id']
            trades[session].append((received, price, qty, side))
            audit['updates'] += 1
    return quotes, trades, audit


def build(quotes, trades):
    """As-of receipt-time, 1s grid. All inputs <= decision time; labels never cross gaps."""
    groups = []
    for q in quotes:
        if (not groups or q[0] != groups[-1][-1][0] or q[1]-groups[-1][-1][1] > 5
                or q[1] < groups[-1][-1][1]):
            groups.append([])
        groups[-1].append(q)
    rows = []
    for group in groups:
        if group[-1][1]-group[0][1] < 91:
            continue
        qt = [q[1] for q in group]
        ts = trades.get(group[0][0], [])
        tt = [x[0] for x in ts]
        # A complete 30-second trailing window is required after every boundary.
        for t in range(math.ceil(qt[0])+30, math.floor(qt[-1])-60+1):
            qi = bisect.bisect_right(qt,t)-1
            q = group[qi]
            _, received, bid, ask, bq, aq = q
            if not (0 <= t-received <= 5 and 0 < bid <= ask and bq+aq > 0):
                continue
            mid = (bid+ask)/2
            past = []
            for offset in range(31):
                idx = bisect.bisect_right(qt,t-30+offset)-1
                if idx < 0 or t-30+offset-qt[idx] > 5:
                    break
                past.append((group[idx][2]+group[idx][3])/2)
            if len(past) != 31:
                continue
            start, end = bisect.bisect_right(tt,t-10), bisect.bisect_right(tt,t)
            recent = ts[start:end]
            buy = [(p,v) for _,p,v,s in recent if s == 'buy']
            sell = [(p,v) for _,p,v,s in recent if s == 'sell']
            bv, sv = sum(v for _,v in buy), sum(v for _,v in sell)
            def vwap_offset(items, total):
                return ((sum(p*v for p,v in items)/total)/mid-1)*10000 if total else 0.
            changes = [math.log(b/a)*10000 for a,b in zip(past,past[1:])]
            values = [(bq-aq)/(bq+aq), (ask-bid)/mid*10000,
                      (((ask*bq+bid*aq)/(bq+aq))/mid-1)*10000,
                      math.log(mid/past[-6])*10000, statistics.pstdev(changes),
                      bv-sv, (bv-sv)/(bv+sv) if bv+sv else 0.,
                      vwap_offset(buy,bv), vwap_offset(sell,sv), float(bv>0), float(sv>0)]
            labels = {}
            for h in HORIZONS:
                idx = bisect.bisect_right(qt,t+h)-1
                future = group[idx]
                if t+h-future[1] > 5:
                    break
                labels[h] = math.log(((future[2]+future[3])/2)/mid)*10000
            if len(labels)==len(HORIZONS):
                rows.append(dict(session=q[0], t=t, mid=mid, x=values, y=labels))
    return rows


def folds(rows):
    """Final 20% by wall-clock time sealed. Three expanding development folds."""
    if not rows:
        return [], None
    start, end = rows[0]['t'], rows[-1]['t']
    sealed = start + .8*(end-start)
    width = (sealed-start)/4
    result = []
    for k in range(1,4):
        boundary = start+k*width
        stop = start+(k+1)*width
        train = [i for i,r in enumerate(rows) if r['t']+60 < boundary]
        valid = [i for i,r in enumerate(rows) if boundary <= r['t'] and r['t']+60 < stop]
        result.append((train,valid))
    return result, sealed


def metric(y, pred):
    import numpy as np
    y, pred = np.asarray(y), np.asarray(pred)
    active = y != 0
    return dict(n=len(y), mse_bps2=float(np.mean((y-pred)**2)),
                direction_accuracy_nonzero=float(np.mean(np.sign(y[active])==np.sign(pred[active]))) if active.any() else None,
                zero_return_fraction=float(np.mean(~active)))


def execution(rows, predictions, quotes, horizon, delay, fee_bps, end_time=float('inf')):
    """Long-only fixed-horizon independent trials. No portfolio/leverage inference."""
    by_session = defaultdict(list)
    for q in quotes:
        by_session[q[0]].append(q)
    clocks = {s:[q[1] for q in qs] for s,qs in by_session.items()}
    outcomes, busy_until = [], -float('inf')
    skipped = 0
    for row, pred in zip(rows,predictions):
        if row['t'] <= busy_until or pred <= row['x'][1]+2*fee_bps:
            continue
        qs, clock = by_session[row['session']], clocks[row['session']]
        # First observed quote at/after each arrival, within a 5-second tolerance.
        i = bisect.bisect_left(clock, row['t']+delay)
        if i >= len(qs) or clock[i]-(row['t']+delay)>5:
            skipped += 1
            continue
        j = bisect.bisect_left(clock,clock[i]+horizon+delay)
        if j >= len(qs) or clock[j] >= end_time or clock[j]-(clock[i]+horizon+delay)>5:
            skipped += 1
            continue
        if any(b-a>5 for a,b in zip(clock[i:j],clock[i+1:j+1])):
            skipped += 1
            continue
        qty = 10/qs[i][3]
        if qty>qs[i][5] or qty>qs[j][4]:
            skipped += 1
            continue
        gross = qs[j][2]/qs[i][3]
        net = (gross*(1-fee_bps/10000)-(1+fee_bps/10000))*10000
        outcomes.append(net)
        busy_until = clock[j]
    return dict(trades=len(outcomes), skipped_unfillable=skipped,
                mean_net_bps=statistics.mean(outcomes) if outcomes else None,
                sum_net_dollars_10_notional=sum(outcomes)*.001,
                note='Fixed $10 non-overlapping trials; no equity-curve or significance claim.')


def run(args):
    import numpy as np
    from catboost import CatBoostRegressor
    import catboost
    db = snapshot(args.db)
    quotes, trades, audit = load(db,args.symbol,args.demo)
    rows = build(quotes,trades)
    split, sealed = folds(rows)
    settings = dict(version=VERSION,symbol=args.symbol,demo=args.demo,horizons=HORIZONS,
                    features=FEATURES,window_seconds=10,quote_max_age=5,seed=42,
                    catboost=dict(iterations=200,depth=4,learning_rate=.03,l2_leaf_reg=5),
                    fees_bps=[0,10,40,80],delays=[0,.5,1],final_fraction=.2)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    settings['implementation_sha256'] = source_hash
    digest = hashlib.sha256(json.dumps([settings,quotes,dict(trades),audit],sort_keys=True).encode()).hexdigest()
    out = Path(args.output)/digest[:16]
    out.mkdir(parents=True,exist_ok=True)
    # Refuse silent overwriting: a repeated run returns the existing immutable result.
    if (out/'report.json').exists():
        db.close()
        print('Existing identical experiment:',out)
        return
    frozen = sqlite3.connect(str(out/'snapshot.sqlite3'))
    db.backup(frozen)
    # Standalone artifact: no WAL sidecars or write permissions needed to replay.
    frozen.execute('PRAGMA journal_mode=DELETE')
    frozen.close()
    db.close()
    (out/'implementation.py').write_bytes(Path(__file__).read_bytes())
    report = dict(settings=settings,dataset_sha256=digest,audit=audit,samples=len(rows),
                  reserved_test_starts=sealed,created_utc_epoch=time.time(),
                  packages=dict(numpy=np.__version__,catboost=catboost.__version__),
                  status='DIAGNOSTIC ONLY — not validated for deployment',folds=[],
                  limitations=['Paper-inspired spot adaptation, not exact reproduction.',
                               'Local receipt time; no measured exchange latency.',
                               'No statistical significance or profitability conclusion.',
                               'Final 20% sealed; labels purged by 60 seconds at all boundaries.',
                               'Execution trials are not a full portfolio simulator.'])
    if audit['trade_id_gaps'] or audit['invalid_trades']:
        report['status']='BLOCKED: trade stream integrity audit failed'
        split=[]
    predictions = []
    for fold,(train,valid) in enumerate(split,1):
        item=dict(fold=fold,train=len(train),validation=len(valid),results=[])
        report['folds'].append(item)
        if len(train)<100 or len(valid)<30:
            item['status']='INSUFFICIENT DATA (minimum 100 train / 30 validation; smoke thresholds only)'
            continue
        x=np.asarray([r['x'] for r in rows])
        for h in HORIZONS:
            y=np.asarray([r['y'][h] for r in rows])
            # Price-only ablation removes all size and trade-flow inputs.
            for name,cols in [('price_only',[1,3,4]),('full',list(range(len(FEATURES))))]:
                model=CatBoostRegressor(**settings['catboost'],random_seed=42,
                                       loss_function='RMSE',verbose=False,thread_count=2,
                                       allow_writing_files=False)
                model.fit(x[train][:,cols],y[train])
                pred=model.predict(x[valid][:,cols])
                result=dict(horizon=h,model=name,metrics=metric(y[valid],pred),execution=[])
                for delay in settings['delays']:
                    for fee in settings['fees_bps']:
                        result['execution'].append(dict(delay=delay,fee_bps=fee,**execution(
                            [rows[i] for i in valid],pred,quotes,h,delay,fee,
                            end_time=min(sealed,max(rows[i]['t'] for i in valid)+60))))
                item['results'].append(result)
                model.save_model(str(out/('fold%s_h%s_%s.cbm'%(fold,h,name))))
                for i,p in zip(valid,pred):
                    predictions.append([fold,h,name,rows[i]['t'],float(p),float(y[i])])
            item['results'].append(dict(horizon=h,model='zero',metrics=metric(y[valid],np.zeros(len(valid)))))
            item['results'].append(dict(horizon=h,model='train_mean',metrics=metric(y[valid],np.full(len(valid),float(y[train].mean())))))
    with (out/'predictions.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['fold','horizon','model','decision_time','prediction_bps','actual_bps']);writer.writerows(predictions)
    # Export development rows only; sealed labels are never persisted or scored.
    with (out/'development.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['time','session',*FEATURES,*['target_%ss_bps'%h for h in HORIZONS]])
        for r in rows:
            if r['t']+60 < sealed:
                writer.writerow([r['t'],r['session'],*r['x'],*[r['y'][h] for h in HORIZONS]])
    (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    lines=['# Microstructure adaptation diagnostic','',report['status'],'',
           'Dataset fingerprint: `'+digest+'`','', 'Samples: %s. Final 20%% is reserved and unscored.'%len(rows),'',
           '| Fold | Horizon | Model | N | MSE (bps²) |','|---|---|---|---|---|']
    for f in report['folds']:
        for r in f['results']:
            lines.append('| %s | %ss | %s | %s | %.6f |'%(f['fold'],r['horizon'],r['model'],r['metrics']['n'],r['metrics']['mse_bps2']))
    lines += ['', 'Execution scenarios, source audit, parameters and limitations: see report.json.',
              'These results must not be used to select a live strategy.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print('Research artifacts:',out)
    print('Samples:',len(rows),'|',report['status'])
    for f in report['folds']:
        print('Fold',f['fold'],'train',f['train'],'validation',f['validation'],f.get('status','completed'))
