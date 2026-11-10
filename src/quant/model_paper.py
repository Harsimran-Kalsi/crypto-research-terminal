"""Isolated diagnostic paper account driven by the frozen research model.
No leverage, exchange credentials, or live order transport.
"""
import json
from pathlib import Path
import sqlite3
import time

from . import paper
from .microprice import predict

SCHEMA='''
CREATE TABLE IF NOT EXISTS model_runner (
 id INTEGER PRIMARY KEY CHECK(id=1), source_quote_id INTEGER NOT NULL DEFAULT 0,
 heartbeat REAL, model_id TEXT NOT NULL, source TEXT NOT NULL, reason TEXT NOT NULL,
 edge_bps REAL, forecast REAL);
'''


def initialize(db, source_path, key, model, fee_bps=40., delay=.5):
    source_path=str(Path(source_path).resolve())
    strategy=dict(name='microprice-diagnostic-v1',model_id=key,entry_edge_bps=0.,
                  source=source_path,description='Experimental execution probe; not cost-gated')
    paper.initialize(db,model['symbol'],model['demo'],fee_bps,delay,hold=15.,strategy=strategy)
    db.executescript(SCHEMA)
    with db:
        db.execute('INSERT OR IGNORE INTO model_runner(id,model_id,source,reason) VALUES(1,?,?,?)',
                   (key,source_path,'WAITING FOR FRESH SOURCE QUOTES'))


def tick(db, source, key, model, now=None):
    now=time.time() if now is None else now
    row=source.execute('SELECT id,session,received,bid,ask,bid_qty,ask_qty FROM quotes '
                       'WHERE symbol=? AND session LIKE ? ORDER BY id DESC LIMIT 1',
                       (model['symbol'],'demo-%' if model['demo'] else 'live-%')).fetchone()
    entry=False;edge=None;estimate=None
    reason='WAITING FOR QUOTES'
    if row:
        qid,session,ts,bid,ask,bq,aq=row
        runner=db.execute('SELECT source_quote_id FROM model_runner WHERE id=1').fetchone()[0]
        if qid>runner:
            with db:
                db.execute('INSERT INTO quotes(session,received,symbol,bid,ask,bid_qty,ask_qty) VALUES(?,?,?,?,?,?,?)',
                           (session,ts,model['symbol'],bid,ask,bq,aq))
                db.execute('UPDATE model_runner SET source_quote_id=? WHERE id=1',(qid,))
        if not 0<=now-ts<=5:
            reason='STALE FEED: NEW ENTRIES BLOCKED'
        elif ts<=model['train_end']:
            reason='WAITING FOR POST-TRAINING QUOTES'
        else:
            estimate,reason=predict(model,bid,ask,bq,aq)
            if estimate is not None:
                edge=(estimate/ask-1)*10000
                entry=edge>0.
                reason='SIGNAL: PAPER ENTRY ELIGIBLE' if entry else 'WAIT: ESTIMATE NOT ABOVE ASK'
    # The existing engine applies delay, fresh post-signal fills, liquidity, fees,
    # persistence and loss limits. Its database is separate from research data.
    paper.step(db,now,entry_signal=entry)
    with db:
        db.execute('UPDATE model_runner SET heartbeat=?,reason=?,edge_bps=?,forecast=? WHERE id=1',
                   (now,reason,edge,estimate))


def run(args):
    from .cli import connect
    if Path(args.db).resolve()==Path(args.account_db).resolve():
        raise ValueError('Use a separate account database to preserve research isolation')
    source=sqlite3.connect(Path(args.db).resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    db=connect(args.account_db)
    try:
        row=source.execute('SELECT id,payload FROM shadow_model WHERE symbol=? AND demo=? ORDER BY fitted_at DESC LIMIT 1',
                           (args.symbol,int(args.demo))).fetchone()
        if not row:
            raise ValueError('Start quant shadow first to calibrate a model')
        key,payload=row;model=json.loads(payload)
        initialize(db,args.db,key,model,args.fee_bps,args.delay)
        print('MODEL PAPER ONLY · frozen model %s · $100 cash / $10 notional / 15s hold / no leverage'%key,flush=True)
        print('Diagnostic entries are not fee-gated. Research predictions remain independent.',flush=True)
        deadline=time.monotonic()+args.seconds if args.seconds else float('inf')
        while time.monotonic()<deadline:
            tick(db,source,key,model)
            time.sleep(.2)
    finally:
        db.close();source.close()


def panels(path,symbol,demo):
    from rich.console import Group
    from rich.columns import Columns
    from rich.panel import Panel
    from rich.table import Table
    from .charts import chart
    if not Path(path).exists():
        return Panel('Start quant model-paper to run simulated trades alongside research.',title='MODEL PAPER / NO REAL MONEY')
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='model_runner'").fetchone():
            return Panel('Model-paper account is not initialized.',title='MODEL PAPER')
        a=paper.account(db);c=json.loads(a['config'])
        if c['symbol']!=symbol or c['demo']!=demo:
            return Panel('Paper account belongs to a different symbol or data mode.',title='MODEL PAPER')
        heartbeat,reason,edge,forecast=db.execute('SELECT heartbeat,reason,edge_bps,forecast FROM model_runner WHERE id=1').fetchone()
        fresh=heartbeat is not None and 0<=time.time()-heartbeat<3
        quote=db.execute('SELECT received,bid,ask FROM quotes ORDER BY id DESC LIMIT 1').fetchone()
        bid=quote[1] if quote else 0
        mark=a['qty']*bid*(1-c['fee_bps']/10000)
        equity=a['cash']+mark
        unreal=mark-a['cost'] if a['qty'] else 0
        held=max(0,(quote[0]-a['entered'])) if quote and a['entered'] else 0
        text=('EQUITY $%.4f   NET %+.4f   REALIZED %+.4f   UNREALIZED %+.4f\n'
              'CASH $%.4f   FEES $%.4f   POSITION %.8f BTC   HELD %.1fs\n'
              '%s · %s\n%s\n'
              'Estimate above ask: %s | round-trip fee assumption: %.1f bps\n'
              'UNVALIDATED DIAGNOSTIC · $10 trades · 15s hold · %.1f bps/side · no leverage' %
              (equity,equity-c['initial'],a['realized'],unreal,a['cash'],a['fees'],a['qty'],held,
               'ACTIVE' if fresh else 'STOPPED / STALE',a['status'],reason,
               '%+.3f bps'%edge if edge is not None else 'unavailable',2*c['fee_bps'],c['fee_bps']))
        if quote and time.time()-quote[0]>5:
            text+='\nSTALE PRICE: equity is marked at last available quote.'
        points=db.execute('SELECT at,equity FROM paper_equity ORDER BY quote_id DESC LIMIT 3000').fetchall()[::-1]
        fills=db.execute('SELECT at,side,price,qty,fee,net_pnl FROM paper_fills ORDER BY id DESC LIMIT 8').fetchall()
        pricepoints=db.execute('SELECT received,(bid+ask)/2 FROM quotes ORDER BY id DESC LIMIT 3000').fetchall()[::-1]
        # Plot fill markers at contemporaneous midpoint so they stay on the price scale.
        markers=[]
        for t,side,price,*_ in fills:
            q=db.execute('SELECT (bid+ask)/2 FROM quotes WHERE received<=? ORDER BY id DESC LIMIT 1',(t,)).fetchone()
            if q:markers.append((t,q[0],side))
        tape=Table(expand=True,box=None)
        for column in ('UTC','SIDE','FILL','SIZE','FEE','NET CLOSED'):tape.add_column(column)
        from datetime import datetime,timezone
        for t,side,price,qty,fee,pnl in fills:
            tape.add_row(datetime.fromtimestamp(t,timezone.utc).strftime('%H:%M:%S'),
                         '[green]BUY[/green]' if side=='BUY' else '[red]SELL[/red]',
                         '%.2f'%price,'%.8f'%qty,'$%.4f'%fee,'%+.4f'%pnl if pnl is not None else '—')
        if not fills:tape.add_row('—','WAITING','No fills yet','—','—','—')
        return Group(Panel(text,title='MODEL PAPER / SIMULATED MONEY',border_style='yellow'),
                     Columns([Panel(chart(pricepoints,markers,width=40,height=4),title='PRICE / 3 MIN / B BUY / S SELL',border_style='cyan'),
                              Panel(chart(points,width=40,height=4),title='EQUITY / AFTER COSTS / 3 MIN',border_style='green')],equal=True,expand=True),
                     Panel(tape,title='PAPER EXECUTIONS / NEWEST FIRST',border_style='dim'))
    finally:
        db.close()
