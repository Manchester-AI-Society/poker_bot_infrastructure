Benchmark Suite
===============

This folder contains a lightweight benchmark harness to measure runtime hot
paths in the poker server implementation.

How to run
----------

1. Activate your virtual environment.
2. Run the benchmark script from repository root.

Example full run:

python benchmarks/run_benchmarks.py

Example single scenario:

python benchmarks/run_benchmarks.py --only showdown_evaluator_7card

Save machine-readable output:

python benchmarks/run_benchmarks.py --json-output benchmarks/latest.json

Scenarios included
------------------

- action_engine_rules
  - Measures legal action calculation and min raise target calculation.
  - Useful for action validation and decision latency.

- state_projection_public
  - Measures building player-visible state payloads.
  - Useful for API payload shaping overhead.

- showdown_evaluator_7card
  - Measures 7-card best-hand evaluation throughput.
  - Useful for showdown performance bottleneck detection.

- event_log_pagination
  - Measures paginated event retrieval under large log volume.
  - Useful for event history endpoint scalability checks.

- service_match_lifecycle
  - Measures full async lifecycle from start_match to finished hand,
    including action submission loop.
  - Useful for end-to-end service overhead profiling.

- connection_broadcast
  - Measures websocket fanout with many connected players.
  - Useful for realtime event distribution cost.

Recommended process to identify optimisations
---------------------------------------------

1. Run baseline and save JSON output.
2. Make your optimisation change.
3. Re-run with same iteration counts and seed.
4. Compare avg_milliseconds and ops_per_second for affected scenarios.
5. Use a focused run with --only to reduce noise while tuning.

Tips
----

- Keep the machine as idle as possible while benchmarking.
- Use at least 3 repeated runs and compare median values.
- Increase iteration flags when results are noisy.
