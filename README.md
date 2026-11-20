# Fresmart Pricing Studio

Price optimisation for every active Fresmart article (Newaco, Angola). Private, for the internal team only.

## Open the studio online

https://groupsnsaidev.github.io/price-optimization/ (ask the project lead for the password).

The web copy in `docs/` holds the studio data encrypted (AES-256); the password unlocks it in the browser. To refresh it after new data: `python scripts/build_studio_data.py`, then `python scripts/publish_studio.py`, commit and push. The password is kept in `.env` as `STUDIO_PASSWORD`; to change it, edit that line and re-run `publish_studio.py`.

## Run it locally

1. Clone the repo (or download it as a ZIP from the green **Code** button).
2. Build the data (`python scripts/build_studio_data.py`, needs the pipeline outputs), then in the repo folder run:

   ```
   python -m http.server 8050 -d dashboard
   ```

3. Open http://localhost:8050/ in a browser.

The studio walks through eight pricing steps (Overview → Today's price → Price elasticity → Forecast & target → Promotions → Recommended price → Simulator → Scenarios). Each step opens after the one before is confirmed; **Start again** on the step bar resets it.

## What is in the repo

- `dashboard/` – the Pricing Studio code (its readable data, `dashboard/studio/data/`, stays local).
- `docs/` – the password-locked web copy served by GitHub Pages.
- `scripts/` – the pipeline: data cleaning, stock-outs, forecast, price elasticity, optimiser, rules, checks, and `build_studio_data.py`.
- `analysis/allsku/PROJECT_PLAN.md` – the project plan.

Raw SQL extracts, Excel outputs and the `.env` database credentials are not in the repo. Rebuilding the studio data needs those locally: run the pipeline, then `python scripts/build_studio_data.py`.

Confidential: contains Fresmart prices, costs and margins. Do not make this repository public.
