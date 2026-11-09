import argparse
import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sqlite3
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, session TEXT NOT NULL, received REAL NOT NULL,
 channel TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes (
 id INTEGER PRIMARY KEY, session TEXT NOT NULL, received REAL NOT NULL,
 symbol TEXT NOT NULL, bid REAL NOT NULL, ask REAL NOT NULL,
 bid_qty REAL NOT NULL, ask_qty REAL NOT NULL);
CREATE INDEX IF NOT EXISTS quotes_time ON quotes(received);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(SCHEMA)
    return db


def valid_quote(q):
    values = [q[k] for k in ('bid', 'ask', 'bid_qty', 'ask_qty')]
    return (all(math.isfinite(float(v)) for v in values)
            and 0 < q['bid'] <= q['ask'] and min(q['bid_qty'], q['ask_qty']) >= 0
            and q['bid_qty'] + q['ask_qty'] > 0)


def record(db, session, message, received):
    """Raw messages and parsed quotes commit together; receive time is local UTC epoch."""
    channel = message.get('channel', message.get('method', 'system'))
    with db:
        db.execute('INSERT INTO events(session,received,channel,payload) VALUES(?,?,?,?)',
                   (session, received, channel, json.dumps(message)))
        if channel == 'ticker':
            for q in message.get('data', []):
                if valid_quote(q):
                    db.execute('INSERT INTO quotes(session,received,symbol,bid,ask,bid_qty,ask_qty) '
                               'VALUES(?,?,?,?,?,?,?)',
                               (session, received, q['symbol'], q['bid'], q['ask'],
                                q['bid_qty'], q['ask_qty']))


async def collect(args):
    import websockets
    db = connect(args.db)
    session = ('demo-' if args.demo else 'live-') + str(uuid.uuid4())
    with db:
        db.execute('INSERT INTO events(session,received,channel,payload) VALUES(?,?,?,?)',
                   (session, time.time(), 'manifest', json.dumps({
                       'mode': 'synthetic' if args.demo else 'live', 'symbol': args.symbol,
                       'version': '0.1.0', 'source': 'synthetic' if args.demo else 'Kraken websocket v2',
                       'note': 'Local receipt timestamps; no exchange latency measurement.'})))
    print('Recording %s to %s; Ctrl+C stops collector. No trading.' % (session, args.db), flush=True)
    deadline = time.monotonic() + args.seconds if args.seconds else float('inf')
    rng = random.Random(42)
    mid, backoff = 70000.0, 1
    try:
        while time.monotonic() < deadline:
            if args.demo:
                mid *= 1 + rng.gauss(0, 0.00003)
                record(db, session, {'channel': 'ticker', 'data': [{
                    'symbol': args.symbol, 'bid': mid - 0.5, 'ask': mid + 0.5,
                    'bid_qty': rng.uniform(.1, 3), 'ask_qty': rng.uniform(.1, 3)}]}, time.time())
                await asyncio.sleep(.25)
                continue
            try:
                async with websockets.connect('wss://ws.kraken.com/v2', open_timeout=15,
                                              ping_interval=20, ping_timeout=20) as ws:
                    for channel in ('ticker', 'trade'):
                        params = {'channel': channel, 'symbol': [args.symbol], 'snapshot': True}
                        if channel == 'ticker':
                            params['event_trigger'] = 'bbo'
                        await ws.send(json.dumps({'method': 'subscribe', 'params': params}))
                    while time.monotonic() < deadline:
                        remaining = deadline - time.monotonic()
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(30, remaining))
                        message = json.loads(raw)
                        record(db, session, message, time.time())
                        if message.get('success') is False:
                            raise ValueError('Subscription rejected: ' + str(message.get('error')))
                        if message.get('channel') == 'ticker':
                            backoff = 1
            except ValueError:
                raise
            except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as exc:
                if time.monotonic() >= deadline:
                    break
                record(db, session, {'channel': 'disconnect', 'error': type(exc).__name__ + ': ' + str(exc)}, time.time())
                print('Feed interrupted; retrying in %ss: %s' % (backoff, exc), flush=True)
                await asyncio.sleep(min(backoff, max(0, deadline - time.monotonic())))
                backoff = min(backoff * 2, 30)
                # A new session excludes disconnected intervals from research labels.
                session = 'live-' + str(uuid.uuid4())
    finally:
        db.close()


def spark(values, width=74):
    values = list(values)[-width:]
    if not values:
        return 'Waiting for recorded quotes'
    low, high = min(values), max(values)
    return ''.join('▁▂▃▄▅▆▇█'[min(7, int((v-low)/(high-low or 1)*7))] for v in values)


def screen(db, symbol):
    from .paper import panel
    from .microprice import panel as shadow_panel
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    rows = db.execute('SELECT session,received,bid,ask,bid_qty,ask_qty FROM quotes '
                      'WHERE symbol=? ORDER BY id DESC LIMIT 160', (symbol,)).fetchall()
    if not rows:
        return Panel('Run quant collect in another terminal.\nNo data yet.', title='QUANT / OBSERVATORY')
    session, ts, bid, ask, bq, aq = rows[0]
    age, mid = max(0, time.time()-ts), (bid+ask)/2
    demo = session.startswith('demo-')
    status = 'STALE' if age > 5 else 'FRESH'
    color = 'red' if age > 5 else 'cyan'
    metrics = Table.grid(expand=True, padding=(0, 3))
    metrics.add_row('MID PRICE', 'SPREAD', 'QUOTE AGE', 'TOP-OF-BOOK IMBALANCE')
    metrics.add_row('$%s' % format(mid, ',.2f'), '%.3f bps' % ((ask-bid)/mid*10000),
                    '%.2fs' % age, '%+.3f' % ((bq-aq)/(bq+aq)))
    chart = spark([(r[2]+r[3])/2 for r in reversed(rows) if r[0] == session])
    tape = Table(expand=True, box=None)
    tape.add_column('UTC', style='dim'); tape.add_column('CHANNEL', style='cyan'); tape.add_column('EVENT')
    events = db.execute('SELECT received,channel,payload FROM events ORDER BY id DESC LIMIT 9').fetchall()
    for received, channel, payload in events:
        m = json.loads(payload)
        detail = m.get('error') or ('%s record(s)' % len(m['data']) if 'data' in m else payload[:95])
        tape.add_row(datetime.fromtimestamp(received, timezone.utc).strftime('%H:%M:%S'), channel, str(detail))
    return Group(
        Panel(Text('QUANT / OBSERVATORY     %s     %s     %s' %
                   (symbol, 'SYNTHETIC DEMO' if demo else 'LIVE MARKET DATA', status), style=color),
              subtitle='RESEARCH ONLY · NO ORDERS · Ctrl+C closes viewer'),
        Panel(metrics, title='MARKET TELEMETRY', border_style='cyan'),
        Panel(Text(chart, style='cyan'), title='MID PRICE / LAST 160 QUOTE EVENTS', border_style='dim'),
        shadow_panel(db, symbol, demo),
        panel(db, bid, time.time(), symbol, demo),
        Panel(tape, title='EVENT JOURNAL', border_style='dim'))


def watch(args):
    from rich.live import Live
    db = connect(args.db)
    try:
        if args.once:
            from rich.console import Console
            Console().print(screen(db, args.symbol))
        else:
            with Live(screen(db, args.symbol), refresh_per_second=4, screen=True) as live:
                while True:
                    live.update(screen(db, args.symbol))
                    time.sleep(.25)
    finally:
        db.close()


def samples(rows, horizon=60, max_gap=5):
    """Non-overlapping labels within uninterrupted sessions. No interpolation over gaps."""
    result, i = [], 0
    while i < len(rows):
        session, t, bid, ask, bq, aq = rows[i]
        j = i + 1
        while j < len(rows) and rows[j][1] < t + horizon:
            if rows[j][0] != session or rows[j][1] - rows[j-1][1] > max_gap:
                break
            j += 1
        if (j < len(rows) and rows[j][0] == session
                and rows[j][1] >= t+horizon and rows[j][1]-(t+horizon) <= max_gap
                and rows[j][1]-rows[j-1][1] <= max_gap):
            future = (rows[j][2]+rows[j][3])/2
            result.append(((bq-aq)/(bq+aq), (future/((bid+ask)/2)-1)*10000))
            i = j
        else:
            i += 1
    return result


def evaluate(args):
    db = connect(args.db)
    rows = db.execute('SELECT session,received,bid,ask,bid_qty,ask_qty FROM quotes '
                      'WHERE symbol=? AND session LIKE ? ORDER BY received,id',
                      (args.symbol, 'demo-%' if args.demo else 'live-%')).fetchall()
    db.close()
    data = samples(rows)
    print('H1 BASELINE DIAGNOSTIC | %s | %s' % (args.symbol, 'SYNTHETIC' if args.demo else 'LIVE'))
    print('Non-overlapping 60s labels: %s. Maximum permitted quote gap: 5s.' % len(data))
    if len(data) < 30:
        print('Insufficient evidence. Collect more data; minimum 30 labels is only a smoke-test threshold.')
        return
    signed = [math.copysign(1, x)*y for x, y in data if x != 0]
    print('Mean sign(imbalance) × future midpoint return: %.4f bps' % (sum(signed)/len(signed) if signed else 0))
    print('Descriptive only: no fitted model, significance claim, execution simulation, or profitability claim.')


def main():
    parser = argparse.ArgumentParser(description='Quant Observatory — public data research; no trading keys')
    sub = parser.add_subparsers(dest='command', required=True)
    research = sub.add_parser('research', help='Run the paper-inspired offline development experiment')
    research.add_argument('--db', default='data/live.sqlite3')
    research.add_argument('--symbol', default='BTC/USD')
    research.add_argument('--demo', action='store_true')
    research.add_argument('--output', default='data/research')
    reference = sub.add_parser('microprice-reference', help='Check independent estimator on author sample data')
    reference.add_argument('--directory', default='data/reference')
    reference.add_argument('--output', default='data/reference/method-check.json')
    shadow = sub.add_parser('shadow', help='Run frozen micro-price estimator without trading')
    shadow.add_argument('--db', default='data/live.sqlite3')
    shadow.add_argument('--symbol', default='BTC/USD')
    shadow.add_argument('--demo', action='store_true')
    shadow.add_argument('--seconds', type=float, default=0)
    for name in ('collect', 'watch', 'evaluate', 'paper'):
        p = sub.add_parser(name)
        p.add_argument('--db', default='data/live.sqlite3')
        p.add_argument('--symbol', default='BTC/USD')
        if name != 'watch':
            p.add_argument('--demo', action='store_true', help='Synthetic data; use a separate database')
        if name == 'collect':
            p.add_argument('--seconds', type=float, default=0, help='0 runs until interrupted')
        if name == 'watch':
            p.add_argument('--once', action='store_true')
        if name == 'paper':
            p.add_argument('--fee-bps', type=float, default=40., help='Hypothetical fee per side, not an exchange quote')
            p.add_argument('--delay', type=float, default=.5, help='Simulated execution delay in seconds')
            p.add_argument('--seconds', type=float, default=0)
    args = parser.parse_args()
    if getattr(args, 'demo', False) and args.db == 'data/live.sqlite3':
        args.db = 'data/demo.sqlite3'
    try:
        if args.command == 'microprice-reference':
            from .microprice import reference
            reference(args)
        elif args.command == 'shadow':
            from .microprice import run_shadow
            if not math.isfinite(args.seconds) or args.seconds < 0:
                parser.error('--seconds must be finite and nonnegative')
            run_shadow(args)
        elif args.command == 'research':
            from .research import run
            run(args)
        elif args.command == 'paper':
            from .paper import run
            if not math.isfinite(args.seconds) or args.seconds < 0:
                parser.error('--seconds must be finite and nonnegative')
            run(args)
        elif args.command == 'collect':
            if args.seconds < 0:
                parser.error('--seconds must be nonnegative')
            asyncio.run(collect(args))
        elif args.command == 'watch':
            watch(args)
        else:
            evaluate(args)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
