from collections import defaultdict
import sqlite3
import unittest
from quant.cli import SCHEMA, record
from quant.research import build, execution, folds, load


def fixture(n=1200):
    return [('live-a', float(t),100+t*.001,100.02+t*.001,2.,1.) for t in range(n)]


class ResearchTests(unittest.TestCase):
    def test_future_events_cannot_change_past_features(self):
        qs = fixture()
        trades = defaultdict(list, {'live-a':[(35.,100.,.1,'buy'),(50.,101.,.2,'sell')]})
        first = next(r for r in build(qs,trades) if r['t']==40)
        altered = [q if q[1]<=40 else (q[0],q[1],200.,201.,90.,1.) for q in qs]
        trades['live-a'].append((41.,999.,100.,'sell'))
        second = next(r for r in build(altered,trades) if r['t']==40)
        self.assertEqual(first['x'],second['x'])
        self.assertNotEqual(first['y'],second['y'])
        self.assertAlmostEqual(first['x'][5],.1)

    def test_gaps_and_session_boundaries_do_not_make_labels(self):
        rows=build(fixture(150)+[('live-b',q[1]+300,*q[2:]) for q in fixture(150)],{})
        self.assertTrue(rows)
        self.assertTrue(all(r['t']+60<=149 or r['t']>=330 for r in rows))
        qs=[q for q in fixture(300) if not 100<=q[1]<=120]
        rows=build(qs,{})
        self.assertTrue(all(r['t']+60<100 or r['t']>=151 for r in rows))

    def test_purged_folds_leave_final_period_unscored(self):
        rows=build(fixture(),{})
        splits,sealed=folds(rows)
        for train,valid in splits:
            self.assertTrue(train and valid)
            self.assertLess(max(rows[i]['t']+60 for i in train),min(rows[i]['t'] for i in valid))
            self.assertLess(max(rows[i]['t']+60 for i in valid),sealed)

    def test_snapshots_and_duplicates_excluded(self):
        db=sqlite3.connect(':memory:');db.executescript(SCHEMA)
        trade=dict(symbol='BTC/USD',price=100,qty=.1,side='buy',trade_id=1)
        for kind in ['snapshot','update','update']:
            record(db,'live-a',dict(channel='trade',type=kind,data=[trade]),1.)
        _,trades,audit=load(db,'BTC/USD')
        self.assertEqual(len(trades['live-a']),1)
        self.assertEqual(audit['snapshots_excluded'],1)
        self.assertEqual(audit['duplicate_trades'],1)

    def test_execution_costs_nonoverlap_and_boundary(self):
        qs=[('live-a',float(t),99.,100.,10.,10.) for t in range(101)]
        rows=[dict(session='live-a',t=t,x=[0,0]) for t in range(10)]
        result=execution(rows,[1000]*len(rows),qs,3,.5,40)
        # 100 buy -> 99 sell, then 40bps fee on each side: -179.6bps.
        self.assertAlmostEqual(result['mean_net_bps'],-179.6)
        self.assertEqual(result['trades'],2)
        self.assertEqual(execution(rows[:1],[1000],qs,3,.5,40,end_time=4)['trades'],0)
        self.assertEqual(execution(rows[:1],[10],qs,3,.5,40)['trades'],0)


if __name__=='__main__':
    unittest.main()
