# Fresmart all-SKU price optimisation: full step plan (v2, 15 Nov 2026)

Decisions so far:
- Only ACTIVE SKUs. All 3,812 active SKUs are modelled; recommendations go to the 2,360 on the shelf with stock.
- Pure SKU lens first; the short description layer comes later.
- Three approved groupings: contribution, price sensitivity, insight group.
- Max-profit guardrails (no sweet spot limits).
- Impact is computed weekly for 52 weeks, so the user picks any start and end date.
- The dashboard is changed only when the user asks.
- Stop after each step for review.

Status: ✅ done · ▶ next · ☐ to do · NEW = added from the Conzmo P&P Tempo method.

## Phase A: Define
| # | Step | Tests / choices | Output |
|---|---|---|---|
| A1 ☐ NEW | Project charter + paired CTQ: GP goal + unit guardrail + price-image guardrail, sponsor, owner, benefit check with finance | — | 1-page charter |
| A2 ☐ NEW | Pricing rules catalogue: each rule hard / soft, owner, data source (from the 13 demo rules + new) | — | rules_catalogue.xlsx |

## Phase B: Data
| # | Step | Tests / choices | Output |
|---|---|---|---|
| B1 ✅ | Data refresh to 12 Nov 2026 (sales, price log, stock, master, macro) | totals vs previous months | checkpoints/, macro/ |
| B2 ✅ | Clean + weekly table (outliers, cost outliers, stock-outs, partial weeks, store ramp-up, low availability) | — | clean/weekly_model.parquet |
| B3 ✅ | Below-cost review | diagnosis order tested (clearance vs cost data vs pricing) | analysis/allsku/below_cost_review.xlsx |
| B4 ✅ | Three groupings (contribution, sensitivity, insight) | trend like-for-like; stability rule replaced CV | sku_portfolio.xlsx, sku_behaviour.xlsx |
| B5 ✅ | Scope: 3,812 active / 2,360 recommendation | on-shelf + stock rule | analysis/allsku/scope.xlsx |
| B6 ☐ NEW | Unrecorded markdowns / promos: tag weeks priced below regular | test 5 / 8 / 12% thresholds, share of rows, effect on elasticity | flag in model table |
| B7 ☐ NEW | Price-change transition weeks (label alignment) | test 0 / 1 / 2-week windows on elasticity stability | flag in model table |
| B8 ☐ NEW | Price accuracy check (MSA proxy): realised vs system price per SKU-store | target ≥98% within 2% | price_accuracy.xlsx |

## Phase C: Features and selection (demo steps 5–7)
| # | Step | Tests / choices | Output |
|---|---|---|---|
| C1 ☐ | Feature build: demo 60 features + new flags (markdown, transition, KVI, insight group, SubGroup price index) | time split train / valid / test, event-ordered | features.parquet |
| C2 ☐ | Feature selection | linear: VIF + Lasso; trees: RFE with LightGBM; compare CV WAPE | selected_features.json |
| C3 ☐ | PCA test | keep a PCA block only if CV WAPE improves (demo: none did) | test log |

## Phase D: Price sensitivity (demo steps 8–9)
| # | Step | Tests / choices | Output |
|---|---|---|---|
| D1 ☐ | Statistical tests per SKU | 3 specs: store FE, week FE, chain time series; sign, significance; clearance weeks out | sku_evidence |
| D2 ☐ | Elasticity candidates + combination | linear, multiple, 3 log-log; DerSimonian-Laird combination | raw elasticities |
| D3 ☐ | Pooling | EB to SubGroup vs hierarchical (SKU → SubGroup → MainGroup); NEW test: pool toward product clusters (SubGroup) vs behaviour clusters vs both; chosen by back-test D7 | pooled elasticities |
| D4 ☐ | Rise vs cut | separate rise / cut response, calibrated on price events, capped 1.5x overall and −5 | Rise / Cut values |
| D5 ☐ | Own vs switching | own-only vs SubGroup move; cross-effects within substitute clusters (both specs positive, p<0.10), diversion cap 60% | cross_elasticity |
| D6 ☐ | Bounds + confidence | bounds −4 to −0.2; High / Medium / Low; Low → cautious = prior −1 SD | final elasticity |
| D8 ☐ NEW | Store-cluster sensitivity | sensitivity by store cluster (wholesale, premium, other); decide one chain price vs zone prices | store_cluster_elasticity |
| D9 ☐ NEW | Sensitivity over time | last 12 months vs older; weight recent data if it differs (inflation fell from 31% to 8%) | stability test |
| D7 ☐ NEW | Back-test of price response | hold out last 6 months of price changes; predicted vs actual unit change; compare D2–D5 options; range coverage check | backtest_price.xlsx |

## Phase E: Demand baseline (demo steps 10–12) — we build our own CHAIN-level baseline (SKU × week, 52 weeks); the user can also upload their own chain-level forecast (see I2), E3 benchmarks it when available
| # | Step | Tests / choices | Output |
|---|---|---|---|
| E1 ☐ | Demand models | Linear, RF, LightGBM, XGBoost, CatBoost, ensemble; NEW test: one global model vs per-cluster vs per-SKU models; price monotone check | model_validation.xlsx |
| E2 ☐ | Training design | target relative to 13-week level, recency weights (26-week half-life), 6 CV folds, level calibration vs Duan smearing, frozen inputs at origin | champion model |
| E3 ☐ | Benchmark + blend | vs B1 last-13-week avg, B2 B1×season, B3 LY×trend; 7 origins × 13 weeks; blends 30/70, 50/50 (demo locked 30/70: re-test) | forecast_benchmark.xlsx |
| E4 ☐ | Seasonal path | analog years 2024 + 2025; SKU override only where both agree; filtered vs unfiltered on Q4 2025 holdout | seasonal path |
| E5 ☐ | 52-week weekly forecast + calibrated ranges, chain level (SKU × week) | coverage check of ranges | baseline_forecast.parquet |
| E6 ☐ | Explainability | SHAP, permutation importance, PDP; ML price slope vs D elasticity; model card | explainability.xlsx |

## Phase F: Simulation and profit (demo steps 13–14)
| # | Step | Tests / choices | Output |
|---|---|---|---|
| F1 ☐ | Supply-at-risk + stock rule | <70% of usual stores in last 4 weeks | supply_risk |
| F2 ☐ | Price grid −15% to +15% within tested range | own + cross effects, 95% ranges, rival gain value-equivalent capped 60% | simulation_grid |
| F3 ☐ | Profit grid | net ex-VAT price, latest 4-week cost, FX, CPI cost drift, rival GP | profit_grid |
| F4 ☐ NEW | Cost pass-through scan | cost change vs price change, suggested catch-up | pass_through.xlsx |
| F5 ☐ NEW | Overstock and slow movers | many weeks of stock + falling sales → markdown candidate, not a rise | markdown_list.xlsx |

## Phase G: Optimisation (demo step 15)
| # | Step | Tests / choices | Output |
|---|---|---|---|
| G1 ☐ | Objective + guardrails (Max-profit plan) | step ≤10%, tested range, unit loss ≤10% class A / ≤15% others, cautious GP must not fall, no rise if repriced ≥15% recently, no cut if supply at risk, KVI rule, min gain, smallest move for 90% of gain; NEW: method by tier (core = full model, thin tail = cost pass-through + margin floor), substitutes optimised together, basket price rise ≤ set months of CPI | config |
| G2 ☐ NEW | Optimiser | coordinate ascent (demo) vs MILP over real price points with ladder / ending rules; compare GP, rule breaks, run time | optimal_prices |
| G3 ☐ | Volume vs GP frontier | unit-loss caps 5 / 10 / 15 / 20% | frontier |
| G5 ☐ NEW | Timing of price changes | best start week per wave around the December peak (before / after / split) | timing plan |
| G4 ☐ | Scenarios | base / cautious / optimistic; FX +10%; CPI cost shock; poultry ban | scenarios.xlsx |

## Phase H: Finalise (demo steps 16–17)
| # | Step | Tests / choices | Output |
|---|---|---|---|
| H1 ☐ | Shelf prices | latest price record, store mode, incl. IVA, ...9 / ...99 endings, guardrails re-checked; NEW: rounding impact reported; NEW: key price thresholds (999 / 9,999 Kz...) not crossed without reason | price list |
| H2 ☐ | Store rules | store tiers kept, HRCA out, wholesale no staple rises, stores >12% off chain flagged | — |
| H3 ☐ | Business rules check | rules catalogue (A2), FAIL → overrides, price lines (same price / pack / name) | business_rules.xlsx |
| H4 ☐ NEW | Reason codes | plain-language reason per SKU | in price list |
| H5 ☐ | Waves + test design | waves sized by store label capacity (NEW); review list; matched test pairs with placebo MDE for big / uncertain moves | rollout plan |
| H7 ☐ NEW | Holdout control stores | a few matched stores keep old prices 4-8 weeks to measure the true gain for finance | holdout design |
| H6 ☐ | Impact for any date window | weekly 52-week impact; totals for the chosen start / end | weekly_impact.parquet |

## Phase I: Report and dashboard (demo step 18)
| # | Step | Output |
|---|---|---|
| I1 ☐ | Excel price list + business deck (USD, Newaco theme) | .xlsx, .pptx |
| I2 ☐ | Dashboard update incl. date picker + "Upload forecast" (CSV/XLSX template SKU_Code, Week_Start, Units; validation report; switch Our / Uploaded; missing SKUs fall back to ours; kept in the browser) | dashboard |
| I3 ☐ | Re-optimise on an uploaded forecast: `python scripts/allsku_optimise.py --forecast file.csv` | prices |

## Phase J: Go-live and control (NEW, Conzmo)
| # | Step |
|---|---|
| J1 ☐ | Approval workflow: auto-approve small rule-compliant changes, route big ones, log overrides |
| J2 ☐ | Release to POS + reconciliation (approved vs loaded) |
| J3 ☐ | Execution compliance from sales data (selling price vs approved) |
| J4 ☐ | SPC control charts: margin (I-MR), price accuracy (p-chart), KVI units |
| J5 ☐ | Post-change evaluation after 4 weeks + test read (DiD) |
| J6 ☐ | Quarterly re-estimation, drift check, champion-challenger |
| J7 ☐ | Standard work (weekly / monthly / quarterly), FMEA, poka-yoke (block below-cost prices), one price master |

## Phase K: Later
| # | Step |
|---|---|
| K1 ☐ | Short description layer: ladders, pooling, switching between sibling SKUs |
| K2 ☐ | Data requests: competitor prices on KVIs, supplier rebates, receipt-level data, shelf price audits, private-label list |

## Status 15 Nov 2026
Done: A1-A2 (drafts, 8 items to confirm), B1-B9 (incl. IVA correction), C1-C3, D1-D9, E1-E6, F1-F5, G1-G5, H1-H7, I3 (--forecast).
Open: answers to the business questions PDF (output/Business_Questions/), I1 business deck, I2 dashboard (only when asked), phase J at go-live, K later.
Scripts in run order: allsku_weekly -> allsku_price_accuracy -> sku_portfolio -> sku_behaviour -> allsku_scope -> below_cost_review ->
allsku_features -> allsku_elasticity -> allsku_baseline -> allsku_optimise [--forecast] -> allsku_finalise [--start --end].
