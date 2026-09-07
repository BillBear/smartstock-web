import copy
import math
import unittest

from app.evaluation.ranking_quality_experiments import (
    _bootstrap_ci, _paired_top5_comparison, _shadow_selection,
    run_ranking_experiments,
)
from scripts.analyze_ranking_quality import resolve_existing_dd_prob_veto_threshold


def _row(trade_date, symbol, rank_no, dd_prob, risk_adjusted, return_10d, action="watch", source="TuShare"):
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "rank_no": rank_no,
        "dd_prob": dd_prob,
        "risk_adjusted": risk_adjusted,
        "action": action,
        "history_source": source,
        "tradable_label": "tradable",
        "future_return_5d": return_10d / 2,
        "future_return_10d": return_10d,
        "future_return_20d": return_10d * 1.5,
    }


class RankingQualityExperimentTests(unittest.TestCase):
    def _swing_fixture(self, count=130, spacing=1):
        from datetime import date, timedelta
        from tests.test_swing_replay import PROTOCOL
        import json
        start = date(2025, 1, 1)
        dates = [(start + timedelta(days=i)).isoformat() for i in range(count * spacing)]
        rows = [dict(_row(day, str(rank), rank, .2, rank, rank),
                     probability_source='rule', baseline_kind='reconstructed_research',
                     market_state_tag='bull' if n < 60 else 'neutral',
                     label_end_dates={'20': day})
                for n, day in enumerate(dates[::spacing]) for rank in range(1, 7)]
        return rows, json.loads(PROTOCOL.read_text()), dates

    def _e3_trace_rows(self, dates=("2026-07-01", "2026-07-02")):
        rows = []
        for trade_date in dates:
            for rank in range(1, 7):
                raw_total = 77.0 - rank
                up_prob = 0.75 - rank * 0.03
                dd_prob = 0.14 + rank * 0.02
                relative_score = 48.0 + (6.5 - rank) / 6.0 * 24.0
                quality_score = (
                    up_prob * 100.0 * 0.22
                    + (1.0 - dd_prob) * 100.0 * 0.20
                    + 50.0 * 0.20
                    + 61.0 * 0.24
                    + 53.8 * 0.14
                )
                bonus = 3.0 if dd_prob <= 0.20 else 2.0
                total = round(raw_total * 0.34 + quality_score * 0.46 + relative_score * 0.20 + bonus, 2)
                row = dict(
                    _row(trade_date, str(rank), rank, dd_prob, 50.0, float(rank)),
                    baseline_kind="observed_production",
                    probability_source="ml_fusion_trace_v1",
                    market_state_tag="neutral",
                    label_end_dates={"20": trade_date},
                    raw_total=raw_total,
                    total=total,
                    up_prob=up_prob,
                    expected_edge_pct=2.0,
                    profit_factor_proxy=1.4,
                    confidence_level="medium",
                    main_net_inflow_yi=0.0,
                    ml_fusion_trace={
                        "schema_version": "ml_fusion_trace_v2",
                        "status": "applied",
                        "rule": {
                            "up_prob": 0.42 + rank * 0.04,
                            "dd_prob": 0.42 - rank * 0.025,
                            "total_score": 44.0 + rank,
                        },
                        "fused": {"up_prob": up_prob, "dd_prob": dd_prob, "total_score": raw_total},
                        "ranking_inputs": {
                            "risk_level": "medium",
                            "selection_action": "watch",
                            "confidence_level": "medium",
                            "expected_edge_pct": 2.0,
                            "profit_factor_proxy": 1.4,
                            "risk_adjusted_score": 50.0,
                            "main_net_inflow_yi": 0.0,
                            "market_state_tag": "neutral",
                        },
                        "ranking": {"raw_total": raw_total, "total": total},
                    },
                )
                rows.append(row)
        return rows

    def test_e3_replays_rule_ranking_only_for_whole_dates_with_complete_trace(self):
        from app.evaluation.ranking_quality_experiments import build_e3_rule_trial

        rows = self._e3_trace_rows()
        del rows[0]["ml_fusion_trace"]
        trial = build_e3_rule_trial(rows)

        self.assertEqual(trial["unavailable_reasons"], [])
        self.assertEqual(trial["trace_diagnostics"]["included_dates"], ["2026-07-02"])
        self.assertEqual(trial["trace_diagnostics"]["excluded_dates"][0]["trade_date"], "2026-07-01")
        self.assertEqual(trial["trace_diagnostics"]["excluded_dates"][0]["reason"], "incomplete_ml_fusion_trace")
        self.assertEqual(
            [row["symbol"] for row in trial["rows"] if row["trade_date"] == "2026-07-02"],
            ["6", "5", "4", "3", "2", "1"],
        )
        self.assertEqual(
            {(row["trade_date"], row["symbol"]) for row in trial["rows"]},
            {("2026-07-02", str(rank)) for rank in range(1, 7)},
        )

    def test_e3_is_available_when_complete_trace_replays_same_pool(self):
        from app.evaluation.ranking_quality_experiments import evaluate_swing_experiments
        from tests.test_swing_replay import PROTOCOL
        import json

        rows = self._e3_trace_rows(dates=("2026-07-01",))
        result = evaluate_swing_experiments(rows, json.loads(PROTOCOL.read_text()), ["2026-07-01"], required_coverage=1)

        e3 = result["experiments"]["E3"]
        self.assertEqual(e3["status"], "available")
        self.assertEqual(e3["metrics"]["selection_by_date"]["2026-07-01"], ["6", "5", "4", "3", "2", "1"])
        self.assertEqual(e3["trace_diagnostics"]["included_dates"], ["2026-07-01"])

    def test_e3_rejects_invalid_stored_rank_without_repairing_it(self):
        from app.evaluation.ranking_quality_experiments import build_e3_rule_trial

        rows = self._e3_trace_rows(dates=("2026-07-01",))
        rows[0]["rank_no"] = "not-a-rank"
        trial = build_e3_rule_trial(rows)

        self.assertEqual(trial["rows"], [])
        self.assertEqual(trial["unavailable_reasons"], ["no_complete_ml_fusion_trace_dates"])
        self.assertEqual(
            trial["trace_diagnostics"]["excluded_dates"][0]["reason_counts"],
            {"stored_rank_no_invalid": 1},
        )

    def test_missing_contiguous_blocks_is_insufficient_not_negative_evidence(self):
        from app.evaluation.ranking_quality_experiments import evaluate_swing_experiments
        rows, protocol, dates = self._swing_fixture(spacing=2)
        result = evaluate_swing_experiments(rows, protocol, dates, required_coverage=1)
        trial = result['experiments']['E1']
        self.assertEqual(trial['paired']['statistics_by_horizon']['10']['status'], 'insufficient_blocks')
        self.assertEqual(trial['decision'], 'insufficient_evidence')
        self.assertEqual(result['decision'], 'insufficient_evidence')

    def test_qualification_groups_cannot_reintroduce_incomplete_primary_date(self):
        from app.evaluation.ranking_quality_experiments import evaluate_swing_experiments
        rows, protocol, dates = self._swing_fixture(count=2)
        for row in rows:
            row['dd_prob'] = .9 - row['rank_no'] / 100
        rows[-1]['future_return_10d'] = None
        rows[-1]['history_source'] = 'AKShare'
        result = evaluate_swing_experiments(rows, protocol, dates)['experiments']['E1']
        self.assertEqual(result['paired']['matched_dates'], dates[:1])
        self.assertEqual(result['groups']['source']['tushare_only']['paired']['matched_dates'], dates)
        evidence = result['qualification'].get('group_evidence', {})
        self.assertEqual(evidence.get('source', {}).get('tushare_only', {}).get('dates'), dates[:1])
        self.assertEqual(evidence.get('market_state', {}).get('bull', {}).get('dates'), dates[:1])

    def test_sparse_third_state_does_not_remove_two_adequate_states(self):
        from app.evaluation.ranking_quality_experiments import evaluate_swing_experiments
        rows, protocol, dates = self._swing_fixture(count=121)
        for row in rows[-6:]:
            row['market_state_tag'] = 'bear'
        result = evaluate_swing_experiments(rows, protocol, dates, required_coverage=1)['experiments']['E1']
        qualification = result['qualification']
        self.assertTrue(qualification['checks']['market_state_coverage'])
        self.assertEqual(qualification['adequate_market_states'], ['bull', 'neutral'])
        self.assertEqual(qualification['sparse_market_states'], {'bear': 1})

    def test_missing_auxiliary_outcomes_is_insufficient_evidence(self):
        from app.evaluation.ranking_quality_experiments import evaluate_swing_experiments
        rows, protocol, dates = self._swing_fixture()
        for row in rows:
            row['future_return_20d'] = None
        result = evaluate_swing_experiments(rows, protocol, dates, required_coverage=1)['experiments']['E1']
        self.assertEqual(result['decision'], 'insufficient_evidence')

    def test_state_only_outside_primary_dates_is_descriptive_not_a_gate(self):
        from app.evaluation.ranking_quality_experiments import evaluate_swing_experiments
        rows, protocol, dates = self._swing_fixture(count=121)
        for row in rows[-6:]:
            row['market_state_tag'] = 'bear'
        rows[-1]['future_return_10d'] = None
        result = evaluate_swing_experiments(rows, protocol, dates, required_coverage=1)['experiments']['E1']
        self.assertEqual(result['paired']['matched_date_count'], 120)
        self.assertEqual(result['qualification']['group_evidence']['market_state']['bear']['dates'], [])
        self.assertTrue(result['qualification']['evidence_available']['market_states'])
        self.assertEqual(result['decision'], 'no_shadow_candidate')

    def test_adequate_null_improvement_is_no_shadow_not_an_execution_pass(self):
        import app.evaluation.ranking_quality_experiments as module
        from tests.test_swing_replay import PROTOCOL
        from datetime import date,timedelta
        import json
        dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(130)]
        rows=[dict(_row(day,str(i),i,.2,i,i),probability_source='rule',baseline_kind='reconstructed_research',
            feature_bar_count=120,market_state_tag='bull' if n<65 else 'neutral',
            label_end_dates={'20':(date.fromisoformat(day)+timedelta(days=20)).isoformat()})
            for n,day in enumerate(dates) for i in range(1,7)]
        result=module.evaluate_swing_experiments(rows,json.loads(PROTOCOL.read_text()),dates,required_coverage=1)
        self.assertEqual(result['decision'],'no_shadow_candidate')
        self.assertEqual(result['experiments']['E1']['holm']['p_value'],1)
        self.assertIsNone(result['formal_shadow_candidate'])
        self.assertFalse(result['execution_run'])

    def test_swing_purge_uses_actual_end_whole_dates_and_ties_keep_original_rank(self):
        import app.evaluation.ranking_quality_experiments as module
        from tests.test_swing_replay import PROTOCOL
        import json
        protocol=json.loads(PROTOCOL.read_text())
        rows=[dict(_row('2026-02-27',str(i),i,.2,i,i),baseline_kind='reconstructed_research',
            probability_source='rule',label_end_dates={'20':'2026-03-01' if i==1 else '2026-02-28'}) for i in range(1,3)]
        segments=module.swing_segments(rows,protocol)
        self.assertEqual(segments['validation']['dates'],[])
        rows[0]['label_end_dates']['20']='2026-02-28'
        self.assertEqual(module.swing_segments(rows,protocol)['validation']['dates'],['2026-02-27'])
        result=module.evaluate_swing_experiments(rows,protocol,['2026-02-27'])
        self.assertEqual(result['experiments']['E1']['metrics']['selection_by_date']['2026-02-27'],['1','2'])

    def test_incomplete_pool_narrows_all_primary_statistics_to_same_dates(self):
        import app.evaluation.ranking_quality_experiments as module
        from tests.test_swing_replay import PROTOCOL
        import json
        rows=[dict(_row(day,str(i),i,.9-i/100,i,i),probability_source='rule',
            baseline_kind='reconstructed_research') for day in ('2026-07-01','2026-07-02') for i in range(1,7)]
        rows[-1]['future_return_10d']=None
        r=module.evaluate_swing_experiments(rows,json.loads(PROTOCOL.read_text()),['2026-07-01','2026-07-02'])['experiments']['E1']
        self.assertEqual(r['paired']['matched_dates'],['2026-07-01'])
        self.assertEqual(list(r['paired']['statistics_by_horizon']['10']['daily_deltas']),['2026-07-01'])
        self.assertEqual(list(r['sensitivity']['day_removed_mean_deltas']),['2026-07-01'])
        self.assertFalse(r['provisional_ranking_candidate'])
        self.assertIn('auxiliary_same_date_metrics',r['paired'])
        self.assertEqual(r['paired']['auxiliary_same_date_metrics']['10']['3']['dates'],['2026-07-01'])

    def test_daily_rank_metrics_do_not_weight_large_date_more_and_report_slots(self):
        from app.evaluation.ranking_quality_experiments import _evaluate_variant
        rows=[_row('2026-07-01',str(i),i,.2,i,i) for i in range(1,7)]
        rows += [_row('2026-07-02',str(i),i,.2,i,-i) for i in range(1,4)]
        result=_evaluate_variant(rows,'baseline',lambda r:(r['rank_no'],r['symbol']))['metrics']['10']
        self.assertIn('daily_equal_weight_spearman',result)
        self.assertEqual(result['daily_equal_weight_spearman'],0)
        self.assertEqual(result['top_k']['5']['planned_slots'],8)
        self.assertEqual(result['top_k']['5']['observed_slots'],8)

    def test_frozen_swing_e1_preserves_labels_slots_and_probability_scale(self):
        import app.evaluation.ranking_quality_experiments as module
        from tests.test_swing_replay import PROTOCOL
        import json
        self.assertTrue(hasattr(module, 'evaluate_swing_experiments'))
        rows = [dict(_row('2026-07-01', str(i), i, .9-i/100, i, i),
                     probability_source='rule', baseline_kind='reconstructed_research',
                     label_end_dates={'20':'2026-07-29'}) for i in range(1, 7)]
        original = copy.deepcopy(rows)
        result = module.evaluate_swing_experiments(rows, json.loads(PROTOCOL.read_text()),
                                                  ['2026-07-01'])
        self.assertEqual(rows, original)
        self.assertEqual(set(result['experiments']), {'E1','E2','E3'})
        self.assertEqual(result['experiments']['E1']['metrics']['selection_by_date']['2026-07-01'],
                         ['6','5','4','3','2','1'])
        self.assertEqual(result['experiments']['E3']['status'], 'unavailable')
        self.assertEqual(result['experiments']['E3']['holm']['p_value'], 1)
        self.assertEqual(result['decision'], 'insufficient_evidence')
        rows[0]['probability_source'] = 'ml'
        result = module.evaluate_swing_experiments(rows, json.loads(PROTOCOL.read_text()), ['2026-07-01'])
        self.assertEqual(result['experiments']['E1']['status'], 'unavailable')

    def test_block_inference_does_not_bridge_missing_dates_and_holm_keeps_null_family(self):
        import app.evaluation.ranking_quality_experiments as module
        self.assertTrue(hasattr(module, 'swing_block_inference'))
        index = [f'2026-07-{i:02d}' for i in range(1, 32)]
        deltas = {day:1.0 for i, day in enumerate(index) if i != 15}
        result = module.swing_block_inference(deltas, index, 10)
        self.assertEqual(result['run_lengths'], [15,15])
        self.assertEqual(result['block_count'], 2)
        self.assertIsNone(result['p_value'])
        result = module.swing_block_inference(dict.fromkeys(index, 1.0), index, 10)
        self.assertGreater(result['p_value'], 0)
        self.assertNotEqual(result['p_value'], result.get('bootstrap_negative_fraction', 0))
        corrected = module.swing_holm({'E1':.02, 'E2':None, 'E3':None})
        self.assertAlmostEqual(corrected['E1']['adjusted_p'], .06)
        self.assertFalse(corrected['E1']['reject'])

    def test_swing_comparison_rejects_pool_label_identity_drift(self):
        import app.evaluation.ranking_quality_experiments as module
        self.assertTrue(hasattr(module, 'validate_swing_pair'))
        rows = [dict(_row('2026-07-01', '000001', 1, .2, 1, 2), baseline_kind='reconstructed_research')]
        module.validate_swing_pair(rows, copy.deepcopy(rows))
        for key,value in [('symbol','000002'), ('future_return_10d',3), ('baseline_kind','observed_production')]:
            changed = copy.deepcopy(rows); changed[0][key] = value
            with self.assertRaises(ValueError): module.validate_swing_pair(rows, changed)

    def test_qualification_sensitivity_uses_same_full_pool_dates(self):
        rows = [_row(date, str(i), i, .2, 10-i, i)
                for date in ("2026-07-01", "2026-07-02") for i in range(1, 7)]
        rows[-1]["future_return_10d"] = None
        paired = self._experiments(rows)["A_dd_prob_ascending"]["paired_comparison"]
        self.assertEqual(paired["matched_date_count"], 2)
        self.assertEqual(paired["qualification"]["matched_dates"], ["2026-07-01"])
        self.assertEqual(list(paired["qualification"]["leave_one_contributor_out"]["day_removed_mean_deltas"]), ["2026-07-01"])

    def _experiments(self, rows, source="all_sources"):
        return run_ranking_experiments(rows, 0.30, "existing_rule", 100, 7)["segments"][source]["all_candidates"]["experiments"]

    def test_veto_preserves_slots_and_original_pool(self):
        rows = [_row("2026-07-01", str(i), i, .5 if i == 1 else .2, i, i) for i in range(1, 12)]
        experiments = self._experiments(rows)
        baseline = experiments["baseline_current_rank"]
        veto = experiments["C_dd_prob_veto"]
        top5 = veto["metrics"]["10"]["top_k"]["5"]
        self.assertEqual(top5["avg_return"], (0 + 2 + 3 + 4 + 5) / 5)
        self.assertEqual(top5["candidate_count"], 4)
        self.assertEqual(top5["relative_candidate_pool_excess_return"], -3.2)
        self.assertEqual(veto["slot_selection_by_date"]["2026-07-01"][:6], [None, "2", "3", "4", "5", "6"])
        self.assertLess(veto["metrics"]["10"]["ndcg_at_10"], baseline["metrics"]["10"]["ndcg_at_10"])
        dcg = sum(value / math.log2(index + 2) for index, value in enumerate([0] + list(range(2, 11))))
        ideal = sum(value / math.log2(index + 2) for index, value in enumerate(range(11, 1, -1)))
        self.assertEqual(veto["metrics"]["10"]["ndcg_at_10"], round(dcg / ideal, 6))

    def test_all_veto_day_remains_zero_cash_return(self):
        rows = [_row("2026-07-01", str(i), i, .5, i, -i) for i in range(1, 7)]
        veto = self._experiments(rows)["C_dd_prob_veto"]
        self.assertEqual(veto["_daily_top5_returns"], {"2026-07-01": 0.0})
        self.assertEqual(veto["metrics"]["10"]["top_k"]["5"]["avg_return"], 0.0)
        self.assertEqual(veto["paired_comparison"]["matched_date_count"], 1)

    def test_missing_label_does_not_promote_rank_six(self):
        rows = [_row("2026-07-01", str(i), i, .2, 10-i, i) for i in range(1, 7)]
        rows[0]["future_return_10d"] = None
        baseline = self._experiments(rows)["baseline_current_rank"]
        top5 = baseline["metrics"]["10"]["top_k"]["5"]
        self.assertIsNone(top5["avg_return"])
        self.assertEqual(top5["complete_date_count"], 0)
        self.assertEqual(top5["incomplete_date_count"], 1)
        self.assertEqual(baseline["_daily_top5_returns"], {})
        self.assertEqual(baseline["selection_by_date"]["2026-07-01"], [str(i) for i in range(1, 7)])

    def test_missing_pool_label_disables_pool_metrics_not_complete_top5(self):
        rows = [_row("2026-07-01", str(i), i, .2, i, i) for i in range(1, 7)]
        rows[-1]["future_return_10d"] = None
        baseline = self._experiments(rows)["baseline_current_rank"]
        metrics = baseline["metrics"]["10"]
        self.assertEqual(metrics["top_k"]["5"]["avg_return"], 3.0)
        self.assertIsNone(metrics["top_k"]["5"]["relative_candidate_pool_excess_return"])
        self.assertIsNone(metrics["ndcg_at_10"])

    def test_pairing_excludes_missing_top_slot_even_when_trial_is_complete(self):
        rows = [_row(date, str(i), i, .2, i, i) for date in ("2026-07-01", "2026-07-02") for i in range(1, 7)]
        rows[0]["future_return_10d"] = None
        experiment = self._experiments(rows)["B_risk_adjusted_descending"]
        paired = experiment["paired_comparison"]
        self.assertEqual(paired["matched_dates"], ["2026-07-02"])
        self.assertEqual(paired["experiment_only_date_count"], 1)
        self.assertEqual(paired["paired_primary_metrics"]["matched_dates"], ["2026-07-02"])

    def test_rank_variants_cannot_invent_missing_sort_features(self):
        for feature, variant in (("dd_prob", "A_dd_prob_ascending"), ("risk_adjusted", "B_risk_adjusted_descending")):
            rows = [_row("2026-07-01", str(i), i, .2, i, i) for i in range(1, 7)]
            rows[0][feature] = None
            result = self._experiments(rows)[variant]
            self.assertEqual(result["status"], "unavailable", feature)
            self.assertIn(feature, result["reason"])

    def test_return_contributions_keep_original_slot_weights_under_veto(self):
        rows = [_row("2026-07-01", str(i), i, .5 if i == 1 else .2, i, i) for i in range(1, 7)]
        experiments = self._experiments(rows)
        veto = experiments["C_dd_prob_veto"]
        self.assertEqual(veto["_daily_top5_contributions"]["2026-07-01"], {"2": .4, "3": .6, "4": .8, "5": 1.0})
        self.assertEqual(veto["paired_comparison"]["leave_one_contributor_out"]["symbol_removed_mean_deltas"]["1"], 0.0)

    def test_empty_sample_is_insufficient_not_a_zero_return_result(self):
        result = run_ranking_experiments([], .3, "existing", 100, 7)
        self.assertEqual(result["shadow_selection"]["status"], "insufficient_evidence")
        baseline = result["segments"]["all_sources"]["all_candidates"]["experiments"]["baseline_current_rank"]
        self.assertIsNone(baseline["metrics"]["10"]["top_k"]["5"]["avg_return"])

    def test_paired_primary_criteria_ignore_unmatched_high_return_day(self):
        rows = [_row(date, str(i), i, .2, i, i) for date in ("2026-07-01", "2026-07-02") for i in range(1, 7)]
        rows[0]["future_return_10d"] = None
        rows[5]["future_return_10d"] = 10000
        trial = self._experiments(rows)["B_risk_adjusted_descending"]
        paired_metrics = trial["paired_comparison"]["paired_primary_metrics"]
        self.assertEqual(paired_metrics["baseline"]["top5_median"], 3.0)
        self.assertEqual(paired_metrics["experiment"]["top5_median"], 4.0)

    def test_source_sensitivity_masks_labels_without_reordering(self):
        rows = [_row("2026-07-01", str(i), i, .2, i, i) for i in range(1, 7)]
        rows[0]["history_source"] = "AKShare"
        original = copy.deepcopy(rows)
        full = self._experiments(rows)
        tushare = self._experiments(rows, "tushare_only")
        for name in full:
            self.assertEqual(full[name]["selection_by_date"], tushare[name]["selection_by_date"])
        self.assertIsNone(tushare["baseline_current_rank"]["metrics"]["10"]["top_k"]["5"]["avg_return"])
        self.assertEqual(rows, original)

    def test_unknown_tradability_and_dd_prob_are_not_cash(self):
        rows = [_row("2026-07-01", str(i), i, .2, i, i) for i in range(1, 7)]
        rows[0]["tradable_label"] = "unavailable"
        rows[0]["dd_prob"] = None
        experiments = self._experiments(rows)
        self.assertIsNone(experiments["baseline_current_rank"]["metrics"]["10"]["top_k"]["5"]["avg_return"])
        self.assertIsNone(experiments["C_dd_prob_veto"]["metrics"]["10"]["top_k"]["5"]["avg_return"])

    def test_bootstrap_requires_horizon_sized_blocks(self):
        short = _bootstrap_ci([1.0] * 20, 100, 7)
        self.assertEqual(short["status"], "insufficient_blocks")
        self.assertIsNone(short["lower"])
        enough = _bootstrap_ci([1.0] * 30, 100, 7)
        self.assertEqual(enough["block_length_dates"], 10)
        self.assertEqual(enough["lower"], 1.0)
        self.assertEqual(enough, _bootstrap_ci([1.0] * 30, 100, 7))

    def test_block_bootstrap_preserves_clustered_daily_dependence(self):
        result = _bootstrap_ci([-1.0] * 10 + [0.0] * 10 + [1.0] * 10, 1000, 7)
        self.assertLess(result["lower"], -.4)
        self.assertGreater(result["upper"], .4)

    def test_no_tushare_complete_day_is_explicit_insufficient_evidence(self):
        rows = [_row("2026-07-01", str(i), i, .2, i, i, source="AKShare") for i in range(1, 7)]
        result = run_ranking_experiments(rows, .3, "existing", 100, 7)
        source = result["segments"]["tushare_only"]["all_candidates"]
        self.assertEqual(source["candidate_pool"]["10"]["incomplete_date_count"], 1)
        self.assertEqual(source["candidate_pool"]["10"]["evaluated_date_count"], 0)
        self.assertEqual(result["shadow_selection"]["status"], "insufficient_evidence")

    def test_single_stock_gain_rejected_by_actual_contribution_removal(self):
        baseline = {"_daily_top5_returns": {"d1": 0, "d2": 0}, "_daily_top5_contributions": {"d1": {"driver": 0, "other": 0}, "d2": {"driver": 0, "other": 0}}}
        trial = {"_daily_top5_returns": {"d1": 2, "d2": 3}, "_daily_top5_contributions": {"d1": {"driver": 2, "other": 0}, "d2": {"driver": 3, "other": 0}}}
        paired = _paired_top5_comparison(baseline, trial, 100, 7)
        sensitivity = paired["leave_one_contributor_out"]
        self.assertEqual(sensitivity["symbol_removed_mean_deltas"]["driver"], 0.0)
        self.assertFalse(sensitivity["positive_after_every_symbol_removal"])

    def test_single_day_gain_rejected_with_fixed_denominator(self):
        baseline = {"_daily_top5_returns": {"d1": 0, "d2": 0}, "_daily_top5_contributions": {"d1": {}, "d2": {}}}
        trial = {"_daily_top5_returns": {"d1": 2, "d2": -1}, "_daily_top5_contributions": {"d1": {"a": 2}, "d2": {"b": -1}}}
        sensitivity = _paired_top5_comparison(baseline, trial, 100, 7)["leave_one_contributor_out"]
        self.assertEqual(sensitivity["day_removed_mean_deltas"]["d1"], -0.5)
        self.assertFalse(sensitivity["positive_after_every_day_removal"])

    def _selection_segments(self):
        base = {"top5_median": 1, "top5_severe_loss": .2, "top5_excess": 0, "ndcg_at_10": .3}
        better = {"top5_median": 2, "top5_severe_loss": .1, "top5_excess": 1, "ndcg_at_10": .5}
        experiment = {
            "status": "available",
            "paired_comparison": {
                "mean_daily_top5_return_difference": 1.0,
                "bootstrap_95pct_ci": {"status": "evaluated", "lower": .1, "upper": 2},
                "paired_primary_metrics": {"matched_date_count": 30, "baseline": base, "experiment": better},
                "leave_one_contributor_out": {"status": "evaluated", "positive_after_every_day_removal": True, "positive_after_every_symbol_removal": True},
            },
        }
        experiments = {name: copy.deepcopy(experiment) for name in ("baseline_current_rank", "A_dd_prob_ascending", "B_risk_adjusted_descending", "C_dd_prob_veto")}
        return {source: {"all_candidates": {"experiments": copy.deepcopy(experiments)}} for source in ("all_sources", "tushare_only")}

    def test_shadow_selection_checks_all_tushare_criteria(self):
        for metric, bad in (("top5_median", 0), ("top5_severe_loss", .3), ("top5_excess", -1), ("ndcg_at_10", .1)):
            segments = self._selection_segments()
            for experiment in segments["tushare_only"]["all_candidates"]["experiments"].values():
                experiment["paired_comparison"]["paired_primary_metrics"]["experiment"][metric] = bad
            result = _shadow_selection(segments)
            self.assertEqual(result["selected"], [], metric)
            self.assertFalse(result["candidates"]["A_dd_prob_ascending"]["criteria"]["tushare_only_direction_consistent"], metric)

    def test_shadow_selection_selects_at_most_one_deterministically(self):
        result = _shadow_selection(self._selection_segments())
        self.assertEqual(result["selected"], ["A_dd_prob_ascending"])
        self.assertEqual(result["candidates"]["B_risk_adjusted_descending"]["status"], "qualified_not_selected")

    def test_shadow_selection_refuses_inference_on_insufficient_blocks(self):
        segments = self._selection_segments()
        for experiment in segments["all_sources"]["all_candidates"]["experiments"].values():
            experiment["paired_comparison"]["bootstrap_95pct_ci"] = {"status": "insufficient_blocks", "lower": None, "upper": None}
        result = _shadow_selection(segments)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["selected"], [])

    def test_veto_threshold_uses_only_current_medium_trend_breakout_rule(self):
        threshold, source = resolve_existing_dd_prob_veto_threshold({}, "trend_breakout", "medium")
        unavailable, unavailable_source = resolve_existing_dd_prob_veto_threshold({}, "pullback_rebound", "medium")

        self.assertEqual(threshold, 0.30)
        self.assertIn("CoachService", source)
        self.assertIsNone(unavailable)
        self.assertIsNone(unavailable_source)

    def test_experiment_c_applies_existing_veto_without_backfilling(self):
        rows = [
            _row("2026-07-01", "000001", 1, 0.50, 90, -12, action="buy"),
            _row("2026-07-01", "000002", 2, 0.20, 70, 8, action="watch"),
            _row("2026-07-01", "000003", 3, 0.25, 80, 6, action="watch"),
            _row("2026-07-02", "000004", 1, 0.45, 85, -10, action="buy"),
            _row("2026-07-02", "000005", 2, 0.20, 65, 9, action="watch"),
            _row("2026-07-02", "000006", 3, 0.25, 75, 7, action="watch", source="AKShare"),
        ]

        result = run_ranking_experiments(rows, dd_prob_veto_threshold=0.30, threshold_source="existing_medium_trend_breakout_buy_rule", bootstrap_iterations=100, bootstrap_seed=7)

        experiment_c = result["segments"]["all_sources"]["all_candidates"]["experiments"]["C_dd_prob_veto"]
        self.assertEqual(experiment_c["status"], "available")
        self.assertEqual(experiment_c["coverage"]["accepted_row_count"], 4)
        self.assertEqual(experiment_c["selection_by_date"]["2026-07-01"], ["000002", "000003"])
        self.assertEqual(experiment_c["metrics"]["10"]["top_k"]["3"]["candidate_count"], 2)
        self.assertGreater(experiment_c["paired_comparison"]["mean_daily_top5_return_difference"], 0)
        self.assertIn("tushare_only", result["segments"])

    def test_experiment_c_is_unavailable_without_a_single_existing_threshold(self):
        rows = [_row("2026-07-01", "000001", 1, 0.20, 70, 5)]

        result = run_ranking_experiments(rows, dd_prob_veto_threshold=None, threshold_source=None, bootstrap_iterations=20, bootstrap_seed=7)

        experiment_c = result["segments"]["all_sources"]["all_candidates"]["experiments"]["C_dd_prob_veto"]
        self.assertEqual(experiment_c["status"], "unavailable")
        self.assertIn("threshold", experiment_c["reason"])


if __name__ == "__main__":
    unittest.main()
