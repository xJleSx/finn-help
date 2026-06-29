#!/usr/bin/env python3
"""Phase 1: collect all format/prompt templates and generate a gap report.

Usage:
    python tools/audit_formatters.py

Output:
    - Prints all format functions and their current DB queries
    - Shows what enrichment data is now available but unused
    - Suggests improvements for Phase 2-3
"""

import ast
import sys
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC.parent))


def extract_function_info(filepath: Path) -> list[dict]:
    """Parse a Python file and extract function signatures + docstrings."""
    try:
        with open(filepath, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except SyntaxError:
        return []

    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = {
                "name": node.name,
                "lineno": node.lineno,
                "docstring": ast.get_docstring(node) or "",
                "args": [arg.arg for arg in node.args.args],
            }
            functions.append(func)
    return functions


def main():
    report = defaultdict(list)

    # key formatter/prompt files to audit
    targets = [
        "interfaces/telegram.py",
        "interfaces/telegram_helpers.py",
        "interfaces/telegram_alerter.py",
        "interfaces/nlq.py",
        "llm/prompts.py",
        "llm/router.py",
        "notifications/__init__.py",
        "notifications/service.py",
        "cli.py",
        "scheduler/reporting.py",
        "analysis/rebalancing.py",
        "analysis/risk_explorer.py",
        "analysis/stress.py",
    ]

    for rel_path in targets:
        full = SRC / rel_path
        if not full.exists():
            print(f"[SKIP] {rel_path} not found")
            continue

        funcs = extract_function_info(full)
        # filter to format/render functions
        relevant = [
            f
            for f in funcs
            if any(
                keyword in f["name"].lower()
                for keyword in ["format", "render", "prompt", "advice", "report"]
            )
        ]
        if relevant:
            report[rel_path] = relevant

    # print report
    print("=" * 72)
    print("PHASE 1 — CURRENT FORMATTER/PROMPT INVENTORY")
    print("=" * 72)

    for path, funcs in sorted(report.items()):
        print(f"\n--- {path} ({len(funcs)} format functions) ---")
        for f in funcs:
            doc = f["docstring"][:120].replace("\n", " ") if f["docstring"] else "(no docstring)"
            print(f"  {f['name']}({', '.join(f['args'])}) [{doc}]")

    # gap analysis: enrichment data available but likely unused
    print("\n" + "=" * 72)
    print("GAP ANALYSIS — Enrichment Data Available (DB) vs. Used in Formatters")
    print("=" * 72)

    models_check = {
        "CompanyProfile": "company_profiles (description, website, employees, industry, etc.)",
        "FinancialReport": "financial_reports (net_profit, revenue, ROE, ROA, assets, etc.)",
        "BondOffering": "bond_offerings (coupon_rate, YTM, maturity, rating, amortization, etc.)",
        "CorporateEvent": "corporate_events (dividends, buyback, splits, emission)",
        "AltDataPoint": "alt_data_points (CBR, Rosstat, GoogleTrends)",
        "FundamentalMetric": "fundamental_metrics (market_cap, P/E, P/B, EPS, etc.)",
    }

    for model, desc in models_check.items():
        used_in = []
        for path, funcs in report.items():
            for f in funcs:
                doc = f["docstring"] or ""
                if model.lower() in doc.lower() or desc.split()[0].strip("_") in doc:
                    used_in.append(f"{path}:{f['name']}")
        if used_in:
            print(f"  [USED] {model} ({desc}) — found in: {', '.join(used_in)}")
        else:
            print(f"  [GAP]  {model} ({desc}) — NOT referenced in any format function")

    print("\n" + "=" * 72)
    print("NEXT STEPS (Phase 2-3)")
    print("=" * 72)
    print("""
    1. Review each [GAP] model above and check if bot responses would benefit
    2. Design new format templates that use enriched context
    3. Update llm/prompts.py SYSTEM_PROMPT to include new data fields
    4. Refactor telegram.py + nlq.py formatters to use rich CompanyProfile data
    5. Add FinancialReport metrics to /analyze output
    6. Add BondOffering details to bond analysis
    7. Add CorporateEvent (upcoming dividends, buybacks) to alerts
    8. A/B test before/after quality
    """)


if __name__ == "__main__":
    main()
