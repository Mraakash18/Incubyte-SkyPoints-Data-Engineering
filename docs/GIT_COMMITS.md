# Genuine incremental Git workflow

Incubyte asks for incremental commits showing how the solution evolved. **Do not invent commit history.** As you reproduce, review, test, and improve this starter project, commit the actual changes in small meaningful steps.

## Initialize and publish

```bash
git init
git add data/ README.md docs/DECISIONS.md
git commit -m "docs: define SkyPoints input contracts and data quality assumptions"
```

Then, as you genuinely implement or revise each component, commit it:

```bash
git add skypoints/ingest.py skypoints/transform.py
git commit -m "feat: parse heterogeneous sources and validate member records"

git add skypoints/pipeline.py skypoints/cli.py
git commit -m "feat: implement staging, canonical member state and country routing"

git add sql/
git commit -m "feat: add Snowflake schema, transforms and quality checks"

git add tests/
git commit -m "test: cover invalid dates, country moves, idempotency and redemptions"

git add docs/ requirements.txt .gitignore
git commit -m "docs: explain architecture, AI use, scale and live demo"
```

These are **example grouping commands**, not evidence of when the code was originally authored. If you start from the complete generated project, your first commit should truthfully identify it as an AI-assisted baseline; then make genuine incremental commits for fixes and improvements you personally review and test.

Example honest first commit:

```bash
git add .
git commit -m "chore: add AI-assisted SkyPoints starter implementation"
```

Then commit your real test fixes, decisions, and improvements as they occur. Use `git log --oneline` to show your progress. Push to a new GitHub repository using GitHub's instructions. Do not commit secrets or access tokens.
