# Grafana Dashboards

## Redis Export Monitoring Dashboard

Visual monitoring for Redis KPI export operations.

### Panels

1. **Export Batches per Second** - Rate of pipeline batch execution
2. **Average Batch Duration (ms)** - Performance metric with 100ms warning threshold
3. **Keys Written per Minute** - Throughput indicator
4. **Export Success Rate** - Health indicator (green > 99%, yellow > 90%, red < 90%)
5. **Failed Batches (last 5m)** - Alert indicator
6. **Export Metrics Summary** - Current totals table

### Import Instructions

**Option 1: Via Grafana UI**

1. Open Grafana: http://localhost:3000
2. Navigate to **Dashboards → Import**
3. Click **Upload JSON file**
4. Select `ops/grafana/redis_export_dashboard.json`
5. Choose folder and click **Import**

**Option 2: Via API**

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d @ops/grafana/redis_export_dashboard.json \
  http://localhost:3000/api/dashboards/db
```

**Option 3: Provisioning (Recommended for Production)**

Add to Grafana provisioning config:

```yaml
# /etc/grafana/provisioning/dashboards/redis-export.yaml
apiVersion: 1

providers:
  - name: 'Redis Export'
    folder: 'Monitoring'
    type: file
    options:
      path: /path/to/mm-bot/ops/grafana
```

Restart Grafana to apply.

### Variables

- **$env**: Environment filter (dev, staging, prod)

To use: Modify dashboard JSON to add `{env="$env"}` label matchers to queries if your Prometheus metrics include environment labels.

### Alerts Integration

This dashboard works with Prometheus alerts defined in `ops/alerts/redis_export_rules.yml`.

Configure alert annotations in Grafana to see alert firing times on graphs.

### Thresholds

- Batch duration > 100ms: Warning (yellow)
- Success rate < 99%: Warning (yellow)
- Success rate < 90%: Critical (red)
- Failed batches > 0: Warning (yellow)
- Failed batches > 5: Critical (red)

### Refresh Rate

Default: 30 seconds (configurable in dashboard settings)

### Time Range

Default: Last 1 hour (adjustable via time picker)

