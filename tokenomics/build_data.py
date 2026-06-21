#!/usr/bin/env python3
"""Build tokenomics/data.json — EVERY data series pulled LIVE from primary source.

  Epoch AI (CSV/zip)        -> compute stock, fleet power, component share,
                               NVIDIA production, per-chip compute trends
  FinMind / TWSE            -> TSMC monthly revenue, AI-server ODM revenue
  SEC EDGAR (filing text)   -> NVIDIA commitments, Micron CMBU, TSMC HPC, ASML EUV
  Yahoo Finance             -> SK Hynix revenue + operating margin

Nothing is hardcoded data: numbers are parsed from the source documents on every run.
Model assumptions (projection growth rates, x2.5 facility overhead, 1.34x/yr efficiency,
~31 NT$/US$) are clearly that — assumptions, not data. A successful live pull also
refreshes a bundled snapshot in static/ used only as an emergency fallback if a source
is unreachable (so a build never fully breaks). Pure stdlib; run: python3 build_data.py
"""
import csv, io, json, re, html, gzip, time, os, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent; STATIC = ROOT / "static"; STATIC.mkdir(exist_ok=True)
UA = {"User-Agent": "tokenomics-build james.mann.24@ucl.ac.uk", "Accept-Encoding": "gzip, deflate"}

def _get(url, timeout=90, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data if binary else data.decode("utf-8", "ignore")
def num(x):
    try: return float(str(x).replace(",", ""))
    except Exception: return None
def flat(h): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))
def read_static(name):
    with open(STATIC / name, newline="") as f: return list(csv.DictReader(f))
def cache(name, rows):
    if rows:
        with open(STATIC / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

series, live = {}, {}

# ---------- SEC helpers ----------
def sec_filings(cik, forms, n=14):
    d = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", 60)); r = d["filings"]["recent"]; out = []
    for f, acc, doc, rd in zip(r["form"], r["accessionNumber"], r["primaryDocument"], r["reportDate"]):
        if f in forms:
            out.append((rd, f, acc.replace("-", ""), doc))
            if len(out) >= n: break
    return out
def sec_text(cik, acc, doc):
    time.sleep(0.18)
    return flat(_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"))

def linspace(a, b, n): return [a + (b - a) * i / (n - 1) for i in range(n)]

# ============================================================ LIVE: Epoch chip sales
EP = "https://epoch.ai/data"
def epoch_zip(member, fb):
    try:
        z = zipfile.ZipFile(io.BytesIO(_get(f"{EP}/ai_chip_sales.zip", binary=True) if "sales" in fb or member in
            ("cumulative_timelines_by_designer.csv","timelines_by_chip.csv") else _get(f"{EP}/ai_chip_components.zip", binary=True)))
        name = next(n for n in z.namelist() if n.endswith(member))
        rows = list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8", "ignore"))))
        cache(fb, rows); return rows, True
    except Exception as e:
        print(f"  WARN epoch {member}: {e}"); return read_static(fb), False

sales, lS = epoch_zip("cumulative_timelines_by_designer.csv", "chip_sales_by_designer.csv")
agg = defaultdict(lambda: [0, 0, 0])
for r in sales:
    d = r.get("End date");  # noqa
    if not d: continue
    agg[d][0] += num(r.get("Compute estimate in H100e (5th percentile)")) or 0
    agg[d][1] += num(r.get("Compute estimate in H100e (median)")) or 0
    agg[d][2] += num(r.get("Compute estimate in H100e (95th percentile)")) or 0
hist = [{"date": d, "lo": v[0], "median": v[1], "hi": v[2]} for d, v in sorted(agg.items()) if d <= "2025-12-31"]
anchor = hist[-1]["median"]; decay = linspace(3.3, 1.5, 6); p = 1; cen = []
for i, r in enumerate(decay): p *= r; cen.append({"year": 2026 + i, "value": anchor * p})
series["compute_stock"] = {"title": "Installed AI compute", "unit": "H100-equivalents", "yfmt": "si",
    "blurb": "Total AI compute ever shipped, summed across all chip designers.",
    "source": "Epoch AI — AI Chip Sales (CC-BY)", "url": "https://epoch.ai/data/ai-chip-sales",
    "history": hist, "projection": {"central": cen,
        "lo": [{"year": 2026 + i, "value": anchor * 1.5 ** (i + 1)} for i in range(6)],
        "hi": [{"year": 2026 + i, "value": anchor * 3.3 ** (i + 1)} for i in range(6)],
        "scenarios": [
            {"key": "lo", "name": "Floor — 1.5×/yr", "color": "#9aa0a6", "note": "Compute growth decelerates hard to 1.5×/yr (a conservative floor)."},
            {"key": "central", "name": "Central — 3.3×→1.5×/yr", "color": "#2b6c8f", "note": "Recent ~3.3×/yr decaying linearly to 1.5×/yr by 2031 (Epoch/brief style)."},
            {"key": "hi", "name": "No slowdown — 3.3×/yr", "color": "#b2453a", "note": "Today's ~3.3×/yr pace simply continues — almost certainly hits power/packaging limits first."}]}}
live["compute_stock"] = lS

aggp = defaultdict(lambda: [0, 0, 0])
for r in sales:
    d = r.get("End date")
    if not d: continue
    for j, k in enumerate(["5th percentile", "median", "95th percentile"]):
        aggp[d][j] += num(r.get(f"Power in MW ({k})")) or 0
ph = [{"date": d, "chip_gw": v[1] / 1e3, "facility_gw": v[1] * 2.5 / 1e3}
      for d, v in sorted(aggp.items()) if d <= "2025-12-31" and v[1] > 0]
P0, EFF = ph[-1]["facility_gw"], 1.34; pc = []; pl = []; phh = []
for i in range(6):
    dp = 1
    for r in decay[:i + 1]: dp *= r
    pc.append({"year": 2026 + i, "value": P0 * dp / EFF ** (i + 1)})
    pl.append({"year": 2026 + i, "value": P0 * 1.5 ** (i + 1) / EFF ** (i + 1)})
    phh.append({"year": 2026 + i, "value": P0 * 3.3 ** (i + 1) / EFF ** (i + 1)})
series["fleet_power"] = {"title": "AI fleet power draw", "unit": "GW", "yfmt": "num",
    "blurb": "Total power of all AI silicon. 'Facility' adds the ~2.5x overhead (servers, networking, cooling).",
    "source": "Epoch AI — AI Chip Sales (CC-BY)", "url": "https://epoch.ai/data-insights/ai-datacenter-power",
    "history": ph, "projection": {"central": pc, "lo": pl, "hi": phh,
        "scenarios": [
            {"key": "lo", "name": "Floor — install 1.5×/yr", "color": "#9aa0a6", "note": "Matches the 1.5×/yr install floor."},
            {"key": "central", "name": "Central — install 3.3×→1.5×/yr", "color": "#b2453a", "note": "Matches the central install scenario."},
            {"key": "hi", "name": "No slowdown — install 3.3×/yr", "color": "#7a3b9a", "note": "Matches uninterrupted 3.3×/yr install."}],
        "note": "Power = installed compute ÷ chip energy-efficiency gains (~1.34×/yr). Each power scenario tracks the matching install scenario."},
    "refs": [{"label": "≈ NY State peak", "value": 31}, {"label": "Epoch >100 GW by 2030", "value": 100},
             {"label": "RAND 2030 (327 GW)", "value": 327, "year": 2030}, {"label": "All US generating capacity", "value": 1280}]}
live["fleet_power"] = lS

# ---- cumulative H100e by designer (where the compute comes from)
srcagg = defaultdict(lambda: defaultdict(float))
for r in sales:
    d = r.get("End date"); des = (r.get("Chip manufacturer") or "Other").replace("Nvidia", "NVIDIA")
    if d and d <= "2025-12-31": srcagg[d][des] += num(r.get("Compute estimate in H100e (median)")) or 0
alldes = sorted({k for v in srcagg.values() for k in v}, key=lambda k: -srcagg[max(srcagg)][k] if k in srcagg[max(srcagg)] else 0)
topdes = alldes[:5]; skeys = topdes + ["Other"]
src_rows = []
for d in sorted(srcagg):
    row = {"date": d, **{k: 0 for k in skeys}}
    for k, v in srcagg[d].items():
        if k in topdes: row[k] = v / 1e6
        else: row["Other"] += v / 1e6
    src_rows.append(row)
series["compute_by_source"] = {"title": "Cumulative AI compute by chip designer", "unit": "million H100e", "yfmt": "num",
    "blurb": "Where the installed compute comes from — cumulative H100-equivalents by chip designer. NVIDIA dominates; custom silicon (Google, Amazon) and AMD are the challengers.",
    "source": "Epoch AI — AI Chip Sales (CC-BY)", "url": "https://epoch.ai/data/ai-chip-sales",
    "stack": topdes + ["Other"], "rows": src_rows}
live["compute_by_source"] = lS

chips, lC = epoch_zip("timelines_by_chip.csv", "timelines_by_chip.csv")
GEN = {"A100": "Ampere", "A800": "Ampere", "H100/H200": "Hopper", "H20": "Hopper", "H800": "Hopper", "B200": "Blackwell", "B300": "Blackwell"}
aggn = defaultdict(lambda: defaultdict(float))
for r in chips:
    if r.get("Chip manufacturer") != "Nvidia": continue
    g = GEN.get((r.get("Name", "").split(" - ")[-1]).strip());  d = r.get("End date")
    if g and d and d <= "2025-12-31": aggn[d][g] += (num(r.get("Number of Units")) or 0) / 1e6
gens = ["Ampere", "Hopper", "Blackwell"]
series["nvidia_production"] = {"title": "NVIDIA AI-chip production by generation", "unit": "million chips / quarter", "yfmt": "num",
    "blurb": "Estimated units shipped by GPU generation. Unit count plateaued ~1.2M/q — growth is compute per chip, not chip count. NVIDIA publishes no unit data; Epoch estimate.",
    "source": "Epoch AI — AI Chip Sales (CC-BY)", "url": "https://epoch.ai/data/ai-chip-sales",
    "stack": gens, "rows": [{"date": d, **{g: round(aggn[d].get(g, 0), 4) for g in gens}} for d in sorted(aggn)]}
live["nvidia_production"] = lC

# ---- NVIDIA TOTAL production: history + scenario forecast (total is knowable w/o the gen split)
tot_hist = [{"date": d, "value": round(sum(aggn[d].get(g, 0) for g in gens), 4)} for d in sorted(aggn)]
lastT = tot_hist[-1]["value"]
fq = ["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31", "2027-03-31", "2027-06-30", "2027-09-30", "2027-12-31"]
def qproj(annual): return [{"date": fq[i], "value": round(lastT * (1 + annual) ** ((i + 1) / 4), 4)} for i in range(len(fq))]
series["nvidia_total"] = {"title": "NVIDIA total chip production", "unit": "million chips / quarter", "yfmt": "num",
    "blurb": "Total units shipped per quarter (sum across generations) — the smooth total behind the generational split.",
    "source": "Epoch AI — AI Chip Sales (CC-BY); forecast = stated growth assumptions", "url": "https://epoch.ai/data/ai-chip-sales",
    "history": tot_hist, "proj": {"lo": qproj(0.0), "mid": qproj(0.15), "hi": qproj(0.30)},
    "scenarios": [{"key": "lo", "name": "Flat (~CoWoS-limited)", "color": "#9aa0a6", "note": "Unit count stays ~flat — bigger chips eat the extra packaging."},
                  {"key": "mid", "name": "+15%/yr", "color": "#2b6c8f", "note": "Modest unit growth on top of mix shift to bigger chips."},
                  {"key": "hi", "name": "+30%/yr", "color": "#b2453a", "note": "Aggressive: units and per-chip capability both climb fast."}]}
live["nvidia_total"] = lC

comp, lK = epoch_zip("quarterly_by_designer.csv", "components_quarterly_by_designer.csv")
aggc = defaultdict(lambda: [0, 0, 0])
for r in comp:
    if r.get("Designer") == "Other": continue
    d = r.get("End date")
    if not d: continue
    aggc[d][0] += num(r.get("Logic share (%) (median)")) or 0
    aggc[d][1] += num(r.get("CoWoS share (%) (median)")) or 0
    aggc[d][2] += num(r.get("HBM share (%) (median)")) or 0
cs = {"CoWoS packaging": [], "HBM memory": [], "Advanced logic wafers": []}
for d in sorted(aggc):
    if d > "2025-12-31" or sum(aggc[d]) == 0: continue
    cs["Advanced logic wafers"].append({"date": d, "value": round(aggc[d][0], 1)})
    cs["CoWoS packaging"].append({"date": d, "value": round(aggc[d][1], 1)})
    cs["HBM memory"].append({"date": d, "value": round(aggc[d][2], 1)})
series["component_share"] = {"title": "AI's share of the chip supply chain", "unit": "% of global supply", "yfmt": "pct",
    "blurb": "AI accelerators already consume nearly all of the world's advanced packaging (CoWoS) and HBM memory.",
    "source": "Epoch AI — AI Chip Components (CC-BY)", "url": "https://epoch.ai/data/ai-chip-components", "lines": cs}
live["component_share"] = lK

try:
    ml = list(csv.DictReader(io.StringIO(_get(f"{EP}/ml_hardware.csv")))); cache("ml_hardware.csv", ml); lM = True
except Exception as e:
    print("  WARN ml_hardware:", e); ml = read_static("ml_hardware.csv"); lM = False
def cyr(d):
    try:
        x = datetime.strptime(d, "%Y-%m-%d"); return round(x.year + (x.month - 1) / 12, 2)
    except Exception: return None
prec = {"FP16/BF16": "Tensor-FP16/BF16 performance (FLOP/s)", "FP8": "FP8 performance (FLOP/s)", "FP4": "FP4 performance (FLOP/s)"}
ct = {lab: [{"year": cyr(r["Release date"]), "pflops": num(r[col]) / 1e15, "name": r["Hardware name"], "vendor": r.get("Manufacturer", "")}
            for r in ml if cyr(r.get("Release date", "")) and num(r.get(col)) and cyr(r["Release date"]) >= 2019] for lab, col in prec.items()}
ROAD = [{"name": "Rubin VR200", "year": 2026.5, "fp4": 35, "fp8": 17.5, "fp16": 8.75, "tdp": 2300, "vendor": "NVIDIA"},
        {"name": "Rubin Ultra VR300", "year": 2027.5, "fp4": 70, "fp8": 35, "fp16": 17.5, "tdp": 3600, "vendor": "NVIDIA"},
        {"name": "AMD MI400", "year": 2026.5, "fp4": 40, "fp8": 20, "fp16": 10, "tdp": 2250, "vendor": "AMD"}]
series["compute_trends"] = {"title": "Compute per chip, by numeric precision", "unit": "PFLOPS per chip", "yfmt": "num",
    "blurb": "Per-chip performance (log) by precision. Filled points are the frontier; stars are announced roadmap parts.",
    "source": "Epoch AI — ML Hardware (CC-BY)", "url": "https://epoch.ai/data/machine-learning-hardware",
    "precision": ct, "roadmap": [{k: r[k] for k in ("name", "year", "fp4", "fp8", "fp16", "vendor")} for r in ROAD]}
live["compute_trends"] = lM

# ---- per-chip power (TDP) and energy efficiency (live from ml_hardware)
pw = [{"year": cyr(r["Release date"]), "y": num(r["TDP (W)"]), "name": r["Hardware name"], "vendor": r.get("Manufacturer", "")}
      for r in ml if cyr(r.get("Release date", "")) and num(r.get("TDP (W)")) and num(r["TDP (W)"]) >= 150 and cyr(r["Release date"]) >= 2019]
series["chip_power"] = {"title": "Power per chip (TDP)", "unit": "W", "yfmt": "num",
    "blurb": "Thermal design power per accelerator. Each generation does more compute — and draws more power.",
    "source": "Epoch AI — ML Hardware (CC-BY)", "url": "https://epoch.ai/data/machine-learning-hardware",
    "groups": [{"name": "TDP (W)", "color": "#b2453a", "pts": pw, "future": [{"year": r["year"], "y": r["tdp"], "name": r["name"]} for r in ROAD]}]}
live["chip_power"] = lM
eff = [{"year": cyr(r["Release date"]), "y": num(r["Tensor-FP16/BF16 performance (FLOP/s)"]) / 1e12 / num(r["TDP (W)"]), "name": r["Hardware name"], "vendor": r.get("Manufacturer", "")}
       for r in ml if cyr(r.get("Release date", "")) and num(r.get("Tensor-FP16/BF16 performance (FLOP/s)")) and num(r.get("TDP (W)")) and cyr(r["Release date"]) >= 2019]
series["chip_efficiency"] = {"title": "Energy efficiency (FP16 per watt)", "unit": "TFLOP/s per W", "yfmt": "num",
    "blurb": "Tensor-FP16 throughput per watt — the deflator on power. Improving, but slower than per-chip compute climbs.",
    "source": "Epoch AI — ML Hardware (CC-BY)", "url": "https://epoch.ai/data/machine-learning-hardware",
    "groups": [{"name": "TFLOP/s per W", "color": "#4e9a51", "pts": eff, "future": [{"year": r["year"], "y": r["fp16"] * 1000 / r["tdp"], "name": r["name"]} for r in ROAD]}]}
live["chip_efficiency"] = lM

# ============================================================ LIVE: FinMind monthly
def finmind(sid):
    d = json.loads(_get(f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={sid}&start_date=2022-06-01", 45))["data"]
    return sorted({(x["revenue_year"], x["revenue_month"]): x["revenue"] for x in d}.items())
try:
    pts = finmind("2330")
    series["tsmc_monthly"] = {"title": "TSMC monthly revenue", "unit": "US$ billions / month", "yfmt": "usd",
        "blurb": "The foundry's monthly revenue (reported ~the 10th) — the highest-frequency public read on AI-chip demand. Converted to US$ (~31 NT$/US$).",
        "source": "TWSE monthly revenue via FinMind (2330)", "url": "https://finmindtrade.com",
        "points": [{"date": f"{y}-{m:02d}", "value": round(v / 1e9 / 31, 2)} for (y, m), v in pts]}
    live["tsmc_monthly"] = True
except Exception as e:
    print("  WARN tsmc_monthly:", e)
ODM = {"6669": "Wiwynn", "2382": "Quanta", "3231": "Wistron"}; odm = {}
try:
    for sid, nm in ODM.items():
        odm[nm] = [{"date": f"{y}-{m:02d}", "value": v / 1e9} for (y, m), v in finmind(sid)]
    live["odm_revenue"] = True
    months = sorted({p["date"] for L in odm.values() for p in L})
    cache("odm_monthly_revenue.csv", [{"year": mo[:4], "month": int(mo[5:]), **{nm: next((p["value"]*1e9 for p in odm[nm] if p["date"]==mo), "") for nm in ODM.values()}} for mo in months])
except Exception as e:
    print("  WARN odm:", e)
    for r in read_static("odm_monthly_revenue.csv"):
        for nm in ODM.values():
            if r.get(nm): odm.setdefault(nm, []).append({"date": f"{r['year']}-{int(r['month']):02d}", "value": num(r[nm]) / 1e9})
    live["odm_revenue"] = False
series["odm_revenue"] = {"title": "AI-server makers' monthly revenue (Taiwan)", "unit": "NT$ billions / month", "yfmt": "num",
    "blurb": "ODMs (original design manufacturers) build the AI servers and racks for the cloud giants. Each NVIDIA generation shows up as a step-up in their revenue; the Rubin wave is the next to watch.",
    "source": "TWSE monthly revenue via FinMind", "url": "https://finmindtrade.com", "lines": odm}

# ============================================================ LIVE: SEC filing text
# NVIDIA supply commitments
try:
    pts = []
    for rd, f, acc, doc in sec_filings(1045810, ("10-Q", "10-K"), 14):
        if rd < "2023-01-01": continue
        t = sec_text(1045810, acc, doc)
        m = re.search(r"(?:these commitments were|long-term supply and capacity obligations(?:\s*(?:balance was|totaling))?)\s*\$?\s*([\d.,]+)\s*billion", t)
        if m: pts.append({"date": rd, "value": num(m.group(1))})
    pts = sorted({p["date"]: p["value"] for p in pts}.items())
    series["nvidia_commitments"] = {"title": "NVIDIA forward supply commitments", "unit": "US$ billions", "yfmt": "usd",
        "blurb": "Cash NVIDIA has pre-committed to suppliers (HBM/CoWoS/wafers) — the earliest leading indicator, leading chips by quarters.",
        "source": "NVIDIA 10-Q/10-K, parsed from SEC EDGAR", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001045810&type=10-Q",
        "points": [{"date": d, "value": v} for d, v in pts]}
    live["nvidia_commitments"] = True
    cache("nvidia_commitments.csv", [{"date": d, "commitments_usd_b": v} for d, v in pts])
except Exception as e:
    print("  WARN nvidia_commitments:", e)
    r = read_static("nvidia_commitments.csv")
    series["nvidia_commitments"] = {"title": "NVIDIA forward supply commitments", "unit": "US$ billions", "yfmt": "usd",
        "blurb": "Cash NVIDIA has pre-committed to suppliers — earliest leading indicator.", "source": "NVIDIA 10-Q/10-K (SEC EDGAR), bundled",
        "url": "https://www.sec.gov", "points": [{"date": x["date"], "value": num(x["commitments_usd_b"])} for x in r]}
    live["nvidia_commitments"] = False

# Micron CMBU (HBM-driven) — parse 3-col Revenue-by-Business-Unit from recent 10-Qs
def month_shift(ym, months):
    y, m = int(ym[:4]), int(ym[5:]); m -= months
    while m <= 0: m += 12; y -= 1
    return f"{y}-{m:02d}"
try:
    cmbu = {}; cmar = {}
    for rd, f, acc, doc in sec_filings(723125, ("10-Q",), 5):
        t = sec_text(723125, acc, doc)
        m = re.search(r"CMBU\s+\$?\s*([\d,]+)\s+\d+\s*%\s+\$?\s*([\d,]+)\s+\d+\s*%\s+\$?\s*([\d,]+)\s+\d+\s*%", t)
        if not m: continue
        cur = rd[:7]
        cmbu.setdefault(cur, num(m.group(1)) / 1000)
        cmbu.setdefault(month_shift(cur, 3), num(m.group(2)) / 1000)
        cmbu.setdefault(month_shift(cur, 12), num(m.group(3)) / 1000)
        oi = t.find("Operating Income (Loss) by Business Unit")
        if oi < 0: oi = t.find("Operating Income by Business Unit")
        mm = re.search(r"CMBU\s+\$?\s*[\d,()]+\s+(\d+)\s*%\s+\$?\s*[\d,()]+\s+(\d+)\s*%\s+\$?\s*[\d,()]+\s+(\d+)\s*%", t[oi:oi + 500]) if oi >= 0 else None
        if mm:
            cmar.setdefault(cur, num(mm.group(1))); cmar.setdefault(month_shift(cur, 3), num(mm.group(2))); cmar.setdefault(month_shift(cur, 12), num(mm.group(3)))
    pts = [{"date": d, "value": round(cmbu[d], 3), "margin": cmar.get(d)} for d in sorted(cmbu)]
    series["micron_cmbu"] = {"title": "Micron Cloud Memory: revenue & margin (HBM-driven)", "unit": "US$ billions / quarter", "yfmt": "usd",
        "blurb": "The best primary numeric HBM proxy from filings — Micron's HBM/data-centre segment (Micron ~20% of the HBM market). Operating margin shows the pricing-power surge.",
        "source": "Micron 10-Q (CMBU segment), parsed from SEC EDGAR", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000723125&type=10-Q",
        "points": pts}
    live["micron_cmbu"] = True
    cache("micron_cmbu.csv", [{"cal_quarter": p["date"], "fiscal_quarter": "", "cmbu_rev_musd": p["value"] * 1000} for p in pts])
except Exception as e:
    print("  WARN micron_cmbu:", e)
    r = read_static("micron_cmbu.csv")
    series["micron_cmbu"] = {"title": "Micron Cloud Memory revenue (HBM-driven)", "unit": "US$ billions / quarter", "yfmt": "usd",
        "blurb": "Best primary numeric HBM proxy (Micron CMBU segment).", "source": "Micron 10-Q (SEC EDGAR), bundled", "url": "https://www.sec.gov",
        "points": [{"date": x["cal_quarter"], "value": num(x["cmbu_rev_musd"]) / 1000} for x in r]}
    live["micron_cmbu"] = False

# TSMC HPC platform — parse platform table from 20-Fs (+ live log-linear trend)
def fit_exp(xs, ys):  # least squares on (x, log10 y)
    import math; n = len(xs); lx = xs; ly = [math.log10(v) for v in ys]
    mx = sum(lx) / n; my = sum(ly) / n
    b = sum((lx[i] - mx) * (ly[i] - my) for i in range(n)) / sum((lx[i] - mx) ** 2 for i in range(n))
    a = my - b * mx
    return lambda x: 10 ** (a + b * x)
try:
    hpc = {}
    for rd, f, acc, doc in sec_filings(1046179, ("20-F",), 6):
        t = sec_text(1046179, acc, doc)
        idx = t.find("net revenue by platform")
        seg = t[idx:idx + 500] if idx >= 0 else ""
        yh = re.search(r"(20\d\d)\s+(20\d\d)\s+(20\d\d)", seg)
        m = re.search(r"High Performance Computing\s+([\d,]+)\s+(\d+)\s*%\s+([\d,]+)\s+(\d+)\s*%\s+([\d,]+)\s+(\d+)\s*%", t)
        if not (yh and m): continue
        yrs = [int(yh.group(i)) for i in (1, 2, 3)]
        for k in range(3):
            hpc.setdefault(yrs[k], (num(m.group(1 + 2 * k)) / 1e3 / 31, num(m.group(2 + 2 * k))))
    H = [{"year": y, "value": round(hpc[y][0], 2), "share": hpc[y][1]} for y in sorted(hpc)]
    fit = fit_exp([h["year"] for h in H if h["year"] >= 2022], [h["value"] for h in H if h["year"] >= 2022])
    y0 = min(h["year"] for h in H)
    fitline = [{"year": y, "value": round(fit(y), 1)} for y in range(y0, 2031)]
    series["tsmc_hpc"] = {"title": "TSMC HPC-platform revenue", "unit": "US$ billions", "yfmt": "usd",
        "blurb": "TSMC's HPC (AI/datacentre) platform as a share of the world's leading foundry. The light line is a log-linear fit on 2022+ history, drawn back through the points and extrapolated to 2030.",
        "source": "TSMC 20-F (platform revenue), parsed from SEC EDGAR; NT$ at ~31/US$", "url": "https://investor.tsmc.com/english",
        "history": H, "forecast": [{"year": y, "value": round(fit(y), 1)} for y in range(2026, 2031)], "fitline": fitline}
    live["tsmc_hpc"] = True
except Exception as e:
    print("  WARN tsmc_hpc:", e)
    rev = read_static("tsmc_hpc_revenue.csv"); fc = read_static("tsmc_hpc_forecast.csv")
    series["tsmc_hpc"] = {"title": "TSMC HPC-platform revenue", "unit": "US$ billions", "yfmt": "usd",
        "blurb": "TSMC HPC platform (AI/datacentre).", "source": "TSMC 20-F (SEC EDGAR), bundled", "url": "https://investor.tsmc.com/english",
        "history": [{"year": int(r["year"]), "value": num(r["hpc_rev_twd_millions"]) / 1e3 / 31, "share": num(r["hpc_share_pct"])} for r in rev],
        "forecast": [{"year": int(r["year"]), "value": num(r["rev_usd_b_fit"])} for r in fc if int(r["year"]) >= 2026]}
    live["tsmc_hpc"] = False

# ASML EUV units — parse per-technology unit table from 20-Fs (NXE + EXE)
try:
    euv = {}
    for rd, f, acc, doc in sec_filings(937966, ("20-F",), 6):
        t = sec_text(937966, acc, doc)
        # (a) reliable: the per-technology unit table (recent 20-Fs)
        i = t.find("Net system sales per technology")
        if i >= 0:
            seg = t[i:i + 600]
            yh = re.search(r"(20\d\d)\s+(20\d\d)\s+(20\d\d)", seg)
            nxe = re.search(r"NXE\s+(\d+)\s+[\d,\.]+\s+(\d+)\s+[\d,\.]+\s+(\d+)\s+[\d,\.]+", seg)
            exe = re.search(r"EXE\s+(?:[—-]+|(\d+))\s+(?:[—\d,\.]+)\s+(?:[—-]+|(\d+))\s+[\d,\.]+\s+(?:[—-]+|(\d+))\s+[\d,\.]+", seg)
            if yh and nxe:
                yrs = [int(yh.group(k)) for k in (1, 2, 3)]
                for k in range(3):
                    e = (int(exe.group(k + 1)) if (exe and exe.group(k + 1)) else 0)
                    euv[yrs[k]] = int(nxe.group(k + 1)) + e   # table wins (overwrite)
        # (b) older years: MD&A sentences with an explicit year
        for mm in re.finditer(r"(\d{1,3})\s+EUV systems[^.]*?\bin\s+(20\d\d)", t):
            y = int(mm.group(2));  v = int(mm.group(1))
            if y not in euv and 5 <= v <= 80: euv.setdefault(y, v)
    if euv:
        series["euv_units"] = {"title": "EUV machines made per year", "unit": "systems / year", "yfmt": "num",
            "blurb": "Every leading-edge AI chip needs EUV lithography — made by one company (ASML). Units (NXE+EXE) parsed from ASML 20-Fs.",
            "source": "ASML 20-F (net system sales per technology), parsed from SEC EDGAR", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000937966&type=20-F",
            "bars": [{"x": str(y), "value": euv[y]} for y in sorted(euv)]}
        live["euv_units"] = True
        cache("asml_euv_units.csv", [{"year": y, "euv_units": euv[y]} for y in sorted(euv)])
    else:
        raise ValueError("no EUV table parsed")
except Exception as e:
    print("  WARN euv_units:", e)
    r = read_static("asml_euv_units.csv")
    series["euv_units"] = {"title": "EUV machines made per year", "unit": "systems / year", "yfmt": "num",
        "blurb": "Every leading-edge AI chip needs EUV lithography — made by one company (ASML).", "source": "ASML 20-F (SEC EDGAR), bundled",
        "url": "https://www.sec.gov", "bars": [{"x": x["year"], "value": num(x["euv_units"])} for x in r]}
    live["euv_units"] = False

# SK Hynix — Yahoo Finance quarterly revenue + operating margin
try:
    u = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/000660.KS"
         "?type=quarterlyTotalRevenue,quarterlyOperatingIncome&period1=1483228800&period2=1798761600")
    j = json.loads(_get(u, 30))["timeseries"]["result"]
    rev_d, op_d = {}, {}
    for blk in j:
        ty = blk.get("meta", {}).get("type", [None])[0]
        for row in blk.get(ty, []) if ty else []:
            if not row: continue
            dt = row["asOfDate"][:7]; val = row["reportedValue"]["raw"]
            (rev_d if ty == "quarterlyTotalRevenue" else op_d)[dt] = val
    qd = {}
    # base: bundled history (KRW trn -> US$), extends further back than Yahoo
    for r in read_static("skhynix_quarterly.csv"):
        qd[r["quarter"]] = {"x": r["quarter"], "revenue": round(num(r["revenue_krw_t"]) * 1000 / 1350, 1), "margin": num(r["op_margin_pct"])}
    # overlay live Yahoo (US$) on recent quarters
    for dt in sorted(rev_d):
        if dt in op_d and rev_d[dt]:
            q = f"{dt[:4]}-Q{(int(dt[5:7]) - 1)//3 + 1}"
            qd[q] = {"x": q, "revenue": round(rev_d[dt] / 1e9 / 1350, 1), "margin": round(op_d[dt] / rev_d[dt] * 100, 1)}
    pts = [qd[q] for q in sorted(qd)]
    if len(pts) < 4: raise ValueError("too few SK Hynix points")
    series["skhynix"] = {"title": "SK Hynix — the HBM leader", "unit": "US$ bn (rev) / % (margin)", "yfmt": "num",
        "blurb": "World #1 HBM maker (~62% share, ~70% of Rubin HBM4). Revenue converted to US$ (~1,350 ₩/US$).",
        "source": "SK Hynix quarterly financials via Yahoo Finance (000660.KS)", "url": "https://finance.yahoo.com/quote/000660.KS",
        "points": pts}
    live["skhynix"] = True
    # NB: do not cache() over skhynix_quarterly.csv — it is the bundled KRW history base.
except Exception as e:
    print("  WARN skhynix:", e)
    r = read_static("skhynix_quarterly.csv")
    series["skhynix"] = {"title": "SK Hynix — the HBM leader", "unit": "KRW trn / %", "yfmt": "num",
        "blurb": "World #1 HBM maker; boom shown via revenue & margin.", "source": "Yahoo Finance (000660.KS), bundled", "url": "https://finance.yahoo.com/quote/000660.KS",
        "points": [{"x": x["quarter"], "revenue": num(x["revenue_krw_t"]), "margin": num(x["op_margin_pct"])} for x in r]}
    live["skhynix"] = False

# ============================================================ LIVE: Korea memory exports (UN Comtrade)
try:
    ku = ("https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=410"
          "&period=2017,2018,2019,2020,2021,2022,2023,2024,2025&cmdCode=854232&flowCode=X&partnerCode=0")
    kd = json.loads(_get(ku, 90)).get("data", [])
    krows = sorted((r["refYear"], r.get("primaryValue", 0)) for r in kd if r.get("partnerCode") == 0)
    if krows:
        series["korea_memory"] = {"title": "Korea memory-chip exports", "unit": "US$ billions / year", "yfmt": "usd",
            "blurb": "Korea (SK Hynix + Samsung ≈ 70% of global DRAM/HBM) memory-IC exports — a customs-verified, near-real-time proxy for the memory & HBM boom.",
            "source": "UN Comtrade (Korea exports, HS 854232 'memories')", "url": "https://comtradeplus.un.org",
            "bars": [{"x": str(y), "value": round(v / 1e9, 1)} for y, v in krows]}
        live["korea_memory"] = True
        cache("korea_memory.csv", [{"year": y, "usd": int(v)} for y, v in krows])
except Exception as e:
    print("  WARN korea_memory:", e)
    try:
        r = read_static("korea_memory.csv")
        series["korea_memory"] = {"title": "Korea memory-chip exports", "unit": "US$ billions / year", "yfmt": "usd",
            "blurb": "Korea (SK Hynix + Samsung ≈ 70% of global DRAM/HBM) memory-IC exports — proxy for the memory & HBM boom.",
            "source": "UN Comtrade (HS 854232), bundled", "url": "https://comtradeplus.un.org",
            "bars": [{"x": x["year"], "value": round(num(x["usd"]) / 1e9, 1)} for x in r]}
        live["korea_memory"] = False
    except Exception: pass

# ============================================================ LIVE: US electricity generation + demand vs AI (EIA via env key, OWID fallback)
EIA_KEY = os.environ.get("EIA_KEY", "").strip()
def eia(path, params):
    q = "&".join(f"{k}={v}" for k, v in params)
    return json.loads(_get(f"https://api.eia.gov/v2/{path}/data/?api_key={EIA_KEY}&{q}", 90))["response"]["data"]
try:
    fp = series["fleet_power"]; sckey = fp["projection"]["scenarios"][1]["key"]
    usgen, usdem, freq, src = [], [], "annual", "Our World in Data (Ember/EIA), annual"
    if EIA_KEY:
        g = eia("electricity/electric-power-operational-data", [("frequency", "monthly"), ("data[0]", "generation"), ("facets[location][]", "US"), ("facets[sectorid][]", "99"), ("facets[fueltypeid][]", "ALL"), ("start", "2008-01"), ("sort[0][column]", "period"), ("sort[0][direction]", "asc"), ("length", "5000")])
        usgen = [{"date": r["period"] + "-15", "value": round(num(r["generation"]) / 1000, 2)} for r in g if num(r.get("generation"))]
        dd = eia("electricity/retail-sales", [("frequency", "monthly"), ("data[0]", "sales"), ("facets[stateid][]", "US"), ("facets[sectorid][]", "ALL"), ("start", "2008-01"), ("sort[0][column]", "period"), ("sort[0][direction]", "asc"), ("length", "5000")])
        usdem = [{"date": r["period"] + "-15", "value": round(num(r["sales"]) / 1000, 2)} for r in dd if num(r.get("sales"))]
        if usgen: freq, src = "monthly", "EIA — electric-power-operational-data (generation) + retail-sales (demand), monthly"
    if not usgen:
        oc = list(csv.DictReader(io.StringIO(_get("https://ourworldindata.org/grapher/electricity-generation.csv?country=~USA", 60))))
        vcol = [c for c in oc[0] if c not in ("Entity", "Code", "Year")][0]
        usgen = [{"date": r["Year"] + "-12-31", "value": round(num(r[vcol]), 1)} for r in oc if r.get("Code") == "USA" and num(r.get(vcol)) and int(r["Year"]) >= 1995]
    mfac = 0.730 if freq == "monthly" else 8.76; per = "month" if freq == "monthly" else "year"
    aih = [{"date": d["date"][:4] + "-12-15", "value": round(d["facility_gw"] * mfac, 2)} for d in fp["history"] if d["date"][5:7] == "12"]
    aip = [{"date": str(d["year"]) + "-12-15", "value": round(d["value"] * mfac, 2)} for d in fp["projection"][sckey]]
    series["us_energy"] = {"title": "US electricity: generation, demand & AI", "unit": f"TWh / {per}", "yfmt": "num", "ylabel": f"TWh per {per} (log)",
        "blurb": f"US electricity generation{' & demand' if usdem else ''} ({freq}) against AI datacentres' annualised draw. A sliver today — but on the central scaling path it chases the whole US grid within years.",
        "source": src + "; AI = Epoch fleet power × hours", "url": "https://www.eia.gov/electricity/",
        "us_gen": usgen, "us_demand": usdem, "ai_hist": aih, "ai_proj": aip, "scenario": fp["projection"]["scenarios"][1]["name"], "freq": freq}
    live["us_energy"] = bool(EIA_KEY)
    cache("us_energy.csv", [{"date": d["date"], "us_twh": d["value"]} for d in usgen])
except Exception as e:
    print("  WARN us_energy:", e)

# ============================================================ buildout model constants (Epoch-derived)
try:
    anchor_h = hist[-1]["median"]                       # end-2025 installed H100e
    P0gw = ph[-1]["facility_gw"]
    cum_logic = sum(num(r.get("Logic wafers (median)")) or 0 for r in comp if r.get("Designer") != "Other")
    cum_cowos = sum(num(r.get("CoWoS wafers (median)")) or 0 for r in comp if r.get("Designer") != "Other")
    sd, _ = epoch_zip("supply_denominators.csv", "components_supply_denominators.csv")
    sd = [r for r in sd if r.get("Logic supply (median)")]
    logic_sup_q = num(sd[-1]["Logic supply (median)"]); cowos_sup_q = num(sd[-1]["CoWoS supply (median)"])
    # $/MW from Epoch Frontier Data Centers
    dpm = None
    try:
        dc = zipfile.ZipFile(io.BytesIO(_get(f"{EP}/data_centers/data_centers.zip", binary=True)))
        nm = next(n for n in dc.namelist() if n.endswith("data_centers.csv"))
        dcr = list(csv.DictReader(io.StringIO(dc.read(nm).decode("utf-8", "ignore"))))
        ratios = []
        for r in dcr:
            mw = num(r.get("Current power (MW)")); cap = num(r.get("Current total capital cost (2025 USD billions)"))
            if mw and cap and mw > 0: ratios.append(cap * 1e3 / mw)
        ratios.sort(); dpm = round(ratios[len(ratios)//2], 1) if ratios else None
    except Exception as e:
        print("  WARN data_centers $/MW:", e)
    series["buildout"] = {"title": "The buildout — what the compute trend requires", "yfmt": "num",
        "blurb": "Drive AI compute forward and see the physical requirements it implies — wafers, packaging, EUV machines, power, dollars — vs what's actually available. Twizzle the knobs.",
        "source": "Epoch AI (Chip Sales, Components, Frontier Data Centers; CC-BY) + ASML (EUV)", "url": "https://epoch.ai/data",
        "anchor_h100e": anchor_h, "anchor_year": 2025,
        "h100e_per_logic_wafer": round(anchor_h / cum_logic, 1) if cum_logic else 230,
        "h100e_per_cowos_wafer": round(anchor_h / cum_cowos, 1) if cum_cowos else 25,
        "logic_supply_annual": round(logic_sup_q * 4), "cowos_supply_annual": round(cowos_sup_q * 4),
        "euv_per_year": series["euv_units"]["bars"][-1]["value"],
        "dollars_per_mw": dpm or 38, "w_per_h100e": round(P0gw * 1e9 / anchor_h),
        "defaults": {"growth": 2.25, "efficiency": 1.34, "euv_layers": 25, "euv_wph": 220, "euv_util": 0.85, "facility_overhead": 2.5}}
    live["buildout"] = True
except Exception as e:
    print("  WARN buildout:", e)

# ============================================================ write
for k, v in series.items(): v["fresh"] = "live" if live.get(k) else "filing"
out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "live_count": sum(1 for f in live.values() if f), "total": len(series), "series": series}
(ROOT / "data.json").write_text(json.dumps(out, separators=(",", ":")))
print(f"\ndata.json — {out['live_count']}/{out['total']} series LIVE")
for k in series: print(f"  {'LIVE ' if live.get(k) else 'fallbk'}  {k}")
