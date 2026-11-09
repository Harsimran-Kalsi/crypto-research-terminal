import tempfile
from pathlib import Path
import unittest
import numpy as np
from quant.cli import connect,record
from quant.microprice import adjustment,fit,predict,setup,shadow_step
from quant.paper import initialize,step,account


class MicropriceTests(unittest.TestCase):
    def test_markov_recursion_matches_hand_computed_chain(self):
        q=np.eye(2)*.5
        moved=np.array([[.25,.25],[.25,.25]])
        reward=np.array([-.5,.5])
        np.testing.assert_allclose(adjustment(q,reward,moved),[-1,1])

    def model(self):
        rows=[]
        for i in range(1000):
            mid=100+(i%9)*.01
            rows.append(('live-a',float(i),mid-.005,mid+.005,1+(i%7),1+(i%11)))
        return fit(rows,tick=.01,bins=4,spread_states=1)

    def test_fitted_offsets_are_symmetric_and_unsupported_abstains(self):
        m=self.model()
        np.testing.assert_allclose(m['offset_ticks'],[-x for x in reversed(m['offset_ticks'])],atol=1e-10)
        self.assertIsNone(predict(m,99,101,1,1)[0])
        self.assertGreater(m['pairs'],100)

    def test_shadow_is_prospective_deduplicated_and_restart_persistent(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.db'
            db=connect(path);setup(db)
            m=self.model();m.update(symbol='BTC/USD',demo=False)
            def quote(t):
                record(db,'live-b',dict(channel='ticker',data=[dict(symbol='BTC/USD',bid=99.995,ask=100.005,bid_qty=3,ask_qty=1)]),t)
            quote(999);shadow_step(db,'test',m,999)
            self.assertEqual(db.execute('select count(*) from shadow_forecast').fetchone()[0],0)
            quote(1000);shadow_step(db,'test',m,1000);shadow_step(db,'test',m,1000)
            for t in (1001,1002,1003,1004): quote(t)
            shadow_step(db,'test',m,1004)
            self.assertEqual(db.execute('select count(*) from shadow_score').fetchone()[0],1)
            count=db.execute('select count(*) from shadow_forecast').fetchone()[0]
            shadow_step(db,'test',m,1010)  # stale quote cannot generate a forecast
            self.assertEqual(db.execute('select count(*) from shadow_forecast').fetchone()[0],count)
            db.close();db=connect(path)
            self.assertEqual(db.execute('select count(*) from shadow_score').fetchone()[0],1)
            db.close()

    def test_pausing_blocks_entry_but_manages_existing_exit(self):
        with tempfile.TemporaryDirectory() as d:
            db=connect(Path(d)/'test.db');initialize(db)
            def quote(t):
                record(db,'live-test',dict(channel='ticker',data=[dict(symbol='BTC/USD',bid=99,ask=100,bid_qty=4,ask_qty=1)]),t)
            quote(100);step(db,100);quote(101);step(db,101)
            self.assertGreater(account(db)['qty'],0)
            with db: db.execute('update paper_control set paused=1')
            quote(161);step(db,161);quote(162);step(db,162);quote(163);step(db,163)
            self.assertEqual(account(db)['qty'],0)
            self.assertIsNone(account(db)['pending'])
            self.assertIn('PAUSED',account(db)['status'])
            db.close()
