#!/usr/bin/env python3
"""Cache-only baseline and frozen experiments; no provider, DB or ML execution."""
import argparse
from collections import defaultdict, deque
import gzip
import hashlib
import json
from pathlib import Path
import sys
from copy import deepcopy
import math

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.swing_protocol import validate_protocol
from app.evaluation.swing_replay import (BAR_FIELDS, LIMITATIONS, QUOTE_RECIPE, checked_bars, _usable,
    digest, iso_day, label_candidates, replay_day, validate_config)
from app.evaluation.ranking_quality_diagnosis import (
    quarantine_ambiguous_dates, validate_labeled_snapshot_sample)
from app.evaluation.ranking_quality_experiments import _evaluate_variant, _candidate_pool_metrics


def _fixed_pool_compute(prepared, saved, actual=False):
    from app.evaluation.swing_replay import FrozenData, FrozenStore, OfflineCoach, signal_clock
    pool = deepcopy(saved['frozen_analysis_pool'])
    if actual:
        for item in pool:
            item['quote']['turnover_rate'] = item['actual_daily_basic']['turnover_rate']
    class FixedPoolCoach(OfflineCoach):
        def _build_dynamic_candidates(self, *args, **kwargs):
            return dict(candidates=[deepcopy(item['quote']) for item in pool], meta=deepcopy(saved['funnel']))
    data, store = FrozenData(prepared), FrozenStore()
    service = FixedPoolCoach(data,store,news_service=None,ml_model_service=None)
    service.fallback_blocked = False
    try:
        with signal_clock(prepared['day']):
            now = service._now_ts(); quotes = prepared['quotes']
            service._universe_state.update(entries=deepcopy(quotes),
                entry_map={r['symbol']:deepcopy(r) for r in quotes}, last_full_refresh_ts=now,
                last_refresh_attempt_ts=now,last_incremental_refresh_ts=now)
            config = prepared['config']; risk = deepcopy(service.DEFAULT_RISK_PROFILE)
            risk.update(risk_level=config['risk_level'],max_position_pct=config['max_position_pct'])
            full,_ = service._compute_today_picks(80,prepared['identity']['user_id'],prepared['day'],
                prepared['identity']['strategy_code'],None,config,risk,config['score_threshold'])
    finally:
        service._pick_executor.shutdown(wait=True)
        if store.forbidden or data.forbidden:
            raise RuntimeError('forbidden experiment IO')
    if service.analysis_inputs != [item['quote'] for item in pool]:
        raise ValueError('fixed analysis pool changed')
    return full


def preserve_turnover_slots(rows, picks):
    """Retain unknown dropped slots for diagnostics, never manufacture a ranking."""
    from app.evaluation.ranking_quality_diagnosis import _flatten_snapshot
    original=sorted(rows,key=lambda r:r['rank_no']); by_symbol={p['symbol']:p for p in picks}
    original_ids={r['symbol'] for r in original}
    survivors=iter(sorted((r for r in original if r['symbol'] in by_symbol),key=lambda r:by_symbol[r['symbol']]['rank_no']))
    trial,changes=[],[]
    fields=('action','decision_grade','decision_executable','score_gate_status','position_pct',
            'entry_range','take_profit','stop_loss','total','raw_total','up_prob','dd_prob')
    for slot,old in enumerate(original,1):
        if old['symbol'] not in by_symbol:
            item=dict(old,_selection_unknown=True,_trial_order=slot,
                      experiment_gate_status='removed_by_original_postprocessing')
            changes.append(dict(trade_date=old['trade_date'],symbol=old['symbol'],gate_removed=True,
                                old={k:old.get(k) for k in fields},new=None))
        else:
            source=next(survivors); pick=by_symbol[source['symbol']]
            item=dict(source,**{k:v for k,v in _flatten_snapshot(pick).items()
                if k not in ('symbol','trade_date','rank_no','name')},_trial_order=slot)
            for key in ('position_pct','entry_range','take_profit','stop_loss','score_gate_status',
                        'decision','score_breakdown','model_probability','reasons','risks'):
                item[key]=deepcopy(pick.get(key))
            changed={k:dict(old=source.get(k),new=item.get(k)) for k in fields if source.get(k)!=item.get(k)}
            if changed: changes.append(dict(trade_date=source['trade_date'],symbol=source['symbol'],fields=changed))
        trial.append(item)
    return trial,changes,sorted(set(by_symbol)-original_ids)


def _turnover_trials(root, manifest, daily, rows, config, protocol, progress):
    from app.evaluation.swing_replay import prepare_inputs, decision_projection
    saved_days = {r['identity']['trade_date']:r for r in daily}
    baseline = defaultdict(list)
    for row in rows: baseline[row['trade_date']].append(row)
    pool = [(day,item) for day,saved in sorted(saved_days.items()) for item in saved['frozen_analysis_pool']]
    missing, zero, no_proxy = [], [], []
    for day,item in pool:
        value = item['actual_daily_basic'].get('turnover_rate')
        key = [day,item['quote']['symbol']]
        if type(value) not in (int,float) or not math.isfinite(value) or value<0: missing.append(key)
        elif value == 0: zero.append(key)
        if not item.get('proxy_was_used'): no_proxy.append(key)
    coverage = (len(pool)-len(missing))/len(pool) if pool else 0
    excluded = sorted({day for day,symbol in missing+zero})
    evidence = dict(field_coverage=coverage,full_sample_analysis_rows=len(pool), missing_actual=missing,
        true_zero_actual=zero, excluded_dates=excluded,unavailable_reasons=[],parity_dates=[],changes=[],
        common_complete_field_dates=sorted(set(baseline)-set(excluded)),
        slot_policy='gate removals stay unknown at original slots; survivors reorder only remaining slots; no refill',
        zero_policy='true zero retained in source; current method would reapply proxy, so whole date unavailable',
        comparison_pool='baseline displayed symbols; full frozen preanalysis pool retained for postprocessing',
        new_output_symbols_excluded=[],global_health='unverified_separate_from_candidate_executable')
    if not pool: evidence['unavailable_reasons'].append('no_frozen_analysis_pool')
    if no_proxy: evidence['unavailable_reasons'].append('proxy_was_not_used')
    if coverage < protocol['qualification']['minimum_optional_field_coverage']:
        evidence['unavailable_reasons'].append('actual_turnover_coverage_below_95pct')
    if evidence['unavailable_reasons']: return None,evidence
    histories = defaultdict(lambda:deque(maxlen=120)); trial=[]
    for day,value in date_files(root,manifest):
        for row in value['rows']:
            if _usable(row): histories[row['symbol']].append({k:row.get(k) for k in BAR_FIELDS})
        if day not in baseline or day in excluded: continue
        saved = saved_days[day]
        prepared = prepare_inputs(dict(trade_date=day,rows=value['rows'],histories=histories,
            strategy_config=config,identity=protocol['identity']),protocol)
        input_hash = digest(dict(quotes=prepared['quotes'],histories={s:df.to_dict('records')
            for s,df in prepared['histories'].items()}))
        if input_hash != saved['provenance']['input_sha256']:
            raise ValueError('frozen feature input hash mismatch')
        for item in saved['frozen_analysis_pool']:
            if item['actual_daily_basic'] != prepared['sidecars'][item['quote']['symbol']]['actual_daily_basic']:
                raise ValueError('frozen actual field differs from dataset')
        parity = _fixed_pool_compute(prepared,saved)
        if digest(decision_projection(parity['picks'])) != saved['identity']['decisions_sha256']:
            evidence['unavailable_reasons'].append('fixed_pool_postprocessing_parity_mismatch:'+day)
            return None,evidence
        evidence['parity_dates'].append(day)
        actual = _fixed_pool_compute(prepared,saved,True)
        day_trial,changes,new=preserve_turnover_slots(baseline[day],actual['picks'])
        evidence['changes'].extend(changes)
        evidence['new_output_symbols_excluded'].extend([[day,s] for s in new])
        trial.extend(day_trial)
        if new or any(r.get('_selection_unknown') for r in day_trial):
            # One frozen-contract counterexample disqualifies E2 for the run;
            # never search remaining dates for a more favorable passing subset.
            eligible=set(evidence['common_complete_field_dates'])
            evidence['early_stop']=dict(reason='first_final_pool_divergence',first_counterexample_date=day,
                tested_dates=len(evidence['parity_dates']),total_eligible_dates=len(eligible),
                untested_gate_dates=sorted(eligible-set(evidence['parity_dates'])),
                action_impact_scope='tested_dates_only_not_full_period')
            progress(f'phase=turnover status=unavailable early_stop=final_pool_divergence date={day}')
            break
        if len(evidence['parity_dates']) % 20 == 0:
            progress(f'phase=turnover parity_dates={len(evidence["parity_dates"])} date={day}')
    evidence['tested_trial_dates'] = sorted(set(r['trade_date'] for r in trial))
    changed_pool_dates=sorted({r['trade_date'] for r in trial if r.get('_selection_unknown')} |
                              {day for day,symbol in evidence['new_output_symbols_excluded']})
    evidence['changed_final_pool_dates']=changed_pool_dates
    if changed_pool_dates:
        evidence['unavailable_reasons'].append('changed_final_pool_after_original_gates_or_caps_no_safe_same_pool_ranking')
    if not trial: evidence['unavailable_reasons'].append('no_complete_field_signal_dates')
    return trial,evidence


def run_experiments(protocol, dataset, observation, baseline, output_dir, progress=None):
    from app.evaluation.ranking_quality_experiments import evaluate_swing_experiments
    from app.evaluation.ranking_quality_diagnosis import swing_diagnostics
    progress = progress or (lambda message:print(message,file=sys.stderr,flush=True))
    protocol = validate_protocol(protocol); root=Path(dataset); base=Path(baseline); output=Path(output_dir)
    if output.exists() and any(output.iterdir()): raise ValueError('output must be fresh; refusing overwrite')
    manifest = dataset_index(root,protocol); frozen=read_json(base/'manifest.json')
    artifacts = {}
    for name,expected in frozen['artifacts'].items():
        if Path(name).name != name: raise ValueError('baseline artifact path escape')
        artifacts[name]=read_json(base/name)
        if digest(artifacts[name]) != expected: raise ValueError('baseline artifact hash mismatch: '+name)
    identity = artifacts['identity.json']
    if identity != frozen['identity'] or identity['schema_version']!='swing-baseline-v1':
        raise ValueError('baseline identity mismatch')
    if artifacts['protocol.json'] != protocol: raise ValueError('baseline protocol mismatch')
    for key in ('dataset_sha256','coverage_sha256'):
        if identity[key]!=manifest[key]: raise ValueError('baseline dataset hash mismatch')
    if identity['dataset_identity_sha256']!=manifest['identity_sha256']:
        raise ValueError('baseline dataset identity mismatch')
    observed=read_json(observation); config=observed['strategy_config']
    validate_config(config,observed['identity'],protocol)
    if Path(observation).stem!=digest(observed) or identity['observation_sha256']!=digest(observed):
        raise ValueError('baseline observation hash mismatch')
    if identity['config_sha256']!=digest(config) or observed['config_sha256']!=digest(config):
        raise ValueError('baseline config hash mismatch')
    backend=Path(__file__).resolve().parents[1]
    for name,sha in identity['implementation_sha256'].items():
        # Evaluation files evolve in Task 6; all frozen replay/production code must match.
        if name.startswith('app/services/') or name in ('app/evaluation/swing_replay.py','app/evaluation/swing_protocol.py'):
            if hashlib.sha256((backend/name).read_bytes()).hexdigest()!=sha:
                raise ValueError('baseline replay implementation hash mismatch: '+name)
    rows=artifacts['reconstructed_research.json']; daily=artifacts['daily_replay.json']
    for r in rows:
        if r.get('baseline_kind')!='reconstructed_research': raise ValueError('baseline kind mismatch')
        for key,val in protocol['identity'].items():
            if r.get(key)!=val: raise ValueError('baseline candidate identity mismatch')
    rows,validation=validate_labeled_snapshot_sample(rows)
    actual_dates=[]; required=total=0
    for day,value in date_files(root,manifest):
        if value['rows']: actual_dates.append(day)
        if value['role']=='signal':
            total+=len(value['rows']); required+=sum(_usable(r) for r in value['rows'])
    e2,evidence=_turnover_trials(root,manifest,daily,rows,config,protocol,progress)
    common_dates = set(r['trade_date'] for r in e2) if e2 is not None and not evidence['unavailable_reasons'] else set(r['trade_date'] for r in rows)
    common=[r for r in rows if r['trade_date'] in common_dates]
    metrics=dict(reconstructed_research=evaluate_swing_experiments(common,protocol,actual_dates,
        e2,evidence,required/total if total else None),
        full_sample=dict(metrics=baseline_metrics(rows,protocol),signal_dates=sorted(set(r['trade_date'] for r in rows)),
            lost_dates=sorted(set(r['trade_date'] for r in rows)-common_dates),required_rows=required,total_rows=total),
        observed_production=evaluate_swing_experiments(artifacts['observed_production.json'],protocol,actual_dates),
        diagnostics=swing_diagnostics(rows,daily),comparison_policy='within_kind_only_no_cross_kind_subtraction',
        validation=validation)
    run_identity=dict(schema_version='swing-experiments-v1',mode='experiments',protocol_sha256=protocol['protocol_sha256'],
        dataset_sha256=manifest['dataset_sha256'],baseline_manifest_sha256=digest(frozen),config_sha256=digest(config),
        implementation_sha256={name:hashlib.sha256((backend/name).read_bytes()).hexdigest() for name in
            ('scripts/run_swing_benchmark.py','app/evaluation/ranking_quality_experiments.py','app/evaluation/ranking_quality_diagnosis.py')})
    values={'protocol.json':protocol,'identity.json':run_identity,'metrics.json':metrics,
            'turnover_trial.json':e2,'turnover_evidence.json':evidence}
    result=dict(identity=run_identity,status=metrics['reconstructed_research']['decision'],
        experiments_run=['E1','E2','E3'],execution_run=False,formal_shadow_candidate=None,
        counts=dict(reference_rows=len(rows),common_rows=len(common),common_dates=len(common_dates)),
        artifacts={name:digest(value) for name,value in values.items()})
    output.mkdir(parents=True,exist_ok=True)
    for name,value in values.items(): write_json(output/name,value)
    write_json(output/'manifest.json',result)
    return result


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


def _execution_artifacts(directory, schema, protocol):
    root = Path(directory); manifest = read_json(root/'manifest.json')
    values = {}
    for name, expected in manifest['artifacts'].items():
        if Path(name).name != name or (root/name).resolve().parent != root.resolve():
            raise ValueError('execution artifact path escape')
        values[name] = read_json(root/name)
        if digest(values[name]) != expected:
            raise ValueError('execution artifact hash mismatch: '+name)
    identity = values['identity.json']
    if identity != manifest['identity'] or identity['schema_version'] != schema:
        raise ValueError('execution artifact identity mismatch')
    if values['protocol.json'] != protocol or identity['protocol_sha256'] != protocol['protocol_sha256']:
        raise ValueError('execution artifact protocol mismatch')
    return manifest, values


def _execution_bundle(rows, daily, config, protocol):
    from app.evaluation.swing_replay import replay_execution
    from app.evaluation.ranking_quality_experiments import swing_segments
    segments = swing_segments(rows,protocol)
    result = dict(scenarios={},fixed_horizon_labels=_evaluate_variant(rows,'saved_label_diagnostics',
        lambda r:(r.get('_execution_order',r['rank_no']),r['symbol']))['metrics'],
        fixed_horizon_scope='saved_5_10_20_valid_bar_labels_with_ranking_costs_not_cash_equity_or_actual_holding_clock')
    intervals = dict(protocol['dates'])
    for month in range(3,9):
        import calendar
        intervals[f'walk_forward_2026-{month:02d}'] = [f'2026-{month:02d}-01',
            f'2026-{month:02d}-{calendar.monthrange(2026,month)[1]}']
    for multiplier in (1,2):
        overall = replay_execution(rows,daily,config,slippage_multiplier=multiplier)
        output = dict(overall=overall,segments={})
        for name, segment in segments.items():
            dates = set(segment['dates']); start,end = intervals[name]
            output['segments'][name] = dict(**segment, capital_policy='fresh_identical_notional_no_position_carry',
                execution=replay_execution([r for r in rows if r['trade_date'] in dates],
                    ((day,value) for day,value in daily if start<=day<=end),config,slippage_multiplier=multiplier))
        result['scenarios'][f'slippage_{multiplier}x'] = output
    return result


def _execution_challenger(rows, experiment_values):
    from app.evaluation.ranking_quality_experiments import validate_swing_pair
    research = experiment_values['metrics.json']['reconstructed_research']
    experiments = research['experiments']
    if set(experiments) != {'E1','E2','E3'}:
        raise ValueError('execution refuses new experiment variants')
    qualified = [name for name in ('E1','E2','E3') if experiments[name].get('provisional_ranking_candidate') is True]
    if not qualified:
        return None, [], [], dict(status='unavailable',reason='no_provisional_ranking_candidate',
                                 ranking_decision=research['decision'])
    name = qualified[0]; result = experiments[name]
    qualification = result.get('qualification') or {}
    if (result['status'] != 'available' or not qualification.get('checks') or
        not all(qualification['checks'].values()) or not qualification.get('evidence_available') or
        not all(qualification['evidence_available'].values()) or name == 'E3'):
        raise ValueError('unverifiable execution challenger qualification')
    dates = set(result['paired']['matched_dates'])
    if not dates:
        raise ValueError('execution challenger has no qualified matched dates')
    reference = [r for r in rows if r['trade_date'] in dates]
    if {r['trade_date'] for r in reference} != dates:
        raise ValueError('execution challenger dates absent from baseline')
    trial_source = reference if name == 'E1' else experiment_values['turnover_trial.json']
    trial = [r for r in trial_source if r['trade_date'] in dates]
    if any(r.get('config_sha256',reference[0]['config_sha256']) != reference[0]['config_sha256'] for r in trial):
        raise ValueError('execution challenger config mismatch')
    validate_swing_pair(reference,trial)
    selection = result['metrics']['slot_selection_by_date']
    orders = {}
    for day in dates:
        symbols = selection[day]
        if len(set(symbols)) != len(symbols) or set(symbols) != {r['symbol'] for r in reference if r['trade_date']==day}:
            raise ValueError('execution challenger frozen selection pool mismatch')
        orders.update({(day,symbol):rank for rank,symbol in enumerate(symbols,1)})
    trial = [dict(r,_execution_order=orders[r['trade_date'],r['symbol']],
                  config_sha256=reference[0]['config_sha256']) for r in trial]
    return name,reference,trial,dict(status='ranking_provisional_only',name=name,
        selection_rule='first_frozen_E1_E2_E3_priority_max_one_no_return_search',
        other_provisional_candidates=qualified[1:],dates=sorted(dates))


def _execution_comparison(reference, trial):
    comparisons = {}
    for scenario, base in reference['scenarios'].items():
        other = trial['scenarios'][scenario]; checks = {}
        pairs = [('overall',base['overall'],other['overall'])] + [(name,value['execution'],
            other['segments'][name]['execution']) for name,value in base['segments'].items()]
        for name,left,right in pairs:
            a,b = left['summary'],right['summary']
            checks[name] = dict(reference=a,challenger=b,
                lower_drawdown=b['raw_mark_max_drawdown_pct']<=a['raw_mark_max_drawdown_pct'],
                no_lower_return_drawdown=all(x['raw_mark_return_drawdown_ratio'] is not None for x in (a,b)) and
                    b['raw_mark_return_drawdown_ratio']>=a['raw_mark_return_drawdown_ratio'],
                positive_increment=b['raw_mark_return_pct']>max(0,a['raw_mark_return_pct']),
                evidence_bounded=left['promotable'] and right['promotable'])
        comparisons[scenario] = checks
    return dict(status='insufficient_evidence',comparisons=comparisons,
                reason='historical_fill_risk_metadata_and_unresolved_exposure_preclude_strong_execution_PASS')


def run_execution(protocol, dataset, observation, baseline, experiments, output_dir, progress=None):
    from app.evaluation.paper_trade_review import audit_paper_execution
    progress = progress or (lambda message:print(message,file=sys.stderr,flush=True))
    protocol = validate_protocol(protocol); root = Path(dataset); output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError('execution output must be fresh')
    manifest = dataset_index(root,protocol)
    baseline_manifest,base = _execution_artifacts(baseline,'swing-baseline-v1',protocol)
    experiment_manifest,trial = _execution_artifacts(experiments,'swing-experiments-v1',protocol)
    observed = read_json(observation); config = observed['strategy_config']; identity = base['identity.json']
    validate_config(config,observed['identity'],protocol)
    if (Path(observation).stem != digest(observed) or identity['observation_sha256'] != digest(observed) or
        observed['config_sha256'] != digest(config) or identity['config_sha256'] != digest(config)):
        raise ValueError('execution observation or config hash mismatch')
    for key in ('dataset_sha256','coverage_sha256'):
        if identity[key] != manifest[key]:
            raise ValueError('execution baseline dataset hash mismatch')
    if identity['dataset_identity_sha256'] != manifest['identity_sha256']:
        raise ValueError('execution dataset identity hash mismatch')
    experiment_identity = trial['identity.json']
    if (experiment_identity['baseline_manifest_sha256'] != digest(baseline_manifest) or
        experiment_identity['dataset_sha256'] != manifest['dataset_sha256'] or
        experiment_identity['config_sha256'] != digest(config)):
        raise ValueError('execution experiment baseline lineage mismatch')
    backend = Path(__file__).resolve().parents[1]
    for name,sha in identity['implementation_sha256'].items():
        if name.startswith('app/services/') or name == 'app/evaluation/swing_protocol.py':
            if hashlib.sha256((backend/name).read_bytes()).hexdigest() != sha:
                raise ValueError('execution frozen production source mismatch: '+name)
    for name in ('app/evaluation/ranking_quality_experiments.py','app/evaluation/ranking_quality_diagnosis.py'):
        if hashlib.sha256((backend/name).read_bytes()).hexdigest() != experiment_identity['implementation_sha256'][name]:
            raise ValueError('execution frozen evaluator source mismatch: '+name)
    frozen_rows = base['reconstructed_research.json']
    rows = []
    for row in frozen_rows:
        if any(row.get(k) != v for k,v in protocol['identity'].items()):
            raise ValueError('execution candidate identity mismatch')
        if row.get('config_sha256',digest(config)) != digest(config):
            raise ValueError('execution candidate config mismatch')
        # Task 5 binds config at artifact identity, not on every candidate row.
        rows.append(dict(row,config_sha256=digest(config)))
    name,reference,challenger,selection = _execution_challenger(rows,trial)
    symbols = {r['symbol'] for r in rows}; daily = []
    for day,value in date_files(root,manifest):
        if day >= protocol['dates']['research'][0] and value['rows']:
            daily.append((day,dict(rows=[{k:r.get(k) for k in BAR_FIELDS} for r in value['rows'] if r['symbol'] in symbols])))
    progress(f'phase=execution frozen_signal_rows={len(rows)} dates={len(daily)}')
    baseline_result = _execution_bundle(rows,daily,config,protocol)
    challenger_result = dict(**selection)
    if name:
        same_reference = _execution_bundle(reference,daily,config,protocol)
        same_trial = _execution_bundle(challenger,daily,config,protocol)
        challenger_result.update(reference=same_reference,trial=same_trial,
            evaluation=_execution_comparison(same_reference,same_trial))
    ranking_decision = trial['metrics.json']['reconstructed_research']['decision']
    decision = 'insufficient_evidence' if name or ranking_decision != 'no_shadow_candidate' else 'no_shadow_candidate'
    execution = dict(baseline=baseline_result,challenger=challenger_result,
        manual=audit_paper_execution(observed.get('manual_paper_trades',[]),config,protocol['identity']['user_id']),
        decision=decision,formal_shadow_candidate=None,production_authorized=False,
        observed_production='saved snapshots retained in baseline; no invented missing executable/position/score fields',
        comparison_policy='same_frozen_signals_pool_dates_capital_positions_exits_no_regeneration',
        signal_config_binding='verified_baseline_artifact_config_attached_to_execution_envelope_not_historical_asof_proof',
        limitations='research_raw_mark_diagnostics_not_verified_market_execution_or_full_A_share_strategy_validity')
    run_identity = dict(schema_version='swing-execution-v1',mode='execution',protocol_sha256=protocol['protocol_sha256'],
        baseline_manifest_sha256=digest(baseline_manifest),experiment_manifest_sha256=digest(experiment_manifest),
        dataset_sha256=manifest['dataset_sha256'],config_sha256=digest(config),observation_sha256=digest(observed),
        implementation_sha256={name:hashlib.sha256((backend/name).read_bytes()).hexdigest() for name in
            ('app/evaluation/swing_replay.py','app/evaluation/paper_trade_review.py','scripts/run_swing_benchmark.py')})
    values = {'protocol.json':protocol,'identity.json':run_identity,'execution.json':execution}
    result = dict(identity=run_identity,status=decision,formal_shadow_candidate=None,execution_run=True,
        counts=dict(reference_rows=len(rows),execution_dates=len(daily),manual_flows=len(observed.get('manual_paper_trades',[]))),
        artifacts={name:digest(value) for name,value in values.items()})
    output.mkdir(parents=True,exist_ok=True)
    for key,value in values.items(): write_json(output/key,value)
    write_json(output/'manifest.json',result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', required=True)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--observation', required=True, help='Frozen content-addressed observation JSON; never DB')
    parser.add_argument('--mode', choices=['baseline','experiments','execution'], default='baseline')
    parser.add_argument('--baseline', help='Frozen Task 5 output directory; required for experiments')
    parser.add_argument('--experiments', help='Frozen Task 6 output directory; required for execution')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == 'execution':
            if not args.baseline or not args.experiments:
                raise ValueError('--baseline and --experiments required for execution')
            result = run_execution(read_json(args.protocol),args.dataset,args.observation,args.baseline,args.experiments,args.output_dir)
        elif args.mode == 'experiments':
            if not args.baseline: raise ValueError('--baseline required for experiments')
            result = run_experiments(read_json(args.protocol),args.dataset,args.observation,args.baseline,args.output_dir)
        else:
            result = run_baseline(read_json(args.protocol), args.dataset, args.observation, args.output_dir)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print('blocked: '+str(exc), file=sys.stderr)
        return 1
    print(json.dumps(dict(status=result['status'], counts=result['counts']), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
