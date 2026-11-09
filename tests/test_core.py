import sqlite3
import unittest
from quant.cli import SCHEMA, record, samples, valid_quote


class CoreTests(unittest.TestCase):
    def test_raw_and_quote_persist_and_replay(self):
        db = sqlite3.connect(':memory:')
        db.executescript(SCHEMA)
        msg = {'channel': 'ticker', 'data': [dict(symbol='BTC/USD', bid=100., ask=102., bid_qty=3., ask_qty=1.)]}
        record(db, 'live-test', msg, 1.)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
        self.assertEqual(db.execute('SELECT bid,ask FROM quotes').fetchone(), (100., 102.))
        msg['data'][0]['ask'] = 99.
        record(db, 'live-test', msg, 2.)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM quotes').fetchone()[0], 1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 2)

    def test_labels_exclude_disconnects_and_stale_gaps(self):
        rows = [('a', t, 100., 102., 3., 1.) for t in range(0, 121)]
        labels = samples(rows)
        self.assertEqual(labels, [(0.5, 0.), (0.5, 0.)])
        self.assertEqual(samples(rows[:30] + rows[40:61]), [])
        self.assertEqual(samples(rows[:30] + [('b', *r[1:]) for r in rows[30:61]]), [])

    def test_nonfinite_or_empty_book_is_rejected(self):
        self.assertFalse(valid_quote(dict(bid=float('nan'), ask=2, bid_qty=1, ask_qty=1)))
        self.assertFalse(valid_quote(dict(bid=1, ask=2, bid_qty=0, ask_qty=0)))


if __name__ == '__main__':
    unittest.main()
