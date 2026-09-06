import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_swing_replay import CONFIG, PROTOCOL, fixture


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_swing_benchmark.py'


class SwingBenchmarkTests(unittest.TestCase):
    def test_execution_consumes_verified_artifacts_without_replay_or_new_variants(self):
        from unittest.mock import patch
        self.assertTrue(hasattr(self.cli,'run_execution'), 'execution CLI missing')
        dataset,observation = self.dataset()
        base = self.root/'execution-base'; experiments = self.root/'execution-experiments'
        self.cli.run_baseline(self.protocol,dataset,observation,base,progress=lambda _:None)
        self.cli.run_experiments(self.protocol,dataset,observation,base,experiments,progress=lambda _:None)
        with patch.object(self.cli,'run_experiments',side_effect=AssertionError('must not regenerate experiments')), \
             patch.object(self.cli,'replay_day',side_effect=AssertionError('must not generate signals')):
            first = self.cli.run_execution(self.protocol,dataset,observation,base,experiments,self.root/'x1',progress=lambda _:None)
            second = self.cli.run_execution(self.protocol,dataset,observation,base,experiments,self.root/'x2',progress=lambda _:None)
        self.assertEqual(first,second)
        self.assertIsNone(first['formal_shadow_candidate'])
        result = self.cli.read_json(self.root/'x1'/'execution.json')
        self.assertEqual(set(result['baseline']['scenarios']),{'slippage_1x','slippage_2x'})
        self.assertEqual(result['challenger']['status'],'unavailable')
        self.assertEqual(result['manual']['status'],'empty')
        self.assertIn('validation',result['baseline']['scenarios']['slippage_1x']['segments'])
        with self.assertRaisesRegex(ValueError,'fresh'):
            self.cli.run_execution(self.protocol,dataset,observation,base,experiments,self.root/'x1')
        frozen = self.cli.read_json(experiments/'manifest.json')
        identity = self.cli.read_json(experiments/'identity.json')
        identity['baseline_manifest_sha256'] = 'wrong_baseline'
        (experiments/'identity.json').write_text(json.dumps(identity))
        frozen['identity'] = identity; frozen['artifacts']['identity.json'] = self.cli.digest(identity)
        (experiments/'manifest.json').write_text(json.dumps(frozen))
        with self.assertRaisesRegex(ValueError,'lineage'):
            self.cli.run_execution(self.protocol,dataset,observation,base,experiments,self.root/'bad-lineage')

    def test_execution_requires_experiment_artifact_argument(self):
        self.assertTrue(hasattr(self.cli,'run_execution'))
        result = self.cli.main(['--protocol',str(PROTOCOL),'--dataset','unused','--observation','unused',
                               '--baseline','unused','--mode','execution','--output-dir','unused'])
        self.assertEqual(result,1)

    def test_execution_challenger_reuses_saved_orders_and_rejects_empty_or_changed_pool(self):
        import copy
        from tests.test_swing_replay import SwingExecutionTests
        helper = SwingExecutionTests(); helper.setUp()
        rows,_ = helper.inputs()
        rows.append(dict(rows[0],symbol='000002',rank_no=2))
        values = {'metrics.json':{'reconstructed_research':{'decision':'insufficient_evidence','experiments':{
            'E1':dict(status='available',provisional_ranking_candidate=True,
                      qualification=dict(checks={'fixture_gate':True},evidence_available={'fixture_evidence':True}),
                      paired={'matched_dates':['2026-07-01']},metrics={'slot_selection_by_date':{'2026-07-01':['000002','000001']}}),
            'E2':dict(status='unavailable'),'E3':dict(status='unavailable')}}}}
        name,base,trial,_ = self.cli._execution_challenger(rows,values)
        self.assertEqual(name,'E1')
        self.assertEqual(base,rows)
        self.assertEqual([r['symbol'] for r in sorted(trial,key=lambda r:r['_execution_order'])],['000002','000001'])
        self.assertEqual([r['total'] for r in trial],[r['total'] for r in rows])
        invalid = copy.deepcopy(values)
        invalid['metrics.json']['reconstructed_research']['experiments']['E1']['paired']['matched_dates'] = []
        with self.assertRaises(ValueError): self.cli._execution_challenger(rows,invalid)
        invalid = copy.deepcopy(values)
        invalid['metrics.json']['reconstructed_research']['experiments']['E1']['metrics']['slot_selection_by_date']['2026-07-01'] = ['000001']
        with self.assertRaises(ValueError): self.cli._execution_challenger(rows,invalid)
        invalid = copy.deepcopy(values)
        invalid['metrics.json']['reconstructed_research']['experiments']['E4'] = {}
        with self.assertRaises(ValueError): self.cli._execution_challenger(rows,invalid)

    def test_turnover_uses_fixed_pool_and_preserves_removed_gate_slots(self):
        from app.evaluation.swing_replay import replay_day,prepare_inputs,digest,decision_projection,label_candidates
        from unittest.mock import patch
        data=fixture(); saved=replay_day(data,self.protocol)
        prepared=prepare_inputs(data,self.protocol)
        input_hash=digest(dict(quotes=prepared['quotes'],histories={s:df.to_dict('records') for s,df in prepared['histories'].items()}))
        current=self.cli._fixed_pool_compute(prepared,saved)
        self.assertEqual(digest(decision_projection(current['picks'])),saved['identity']['decisions_sha256'])
        actual=self.cli._fixed_pool_compute(prepared,saved,True)
        self.assertEqual(input_hash,digest(dict(quotes=prepared['quotes'],histories={s:df.to_dict('records') for s,df in prepared['histories'].items()})))
        self.assertEqual({r['symbol'] for r in actual['picks']},{r['symbol'] for r in current['picks']})
        self.assertNotEqual(decision_projection(actual['picks']),decision_projection(current['picks']))
        rows=label_candidates(saved['candidates'],data['histories'],CONFIG)
        self.assertTrue(hasattr(self.cli,'preserve_turnover_slots'))
        missing=rows[0]['symbol']; picks=[p for p in actual['picks'] if p['symbol']!=missing]
        trial,changes,new=self.cli.preserve_turnover_slots(rows,picks)
        self.assertEqual(len(rows),len(trial))
        self.assertEqual(trial[0]['symbol'],missing)
        self.assertTrue(trial[0]['_selection_unknown'])
        from app.evaluation.ranking_quality_experiments import validate_swing_pair,_evaluate_variant
        validate_swing_pair(rows,trial)
        self.assertIsNone(_evaluate_variant(trial,'trial',lambda r:r['_trial_order'],rows)['metrics']['10']['top_k']['3']['avg_return'])
        self.assertTrue(changes[0]['gate_removed'])
        self.assertFalse(new)
        complete,_,_=self.cli.preserve_turnover_slots(rows,actual['picks'])
        for row in complete:
            self.assertEqual(row['total'],row['score_breakdown']['total'])
            self.assertEqual(row['decision_executable'],row['decision']['executable'])

    def test_turnover_missing_zero_and_late_field_fail_without_pool_refill(self):
        from app.evaluation.swing_replay import replay_day,label_candidates
        from unittest.mock import patch
        data=fixture(); saved=replay_day(data,self.protocol)
        rows=label_candidates(saved['candidates'],data['histories'],CONFIG)
        saved['frozen_analysis_pool'][0]['actual_daily_basic']['turnover_rate']=None
        with patch.object(self.cli,'date_files',side_effect=AssertionError('must fail coverage before replay')):
            trial,evidence=self.cli._turnover_trials(self.root,{},[saved],rows,CONFIG,
                self.protocol,lambda _:None)
        self.assertIsNone(trial)
        self.assertIn('actual_turnover_coverage_below_95pct',evidence['unavailable_reasons'])
        saved['frozen_analysis_pool'][0]['actual_daily_basic']['turnover_rate']=0
        with patch.object(self.cli,'date_files',return_value=iter([])):
            trial,evidence=self.cli._turnover_trials(self.root,{},[saved],rows,CONFIG,
                self.protocol,lambda _:None)
        self.assertEqual(evidence['field_coverage'],1)
        self.assertEqual(evidence['excluded_dates'],[rows[0]['trade_date']])
        self.assertEqual(len(evidence['true_zero_actual']),1)

    def test_changed_final_pool_is_unavailable_not_survivor_efficacy(self):
        from app.evaluation.swing_replay import replay_day,label_candidates
        from unittest.mock import patch
        data=fixture(); saved=replay_day(data,self.protocol)
        later=fixture(81); later_saved=replay_day(later,self.protocol)
        rows=label_candidates(saved['candidates']+later_saved['candidates'],later['histories'],CONFIG)
        by_day={}
        for history in later['histories'].values():
            for row in history: by_day.setdefault(self.cli.iso_day(row['trade_date']),[]).append(row)
        original=self.cli._fixed_pool_compute
        def dropped(prepared,saved,actual=False):
            result=original(prepared,saved,actual)
            if actual: result['picks']=result['picks'][1:]
            return result
        with patch.object(self.cli,'date_files',return_value=iter((d,dict(rows=r)) for d,r in sorted(by_day.items()))), patch.object(self.cli,'_fixed_pool_compute',side_effect=dropped):
            trial,evidence=self.cli._turnover_trials(self.root,{},[saved,later_saved],rows,CONFIG,self.protocol,lambda _:None)
        self.assertEqual(len(trial),len(saved['candidates']))
        self.assertIn('changed_final_pool_after_original_gates_or_caps_no_safe_same_pool_ranking',evidence['unavailable_reasons'])
        self.assertEqual(evidence['early_stop']['tested_dates'],1)
        self.assertEqual(evidence['early_stop']['total_eligible_dates'],2)
        self.assertEqual(evidence['early_stop']['untested_gate_dates'],[later_saved['identity']['trade_date']])


    def test_experiments_frozen_hashes_and_no_live_entry(self):
        self.assertTrue(hasattr(self.cli, 'run_experiments'))
        dataset, observation = self.dataset()
        self.cli.run_baseline(self.protocol, dataset, observation, self.root/'base', progress=lambda _:None)
        first = self.cli.run_experiments(self.protocol, dataset, observation, self.root/'base',
                                        self.root/'e1', progress=lambda _:None)
        second = self.cli.run_experiments(self.protocol, dataset, observation, self.root/'base',
                                         self.root/'e2', progress=lambda _:None)
        self.assertEqual(first, second)
        metrics = self.cli.read_json(self.root/'e1'/'metrics.json')
        e2 = metrics['reconstructed_research']['experiments']['E2']
        self.assertEqual(e2['status'], 'available', e2.get('unavailable_reasons'))
        self.assertEqual(first['experiments_run'], ['E1','E2','E3'])
        self.assertFalse(first['execution_run'])
        path = self.root/'base'/'reconstructed_research.json'
        value = self.cli.read_json(path); value[0]['future_return_10d'] = 999
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.cli.run_experiments(self.protocol, dataset, observation, self.root/'base', self.root/'bad')

    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'offline baseline CLI is not implemented')
        spec = importlib.util.spec_from_file_location('swing_benchmark', SCRIPT)
        self.cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.cli)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.protocol = json.loads(PROTOCOL.read_text())

    def dataset(self):
        from scripts.build_swing_research_dataset import collect, FIELDS
        from unittest.mock import patch
        from datetime import date
        data = fixture()
        by_date = {}
        for rows in data['histories'].values():
            for row in rows: by_date.setdefault(row['trade_date'], []).append(row)
        def fetch(endpoint, params, fields, timeout):
            key = {'daily':'daily','daily_basic':'basics','adj_factor':'factors'}[endpoint]
            rows = [r['raw_inputs'][key] for r in by_date[params['trade_date']]]
            names = FIELDS[endpoint].split(',')
            return {'code':0, 'data':dict(fields=names, items=[[r.get(k) for k in names] for r in rows])}
        with patch('scripts.build_swing_research_dataset.calendar_dates', return_value=sorted(by_date)):
            collect(self.protocol, self.root/'dataset', fetcher=fetch, sleep=lambda _:None,
                    progress=lambda _:None, today=lambda:date(2026,9,5))
        observation = dict(identity=data['identity'], strategy_config=CONFIG,
                           config_sha256=self.cli.digest(CONFIG), snapshots=[],
                           config_provenance='current_saved_profile_not_proven_historical_asof')
        path = self.root / (self.cli.digest(observation)+'.json')
        path.write_text(json.dumps(observation))
        return self.root/'dataset', path

    def test_fresh_repeated_baseline_hashes_and_outputs(self):
        dataset, observation = self.dataset()
        progress = []
        first = self.cli.run_baseline(self.protocol, dataset, observation, self.root/'a', progress=progress.append)
        self.assertTrue(any('signal_dates=20' in line for line in progress))
        self.assertTrue(any('phase=labels' in line for line in progress))
        second = self.cli.run_baseline(self.protocol, dataset, observation, self.root/'b')
        self.assertEqual(first, second)
        self.assertGreater(first['counts']['reconstructed_candidates'], 0)
        self.assertEqual(first['identity']['mode'], 'baseline')
        self.assertFalse(first['production_verified'])
        rows = json.loads((self.root/'a'/'reconstructed_research.json').read_text())
        self.assertIn('proxy_was_used', rows[0])
        self.assertIn('history_source', rows[0])
        self.assertIn('future_return_20d', rows[-1])
        self.assertIsNone(rows[-1]['future_return_20d'])
        self.assertIn('observed_production', first['baselines'])
        metrics = json.loads((self.root/'a'/'metrics.json').read_text())
        self.assertIn('validation', metrics['reconstructed_research']['segments'])
        self.assertIn('watch', metrics['reconstructed_research']['groups']['action'])

    def test_identity_hash_file_and_config_drift_fail_closed(self):
        dataset, observation = self.dataset()
        manifest = json.loads((dataset/'manifest.json').read_text())
        path = dataset/next(iter(manifest['dates'].values()))['output']
        with gzip.open(path,'rt') as f: value=json.load(f)
        value['rows'][0]['close'] += .01
        with gzip.open(path,'wt') as f: json.dump(value,f)
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.cli.run_baseline(self.protocol, dataset, observation, self.root/'a')

    def test_observation_hash_and_output_reuse_are_rejected(self):
        dataset, observation = self.dataset()
        observation.write_text(observation.read_text().replace('"score_threshold": 72', '"score_threshold": 73'))
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.cli.run_baseline(self.protocol, dataset, observation, self.root/'a')

    def test_missing_factor_labels_remain_null_not_later_entry(self):
        from app.evaluation.swing_replay import label_candidates
        data = fixture()
        rows = data['histories']['000001'][-21:]
        signal = dict(symbol='000001', rank_no=1, trade_date=rows[0]['trade_date'])
        rows[1]['adj_factor'] = None
        labeled = label_candidates([signal], {'000001':rows}, CONFIG)
        self.assertIsNone(labeled[0]['future_return_10d'])
        self.assertEqual(labeled[0]['label_missing_reason'], 'adjustment_factor_missing')

    def test_only_baseline_cli_mode_available(self):
        with self.assertRaises(SystemExit) as caught:
            self.cli.main(['--mode', 'execution'])
        self.assertEqual(caught.exception.code, 2)

    def test_late_availability_invalid_later_bar_and_horizon_specific_factor_gaps(self):
        from app.evaluation.swing_replay import label_candidates
        data = fixture()
        rows = data['histories']['000001'][-21:]
        signal = dict(symbol='000001',rank_no=1,trade_date=rows[0]['trade_date'])
        rows[12]['adj_factor'] = None
        labeled = label_candidates([signal], {'000001':rows}, CONFIG)[0]
        self.assertIsNotNone(labeled['future_return_10d'])
        self.assertIsNone(labeled['future_return_20d'])
        self.assertIn('first_hit_path', labeled['horizon_paths']['10'])
        signal['available_at'] = '2026-12-31T20:00:00+08:00'
        labeled = label_candidates([signal], {'000001':rows}, CONFIG)[0]
        self.assertTrue(all(labeled[f'future_return_{h}d'] is None for h in (5,10,20)))

    def test_bar12_factor_gap_preserves_valid_primary_entry_and_status(self):
        from app.evaluation.swing_replay import label_candidates, iso_day
        rows = fixture()['histories']['000001'][-21:]
        signal = dict(symbol='000001',rank_no=1,trade_date=rows[0]['trade_date'])
        rows[12]['adj_factor'] = None
        result = label_candidates([signal],{'000001':rows},CONFIG)[0]
        self.assertIsNotNone(result['future_return_10d'])
        self.assertEqual(result['entry_date'],iso_day(rows[1]['trade_date']))
        self.assertEqual(result['entry_price'],round(rows[1]['open'],6))
        self.assertEqual(result['tradable_label'],'tradable')
        self.assertIsNone(result['label_missing_reason'])
        self.assertEqual(result['label_metadata_horizon'],10)
        self.assertNotIn(10,result['incomplete_horizons'])
        self.assertIn(20,result['incomplete_horizons'])
        self.assertEqual(result['horizon_paths']['20']['label_missing_reason'],'adjustment_factor_missing')
        self.assertEqual(result['max_favorable_excursion'],result['horizon_paths']['10']['mfe'])

    def test_four_future_bars_have_no_complete_5d_path_outcomes(self):
        from app.evaluation.swing_replay import label_candidates
        rows = fixture()['histories']['000001'][-21:-16]
        signal = dict(symbol='000001',rank_no=1,trade_date=rows[0]['trade_date'])
        result = label_candidates([signal],{'000001':rows},CONFIG)[0]
        path = result['horizon_paths']['5']
        self.assertFalse(path['mature'])
        self.assertEqual(path['label_missing_reason'],'insufficient_future_bars')
        for key in ('end_date','mfe','mae','first_hit_path','first_hit_date',
                    'first_hit_take_profit','first_hit_stop_loss'):
            self.assertIsNone(path[key],key)
        self.assertIsNone(result['max_favorable_excursion'])
        self.assertEqual(result['label_missing_reason'],'insufficient_future_bars')
        self.assertIsNotNone(result['entry_date'])

    def test_effective_feature_availability_propagates_to_label_rejection(self):
        from app.evaluation.swing_replay import label_candidates
        rows = fixture()['histories']['000001'][-21:]
        signal = dict(symbol='000001',rank_no=1,trade_date=rows[0]['trade_date'],
                      effective_available_at='2026-12-31T20:00:00+08:00')
        result = label_candidates([signal],{'000001':rows},CONFIG)[0]
        self.assertEqual(result['label_missing_reason'],'input_available_after_entry')
        self.assertTrue(all(result[f'future_return_{h}d'] is None for h in (5,10,20)))

    def test_duplicate_observation_quarantines_entire_date_and_keeps_unknowns(self):
        dataset, observation = self.dataset()
        data = fixture(); day = data['trade_date']
        observed = json.loads(observation.read_text())
        observed['snapshots'] = [dict(symbol='000001',rank_no=1,trade_date=day),
                                 dict(symbol='300750',rank_no=1,trade_date=day)]
        path = self.root/(self.cli.digest(observed)+'.json'); path.write_text(json.dumps(observed))
        result = self.cli.run_baseline(self.protocol, dataset, path, self.root/'a')
        self.assertEqual(result['counts']['observed_quarantined'], 2)

    def test_output_reuse_protocol_drift_and_identity_mutation_reject(self):
        dataset, observation = self.dataset()
        output = self.root/'exists'; output.mkdir(); (output/'keep').write_text('unchanged')
        with self.assertRaisesRegex(ValueError,'fresh'):
            self.cli.run_baseline(self.protocol,dataset,observation,output)
        bad = copy.deepcopy(self.protocol); bad['identity']['user_id']='other'
        with self.assertRaises(ValueError):
            self.cli.run_baseline(bad,dataset,observation,self.root/'a')
        identity = json.loads((dataset/'identity.json').read_text()); identity['source']='other'
        (dataset/'identity.json').write_text(json.dumps(identity))
        with self.assertRaisesRegex(ValueError,'identity hash'):
            self.cli.run_baseline(self.protocol,dataset,observation,self.root/'b')

    def test_segment_embargo_excludes_whole_date_without_refilling_pool(self):
        rows = [dict(symbol='000001',rank_no=1,trade_date='2026-02-20',
                     label_end_dates={'20':'2026-03-12'}),
                dict(symbol='300750',rank_no=2,trade_date='2026-02-20',
                     label_end_dates={'20':'2026-02-28'})]
        result = self.cli.baseline_metrics(rows,self.protocol)['segments']['validation']
        self.assertEqual(result['purged_overlap_or_unknown_20bar_end'],2)
        self.assertEqual(result['backend_order']['coverage']['input_row_count'],0)
