# AI Usage and Verification Log

I used ChatGPT to help generate the initial SkyPoints ETL implementation, Snowflake SQL design, documentation, and automated test cases.

I executed the Python pipeline locally, reviewed the processing logic, inspected the database results, and ran the automated tests.

| Date | Task | AI Assistance | My Verification |
|---|---|---|---|
| 2026-11-20 | Architecture | Helped design raw, staging, current-member, and country-specific tables | Inspected pipeline.py and successfully executed the local ETL |
| 2026-11-20 | Data validation | Helped implement source-specific date parsing and rejection handling | Verified two rejected records and their rejection reasons |
| 2026-11-20 | Incremental processing | Helped implement duplicate detection and latest-record-wins logic | Verified unchanged records were skipped on rerun |
| 2026-11-20 | Country movement | Helped implement member updates across country tables | Executed synthetic Elena move; confirmed USA=0 and India=1 |
| 2026-11-20 | Automated tests | Helped generate Python test cases | Ran pytest -v locally; all 14 tests passed |
| 2026-11-20 | GitHub | Assisted with Git initialization and repository submission | Created the Git commit and successfully pushed the project |

## Limitations

- SQLite was used for local execution and testing.
- Snowflake SQL was provided as a production design but was not executed in Snowflake.
- Billion-record performance was not benchmarked.
- The country-movement demonstration used a synthetic update.
- Sample source files were reconstructed from assessment examples.
- Some source date-format and record-ordering assumptions require confirmation.
