#!/usr/bin/env python3
"""One approved offline variable; never called by the application."""
import argparse
from collections import defaultdict, deque
import hashlib
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_swing_benchmark import (
    read_json, write_json, dataset_index, date_files, _execution_artifacts, _label_from_stream)
from app.evaluation.swing_protocol import validate_protocol
from app.evaluation.swing_replay import (
    BAR_FIELDS, _usable, digest, prepare_inputs, validate_config, replay_execution, decision_projection)
from app.evaluation.ranking_quality_experiments import swing_segments
from app.evaluation.turnover_end_to_end import (
    LABEL_FIELDS, attach_labels, compare_outputs, replay_turnover_day)


def qualification(comparison, protocol, coverage, groups):
    primary = comparison['by_horizon']['10']; paired = primary['paired']
    base = primary['baseline']; trial = primary['trial']; inference = primary['inference']
    b = base['top_k']['5']; t = trial['top_k']['5']; q = protocol['qualification']
    def greater(a,b): return a is not None and b is not None and a>b
    def not_worse(a,b): return a is not None and b is not None and a<=b
    sensitivity = paired['leave_one_contributor_out']
    states = {k:v['by_horizon']['10'] for k,v in groups['market_state'].items() if k!='unknown'}
    enough_states = sum(len(v['dates'])>=q['minimum_paired_dates'] for v in states.values())
    enough = dict(signal_dates=coverage['signal_dates']>=q['minimum_signal_dates'],
        paired_dates=len(primary['dates'])>=q['minimum_paired_dates'],
        field_coverage=coverage['actual_turnover_coverage']>=q['minimum_optional_field_coverage'],
        required_coverage=coverage['required_coverage']>=q['minimum_required_data_coverage'],
        market_states=enough_states>=q['minimum_market_states'],
        inference=inference['status']=='evaluated')
    checks = dict(median=greater(t['median_return'],b['median_return']),
        ndcg=greater(trial['ndcg_at_10'],base['ndcg_at_10']),
        excess=greater(t['relative_candidate_pool_excess_return'],b['relative_candidate_pool_excess_return']),
        severe_loss=not_worse(t['severe_loss_rate'],b['severe_loss_rate']),
        positive_net=greater(t['avg_return'],0),
        ci_positive=greater(inference['ci']['lower'],0),
        corrected_p=not_worse(inference['four_explorations_bonferroni_p'],.05),
        leave_day=sensitivity['positive_after_every_day_removal'],
        leave_symbol=sensitivity['positive_after_every_symbol_removal'],
        state_direction=bool(states) and all(not_worse(0,v['paired']['mean_daily_top5_return_difference'])
            for v in states.values() if v['dates']),
        auxiliary_no_reversal=all(not_worse(v['baseline']['top_k'][str(k)]['avg_return'],v['trial']['top_k'][str(k)]['avg_return'])
            and not_worse(v['trial']['top_k'][str(k)]['severe_loss_rate'],v['baseline']['top_k'][str(k)]['severe_loss_rate'])
            for h,v in comparison['by_horizon'].items() for k in (3,5,10) if (h,k)!=('10',5)))
    status = ('insufficient_evidence' if not all(enough.values()) else
              'ranking_checks_pass_execution_not_verified' if all(checks.values()) else 'no_shadow_candidate')
    return dict(decision=status,availability=enough,checks=checks,formal_shadow_candidate=None,
        source_sensitivity='identical_all_tushare_not_independent_confirmation',
        historical_status='all_intervals_previously_examined_no_unseen_claim',
        production_authorized=False)


def verified_replay_pair(paths, identity):
    """Only accept two byte-identical independently produced signal streams."""
    if len(paths)!=2 or Path(paths[0]).resolve()==Path(paths[1]).resolve():
        raise ValueError('two distinct replay directories required')
    identities=[read_json(Path(p)/'identity.json') for p in paths]
    if identities[0]!=identities[1]: raise ValueError('independent replay identity mismatch')
    previous=identities[0]
    for key,value in identity.items():
        if key=='implementation_sha256':
            for name,sha in value.items():
                approved={sha}
                if name=='scripts/run_turnover_end_to_end.py':
                    # Original signal producer at commit 137aeb3, before recovery support.
                    approved.add('ac4668c55a9d7e0c384d5340f72a752f7fbe99d6da9b5ef625b0be6aa47f144d')
                if previous[key].get(name) not in approved:
                    raise ValueError('replay producer source mismatch: '+name)
        elif previous.get(key)!=value: raise ValueError('replay lineage mismatch: '+key)
    names=[sorted(p.name for p in (Path(root)/'days').glob('*.json')) for root in paths]
    if names[0]!=names[1] or not names[0]: raise ValueError('independent replay date mismatch')
    days={}; hashes={}
    for name in names[0]:
        first=(Path(paths[0])/'days'/name).read_bytes()
        if first!=(Path(paths[1])/'days'/name).read_bytes():
            raise ValueError('independent replay mismatch: '+name)
        days[name[:-5]]=read_json(Path(paths[0])/'days'/name)
        hashes[name]=hashlib.sha256(first).hexdigest()
    return days,dict(producer_identity_sha256=digest(previous),daily_file_sha256=hashes,
                     method='two_independent_byte_identical_replays_no_signal_regeneration')


def run(protocol, dataset, observation, baseline, output_dir, progress=None, replay_pair=None):
    progress = progress or (lambda message:print(message,file=sys.stderr,flush=True))
    protocol = validate_protocol(protocol); root=Path(dataset); out=Path(output_dir)
    if out.exists() and any(out.iterdir()): raise ValueError('output must be fresh')
    dataset_manifest=dataset_index(root,protocol)
    base_manifest,base=_execution_artifacts(baseline,'swing-baseline-v1',protocol)
    observed=read_json(observation); config=observed['strategy_config']; identity=base['identity.json']
    validate_config(config,observed['identity'],protocol)
    if (Path(observation).stem!=digest(observed) or identity['observation_sha256']!=digest(observed)
        or observed['config_sha256']!=digest(config) or identity['config_sha256']!=digest(config)):
        raise ValueError('observation/config identity mismatch')
    for key in ('dataset_sha256','coverage_sha256'):
        if identity[key]!=dataset_manifest[key]: raise ValueError('dataset lineage mismatch')
    if identity['dataset_identity_sha256']!=dataset_manifest['identity_sha256']:
        raise ValueError('dataset identity mismatch')
    backend=Path(__file__).resolve().parents[1]
    for name,sha in identity['implementation_sha256'].items():
        if name.startswith('app/services/') or name=='app/evaluation/swing_protocol.py':
            if hashlib.sha256((backend/name).read_bytes()).hexdigest()!=sha:
                raise ValueError('frozen production source mismatch: '+name)
    saved_days={r['identity']['trade_date']:r for r in base['daily_replay.json']}
    if len(saved_days)!=len(base['daily_replay.json']): raise ValueError('duplicate frozen day')
    files=sorted(set(identity['implementation_sha256']) | {
        'scripts/run_turnover_end_to_end.py','app/evaluation/turnover_end_to_end.py'})
    run_identity=dict(schema_version='turnover-end-to-end-v1',variable='same_day_actual_turnover_only',
        protocol_sha256=protocol['protocol_sha256'],baseline_manifest_sha256=digest(base_manifest),
        dataset_sha256=dataset_manifest['dataset_sha256'],observation_sha256=digest(observed),
        config_sha256=digest(config),
        implementation_sha256={name:hashlib.sha256((backend/name).read_bytes()).hexdigest() for name in files})
    restored={}
    if replay_pair:
        restored,proof=verified_replay_pair(replay_pair,run_identity)
        run_identity['verified_replay_pair']=proof
    out.mkdir(parents=True); (out/'days').mkdir(); write_json(out/'identity.json',run_identity)
    histories=defaultdict(lambda:deque(maxlen=120)); candidates=[]; pool=[]; evidence=[]; excluded={}
    actual_dates=[]; required=total=actual_ok=actual_total=0
    for day,value in date_files(root,dataset_manifest):
        if value['rows']: actual_dates.append(day)
        if not replay_pair:
            for row in value['rows']:
                if _usable(row): histories[row['symbol']].append({k:row.get(k) for k in BAR_FIELDS})
        if value['role']!='signal' or not value['rows']: continue
        if day not in saved_days: raise ValueError('signal missing frozen baseline')
        saved=saved_days[day]; frozen_pool=saved['frozen_analysis_pool']
        total+=len(value['rows']); required+=sum(_usable(r) for r in value['rows'])
        missing=[]
        for item in frozen_pool:
            rate=item['actual_daily_basic'].get('turnover_rate'); actual_total+=1
            if type(rate) in (int,float) and math.isfinite(rate) and rate>0: actual_ok+=1
            else: missing.append(item['quote']['symbol'])
        if missing or not frozen_pool:
            excluded[day]=dict(reason='missing_or_nonpositive_actual_turnover' if missing else 'empty_preanalysis_pool',symbols=missing)
            continue
        if replay_pair:
            checkpoint=restored.pop(day,None)
            if checkpoint is None: raise ValueError('replay missing eligible day: '+day)
            picks,proof=checkpoint['picks'],checkpoint['proof']
            if (proof['trade_date']!=day or proof['baseline_parity'] is not True or
                proof['input_sha256']!=saved['provenance']['input_sha256'] or
                proof['reference_decisions_sha256']!=saved['identity']['decisions_sha256'] or
                proof['trial_decisions_sha256']!=digest(decision_projection(picks))):
                raise ValueError('saved replay proof mismatch: '+day)
            sidecars={item['quote']['symbol']:{k:v for k,v in item.items()
                if k not in ('quote','proxy_was_used','turnover_recipe')} for item in frozen_pool}
            for pick in picks:
                if pick['trade_date']!=day or any(pick.get(k)!=v for k,v in protocol['identity'].items()):
                    raise ValueError('saved replay candidate identity mismatch')
        else:
            prepared=prepare_inputs(dict(trade_date=day,rows=value['rows'],histories=histories,
                strategy_config=config,identity=protocol['identity']),protocol)
            picks,proof=replay_turnover_day(prepared,saved)
            sidecars=prepared['sidecars']
        candidates.extend(picks); evidence.append(proof)
        for i,item in enumerate(frozen_pool,1):
            pool.append(dict(symbol=item['quote']['symbol'],trade_date=day,rank_no=i,
                **protocol['identity'],baseline_kind='reconstructed_research',
                market_state=saved['market_state'],**sidecars[item['quote']['symbol']]))
        # Per-day proof survives interruption; it is not a completed run manifest.
        write_json(out/'days'/(day+'.json'),dict(proof=proof,picks=picks))
        if len(evidence)%10==0:
            progress(f'phase=replay dates={len(evidence)}/{len(saved_days)} date={day} trial_rows={len(candidates)}')
    histories.clear()
    if restored: raise ValueError('unexpected replay dates')
    if not pool: raise ValueError('no eligible preanalysis dates')
    progress(f'phase=labels preanalysis_rows={len(pool)}')
    labels=_label_from_stream(root,dataset_manifest,pool,config)
    trial=attach_labels(candidates,labels)
    accepted={r['trade_date'] for r in pool}
    reference=[dict(r,config_sha256=digest(config)) for r in base['reconstructed_research.json'] if r['trade_date'] in accepted]
    label_index={(r['trade_date'],r['symbol']):r for r in labels}
    for row in reference:
        if any(row.get(k)!=label_index[(row['trade_date'],row['symbol'])].get(k) for k in LABEL_FIELDS):
            raise ValueError('reference forward label drift')
    progress('phase=metrics status=started')
    comparison=compare_outputs(reference,trial,labels,actual_dates)
    segments=swing_segments(labels,protocol)
    segment_metrics={}
    for name,meta in segments.items():
        dates=set(meta['dates'])
        segment_metrics[name]=dict(**meta,comparison=compare_outputs(
            *[[r for r in rows if r['trade_date'] in dates] for rows in (reference,trial,labels)],actual_dates,infer=False))
    groups=dict(action={},market_state={})
    for action in ('buy','watch'):
        groups['action'][action]=compare_outputs(*[[r for r in rows if r.get('action')==action]
            for rows in (reference,trial)],labels,actual_dates,infer=False)
    primary_dates=set(comparison['by_horizon']['10']['dates'])
    for state in sorted({r.get('market_state_tag','unknown') for r in labels}):
        dates={r['trade_date'] for r in labels if r.get('market_state_tag','unknown')==state} & primary_dates
        groups['market_state'][state]=compare_outputs(*[[r for r in rows if r['trade_date'] in dates]
            for rows in (reference,trial,labels)],actual_dates,infer=False)
    coverage=dict(signal_dates=len(saved_days),evaluated_signal_dates=len(evidence),excluded_dates=excluded,
        actual_turnover_rows=actual_total,actual_turnover_coverage=actual_ok/actual_total if actual_total else 0,
        required_coverage=required/total if total else 0)
    decision=qualification(comparison,protocol,coverage,groups)
    metrics=dict(comparison=comparison,segments=segment_metrics,groups=groups,coverage=coverage,**decision,
        action_group_scope='endogenous_output_subsets_not_fixed_gate_causal_comparison')
    for name,value in {'trial.json':trial,'pool.json':labels,'evidence.json':evidence,'metrics.json':metrics}.items():
        write_json(out/name,value)
    progress('phase=execution status=started')
    symbols={r['symbol'] for r in reference+trial}; daily=[]
    for day,value in date_files(root,dataset_manifest):
        if day>=protocol['dates']['research'][0] and value['rows']:
            daily.append((day,dict(rows=[{k:r.get(k) for k in BAR_FIELDS} for r in value['rows'] if r['symbol'] in symbols])))
    execution={}
    for multiplier in (1,2):
        scenario={}
        for name,rows in (('baseline',reference),('trial',trial)):
            item=dict(overall=replay_execution(rows,daily,config,slippage_multiplier=multiplier),segments={})
            for segment,meta in segments.items():
                dates=set(meta['dates'])
                if segment.startswith('walk_forward_'):
                    prefix=segment[len('walk_forward_'):]; start=prefix+'-01'; end=prefix+'-31'
                else: start,end=protocol['dates'][segment]
                item['segments'][segment]=replay_execution([r for r in rows if r['trade_date'] in dates],
                    ((d,v) for d,v in daily if start<=d<=end),config,slippage_multiplier=multiplier)
            scenario[name]=item
        execution[f'slippage_{multiplier}x']=scenario
    write_json(out/'execution.json',execution)
    values={'identity.json':run_identity,'protocol.json':protocol,'metrics.json':metrics,'trial.json':trial,
        'pool.json':labels,'evidence.json':evidence,'execution.json':execution}
    result=dict(identity=run_identity,status=decision['decision'],formal_shadow_candidate=None,
        production_authorized=False,counts=dict(parity_dates=len(evidence),pool_rows=len(labels),
            reference_rows=len(reference),trial_rows=len(trial)),
        execution_scope='unchanged_research_ledger_unresolved_corporate_actions_preclude_verified_strategy_claim',
        artifacts={name:digest(value) for name,value in values.items()})
    for name,value in values.items():
        if (out/name).exists():
            if digest(read_json(out/name))!=digest(value): raise ValueError('partial artifact changed: '+name)
        else: write_json(out/name,value)
    write_json(out/'progress.json',dict(status='finished',counts=result['counts']))
    write_json(out/'manifest.json',result)
    progress('phase=complete status='+result['status'])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('protocol','dataset','observation','baseline','output-dir'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--replay-pair',nargs=2,metavar=('FIRST','SECOND'))
    args=parser.parse_args()
    result=run(read_json(args.protocol),args.dataset,args.observation,args.baseline,args.output_dir,
               replay_pair=args.replay_pair)
    print(result['status'])


if __name__=='__main__': main()
