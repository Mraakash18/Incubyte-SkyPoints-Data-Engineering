# SkyPoints — Incubyte Data Engineer Technical Assessment

A working, testable end-to-end **local ETL demonstration** plus a **Snowflake production-design reference**. It implements raw ingestion, validation, staging, derived age/stale flags, country-specific tables, latest-record-wins moves, flattened JSON redemptions, and automated tests.

**AI usage is allowed and requested by the assessment.** Read and understand the decisions, execute the tests, and document your own reasoning and AI-assisted changes. Do not claim you built, tested, or deployed anything you did not actually do.

## 1. Quick start (Windows PowerShell, macOS, Linux)

Requirements: **Python 3.10+**. Runtime uses only the Python standard library, including a small XLSX adapter.

Open a terminal **inside this folder** and run:

```bash
python -m skypoints.cli --db output/skypoints.db --as-of 2026-11-20
```

On Windows, if `python` does not work, try `py`:

```powershell
py -m skypoints.cli --db output/skypoints.db --as-of 2026-11-20
```

To test the explicit **synthetic country move** (Elena: USA -> India):

```bash
python -m skypoints.cli --db output/skypoints.db --as-of 2026-11-20 --move-demo
```

For a fresh baseline, delete `output/skypoints.db` first, then run again. Re-running on the same DB is safe: already ingested records are not duplicated.

## 2. Run automated tests

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

There are 14 regression tests covering source adapters, ambiguous dates, null DOB, age/stale derivation, ID collisions, quarantines, idempotency, late arrivals, atomic country moves, JSON validation, and redemption joins.

## 3. Expected baseline results

`--as-of 2026-11-20` and the supplied samples:

| Measure | Expected |
|---|---:|
| Raw member rows | 14 (5 global flat + 3 Australia + 3 USA + 3 India) |
| Accepted/staged member rows | 12 |
| Quarantined rows | 2 |
| Current members | 12 |
| India country table | 4 |
| USA country table | 3 |
| Australia country table | 3 |
| Philippines country table | 1 |
| Canada country table | 1 |
| Flattened redemptions | 2 |

Quarantined examples: `australia.xlsx` Jonnathan invalid enrollment `2021-13-13`; `usa.csv` John ambiguous enrollment `1052022`.

The JSON redemptions `RX10091` and `RX10092` join to `GLOBAL:223457` (Elena), **not** to country-local `ID=1`.

## 4. Assessment requirements → files

| Requirement | Implementation |
|---|---|
| Raw, staging, country DDL | `sql/01_snowflake_ddl.sql`; local tables in `skypoints/pipeline.py` |
| Age and stale member | `skypoints/transform.py`; `sql/02_snowflake_transforms.sql` |
| Latest record wins and country move | `skypoints/pipeline.py`; Snowflake transactional MERGE script |
| Flatten JSON and join | `skypoints/pipeline.py`; Snowflake `LATERAL FLATTEN` |
| Mandatory, uniqueness, date validations | `skypoints/transform.py`, `tests/test_pipeline.py`, `sql/03_quality_checks.sql` |
| Billion-record scale and architecture | `docs/ARCHITECTURE.md` |
| Live demo | CLI commands above; `docs/DEMO_SCRIPT.md` |
| AI usage and Git plan | `docs/AI_USAGE_TEMPLATE.md`, `docs/GIT_COMMITS.md` |

## 5. Data and source contracts

The user-supplied samples were recreated from the tables in the assessment conversation. They are **sample fixtures**, not uploaded original binary files. Compare them with the original recruiter attachments before submission.

- `data/input/member_profiles_20240115.txt`: pipe-delimited global membership feed; its IDs are treated as globally authoritative **for this demo only**.
- `data/input/redemptions_20240115.json`: one global member's two redemption transactions.
- `data/input/india.csv`: country-local IDs; US-style `MM/DD/YYYY` dates as indicated by dates like `8/13/1982`.
- `data/input/usa.csv`: compact US dates without separators; **ambiguous dates are quarantined**.
- `data/input/australia.xlsx`: ISO date strings, including one intentionally invalid date.
- `data/demo/member_profiles_20240116.txt`: **synthetic** additional global feed, created only to prove that moving a member from USA to India removes the old country record.

### Important assumptions and limits

1. **Identity:** `GLOBAL:223457` and `USA_LOCAL:1` are different identity namespaces. Country-local IDs are not assumed to be global IDs. Cross-source identity resolution requires a verified mapping from the source system. Until then, a local-country member cannot be safely linked to a global redemption by number alone.
2. **Latest record:** None of the samples provides a member-update timestamp. We use the **feed date** as an explicitly documented proxy; same-date conflicting member versions are quarantined. For production, request a reliable source `updated_at` or monotonically increasing version. The Snowflake schema supports `source_updated_at`.
3. **DOB format:** Global flat feed `03051985` is ambiguous. For the demo only, the parser is configured as `DDMMYYYY`, so it becomes `1985-05-03`. Confirm the contract before production. `Post Code` is mentioned in the spec but absent from the supplied flat-file header, so it stays NULL.
4. **Key mismatch:** The provided specification marks `Member Name` as key but `Member ID` as non-key. We treat the verified membership ID as the stable business key because names can repeat and change. This must be confirmed with the source owner.
5. **Age:** calculated as of the explicitly provided processing date; DOB NULL -> age NULL. Leap-day birthday behavior follows the ordinary month/day comparison convention.
6. **Stale:** `last_flight_date` more than **90 days** before the processing date -> `1`; NULL last flight -> NULL/unknown, not automatically stale. Age and stale flags are **as-of snapshots** and need daily refresh or query-time recomputation in production.
7. **Status:** PENDING redemptions are stored, but only COMPLETED should be included in metrics for *completed* redeemed miles.
8. **Country list:** the demo supports five countries shown in the source sample. Production onboarding uses a controlled registry/migration, not arbitrary SQL table names from source input.
9. **Local demo vs scale:** SQLite and the simple XLSX reader are for correctness and a laptop demonstration, **not** a billion-record production engine. Snowflake/cloud object storage handles production throughput.
10. **Snowflake scripts:** reference SQL requiring a Snowflake account, external stages, and a source adapter to populate `NORMALIZED_MEMBER_INPUT`. They were **not run against Snowflake**. See `docs/ARCHITECTURE.md` for the ingestion and scaling design.

## 6. Inspect the local database

Any SQLite viewer can open `output/skypoints.db`. Or run:

```bash
python -c "import sqlite3; c=sqlite3.connect('output/skypoints.db'); print(c.execute('SELECT member_key,member_name,country_code,age,stale_member FROM current_members ORDER BY country_code,member_name').fetchall())"
```

For a readable live-demo output:

```bash
python -m skypoints.inspect --db output/skypoints.db
```

Other useful queries:

```sql
SELECT source_file, source_row, reason FROM rejected_records;
SELECT member_key, member_name, country_code FROM current_members;
SELECT member_key, member_name FROM country_india;
SELECT r.txn_id, r.status, m.member_name, m.country_code
FROM redemption_transactions r
LEFT JOIN current_members m ON r.member_key=m.member_key;
```

## 7. Production approach

See `sql/01_snowflake_ddl.sql`, `sql/02_snowflake_transforms.sql`, and `docs/ARCHITECTURE.md`.

Production ingestion: cloud object storage -> file validation -> raw immutable landing -> source-specific standardization -> staging -> deduplicated canonical members -> transactional country routing; JSON -> VARIANT -> `LATERAL FLATTEN` -> transaction table -> verified member join.

## 8. Before submitting

- Read `docs/DECISIONS.md` and be able to explain every assumption.
- Run the demo and all tests yourself, with the actual input files if available.
- Add screenshots or terminal output showing baseline, quarantine, JSON join, and country move.
- Follow `docs/GIT_COMMITS.md` for **genuine incremental commits** as you work and improve the solution.
- Fill in `docs/AI_USAGE_TEMPLATE.md` truthfully with the prompts, code reviews, and tests you personally performed.
- Do not claim this demo has been benchmarked at billions/day or validated on Snowflake without doing those experiments.
