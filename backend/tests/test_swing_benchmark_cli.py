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
