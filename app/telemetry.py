from prometheus_client import Counter, Gauge, Histogram

EVENTS = Counter(
    "pi_atlassian_events_total",
    "Atlassian event deliveries by outcome and resource type.",
    ("outcome", "resource_type"),
)
DISPATCH_SECONDS = Histogram(
    "pi_atlassian_event_dispatch_seconds",
    "Time from event dispatch start through targeted ingestion.",
    ("provider", "outcome"),
)
CATCH_UP_SECONDS = Histogram(
    "pi_atlassian_catch_up_seconds",
    "Incremental recovery scan duration.",
    ("outcome",),
)
MCP_CALLS = Counter(
    "pi_atlassian_mcp_calls_total",
    "Rovo MCP calls by identity and outcome.",
    ("identity_class", "tool", "outcome"),
)
PENDING = Gauge(
    "pi_atlassian_pending_events",
    "Accepted Atlassian events waiting for targeted ingestion.",
)
