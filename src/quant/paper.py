"""Persistent long-only paper broker. Never submits exchange orders."""
import json
import math
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS paper_account (
 id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL,
 cash REAL NOT NULL, qty REAL NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
 entered REAL, realized REAL NOT NULL DEFAULT 0, fees REAL NOT NULL DEFAULT 0,
 pending TEXT, due REAL, signal_id INTEGER, last_id INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'WAITING', heartbeat REAL);
CREATE TABLE IF NOT EXISTS paper_fills (
 id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL, at REAL NOT NULL,
 side TEXT NOT NULL, price REAL NOT NULL, qty REAL NOT NULL, fee REAL NOT NULL,
 net_pnl REAL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_control (
 id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL, original_config TEXT);
'''


def initialize(db, symbol='BTC/USD', demo=False, fee_bps=40., delay=.5):
    if not (math.isfinite(fee_bps) and 0 <= fee_bps <= 1000
            and math.isfinite(delay) and 0 <= delay <= 60):
        raise ValueError('Fee must be 0..1000 bps and delay 0..60 seconds')
    db.executescript(SCHEMA)
    config = dict(symbol=symbol, demo=demo, fee_bps=fee_bps, delay=delay,
                  initial=100., notional=10., hold=60., threshold=.4, loss_limit=3.)
    encoded = json.dumps(config, sort_keys=True)
    with db:
        db.execute('INSERT OR IGNORE INTO paper_control VALUES(1,0,NULL)')
        original = db.execute('SELECT original_config FROM paper_control WHERE id=1').fetchone()[0]
        if original:
            # Retire the temporary entry block used by the already-running v0 worker.
            db.execute('UPDATE paper_account SET config=? WHERE id=1', (original,))
            db.execute('UPDATE paper_control SET original_config=NULL WHERE id=1')
        row = db.execute('SELECT config FROM paper_account').fetchone()
        if row and row[0] != encoded:
            raise ValueError('Account settings differ. Resume with original settings or use a separate database.')
        db.execute('INSERT OR IGNORE INTO paper_account(id,config,cash) VALUES(1,?,100)', (encoded,))


def account(db):
    cur = db.execute('SELECT * FROM paper_account WHERE id=1')
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row)) if row else None


def step(db, now=None):
    now = time.time() if now is None else now
    # Serialize workers: state transition and fill are committed atomically.
    db.execute('BEGIN IMMEDIATE')
    try:
        a = account(db)
        c = json.loads(a['config'])
        paused = db.execute('SELECT paused FROM paper_control WHERE id=1').fetchone()[0]
        row = db.execute('SELECT id,received,bid,ask,bid_qty,ask_qty FROM quotes '
                         'WHERE symbol=? AND session LIKE ? ORDER BY id DESC LIMIT 1',
                         (c['symbol'], 'demo-%' if c['demo'] else 'live-%')).fetchone()
        status = 'WAITING FOR QUOTES'
        if row:
            qid, ts, bid, ask, bq, aq = row
            fresh = 0 <= now-ts <= 5
            fee_rate = c['fee_bps']/10000
            equity = a['cash'] + a['qty']*bid*(1-fee_rate)
            halted = equity <= c['initial']-c['loss_limit']
            status = 'STALE: EXITS WAIT FOR FRESH QUOTES' if a['qty'] else 'STALE: ENTRIES BLOCKED'
            if not fresh:
                if a['pending'] == 'BUY':
                    a['pending'], a['due'] = None, None
            else:
                status = 'HOLDING' if a['qty'] else ('PAUSED: BASELINE RETIRED' if paused else ('LOSS LIMIT: ENTRIES HALTED' if halted else 'WAIT: IMBALANCE < +0.40'))
                if (halted or paused) and a['pending'] == 'BUY':
                    a['pending'], a['due'] = None, None
                if a['pending'] and now >= a['due'] and qid > a['signal_id'] and ts >= a['due']:
                    side = a['pending']
                    if side == 'BUY' and not a['qty'] and not halted and not paused:
                        notional = min(c['notional'], a['cash']/(1+fee_rate))
                        qty = notional/ask
                        if qty <= aq and notional > 0:
                            fee = notional*fee_rate
                            a['cash'] -= notional+fee
                            a['qty'], a['cost'], a['entered'] = qty, notional+fee, ts
                            a['fees'] += fee
                            db.execute('INSERT INTO paper_fills(quote_id,at,side,price,qty,fee,reason) VALUES(?,?,?,?,?,?,?)',
                                       (qid, ts, side, ask, qty, fee, 'imbalance baseline'))
                            status = 'PAPER BUY FILLED'
                        else:
                            status = 'BUY CANCELLED: INSUFFICIENT DISPLAYED SIZE'
                        a['pending'], a['due'] = None, None
                    elif side == 'SELL' and a['qty']:
                        if a['qty'] <= bq:
                            proceeds = a['qty']*bid
                            fee = proceeds*fee_rate
                            pnl = proceeds-fee-a['cost']
                            db.execute('INSERT INTO paper_fills(quote_id,at,side,price,qty,fee,net_pnl,reason) VALUES(?,?,?,?,?,?,?,?)',
                                       (qid, ts, side, bid, a['qty'], fee, pnl, 'time exit or account loss limit'))
                            a['cash'] += proceeds-fee
                            a['realized'] += pnl
                            a['fees'] += fee
                            a['qty'], a['cost'], a['entered'] = 0., 0., None
                            a['pending'], a['due'] = None, None
                            status = 'PAPER SELL FILLED'
                        else:
                            status = 'EXIT WAIT: INSUFFICIENT DISPLAYED SIZE'
                # Never re-enter on the quote used for an exit; process signals once.
                elif not a['pending'] and qid > a['last_id']:
                    if a['qty'] and (ts-a['entered'] >= c['hold'] or halted):
                        a['pending'], a['due'], a['signal_id'] = 'SELL', now+c['delay'], qid
                        status = 'EXIT PENDING'
                    elif not a['qty'] and not halted and not paused and (bq-aq)/(bq+aq) >= c['threshold']:
                        a['pending'], a['due'], a['signal_id'] = 'BUY', now+c['delay'], qid
                        status = 'ENTRY PENDING'
                if a['pending'] and status.startswith(('WAIT:', 'HOLDING')):
                    status = a['pending'] + ' PENDING: WAITING FOR POST-DELAY QUOTE'
            a['last_id'] = max(a['last_id'], qid)
        a['status'], a['heartbeat'] = status, now
        fields = ['cash','qty','cost','entered','realized','fees','pending','due','signal_id','last_id','status','heartbeat']
        db.execute('UPDATE paper_account SET '+','.join(k+'=?' for k in fields)+' WHERE id=1', [a[k] for k in fields])
        db.commit()
    except BaseException:
        db.rollback()
        raise


def run(args):
    from .cli import connect
    db = connect(args.db)
    try:
        initialize(db, args.symbol, args.demo, args.fee_bps, args.delay)
        print('PAPER ONLY: $100 account / $10 position / 60s hold. Ctrl+C stops worker; positions persist.', flush=True)
        deadline = time.monotonic()+args.seconds if args.seconds else float('inf')
        while time.monotonic() < deadline:
            step(db)
            time.sleep(.1)
    finally:
        db.close()


def panel(db, bid, now, symbol, demo):
    from rich.panel import Panel
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='paper_account'").fetchone()
    a = account(db) if exists else None
    if not a:
        return Panel('Paper engine not started. Run quant paper in another terminal.', title='PAPER ACCOUNT', border_style='yellow')
    c = json.loads(a['config'])
    if c['symbol'] != symbol or c['demo'] != demo:
        return Panel('Paper account belongs to a different symbol/data mode. Use its matching viewer.', title='PAPER ACCOUNT')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='paper_control'").fetchone():
        control = db.execute('SELECT paused FROM paper_control WHERE id=1').fetchone()
        if control and control[0] and not a['qty']:
            return Panel('Original imbalance baseline retired · historical net P&L %+.4f · fees $%.4f\n'
                         'Account history retained. No strategy trades in research shadow mode.' %
                         (a['realized'],a['fees']), title='ARCHIVED PAPER BASELINE',border_style='dim')
    marked = a['qty']*bid*(1-c['fee_bps']/10000)
    unrealized = marked-a['cost'] if a['qty'] else 0
    age = now-(a['heartbeat'] or 0)
    text = ('EQUITY $%.4f   NET P&L %+.4f   CASH $%.4f\n'
            'REALIZED %+.4f   UNREALIZED %+.4f   FEES $%.4f\n'
            'POSITION %.8f   %s\n'
            'ENGINE %s | fee %.1f bps/side · delay %.2fs · UNVALIDATED BASELINE' %
            (a['cash']+marked, a['cash']+marked-c['initial'], a['cash'], a['realized'],
             unrealized, a['fees'], a['qty'], a['status'],
             'ACTIVE' if 0 <= age < 3 else 'STOPPED / STALE', c['fee_bps'], c['delay']))
    fills = db.execute('SELECT side,price,net_pnl FROM paper_fills ORDER BY id DESC LIMIT 3').fetchall()
    for side, price, pnl in fills:
        text += '\n%s @ %.2f%s' % (side, price, ' · net %+.4f' % pnl if pnl is not None else '')
    return Panel(text, title='PAPER ACCOUNT / LIQUIDATION-VALUE MARK', border_style='yellow')
