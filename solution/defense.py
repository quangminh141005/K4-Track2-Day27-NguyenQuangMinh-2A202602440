"""General streaming defenses; no file access, hidden state, or event-ID rules.

Each event needs at most one metered inspection. Published three-sigma bounds
anchor numeric tests; a robust online estimate can detect smaller deviations
once enough observations have arrived. Extreme observations do not train it.
"""
from api import Verdict
def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def register(ctx):
    ctx.on('data_batch', check_data_batch)
    ctx.on('contract_checkpoint', check_contract_checkpoint)
    ctx.on('lineage_run', check_lineage_run)
    ctx.on('feature_materialization', check_feature_materialization)
    ctx.on('embedding_batch', check_embedding_batch)


def verdict(pillar, reasons):
    return Verdict(alert=bool(reasons), confidence=0.95 if reasons else 0.8,
                   reason='; '.join(reasons) if reasons else 'observed checks within limits',
                   pillar=pillar)


def inspect_error(result, pillar):
    if 'error' in result:
        # A failed inspection is not evidence that the pipeline event is faulty.
        return Verdict(alert=False, confidence=0.0, reason='inspection unavailable: ' + str(result['error']), pillar=pillar)
    return None


def high(ctx, name, value, limit):
    """Combine a calibrated upper limit with a conservative robust tail test.

    Median/MAD resists fault contamination. A 3.5-sigma rule keeps false
    positives low, and the static-limit floor prevents collapsed variance.
    History is local to each metric, bounded, and excludes static violations.
    """
    history = ctx.state.setdefault('metric:' + name, [])
    unusual = value > limit
    if len(history) >= 20:
        center = median(history)
        scale = 1.4826 * median([abs(x - center) for x in history])
        scale = max(scale, abs(limit - center) / 6.0)
        unusual = unusual or value > center + 3.5 * scale
    if value <= limit:
        history.append(value)
        if len(history) > 200:
            del history[0]
    return unusual


def check_data_batch(p, ctx):
    r = ctx.tools.batch_profile(p['batch_id'])
    error = inspect_error(r, 'checks')
    if error is not None:
        return error
    b = ctx.baseline
    reasons = []
    # Two-sided checks retain the independently calibrated lower/upper bounds.
    for field in ('row_count', 'mean_amount'):
        if not b[field + '_min'] <= r[field] <= b[field + '_max']:
            reasons.append(field + ' outside baseline interval')
    if high(ctx, 'null_rate', r['null_rate']['customer_id'], b['null_rate_max']):
        reasons.append('customer_id null rate elevated')
    if high(ctx, 'staleness', r['staleness_min'], b['staleness_min_max']):
        reasons.append('batch stale')
    return verdict('checks', reasons)


def check_contract_checkpoint(p, ctx):
    r = ctx.tools.contract_diff(p['contract_id'], p['checkpoint_batch_id'])
    error = inspect_error(r, 'contracts')
    if error is not None:
        return error
    reasons = list(r['violations'])
    if high(ctx, 'contract_delay', r['freshness_delay_min'], ctx.baseline['freshness_delay_max_min']):
        reasons.append('contract freshness SLA exceeded')
    return verdict('contracts', reasons)


def check_lineage_run(p, ctx):
    r = ctx.tools.lineage_graph_slice(p['run_id'])
    error = inspect_error(r, 'lineage')
    if error is not None:
        return error
    reasons = []
    actual = set(r['actual_upstream'])
    expected = p.get('expected_upstream')
    if expected is not None:
        if actual != set(expected):
            reasons.append('upstream edges differ from declared lineage')
    else:
        # Learn recurring topology from already observed runs, never run IDs.
        scope = str(p.get('pipeline', p.get('job_name', p.get('transform', 'default'))))
        counts = ctx.state.setdefault('upstream:' + scope, {})
        topology = tuple(sorted(actual))
        reference = max(counts, key=counts.get) if counts else None
        if not actual:
            reasons.append('missing upstream lineage')
        elif reference is not None and counts[reference] >= 3 and actual < set(reference):
            reasons.append('upstream edge missing from recurring topology')
        else:
            counts[topology] = counts.get(topology, 0) + 1
    if r['actual_downstream_count'] <= 0:
        reasons.append('orphaned output')
    expected_count = p.get('expected_downstream_count')
    if expected_count is not None and r['actual_downstream_count'] != expected_count:
        reasons.append('downstream count differs from declared lineage')
    if high(ctx, 'lineage_duration', r['duration_ms'], ctx.baseline['lineage_duration_ms_max']):
        reasons.append('transform runtime elevated')
    return verdict('lineage', reasons)


def check_feature_materialization(p, ctx):
    r = ctx.tools.feature_drift(p['feature_view'], p['batch_id'])
    error = inspect_error(r, 'ai_infra')
    if error is not None:
        return error
    reasons = []
    if high(ctx, 'feature:' + p['feature_view'], r['mean_shift_sigma'], ctx.baseline['feature_mean_shift_sigma_max']):
        reasons.append('training-serving feature skew')
    return verdict('ai_infra', reasons)


def check_embedding_batch(p, ctx):
    r = ctx.tools.embedding_drift(p['corpus'], p['chunk_batch_id'])
    error = inspect_error(r, 'ai_infra')
    if error is not None:
        return error
    reasons = []
    if high(ctx, 'centroid:' + p['corpus'], r['centroid_shift'], ctx.baseline['embedding_centroid_shift_max']):
        reasons.append('embedding centroid drift')
    if high(ctx, 'age:' + p['corpus'], r['avg_doc_age_days'], ctx.baseline['corpus_avg_doc_age_days_max']):
        reasons.append('corpus stale')
    return verdict('ai_infra', reasons)
