import tempfile
from pathlib import Path
import unittest
from quant.cli import connect,record
from quant.model_paper import initialize,tick
from quant.paper import account
from quant.charts import chart


class ModelPaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.source_path=Path(self.tmp.name)/'source.db'
        self.account_path=Path(self.tmp.name)/'paper.db'
        self.source=connect(self.source_path);self.db=connect(self.account_path)
        self.model=dict(symbol='BTC/USD',demo=False,train_end=0,tick=.02,bins=1,
                        spread_states=1,edges=[],counts=[100],offset_ticks=[100])
        initialize(self.db,self.source_path,'frozen-test',self.model)

    def tearDown(self):
        self.db.close();self.source.close();self.tmp.cleanup()

    def quote(self,t):
        record(self.source,'live-test',dict(channel='ticker',data=[dict(
            symbol='BTC/USD',bid=99.99,ask=100.01,bid_qty=5,ask_qty=5)]),t)

    def test_isolated_delayed_trade_restart_and_exit(self):
        self.quote(10);tick(self.db,self.source,'frozen-test',self.model,10)
        tick(self.db,self.source,'frozen-test',self.model,11)
        self.assertEqual(account(self.db)['qty'],0)
        self.quote(11);tick(self.db,self.source,'frozen-test',self.model,11)
        self.assertGreater(account(self.db)['qty'],0)
        self.db.close();self.db=connect(self.account_path)
        initialize(self.db,self.source_path,'frozen-test',self.model)
        self.quote(26);tick(self.db,self.source,'frozen-test',self.model,26)
        self.quote(27);tick(self.db,self.source,'frozen-test',self.model,27)
        tick(self.db,self.source,'frozen-test',self.model,27)
        self.assertEqual(account(self.db)['qty'],0)
        self.assertLess(account(self.db)['realized'],0)
        self.assertEqual(self.db.execute('select count(*) from paper_fills').fetchone()[0],2)
        self.assertIsNone(self.source.execute("select name from sqlite_master where name='paper_fills'").fetchone())
        self.assertEqual(self.source.execute('select count(*) from events').fetchone()[0],4)
        self.assertEqual(self.db.execute('select count(*) from paper_equity').fetchone()[0],4)

    def test_stale_and_unsupported_quotes_do_not_buy(self):
        self.quote(10);tick(self.db,self.source,'frozen-test',self.model,20)
        self.assertIsNone(account(self.db)['pending'])
        self.model['counts']=[0]
        self.quote(21);tick(self.db,self.source,'frozen-test',self.model,21)
        self.assertIsNone(account(self.db)['pending'])
        self.assertEqual(account(self.db)['qty'],0)

    def test_refuses_silent_configuration_change(self):
        with self.assertRaises(ValueError):
            initialize(self.db,self.source_path,'different-model',self.model)

    def test_chart_trade_markers_and_gaps(self):
        text=chart([(0,100),(180,101)],[(180,101,'BUY')],width=20,height=4).plain
        self.assertIn('B',text)
        self.assertIn('blank buckets',text)
        self.assertLessEqual(text.count('•'),2)
