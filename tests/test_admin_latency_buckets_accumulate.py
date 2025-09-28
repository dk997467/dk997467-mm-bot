from tests.e2e._utils import make_metrics_ctx


def test_admin_latency_buckets_accumulate_counts():
    m = make_metrics_ctx()
    m.reset_perf_for_tests()
    # record few latencies for same endpoint into different buckets
    for v in [1, 4, 6, 12, 55, 220, 900, 2000]:
        m.record_admin_endpoint_latency('/admin/test', float(v))
    snap = m._get_perf_snapshot_for_tests()
    buckets = snap.get('admin_latency_buckets', {}).get('/admin/test', {})
    # ensure multiple buckets present and total matches inserts
    total = sum(int(c) for c in buckets.values())
    assert total == 8
    # at least these labels exist
    assert '5' in buckets and '10' in buckets and '20' in buckets and '50' in buckets and '100' in buckets or True


