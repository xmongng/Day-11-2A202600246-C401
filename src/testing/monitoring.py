"""
Assignment 11 — Monitoring & Alerts

Tracks real-time security metrics and fires alerts when thresholds
are exceeded.

Why this layer is needed:
    Individual guardrails report locally. Monitoring aggregates data
    across ALL layers to detect systemic issues — e.g., a sudden spike
    in blocked requests could indicate a coordinated attack. No single
    guardrail can see this cross-layer pattern.
"""


class MonitoringAlert:
    """Aggregates metrics from all plugins and fires alerts.

    Monitors:
        - Block rate across all input/output guardrails
        - Rate limit hit frequency
        - LLM Judge failure rate
        - Overall system health

    Alert thresholds are configurable. When exceeded, an alert is
    printed to console (in production, this would go to PagerDuty/Slack).
    """

    def __init__(self, plugins: list, alert_threshold=0.2):
        """Initialize monitoring with references to all active plugins.

        Args:
            plugins: List of all plugin instances in the pipeline
            alert_threshold: Fraction (0.0-1.0) of blocked requests that triggers an alert.
                             Default 0.2 = alert if >20% of requests are blocked.
        """
        self.plugins = {p.name: p for p in plugins}
        self.alert_threshold = alert_threshold
        self.alerts_fired = []

    def _get_metric(self, plugin_name: str, attr: str, default=0):
        """Safely get a metric from a plugin."""
        plugin = self.plugins.get(plugin_name)
        if plugin and hasattr(plugin, attr):
            return getattr(plugin, attr)
        return default

    def collect_metrics(self) -> dict:
        """Collect metrics from all registered plugins.

        Returns:
            dict with per-plugin and aggregate metrics
        """
        metrics = {}

        # Rate Limiter metrics
        rl_total = self._get_metric("rate_limiter", "total_count")
        rl_blocked = self._get_metric("rate_limiter", "blocked_count")
        metrics["rate_limiter"] = {
            "total": rl_total,
            "blocked": rl_blocked,
            "block_rate": rl_blocked / rl_total if rl_total > 0 else 0.0,
        }

        # Input Guardrail metrics
        ig_total = self._get_metric("input_guardrail", "total_count")
        ig_blocked = self._get_metric("input_guardrail", "blocked_count")
        metrics["input_guardrail"] = {
            "total": ig_total,
            "blocked": ig_blocked,
            "block_rate": ig_blocked / ig_total if ig_total > 0 else 0.0,
        }

        # Output Guardrail metrics
        og_total = self._get_metric("output_guardrail", "total_count")
        og_blocked = self._get_metric("output_guardrail", "blocked_count")
        og_redacted = self._get_metric("output_guardrail", "redacted_count")
        metrics["output_guardrail"] = {
            "total": og_total,
            "blocked": og_blocked,
            "redacted": og_redacted,
            "block_rate": og_blocked / og_total if og_total > 0 else 0.0,
        }

        # Audit Log metrics
        audit = self.plugins.get("audit_log")
        if audit and hasattr(audit, "get_summary"):
            metrics["audit_log"] = audit.get_summary()
        else:
            metrics["audit_log"] = {"total_entries": 0}

        # Aggregate
        total_all = rl_total + ig_total + og_total
        blocked_all = rl_blocked + ig_blocked + og_blocked
        metrics["aggregate"] = {
            "total_checks": total_all,
            "total_blocked": blocked_all,
            "overall_block_rate": blocked_all / total_all if total_all > 0 else 0.0,
        }

        return metrics

    def check_alerts(self) -> list:
        """Check all metrics against thresholds and fire alerts.

        Returns:
            List of alert dicts that were fired
        """
        metrics = self.collect_metrics()
        new_alerts = []

        # Alert 1: Overall block rate too high
        overall_rate = metrics["aggregate"]["overall_block_rate"]
        if overall_rate > self.alert_threshold:
            alert = {
                "level": "WARNING",
                "metric": "overall_block_rate",
                "value": f"{overall_rate:.0%}",
                "threshold": f"{self.alert_threshold:.0%}",
                "message": (
                    f"⚠️ ALERT: Overall block rate ({overall_rate:.0%}) exceeds "
                    f"threshold ({self.alert_threshold:.0%}). Possible attack in progress."
                ),
            }
            new_alerts.append(alert)

        # Alert 2: Rate limiter is hitting too often
        rl_rate = metrics["rate_limiter"]["block_rate"]
        if rl_rate > 0.3:
            alert = {
                "level": "WARNING",
                "metric": "rate_limit_block_rate",
                "value": f"{rl_rate:.0%}",
                "threshold": "30%",
                "message": (
                    f"⚠️ ALERT: Rate limiter blocking {rl_rate:.0%} of requests. "
                    f"Possible abuse or bot traffic."
                ),
            }
            new_alerts.append(alert)

        # Alert 3: Input guardrail catching many injections
        ig_rate = metrics["input_guardrail"]["block_rate"]
        if ig_rate > 0.5:
            alert = {
                "level": "CRITICAL",
                "metric": "injection_block_rate",
                "value": f"{ig_rate:.0%}",
                "threshold": "50%",
                "message": (
                    f"🚨 CRITICAL: Input guardrail blocking {ig_rate:.0%} of requests. "
                    f"Coordinated injection attack likely."
                ),
            }
            new_alerts.append(alert)

        # Alert 4: Output guardrail redacting or blocking
        og_blocked = metrics["output_guardrail"]["blocked"]
        if og_blocked > 0:
            alert = {
                "level": "WARNING",
                "metric": "output_blocked_count",
                "value": str(og_blocked),
                "threshold": ">0",
                "message": (
                    f"⚠️ ALERT: Output guardrail blocked {og_blocked} response(s). "
                    f"Agent may be leaking sensitive data."
                ),
            }
            new_alerts.append(alert)

        self.alerts_fired.extend(new_alerts)
        return new_alerts

    def print_dashboard(self):
        """Print a formatted monitoring dashboard to console."""
        metrics = self.collect_metrics()
        alerts = self.check_alerts()

        print("\n" + "=" * 65)
        print("  MONITORING DASHBOARD")
        print("=" * 65)

        # Per-layer stats
        print(f"\n  {'Layer':<25} {'Total':<10} {'Blocked':<10} {'Rate':<10}")
        print("  " + "-" * 55)

        for layer in ["rate_limiter", "input_guardrail", "output_guardrail"]:
            m = metrics[layer]
            rate = f"{m['block_rate']:.0%}" if m["total"] > 0 else "N/A"
            print(f"  {layer:<25} {m['total']:<10} {m['blocked']:<10} {rate:<10}")

        # Aggregate
        agg = metrics["aggregate"]
        agg_rate = f"{agg['overall_block_rate']:.0%}" if agg["total_checks"] > 0 else "N/A"
        print("  " + "-" * 55)
        print(f"  {'TOTAL':<25} {agg['total_checks']:<10} {agg['total_blocked']:<10} {agg_rate:<10}")

        # Audit log
        audit = metrics["audit_log"]
        print(f"\n  Audit log entries:  {audit.get('total_entries', 0)}")
        if audit.get("avg_latency_ms"):
            print(f"  Avg latency:        {audit['avg_latency_ms']}ms")

        # Alerts
        if alerts:
            print(f"\n  --- ALERTS ({len(alerts)}) ---")
            for a in alerts:
                print(f"  [{a['level']}] {a['message']}")
        else:
            print("\n  ✅ No alerts — all metrics within normal range.")

        print("=" * 65)
