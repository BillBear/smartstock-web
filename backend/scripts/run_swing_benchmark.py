#!/usr/bin/env python3
"""Cache-only baseline. No application bootstrap, provider, DB or ML execution."""
import argparse
from collections import defaultdict, deque
import gzip
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.swing_protocol import validate_protocol
from app.evaluation.swing_replay import (BAR_FIELDS, LIMITATIONS, QUOTE_RECIPE, checked_bars, _usable,
    digest, iso_day, label_candidates, replay_day, validate_config)
from app.evaluation.ranking_quality_diagnosis import (
    quarantine_ambiguous_dates, validate_labeled_snapshot_sample)
from app.evaluation.ranking_quality_experiments import _evaluate_variant, _candidate_pool_metrics


def read_json(path):
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        return json.load(handle)


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, allow_nan=False,
                  separators=(',', ':'))
        handle.write('\n')


def dataset_index(root, protocol):
    manifest = read_json(root/'manifest.json')
    identity = read_json(root/'identity.json')
    identity_hash = digest(identity)
    if identity != manifest['identity'] or identity_hash != manifest['identity_sha256']:
        raise ValueError('dataset identity hash mismatch')
    if identity.get('protocol_sha256') != protocol['protocol_sha256'] or validate_protocol(
            read_json(root/'protocol.json')) != protocol:
        raise ValueError('dataset protocol mismatch')
    if identity.get('source') != 'tushare' or identity.get('adjustment') != 'raw':
        raise ValueError('dataset source mismatch')
    if (identity.get('warmup_start') != protocol['dates']['warmup_start'] or
            identity.get('signal_range') != protocol['dates']['research']):
        raise ValueError('dataset date identity mismatch')
    indexed = {day:entry.get('dataset_sha256') for day,entry in manifest['dates'].items()}
    if digest(dict(identity_sha256=identity_hash, dates=indexed)) != manifest['dataset_sha256']:
        raise ValueError('dataset index hash mismatch')
    coverage = {day:{key:entry.get(key) for key in
        ('status','coverage_sha256','daily_rows','complete_rows')} | dict(endpoints={
            endpoint:{key:item.get(key) for key in ('payload_sha256','row_count','status','nonfinite_to_null_count')}
            for endpoint,item in entry['endpoints'].items()}) for day,entry in manifest['dates'].items()}
    if digest(dict(identity_sha256=identity_hash, dates=coverage)) != manifest['coverage_sha256']:
        raise ValueError('dataset coverage hash mismatch')
    if manifest['status'] == 'blocked':
        raise ValueError('blocked dataset')
    return manifest


def date_files(root, manifest):
    for compact, entry in sorted(manifest['dates'].items()):
        if entry.get('output') is None:
            continue
        path = (root/entry['output']).resolve()
        if root.resolve() not in path.parents:
            raise ValueError('dataset output path escapes root')
        value = read_json(path)
        if digest(value) != entry['dataset_sha256'] or digest(value['coverage']) != entry['coverage_sha256']:
            raise ValueError('date file hash mismatch: '+compact)
        if value.get('schema_version') != 'swing-dataset-date-v1' or value['trade_date'] != compact:
            raise ValueError('date file identity mismatch')
        day = iso_day(compact)
        expected_role = ('warmup' if day < manifest['identity']['signal_range'][0] else
                         'label_only' if day > manifest['identity']['signal_range'][1] else 'signal')
        if value['role'] != expected_role or day > manifest['identity']['label_end_date']:
            raise ValueError('date file role mismatch')
        checked_bars(value['rows'])
        if any(iso_day(r['trade_date']) != day for r in value['rows']):
            raise ValueError('date file contains wrong-date rows')
        if len(value['rows']) != entry.get('daily_rows'):
            raise ValueError('date file row count mismatch')
        yield day, value


def _metrics(rows):
    return dict(candidate_pool=_candidate_pool_metrics(rows), backend_order=_evaluate_variant(
        rows, 'frozen_backend_rank', lambda r:(r['rank_no'], r['symbol'])))


def baseline_metrics(rows, protocol):
    result = _metrics(rows)
    intervals = {name:protocol['dates'][name] for name in ('development','validation','walk_forward')}
    for month in range(3,9):
        start = f'2026-{month:02d}-01'
        end = f'2026-{month+1:02d}-01'
        intervals['walk_forward_'+start[:7]] = [start,end]
    result['segments'] = {}
    for name,(start,end) in intervals.items():
        # Conservative maximum-label embargo: unknown or crossing ends do not
        # become independent segment evidence; original overall rows stay intact.
        inclusive = not name.startswith('walk_forward_')
        signal_rows = [r for r in rows if start <= r['trade_date'] and
                       (r['trade_date'] <= end if inclusive else r['trade_date'] < end)]
        unsafe_dates = {r['trade_date'] for r in signal_rows if
            not (r.get('label_end_dates') or {}).get('20') or
            not (r['label_end_dates']['20'] <= end if inclusive else r['label_end_dates']['20'] < end)}
        accepted = [r for r in signal_rows if r['trade_date'] not in unsafe_dates]
        result['segments'][name] = dict(**_metrics(accepted),
            raw_signal_count=len(signal_rows), purged_overlap_or_unknown_20bar_end=len(signal_rows)-len(accepted),
            excluded_dates=sorted(unsafe_dates), purge_unit='whole_date_no_refill',
            status='retrospective_descriptive_no_training_or_independent_unseen_claim')
    dimensions = {
        'action':lambda r:r.get('action') or 'unknown',
        'probability_source':lambda r:r.get('probability_source') or 'unknown',
        'analysis':lambda r:'degraded_proxy' if r.get('analysis_status') == 'degraded' else
                          'full_rules' if r.get('feature_bar_count',0)>=60 else 'legacy_unknown',
        'market_state':lambda r:r.get('market_state_tag') or 'unknown',
        'history_source':lambda r:r.get('history_source') or 'unknown',
    }
    result['groups'] = {}
    for dimension, key in dimensions.items():
        names = set(map(key,rows)) | ({'buy','watch','unknown'} if dimension == 'action' else {'unknown'})
        result['groups'][dimension] = {name:_metrics([r for r in rows if key(r)==name]) for name in sorted(names)}
    result['concentration'] = dict(historical_industry='unknown_not_board_industry',
        historical_market_cap='actual_daily_basic_circ_mv_sidecar_only_no_unfrozen_bucket_cutoffs')
    return result


def _label_from_stream(root, manifest, candidates, config):
    # Each candidate retains at most its same-day bar and twenty future bars.
    # Suspended symbols remain pending, without inventing bars or entering later.
    by_day = defaultdict(list)
    for i,row in enumerate(candidates):
        by_day[iso_day(row['trade_date'])].append(i)
    pending = defaultdict(list); buffers = [[] for _ in candidates]
    for day, value in date_files(root, manifest):
        for i in by_day.pop(day, []):
            pending[candidates[i]['symbol']].append(i)
        today = {r['symbol']:{k:r.get(k) for k in BAR_FIELDS} for r in value['rows']}
        for symbol in list(pending):
            bar = today.get(symbol)
            if bar is None:
                continue
            remaining = []
            for i in pending[symbol]:
                buffers[i].append(bar)
                future_count = sum(iso_day(r['trade_date']) > iso_day(candidates[i]['trade_date']) for r in buffers[i])
                if future_count < 20:
                    remaining.append(i)
            if remaining:
                pending[symbol] = remaining
            else:
                del pending[symbol]
    labeled = []
    for candidate, bars in zip(candidates, buffers):
        labeled.extend(label_candidates([candidate], {candidate['symbol']:bars}, config))
    return labeled


def run_baseline(protocol, dataset, observation, output_dir, progress=None):
    if progress is None:
        progress = lambda message: print(message, file=sys.stderr, flush=True)
    protocol = validate_protocol(protocol)
    root, output = Path(dataset), Path(output_dir)
    observation_path = Path(observation)
    observed = read_json(observation_path)
    observation_hash = digest(observed)
    if observation_path.stem != observation_hash:
        raise ValueError('observation file hash mismatch: expected content-addressed filename')
    config = observed['strategy_config']
    validate_config(config, observed['identity'], protocol)
    if observed.get('config_sha256') != digest(config):
        raise ValueError('observation config hash mismatch')
    if observed.get('config_provenance') != protocol['costs']['provenance']:
        raise ValueError('observation config provenance mismatch')
    manifest = dataset_index(root, protocol)
    if output.exists() and any(output.iterdir()):
        raise ValueError('output must be fresh; refusing overwrite')
    backend = Path(__file__).resolve().parents[1]
    files = ('app/evaluation/swing_replay.py', 'app/evaluation/swing_protocol.py',
             'app/evaluation/ranking_quality_diagnosis.py', 'app/evaluation/ranking_quality_experiments.py',
             'app/services/coach_service.py', 'app/services/technical_analyzer.py', 'app/services/numeric_utils.py',
             'scripts/run_swing_benchmark.py')
    identity = dict(schema_version='swing-baseline-v1', mode='baseline',
        protocol_sha256=protocol['protocol_sha256'], dataset_sha256=manifest['dataset_sha256'],
        dataset_identity_sha256=manifest['identity_sha256'], coverage_sha256=manifest['coverage_sha256'],
        observation_sha256=observation_hash, config_sha256=digest(config), quote_recipe=QUOTE_RECIPE,
        implementation_sha256={name:hashlib.sha256((backend/name).read_bytes()).hexdigest() for name in files})
    histories = defaultdict(lambda:deque(maxlen=120))
    candidates, daily = [], []
    progress('phase=replay status=started')
    for day, value in date_files(root, manifest):
        for row in value['rows']:
            if _usable(row):
                histories[row['symbol']].append({k:row.get(k) for k in BAR_FIELDS})
        if value['role'] != 'signal' or not value['rows']:
            continue
        result = replay_day(dict(trade_date=day, rows=value['rows'], histories=histories,
            strategy_config=config, identity=protocol['identity']), protocol)
        candidates.extend(result.pop('candidates'))
        daily.append(result)
        if len(daily) % 20 == 0:
            progress(f'phase=replay signal_dates={len(daily)} candidates={len(candidates)} date={day}')
    # Free rolling all-market feature history before collecting small label paths.
    histories.clear()
    snapshots = observed.get('snapshots', [])
    for row in snapshots:
        for key, expected in protocol['identity'].items():
            if row.get(key) not in (None, expected):
                raise ValueError('observed snapshot identity mismatch')
    kept, rejected, quarantine = quarantine_ambiguous_dates(snapshots)
    observed_rows = [dict(r,baseline_kind='observed_production',
        probability_source=r.get('probability_source','legacy_unknown')) for r in kept]
    progress(f'phase=labels status=started candidates={len(candidates)+len(observed_rows)}')
    all_labeled = _label_from_stream(root, manifest, candidates+observed_rows, config)
    progress(f'phase=labels status=finished candidates={len(all_labeled)}')
    reconstructed = all_labeled[:len(candidates)]; legacy = all_labeled[len(candidates):]
    reconstructed_valid, reconstructed_validation = validate_labeled_snapshot_sample(reconstructed)
    legacy_valid, legacy_validation = validate_labeled_snapshot_sample(legacy)
    metrics = dict(reconstructed_research=baseline_metrics(reconstructed_valid,protocol),
        observed_production=baseline_metrics(legacy_valid,protocol),
        comparison_policy='within_kind_only_no_cross_kind_efficacy_subtraction',
        statistical_inference='baseline_descriptive_only_no_candidate_qualification')
    values = {'protocol.json':protocol, 'identity.json':identity,
              'daily_replay.json':daily, 'reconstructed_research.json':reconstructed,
              'observed_production.json':legacy, 'observed_quarantine.json':dict(rows=rejected, diagnostics=quarantine),
              'validation.json':dict(reconstructed_research=reconstructed_validation, observed_production=legacy_validation),
              'metrics.json':metrics}
    result = dict(identity=identity, status='research_baseline_only', production_verified=False,
        dataset_status=manifest['status'], baselines=dict(
            reconstructed_research='available', observed_production='available' if snapshots else 'empty',
            same_input_parity='independent_fixture_tests_only_no_historical_reference_inputs'),
        counts=dict(signal_dates=len(daily), reconstructed_candidates=len(candidates),
                    observed_candidates=len(snapshots), observed_quarantined=len(rejected)),
        artifacts={name:digest(value) for name,value in values.items()}, limitations=LIMITATIONS,
        formal_shadow_candidate=None, experiments_run=[], execution_run=False)
    output.mkdir(parents=True, exist_ok=True)
    for name,value in values.items():
        write_json(output/name, value)
    write_json(output/'manifest.json', result)
    progress(f'phase=baseline status=finished signal_dates={len(daily)} candidates={len(candidates)}')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', required=True)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--observation', required=True, help='Frozen content-addressed observation JSON; never DB')
    parser.add_argument('--mode', choices=['baseline'], default='baseline')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    try:
        result = run_baseline(read_json(args.protocol), args.dataset, args.observation, args.output_dir)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print('blocked: '+str(exc), file=sys.stderr)
        return 1
    print(json.dumps(dict(status=result['status'], counts=result['counts']), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
