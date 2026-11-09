import os
import tempfile
import unittest
from quant.cli import connect, record
from quant.paper import initialize, step, account


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'test.db')
        self.db = connect(self.path)
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def quote(self, ts, bid=99., ask=100., bq=4., aq=1.):
        record(self.db, 'live-test', {'channel': 'ticker', 'data': [dict(
            symbol='BTC/USD', bid=bid, ask=ask, bid_qty=bq, ask_qty=aq)]}, ts)

    def enter(self):
        self.quote(100)
        step(self.db, 100)
        self.quote(100.6)
        step(self.db, 100.6)

    def test_delayed_fill_restart_exit_and_accounting(self):
        self.quote(100)
        step(self.db, 100)
        step(self.db, 100.8)  # Same quote cannot fill, even after delay.
        self.assertEqual(account(self.db)['qty'], 0)
        self.quote(101)
        step(self.db, 101)
        self.assertAlmostEqual(account(self.db)['cash'], 89.96)
        self.db.close()
        self.db = connect(self.path)
        initialize(self.db)
        self.assertAlmostEqual(account(self.db)['qty'], .1)
        self.quote(161, bid=102, ask=103)
        step(self.db, 161)
        self.quote(162, bid=102, ask=103)
        step(self.db, 162)
        step(self.db, 162)
        a = account(self.db)
        self.assertEqual(a['qty'], 0)
        self.assertAlmostEqual(a['cash'], 100.1192)
        self.assertAlmostEqual(a['realized'], .1192)
        self.assertAlmostEqual(a['fees'], .0808)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_fills').fetchone()[0], 2)

    def test_stale_entry_cancelled_open_position_retained(self):
        self.quote(100)
        step(self.db, 100)
        step(self.db, 106)
        self.assertIsNone(account(self.db)['pending'])
        self.assertEqual(account(self.db)['qty'], 0)
        self.quote(107)
        step(self.db, 107)
        self.quote(108)
        step(self.db, 108)
        step(self.db, 200)
        self.assertAlmostEqual(account(self.db)['qty'], .1)
        self.quote(201)
        step(self.db, 201)
        self.quote(202)
        step(self.db, 202)
        self.assertEqual(account(self.db)['qty'], 0)

    def test_loss_limit_and_settings_persist(self):
        self.enter()
        self.quote(102, bid=60, ask=61)
        step(self.db, 102)
        self.quote(103, bid=60, ask=61)
        step(self.db, 103)
        self.quote(104, bid=60, ask=61)
        step(self.db, 104)
        self.assertIn('HALTED', account(self.db)['status'])
        self.assertIsNone(account(self.db)['pending'])
        with self.assertRaises(ValueError):
            initialize(self.db, fee_bps=0)

    def test_synthetic_isolation_and_insufficient_size(self):
        record(self.db, 'demo-test', {'channel':'ticker','data':[dict(
            symbol='BTC/USD',bid=99,ask=100,bid_qty=4,ask_qty=1)]}, 100)
        step(self.db, 100)
        self.assertIsNone(account(self.db)['pending'])
        self.quote(101)
        step(self.db, 101)
        self.quote(102, aq=.001)
        step(self.db, 102)
        self.assertEqual(account(self.db)['qty'], 0)
