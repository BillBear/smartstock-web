import copy
import importlib
import importlib.util
import json
import unittest

from tests.test_swing_replay import CONFIG, PROTOCOL, fixture


class TurnoverEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.evaluation.turnover_end_to_end'),
                             'end-to-end comparison is not implemented')
        self.module = importlib.import_module('app.evaluation.turnover_end_to_end')
        self.protocol = json.loads(PROTOCOL.read_text())

    def rows(self):
        identity = self.protocol['identity']
        pool = [dict(symbol=f'{i:06}', rank_no=i+1, trade_date='2026-07-01',
                     baseline_kind='reconstructed_research', **identity,
                     action='buy', history_source='tushare', market_state_tag='neutral',
                     label_end_dates={'20':'2026-07-28'},
                     **{f'future_return_{h}d':float(i) for h in (3,5,10,20)})
                for i in range(12)]
        base = copy.deepcopy(pool[:10])
        trial = [dict(r,rank_no=i+1) for i,r in enumerate(reversed(pool[2:]))]
        return base, trial, pool

    def test_changed_final_membership_uses_common_preanalysis_denominator(self):
        base,trial,pool = self.rows()
        result = self.module.compare_outputs(base,trial,pool,['2026-07-01'])
        primary = result['by_horizon']['10']
        self.assertEqual(primary['dates'],['2026-07-01'])
        self.assertEqual(primary['pool']['avg_return'],5.5)
        self.assertEqual(primary['baseline']['top_k']['5']['avg_return'],2)
        self.assertEqual(primary['trial']['top_k']['5']['avg_return'],9)
        self.assertEqual(primary['trial']['top_k']['5']['relative_candidate_pool_excess_return'],3.5)
        self.assertEqual(primary['paired']['mean_daily_top5_return_difference'],7)
        self.assertEqual(primary['inference']['status'],'insufficient_blocks')

    def test_label_mutation_unknown_membership_duplicates_and_identity_reject(self):
        base,trial,pool = self.rows()
        cases = []
        bad = copy.deepcopy(trial); bad[0]['future_return_10d']=999; cases.append(bad)
        bad = copy.deepcopy(trial); bad[0]['symbol']='999999'; cases.append(bad)
        bad = copy.deepcopy(trial); bad[0]['user_id']='other'; cases.append(bad)
        bad = copy.deepcopy(trial); bad[0]['rank_no']=bad[1]['rank_no']; cases.append(bad)
        for bad in cases:
            with self.assertRaises(ValueError):
                self.module.compare_outputs(base,bad,pool,['2026-07-01'])

    def test_missing_pool_label_and_short_output_do_not_silently_refill(self):
        base,trial,pool = self.rows()
        result = self.module.compare_outputs(base[:4],trial,pool,['2026-07-01'])
        self.assertEqual(result['by_horizon']['10']['dates'],[])
        self.assertIn('fewer_than_10_outputs',result['by_horizon']['10']['excluded']['2026-07-01'])
        pool[-1]['future_return_10d']=None; trial[0]['future_return_10d']=None
        result = self.module.compare_outputs(base,trial,pool,['2026-07-01'])
        self.assertIn('incomplete_preanalysis_labels',result['by_horizon']['10']['excluded']['2026-07-01'])

    def test_replay_parity_only_turnover_changes_no_future_or_mutation(self):
        from app.evaluation.swing_replay import replay_day,prepare_inputs,digest
        data = fixture(); saved = replay_day(data,self.protocol)
        prepared = prepare_inputs(data,self.protocol)
        before = digest(saved)
        trial,evidence = self.module.replay_turnover_day(prepared,saved)
        self.assertTrue(evidence['baseline_parity'])
        self.assertEqual(evidence['changed_input_fields'],['quote.turnover_rate'])
        self.assertEqual(digest(saved),before)
        self.assertEqual({r['symbol'] for r in trial}, {r['symbol'] for r in saved['candidates']})
        self.assertTrue(all(r['config_sha256']==digest(CONFIG) for r in trial))
        self.assertTrue(all(r['turnover_recipe']=='actual_daily_basic_same_day' for r in trial))
        self.assertNotEqual(evidence['reference_decisions_sha256'],evidence['trial_decisions_sha256'])

    def test_missing_zero_nonfinite_actual_turnover_and_tampered_input_reject(self):
        from app.evaluation.swing_replay import replay_day,prepare_inputs
        data=fixture(); saved=replay_day(data,self.protocol); prepared=prepare_inputs(data,self.protocol)
        for value in (None,0,-1,float('nan'),True):
            bad=copy.deepcopy(saved); bad['frozen_analysis_pool'][0]['actual_daily_basic']['turnover_rate']=value
            with self.assertRaises(ValueError): self.module.replay_turnover_day(prepared,bad)
        bad=copy.deepcopy(saved); bad['identity']['decisions_sha256']='bad'
        with self.assertRaisesRegex(ValueError,'parity'): self.module.replay_turnover_day(prepared,bad)
        bad=copy.deepcopy(saved); bad['provenance']['input_sha256']='bad'
        with self.assertRaisesRegex(ValueError,'input hash'): self.module.replay_turnover_day(prepared,bad)

    def test_attaching_labels_keeps_new_symbols_own_labels_and_current_decisions(self):
        base,trial,pool = self.rows()
        pick=dict(symbol=trial[0]['symbol'],trade_date='2026-07-01',rank_no=1,action='watch',
                  decision={'grade':'C','executable':False},score_breakdown={'total':80})
        attached=self.module.attach_labels([pick],pool)[0]
        self.assertEqual(attached['future_return_10d'],11)
        self.assertEqual(attached['action'],'watch')
        self.assertEqual(attached['total'],80)
        self.assertFalse(attached['decision_executable'])
        with self.assertRaises(ValueError):
            self.module.attach_labels([dict(pick,future_return_10d=99)],pool)

    def test_execution_uses_common_pool_purge_dates_for_both_variants(self):
        base,trial,pool=self.rows()
        pool[-1]['label_end_dates']['20']='2026-08-03'
        from app.evaluation.ranking_quality_experiments import swing_segments
        segments=swing_segments(pool,self.protocol)
        self.assertEqual(segments['walk_forward_2026-07']['dates'],[])
        self.assertEqual(segments['walk_forward_2026-07']['excluded_dates'],['2026-07-01'])

    def test_cli_round_trip_repeats_and_rejects_output_reuse_and_source_drift(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.run_turnover_end_to_end'),
                             'end-to-end CLI missing')
        from scripts.run_turnover_end_to_end import run
        from tests.test_swing_benchmark_cli import SwingBenchmarkTests
        helper=SwingBenchmarkTests(); helper.setUp()
        self.addCleanup(helper.doCleanups)
        dataset,observation=helper.dataset()
        baseline=helper.root/'baseline'
        helper.cli.run_baseline(self.protocol,dataset,observation,baseline,progress=lambda _:None)
        first=run(self.protocol,dataset,observation,baseline,helper.root/'t1',progress=lambda _:None)
        second=run(self.protocol,dataset,observation,baseline,helper.root/'t2',progress=lambda _:None)
        self.assertEqual(first,second)
        self.assertFalse(first['production_authorized'])
        self.assertIsNone(first['formal_shadow_candidate'])
        self.assertIn('execution.json',first['artifacts'])
        result=json.loads((helper.root/'t1'/'metrics.json').read_text())
        self.assertEqual(set(result['segments']) & {'development','validation','walk_forward'},
                         {'development','validation','walk_forward'})
        self.assertEqual(result['decision'],'insufficient_evidence')
        with self.assertRaisesRegex(ValueError,'fresh'):
            run(self.protocol,dataset,observation,baseline,helper.root/'t1')
        identity=json.loads((baseline/'identity.json').read_text())
        identity['implementation_sha256']['app/services/coach_service.py']='bad'
        (baseline/'identity.json').write_text(json.dumps(identity))
        manifest=json.loads((baseline/'manifest.json').read_text())
        manifest['identity']=identity; manifest['artifacts']['identity.json']=helper.cli.digest(identity)
        (baseline/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'source mismatch'):
            run(self.protocol,dataset,observation,baseline,helper.root/'bad')
