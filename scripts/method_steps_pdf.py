"""PDF: every step of the all-SKU price optimisation, start to finish, with the data science and Lean Six Sigma
concepts behind each step. One numbered list, no phases.

Output: output/Method/Fresmart_Price_Optimisation_Method_DS_and_Six_Sigma.pdf
"""
from collections import Counter
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "Method"
LOGO = ROOT / "poultry_ban" / "assets" / "newaco_logo.png"
PURPLE, GOLD, INK, GREY, TINT = (colors.HexColor(x) for x in ["#3B0A45", "#A08700", "#1A1A1A", "#6B6B6B", "#F4F0F5"])
PAGE_W = 257  # usable width in mm (landscape A4, 20 mm margins)

S = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=PURPLE),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=11.5, leading=16, textColor=GREY),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=PURPLE, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=GOLD, spaceBefore=6, spaceAfter=3),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=10.5, textColor=GREY),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10.3, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.3, leading=10.5, textColor=colors.white),
    "num": ParagraphStyle("num", fontName="Helvetica-Bold", fontSize=8.3, leading=10.5, textColor=PURPLE),
}
STATUS = {"Done": "#2E7D32", "Draft": "#B26A00", "To do": "#4A5A8A", "Needs data": "#A23B3B", "At go-live": "#6B6B6B",
          "Later": "#6B6B6B"}

# (step, what we do / what we tested and chose, data science steps, Six Sigma steps, status)
STEPS = [
    ("Project charter",
     "Goal, scope, sponsor, owner, finance sign-off. Scope = ACTIVE articles only, pure SKU lens first.",
     "Problem framing: what we predict, what we optimise, what we hold fixed",
     "Project charter, VOC (voice of customer / business)", "Draft"),
    ("Paired success measures",
     "Profit is never chased alone: GP up, while units, customer basket and price image stay within limits.",
     "Objective function and constraints defined before modelling",
     "CTQ tree, paired CTQs", "Draft"),
    ("Map today's pricing process",
     "Who sets prices today, inputs, steps, approvals, how prices reach the till.",
     "-",
     "SIPOC, process map", "To do"),
    ("Measure today's pricing performance (before picture)",
     "How often prices change, how fast price follows cost, share of articles below cost or under 5% margin, margin by group, "
     "price accuracy. Parts already measured (15,712 price steps, 594 articles under 5%); one baseline sheet still to build.",
     "Descriptive statistics, KPI baseline",
     "Baseline measurement, current-state value stream", "To do"),
    ("Pricing rules catalogue (20 rules)",
     "Each rule hard (never break) or soft (flag), with owner and data source. 8 items wait for the business.",
     "Business rules turned into model constraints",
     "Requirements capture, poka-yoke design", "Draft"),
    ("Questions for the business (PDF)",
     "IVA basis, the 14% IVA price gap, KVI rule, targets and limits, stores and articles that changed status.",
     "Assumption log",
     "Stakeholder analysis, VOC", "Done"),
    ("Data collection",
     "Sales per article x store from Azure SQL in weekly chunks; price log, stock, article master; FX and CPI from the IMF API, "
     "Brent from FRED.",
     "Data ingestion, API extraction, chunked loading",
     "Data collection plan", "Done"),
    ("Data refresh and reconciliation",
     "Reloaded to 12 Nov 2026; totals compared with earlier months; backups kept before every refresh.",
     "Reconciliation checks, data versioning",
     "Data integrity check", "Done"),
    ("Data profiling",
     "Row counts, value ranges, data types, coverage by store and week, first and last dates; the partial last week dropped.",
     "Data profiling, schema check",
     "Operational definitions", "Done"),
    ("Keys and joins",
     "Article codes aligned (leading zeros, text vs number) so sales, price, stock and master join correctly.",
     "Key alignment, join validation",
     "Measurement consistency", "Done"),
    ("Data quality checks",
     "Missing values, negative or missing stock, breaks in stock continuity, duplicate rows, zero or missing cost and price.",
     "Data quality rules, validity checks",
     "Data quality checks", "Done"),
    ("Missing value treatment",
     "Price and cost carried forward from the last known week; weeks with no sales kept as zero and flagged; macro months not "
     "yet published carry the last value; median fill inside the forecast.",
     "Imputation (forward fill, median), missing-value flags",
     "-", "Done"),
    ("Outlier and anomaly detection",
     "Spike weeks = units more than 4 robust SDs above the 13-week median (flagged, not deleted); cost outliers; "
     "clearance prices; below-cost weeks.",
     "Robust outlier detection (median / robust SD), anomaly flags",
     "Special-cause variation", "Done"),
    ("Data grain and aggregation",
     "Article x store x week, and article x week for the chain (371K rows); store ramp-up weeks and low availability marked.",
     "Aggregation, panel data structure",
     "Rational subgrouping", "Done"),
    ("Units, currency and real prices",
     "Kwanza converted to USD with the FX rate; prices and cost deflated by CPI to real values; IVA taken out of sales.",
     "Normalisation, deflation, currency conversion",
     "Operational definitions", "Done"),
    ("Price accuracy and IVA check",
     "Selling price vs system price (target 98% within 2%). Found: sales include IVA, so margin is 13.4% not 20.3%; 14% IVA "
     "articles sell about 9% below the system price.",
     "Data validation, net-of-tax rebuild",
     "MSA (measurement system analysis)", "Done"),
    ("Hidden markdown flags",
     "Weeks priced below the regular price tagged; thresholds 5% / 8% / 12% tested on share of rows and elasticity; 8% chosen.",
     "Threshold sensitivity analysis, labelling",
     "Operational definition", "Done"),
    ("Price-change transition weeks",
     "0 / 1 / 2-week windows tested on elasticity stability; price steps above 3% held for 2 weeks.",
     "Label alignment, noise reduction",
     "Measurement error control", "Done"),
    ("Exploratory data analysis",
     "Seasonality, payday weeks (+17%), Christmas (+24.5%), price steps, distributions (skewed units, so logs are used), "
     "margin by group.",
     "EDA, distributions, skewness, seasonality",
     "Graphical analysis, run charts", "Done"),
    ("Below-cost review",
     "Diagnosis order: packing error, not on shelf, purchase blocked, clearance, cost jump, real below cost. 594 articles under "
     "5% margin; 220 raises worth +$180K over 8 weeks.",
     "Rule-based classification",
     "Fishbone, 5 Whys, Pareto", "Done"),
    ("Contribution grouping (ABC)",
     "A = top 80% of sales, B = next 15%, C = rest (A = 600 articles).",
     "Pareto segmentation",
     "Pareto (80/20)", "Done"),
    ("Behaviour groups",
     "Sensitivity, frequency, reach, stability (week-to-week change), trend (like-for-like stores), December season, price vs "
     "inflation, margin direction; combined into insight groups (Everyday KVI, Raise candidate, Danger zone, Margin eroding).",
     "Segmentation, like-for-like trend",
     "Stratification", "Done"),
    ("Scope",
     "3,812 active articles modelled; 2,360 get a recommendation (on shelf in 10+ stores, 10 of 13 weeks, with stock), 89% of "
     "sales.",
     "Population definition, eligibility filter",
     "Scope definition", "Done"),
    ("Process capability baseline",
     "Capability of margin and price accuracy today, to set the control limits used after go-live.",
     "Distribution fitting",
     "Cp / Cpk, control limits", "To do"),
    ("Features: demand history",
     "Units 1, 2, 4 and 52 weeks ago; 4 and 13-week averages; short vs long trend; weeks selling; no-sale last week.",
     "Feature engineering: lags, rolling windows, trend",
     "Xs that drive Y", "Done"),
    ("Features: price",
     "Real price; price vs usual price, split into above and below usual; 1-week price change; SubGroup price index "
     "(leave-one-out, sales weighted) and price relative to it; markdown and transition flags.",
     "Ratio features, piecewise split, leave-one-out group index",
     "Y = f(X)", "Done"),
    ("Features: cost, margin, distribution",
     "Real cost last week, 4-week cost change, net margin; reach, stores selling, stores open, out-of-stock share.",
     "Feature engineering",
     "Y = f(X)", "Done"),
    ("Features: calendar and macro",
     "Payday, holidays, Christmas season, December, weeks to Christmas, week and month as sine / cosine, trend; FX, inflation "
     "(year and month), Brent oil.",
     "Cyclical encoding, event flags, external regressors",
     "Common vs special-cause drivers", "Done"),
    ("Categorical encoding",
     "Groups (segment, insight, ABC, imported) as 0/1 flags; SubGroup as a native category in LightGBM.",
     "One-hot encoding, native categorical handling",
     "-", "Done"),
    ("Target design and transformation",
     "Target = log(units + 1) minus log(13-week average + 1): demand relative to its own recent level.",
     "Log transform, target normalisation",
     "-", "Done"),
    ("Leakage prevention",
     "Every input is known at the decision week: lags shifted, no same-week outcome (e.g. spikes) used as input.",
     "Data leakage control",
     "Mistake-proofing", "Done"),
    ("Train / validation / test split",
     "By time: train before 6 Apr 2026, validation to 5 Jul 2026, test after.",
     "Time-based hold-out",
     "-", "Done"),
    ("Scaling",
     "Inputs standardised (mean 0, SD 1) before Lasso and PCA.",
     "Standardisation (StandardScaler)",
     "-", "Done"),
    ("Multicollinearity check",
     "Inputs with VIF above 10 dropped for the linear set.",
     "VIF (variance inflation factor)",
     "Screening of Xs", "Done"),
    ("Regularised selection",
     "Lasso with time-ordered cross-validation. Keeping all 50 inputs beat VIF + Lasso (WAPE 28.8% vs 39.4%), so all 50 kept.",
     "L1 regularisation (Lasso), embedded selection",
     "Vital few vs trivial many", "Done"),
    ("Wrapper selection",
     "LightGBM recursive elimination (drop weakest 10% while accuracy holds): 45 inputs kept for tree models.",
     "RFE (recursive feature elimination), feature importance",
     "Screening of Xs", "Done"),
    ("Dimensionality reduction",
     "PCA on calendar, macro and demand-lag blocks (90% variance kept). Did not improve accuracy, so not used.",
     "PCA (principal component analysis), explained variance",
     "Variation reduction test", "Done"),
    ("Cross-validation design",
     "5 time-ordered folds (train on the past, test on the next block).",
     "TimeSeriesSplit cross-validation",
     "-", "Done"),
    ("Elasticity per article",
     "3 models: store fixed effects + controls; store + week fixed effects; chain time series. Clearance weeks out.",
     "Log-log regression, fixed effects (within transformation)",
     "Regression analysis", "Done"),
    ("Statistical tests",
     "Sign and significance of the price effect; standard errors clustered by store or HAC for time series.",
     "Hypothesis testing, clustered and HAC standard errors",
     "Hypothesis testing", "Done"),
    ("Combine the estimates",
     "3 estimates combined, weighted by precision. 2,829 articles have their own estimate.",
     "Random-effects meta-analysis (DerSimonian-Laird)",
     "Reduce measurement variation", "Done"),
    ("Behaviour clusters",
     "Articles grouped into 8 clusters by behaviour.",
     "k-means clustering (unsupervised learning)",
     "Stratification", "Done"),
    ("Pooling",
     "No pooling vs SubGroup vs behaviour cluster vs hierarchical, chosen by back-test: behaviour clusters won.",
     "Empirical Bayes shrinkage, hierarchical models",
     "Rational subgrouping", "Done"),
    ("Rise vs cut",
     "Rises and cuts measured separately on real price events (rise -5 to -0.2, cut -4 to -0.1).",
     "Asymmetric response",
     "Stratification", "Done"),
    ("Switching between substitutes",
     "Own move vs SubGroup move; switching only where both models agree; at most 60% of lost units to a substitute.",
     "Cross-price elasticity, diversion ratio",
     "Interaction effects", "Done"),
    ("Limits and confidence",
     "Limits -4 to -0.2. Confidence High 518 / Medium 1,214 / Low 2,080; Low uses a cautious value.",
     "Bounded estimates, uncertainty scoring",
     "Risk-based decisions", "Done"),
    ("Back-test of price response",
     "Price changes from 11 May 2026 held out. Calibration slope about 0.28: real short-run reactions are about 2x weaker "
     "than the model, so the plan is cautious.",
     "Out-of-sample validation, calibration slope, placebo noise, interval coverage",
     "Verify root cause, model validation", "Done"),
    ("Sensitivity by store class",
     "A -1.05, B -1.15, C -1.22, P -1.37, wholesale -0.87: one chain price kept, with store exceptions.",
     "Segment-level estimation",
     "Stratification", "Done"),
    ("Sensitivity over time",
     "Last 12 months vs older (inflation 31% to 8%). Beverages -1.1 to -1.8. Re-weighting tested, not adopted overall.",
     "Structural break / drift test",
     "Stability over time", "Done"),
    ("Demand model candidates",
     "Linear, Random Forest, LightGBM, XGBoost, CatBoost.",
     "Supervised regression, bagging, gradient boosting",
     "Comparative experiment", "Done"),
    ("Model structure",
     "One global model beat one per MainGroup (WAPE 43.9%) and one per article (55.9%).",
     "Global vs local models",
     "Comparative experiment", "Done"),
    ("Hyperparameters",
     "Fixed, sensible settings so far (e.g. LightGBM 700 trees, learning rate 0.04, 63 leaves). A tuning search with "
     "time-ordered CV is still to do.",
     "Hyperparameter tuning (grid / random / Bayesian search)",
     "DOE on model settings", "To do"),
    ("Training design",
     "Price effect forced to be downward (monotone); recent weeks weigh more (26-week half-life); level calibration limited to "
     "0.9-1.1.",
     "Monotone constraints, sample weighting, calibration",
     "Mistake-proofing", "Done"),
    ("Multi-week forecasting method",
     "Inputs frozen at the forecast start beat feeding forecasts back in (WAPE 38.9% vs 45.7%).",
     "Direct vs recursive multi-step forecasting",
     "-", "Done"),
    ("Benchmarks and back-test",
     "Against last 13 weeks, x season, last year x trend; 7 start dates x 13 weeks; WAPE and bias by horizon.",
     "Rolling-origin back-test, WAPE, bias, naive benchmarks",
     "Baseline vs improved", "Done"),
    ("Ensemble",
     "50% ML + 50% seasonal benchmark won: WAPE 42.6% per article-week, 32.7% over 13 weeks; ML weight fades to 0 by week 26.",
     "Model blending (ensemble)",
     "Solution selection", "Done"),
    ("Seasonal path",
     "From 2024 and 2025; an article-level pattern only where both years agree.",
     "Seasonal indices, analogue years",
     "Common-cause variation", "Done"),
    ("52-week forecast with ranges",
     "3,244 articles x 52 weeks from 9 Nov 2026, low / high range (width capped at 1.5x).",
     "Prediction intervals, coverage check",
     "-", "Done"),
    ("Explainability",
     "Which inputs drive the forecast; model price effect compared with the elasticities.",
     "SHAP, permutation importance, partial dependence, model card",
     "Verify the Xs", "Done"),
    ("Use the business forecast instead",
     "python scripts/allsku_optimise.py --forecast file.csv (SKU_Code, Week_Start, Units); missing articles use ours.",
     "Plug-in forecast input",
     "Flexible standard work", "Done"),
    ("Supply risk",
     "Selling in under 70% of usual stores in the last 4 weeks = no price cut.",
     "Availability rule",
     "Risk screening", "Done"),
    ("Stock link",
     "Use stock cover (monthly stock + weekly sales): no cut when stock is short and cannot be refilled; overstock goes to "
     "markdown, not a rise. Weeks of cover is built; the full rule is still to add.",
     "Rule-based constraint from inventory data",
     "Risk screening", "To do"),
    ("Price grid simulation",
     "-15% to +15%, only inside prices already tried; own and switching effects; ranges kept.",
     "Simulation, scenario grid",
     "Design space", "Done"),
    ("Profit grid",
     "Profit = price without IVA - latest cost, with FX and inflation cost drift; profit gained by substitutes counted.",
     "Profit simulation, uncertainty bands",
     "Y = f(X) transfer function", "Done"),
    ("Cost pass-through scan",
     "Cost change vs price change over 26 weeks; catch-up suggestion.",
     "Gap analysis",
     "Gap analysis, Pareto", "Done"),
    ("Overstock and slow movers",
     "Many weeks of stock + falling sales = markdown candidate.",
     "Rule-based targeting",
     "Waste (muda)", "Done"),
    ("Markdown / clearance optimisation",
     "For overstock and slow movers: how deep to cut, for how long, to clear stock at the best profit.",
     "Markdown optimisation (price path over time)",
     "Waste removal", "To do"),
    ("Goal and limits (Max-profit plan)",
     "Step at most 10%; inside tested range; unit loss at most 10% (A) / 15% (others); cautious profit of each SubGroup must "
     "not fall; no rise if repriced 15% in 26 weeks; no cut on supply risk; never below cost; KVIs held; tail = cost "
     "pass-through; smallest move giving 90% of the gain.",
     "Constrained optimisation",
     "CTQs as specification limits", "Done"),
    ("Optimiser",
     "Coordinate ascent +$3.41M but 556 price-order breaks; MILP +$2.25M with 0 breaks. MILP chosen.",
     "Mixed-integer linear programming (HiGHS) vs heuristic search",
     "Solution selection matrix", "Done"),
    ("Profit vs units frontier",
     "Unit-loss limit 5 / 10 / 15 / 20%: $1.53M / $2.20M / $2.49M / $2.61M a year.",
     "Pareto frontier",
     "Trade-off analysis", "Done"),
    ("Scenarios",
     "Cautious / likely / optimistic; cost drift +$2.24M; FX +10% +$2.21M; KVIs unlocked +$2.79M.",
     "Scenario and stress testing, sensitivity analysis",
     "Robustness check", "Done"),
    ("Timing",
     "Start week tested around December; barely matters (about $540K per 13 weeks).",
     "Time-window sensitivity",
     "Pilot planning", "Done"),
    ("Risk review",
     "What can go wrong (wrong cost, wrong IVA, price not loaded, stock-outs, customer backlash), how bad, how likely, how we "
     "catch it.",
     "-",
     "FMEA, risk register (RPN)", "To do"),
    ("Shelf prices",
     "Price with IVA, endings rounded, key price points not crossed without reason; rounding costs -$5.6K a year.",
     "Post-processing",
     "Standardisation", "Done"),
    ("Store rules",
     "Store tiers kept, HRCA out, no staple rises in wholesale, stores more than 12% off the chain flagged.",
     "Rule engine",
     "Standard work", "Done"),
    ("Business rules check",
     "19 rules per article: 0 failures, 954 flags (mostly the 14% IVA price gap).",
     "Automated validation",
     "Poka-yoke", "Done"),
    ("Reason per article",
     "Plain-language reason for each change.",
     "Explainable output",
     "Visual management", "Done"),
    ("Rollout waves",
     "Wave 1: 522 articles ($613K); Review: 704 ($1.38M); Test: 104 ($130K); Hold: 1,914.",
     "Risk-based staging",
     "Pilot, phased rollout", "Done"),
    ("Holdout control stores",
     "30 matched store pairs keep old prices; a 4-week test detects a change of 7.6%.",
     "Matched pairs, placebo test, minimum detectable effect (power)",
     "DOE, control group", "Done"),
    ("Impact for any date window",
     "Weekly impact for 52 weeks; the user picks start and end. Example 30 Nov - 31 Jan: +$380K.",
     "Aggregation",
     "Benefit tracking", "Done"),
    ("Excel price list",
     "Prices, reasons, rules, waves, store exceptions, holdout pairs, date windows.",
     "Reporting",
     "-", "Done"),
    ("Business deck (USD, Newaco theme)",
     "Waits for the IVA and KVI answers.",
     "Data storytelling",
     "Storyboard", "To do"),
    ("Dashboard update",
     "Date picker and forecast upload (template, validation, Our / Uploaded switch). Only when asked.",
     "Interactive analytics",
     "Visual management", "To do"),
    ("Change management and training",
     "Train category teams to read and review the list; how to override and why; who signs off.",
     "-",
     "Change management, RACI, training plan", "To do"),
    ("Reproducibility",
     "Scripts in a fixed run order, fixed random seed (2026), cached steps, backups before each refresh.",
     "Reproducible pipeline",
     "Standard work", "Done"),
    ("Approval workflow",
     "Small rule-compliant changes auto-approved; big ones routed; overrides logged.",
     "Decision rules",
     "RACI, standard work", "At go-live"),
    ("Release to POS and reconciliation",
     "Approved prices vs prices loaded in the till, every release.",
     "Data reconciliation",
     "Poka-yoke, MSA", "At go-live"),
    ("Execution compliance",
     "Selling price from sales data vs approved price, per store.",
     "Monitoring from transaction data",
     "Compliance audit", "At go-live"),
    ("Control charts",
     "Margin (I-MR), price accuracy (p-chart), KVI units; alerts outside limits.",
     "Monitoring, alerting",
     "SPC, Cpk at least 1.33", "At go-live"),
    ("Measure the real gain",
     "After 4 weeks: test vs holdout stores, read with finance.",
     "Difference-in-differences (causal inference)",
     "Verify improvement, benefit sign-off", "At go-live"),
    ("Model monitoring and refresh",
     "Quarterly re-estimation; drift check; a new model must beat the current one.",
     "Drift detection, retraining, champion-challenger",
     "Kaizen", "At go-live"),
    ("Control plan",
     "Weekly / monthly / quarterly routine, block below-cost prices, one price master.",
     "MLOps routine",
     "Control plan, standard work", "At go-live"),
    ("Promotion analysis",
     "Which promotions make or lose money; promo weeks kept out of the base demand.",
     "Uplift / incrementality modelling",
     "Pareto of loss-making promos", "Needs data"),
    ("Competitor prices and price image",
     "KVI prices vs rivals; price index tracked over time.",
     "Price index, competitive response",
     "Benchmarking", "Needs data"),
    ("Government-controlled prices",
     "Articles with legal price limits or a regulated basic basket, added as hard rules.",
     "Hard constraints",
     "Requirements capture", "Needs data"),
    ("Supplier funding and rebates",
     "Rebates and bonuses outside the invoice, added to true margin.",
     "Margin enrichment",
     "-", "Needs data"),
    ("Short description layer (e.g. CLQ 10 kg BR / CN)",
     "Price ladders between sizes and brands, pooling across sibling articles, switching between them.",
     "Hierarchical models, price ladders",
     "Stratification", "Later"),
]

NOT_USED = [
    ["Hyperparameter search", "Not run yet; settings are fixed. Listed as a to-do step."],
    ["Deep learning (LSTM, transformers)", "Not needed at this data size; boosted trees and benchmarks are more accurate and easier to explain."],
    ["ARIMA / Prophet per article", "Thousands of short, noisy series; the global model + seasonal benchmark beat per-article models (55.9%)."],
    ["t-SNE / UMAP", "Only for pictures; PCA already showed no gain from reducing inputs."],
    ["Class balancing (SMOTE etc.)", "Not relevant: we predict units (a number), not a class."],
    ["Reinforcement learning for prices", "Needs live price experiments; the MILP with guardrails is safer to start."],
    ["Store-level (zone) prices", "Store classes react alike (-0.87 to -1.37), so one chain price with exceptions is kept."],
]

LIMITS = [
    ["Model reactions too strong", "Short-run reactions are about 2x weaker than the model says (calibration slope 0.28).",
     "Cautious values used; real gain measured with holdout stores."],
    ["Many articles with little evidence", "2,080 articles have Low confidence.", "Cautious value, small steps, review wave."],
    ["Forecast error", "WAPE 42.6% per article-week (32.7% over 13 weeks).", "Ranges shown; gain read over months, not weeks."],
    ["Sales include IVA", "Margin depends on the IVA answer from finance.", "Net of IVA used until finance confirms."],
    ["14% IVA price gap", "About $30M of sales sell ~9% below the system price.", "Flagged on 954 articles; waits for finance / IT."],
    ["No promo, competitor or rebate data", "Promotion and price-image effects are not in the model.", "Listed as data requests."],
    ["Monthly stock only", "Stock link uses monthly closing stock, not daily.", "Weekly cover estimated; daily stock requested."],
    ["Hyperparameters not tuned", "Accuracy could improve a little.", "Tuning step added."],
]

TIMELINE = [
    ["1-2", "Business answers; to-do steps: today's performance, Cpk baseline, stock link, markdown optimisation, risk review, "
            "hyperparameter tuning", "Business (finance, commercial) + data science"],
    ["3", "Re-run the plan with the answers; business deck; review with category managers", "Data science + category managers"],
    ["4", "Approval; training; load Wave 1 to POS; holdout stores kept", "Pricing owner, IT"],
    ["5-8", "Wave 1 live; weekly compliance and control charts", "Pricing owner, data science"],
    ["9", "Read the real gain with finance; decide the Review wave", "Finance, sponsor"],
    ["Every quarter", "Model refresh, drift check, champion-challenger", "Data science"],
]


def box(text, width=PAGE_W):
    t = Table([[Paragraph(text, S["body"])]], colWidths=[width * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("LINEBEFORE", (0, 0), (0, -1), 3, GOLD),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


def grid(data, widths):
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PURPLE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TINT]),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D9D2DB")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    return t


def table(rows, widths, first_bold=False):
    data = [[Paragraph(c, S["cellb"]) for c in rows[0]]]
    data += [[Paragraph(c, S["num"] if (first_bold and i == 0) else S["cell"]) for i, c in enumerate(r)] for r in rows[1:]]
    return grid(data, widths)


def steps_table():
    head = ["#", "Step", "What we do, what we tested and what we chose", "Data science steps", "Six Sigma steps", "Status"]
    data = [[Paragraph(c, S["cellb"]) for c in head]]
    for i, (step, what, ds, ss, st) in enumerate(STEPS, 1):
        data.append([Paragraph(str(i), S["num"]), Paragraph(f"<b>{step}</b>", S["cell"]), Paragraph(what, S["cell"]),
                     Paragraph(ds, S["cell"]), Paragraph(ss, S["cell"]),
                     Paragraph(f"<b>{st}</b>", ParagraphStyle("st", parent=S["cell"], textColor=colors.HexColor(STATUS[st])))])
    return grid(data, [9, 40, 94, 54, 40, 20])


REPORT_TITLE = "Fresmart Price Optimisation"
REPORT_SUB = "Method report: every step, with the data science and Lean Six Sigma steps behind it"


def on_cover(c, doc):
    c.saveState()
    w, h = landscape(A4)
    band_top = h - 52 * mm
    c.setFillColor(PURPLE); c.rect(0, 0, w, band_top, stroke=0, fill=1)
    c.setFillColor(GOLD); c.rect(0, band_top - 2.2 * mm, w, 2.2 * mm, stroke=0, fill=1)
    if LOGO.exists():
        c.drawImage(str(LOGO), 20 * mm, h - 43 * mm, width=34 * mm, height=34 * mm * 154 / 192, mask="auto")
    c.setFont("Helvetica", 9); c.setFillColor(GREY)
    c.drawRightString(w - 20 * mm, h - 22 * mm, "Newaco Grupo, SA  ·  Fresmart")
    c.drawRightString(w - 20 * mm, h - 27 * mm, "CONFIDENTIAL · INTERNAL USE")
    x, y = 20 * mm, band_top - 34 * mm
    c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x, y, "PRICE OPTIMISATION  ·  ALL ACTIVE ARTICLES")
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 36)
    c.drawString(x, y - 17 * mm, REPORT_TITLE)
    c.setFont("Helvetica", 16)
    c.drawString(x, y - 28 * mm, "Method report")
    c.setFont("Helvetica", 11.5); c.setFillColor(colors.HexColor("#E6DCE8"))
    c.drawString(x, y - 37 * mm, f"Every step, start to finish: {len(STEPS)} steps with the data science and Lean Six Sigma steps behind them")
    c.setStrokeColor(GOLD); c.setLineWidth(0.8)
    c.line(x, 52 * mm, w - 20 * mm, 52 * mm)
    meta = [("Prepared for", "Fresmart management"), ("Prepared by", "Price optimisation team"),
            ("Version", "1.0"), ("Date", "16 November 2026")]
    colw = (w - 40 * mm) / len(meta)
    for i, (k, v) in enumerate(meta):
        c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x + i * colw, 44 * mm, k.upper())
        c.setFillColor(colors.white); c.setFont("Helvetica", 11)
        c.drawString(x + i * colw, 37.5 * mm, v)
    c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#CDBFD1"))
    c.drawString(x, 18 * mm, "Money in US dollars. Profit is without IVA. Figures: Fresmart sales to 12 Nov 2026, active articles.")
    c.restoreState()


def on_page(c, doc):
    c.saveState()
    w, h = landscape(A4)
    c.setFont("Helvetica-Bold", 8); c.setFillColor(PURPLE)
    c.drawString(20 * mm, h - 9 * mm, REPORT_TITLE.upper())
    c.setFont("Helvetica", 8); c.setFillColor(GREY)
    c.drawRightString(w - 20 * mm, h - 9 * mm, "Method report · v1.0 · Confidential")
    c.setStrokeColor(colors.HexColor("#D9D2DB")); c.setLineWidth(0.5)
    c.line(20 * mm, h - 11 * mm, w - 20 * mm, h - 11 * mm)
    c.setStrokeColor(GOLD); c.setLineWidth(1)
    c.line(20 * mm, 13 * mm, w - 20 * mm, 13 * mm)
    c.setFont("Helvetica", 8); c.setFillColor(GREY)
    c.drawString(20 * mm, 8.5 * mm, "Fresmart price optimisation · every step: data science + Lean Six Sigma · November 2026")
    c.drawRightString(w - 20 * mm, 8.5 * mm, f"Page {doc.page}")
    c.restoreState()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "Fresmart_Price_Optimisation_Method_DS_and_Six_Sigma.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=20 * mm, rightMargin=20 * mm, topMargin=15 * mm,
                            bottomMargin=19 * mm, title="Fresmart price optimisation: every step",
                            author="Price optimisation team")
    n = Counter(s[4] for s in STEPS)
    count_row = [f"{n[k]}" for k in STATUS]
    st = [Spacer(1, 1), PageBreak(),
          Paragraph("1. Overview", S["h1"]), Spacer(1, 2),
           Paragraph("This document lists every step of the price optimisation for all Fresmart active articles, in the order they "
                     "are done: from the project goal, data collection and cleaning, feature engineering, feature selection and "
                     "dimensionality reduction, through price sensitivity, demand forecasting, simulation and optimisation, to the "
                     "price list, go-live and control. For each step it shows what we do, what we tested and chose, the data "
                     "science steps and the Lean Six Sigma steps. Money is in US dollars; profit is without IVA.",
                     S["body"]), Spacer(1, 8),
           Paragraph("Where we are", S["h2"]),
           table([list(STATUS)] + [count_row], [PAGE_W / len(STATUS)] * len(STATUS)),
           Spacer(1, 8),
           Paragraph("Results so far (52 weeks from 9 Nov 2026)", S["h2"]),
           table([["Price changes", "Profit gain per year", "Units / sales", "Customer basket", "Rule checks"],
                  ["1,329 rises (median +5%), 1 cut", "+$2.18M (cautious $1.97M, optimistic $2.32M)", "-1.6% / +0.3%",
                   "+1.98% (about 3.3 months of inflation)", "0 failures, 954 flags"]], [50, 62, 40, 58, 47]),
           Spacer(1, 8),
           box("<b>Status:</b> <b>Done</b> = built and tested · <b>Draft</b> = built, waiting for business confirmation · "
               "<b>To do</b> = next, data available · <b>Needs data</b> = waiting for data or a business answer · "
               "<b>At go-live</b> = after the price list is approved · <b>Later</b> = after the SKU lens is accepted."),
           PageBreak(),
           Paragraph("2. All steps", S["h1"]), steps_table(),
           PageBreak(),
           Paragraph("3. Known limitations", S["h1"]),
           table([["Limitation", "What it means", "How we handle it"]] + LIMITS, [60, 100, 97], first_bold=True),
           Spacer(1, 10),
           Paragraph("4. Proposed timeline and owners (to agree)", S["h1"]),
           table([["Week", "What", "Who"]] + TIMELINE, [25, 162, 70], first_bold=True),
           PageBreak(),
           Paragraph("5. Data science methods considered but not used, and why", S["h1"]),
           table([["Method", "Why not (yet)"]] + NOT_USED, [70, 187], first_bold=True),
           Spacer(1, 10),
           Paragraph("6. Concept guide in plain words", S["h1"]),
           table([["Concept", "In plain words"],
                  ["Imputation", "Filling missing values in a sensible way (e.g. carry the last known price forward)."],
                  ["Robust outlier detection", "Find unusual weeks using the median, which a few extreme weeks cannot distort."],
                  ["Feature engineering", "Turning raw data into model inputs (e.g. units last week, price vs usual price)."],
                  ["Cyclical encoding (sine / cosine)", "Lets the model know week 52 and week 1 are next to each other."],
                  ["One-hot encoding", "Turning a group name into 0/1 columns a model can read."],
                  ["Standardisation", "Putting inputs on the same scale so none dominates just because of its units."],
                  ["Data leakage", "Using information the model would not have on the day; we block it."],
                  ["VIF", "Spots inputs that say the same thing as others."],
                  ["Lasso", "A model that pushes useless inputs to zero."],
                  ["RFE", "Removes the weakest inputs one round at a time while accuracy holds."],
                  ["Dimensionality reduction (PCA)", "Squeezes many related inputs into a few summary inputs."],
                  ["Time-series cross-validation", "Always train on the past and test on the future, several times."],
                  ["Fixed effects", "Compare like with like (same store, same week) so price is not confused with other effects."],
                  ["Meta-analysis", "Combine several estimates, trusting the more precise ones more."],
                  ["k-means clustering", "Groups articles that behave alike."],
                  ["Empirical Bayes / pooling", "An article with little data borrows strength from similar articles."],
                  ["Price elasticity", "% change in units for a 1% change in price; -1.5 means a 10% rise loses about 15% of units."],
                  ["Gradient boosting", "Many small decision trees, each fixing the errors of the previous ones."],
                  ["Monotone constraint", "Forces the model to agree that a higher price never sells more."],
                  ["Hyperparameters", "Settings of a model (e.g. number of trees) chosen before training."],
                  ["WAPE / bias", "Forecast error as a % of actual units / whether we forecast too high or too low on average."],
                  ["Calibration slope", "1.0 = model reactions are right in size; 0.28 = real reactions are smaller."],
                  ["Ensemble", "Averaging two forecasts that make different mistakes."],
                  ["Prediction interval", "A low-high range around the forecast."],
                  ["SHAP / partial dependence", "Show which inputs drive the forecast and how."],
                  ["MILP", "Searches all allowed price combinations and finds the best that obeys every rule."],
                  ["Pareto frontier", "The best profit possible for each level of unit loss."],
                  ["Minimum detectable effect", "The smallest change a test can reliably see."],
                  ["Difference-in-differences", "Compare test stores with similar unchanged stores, before and after."],
                  ["Drift, champion-challenger", "Notice when a model gets worse; a new model must beat the old one to replace it."],
                  ["SIPOC / CTQ", "One-line process map / measurable must-haves from the customer and business."],
                  ["MSA", "Check the measurement is right before using it (is the recorded price the real price?)."],
                  ["Pareto (80/20), fishbone, 5 Whys", "Focus on the few that matter; find the root cause, not the symptom."],
                  ["Cp / Cpk, SPC charts", "How reliably a process stays inside its limits; charts that alert when it does not."],
                  ["FMEA", "List what can go wrong, how bad and how likely, and how to prevent it."],
                  ["Poka-yoke", "Mistake-proofing: rules that make wrong prices impossible."],
                  ["DOE / control group", "A planned test with stores that do not change, to prove the gain."],
                  ["Kaizen, control plan", "Small regular improvements; who checks what, how often, and what to do."]],
                 [70, 187], first_bold=True)]

    doc.build(st, onFirstPage=on_cover, onLaterPages=on_page)
    print(path, len(STEPS), dict(n))


if __name__ == "__main__":
    main()
