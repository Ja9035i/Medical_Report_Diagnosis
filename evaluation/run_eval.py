"""
Evaluation harness.

    python -m evaluation.run_eval                      # deterministic metrics only (offline, free)
    python -m evaluation.run_eval --llm                # + full LangGraph pipeline with the LLM in .env
    python -m evaluation.run_eval --llm --providers groq,gemini --limit 10

Deterministic metrics (no LLM):
  - lab extraction: precision / recall / F1 of abnormal "lab:FLAG" pairs
  - red flags: recall on cases that must alert, and false alarms on cases that must not
  - differential: top-1 and top-3 accuracy of the expected condition

LLM metrics (per provider):
  - condition named: the answer mentions the expected condition
  - grounded: the grounding check passed
  - attempts, latency, errors

Retrieval runs in memory over each case's own chunks (vector + BM25 + optional reranker),
so an evaluation never writes to Pinecone or MongoDB.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.cases import CASES, CONDITION_KEYWORDS  # noqa: E402
from server.knowledge.differential import rank_differential  # noqa: E402
from server.labs.critical import check_critical  # noqa: E402
from server.labs.extract import abnormal, extract_lab_values  # noqa: E402

RESULTS_DIR = ROOT / "evaluation" / "results"


# ---------------- deterministic part ----------------

def evaluate_case(case):
    labs = extract_lab_values(case["report"])
    alerts = check_critical(labs)
    found = {f"{lab['key']}:{lab['flag']}" for lab in abnormal(labs)}
    expected = set(case["expected_abnormal"])
    differential = rank_differential(labs)
    ranked_ids = [d["id"] for d in differential]
    top = case["expected_top"]
    return {
        "id": case["id"],
        "true_pos": len(found & expected),
        "false_pos": sorted(found - expected),
        "false_neg": sorted(expected - found),
        "critical_expected": case["expect_critical"],
        "critical_fired": bool(alerts),
        "expected_top": top,
        "ranked": ranked_ids[:3],
        "top1": (ranked_ids[:1] == [top]) if top else not ranked_ids,
        "top3": (top in ranked_ids[:3]) if top else not ranked_ids,
    }


def deterministic_metrics(cases=CASES):
    rows = [evaluate_case(c) for c in cases]
    tp = sum(r["true_pos"] for r in rows)
    fp = sum(len(r["false_pos"]) for r in rows)
    fn = sum(len(r["false_neg"]) for r in rows)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    must_alert = [r for r in rows if r["critical_expected"]]
    must_not = [r for r in rows if not r["critical_expected"]]
    summary = {
        "cases": len(rows),
        "lab_precision": round(precision, 3),
        "lab_recall": round(recall, 3),
        "lab_f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
        "red_flag_recall": round(sum(r["critical_fired"] for r in must_alert) / len(must_alert), 3) if must_alert else 1.0,
        "red_flag_false_alarms": sum(r["critical_fired"] for r in must_not),
        "differential_top1": round(sum(r["top1"] for r in rows) / len(rows), 3),
        "differential_top3": round(sum(r["top3"] for r in rows) / len(rows), 3),
    }
    return summary, rows


# ---------------- LLM part ----------------

_current_chunks = []


async def _memory_vector_search(question, doc_id, k=10):
    """Cosine search over the current case's chunks with the real embedding model."""
    import numpy as np
    from server.config import embeddings

    if not _current_chunks:
        return []
    model = embeddings.get_embed_model()
    matrix = np.asarray(model.encode([c["text"] for c in _current_chunks]), dtype=float)
    query = np.asarray(model.encode(question), dtype=float)
    scores = matrix @ query / ((np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)) + 1e-9)
    return [_current_chunks[i] for i in np.argsort(-scores)[:k]]


def _case_chunks(case):
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from server.privacy.redact import redact_text

    text, _ = redact_text(case["report"])
    pieces = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_text(text)
    return [{"id": f"{case['id']}-{i}", "text": p, "source": f"{case['id']}.txt", "page": None}
            for i, p in enumerate(pieces)]


def _mentions(answer, condition_id):
    text = (answer or "").lower()
    return any(word in text for word in CONDITION_KEYWORDS.get(condition_id, []))


async def llm_metrics(provider, cases, delay=0.0):
    from server.config import llm
    from server.diagnosis import retrieval
    from server.diagnosis.graph import run_diagnosis_graph

    os.environ["LLM_PROVIDER"] = provider
    getattr(llm.get_llm, "cache_clear", lambda: None)()  # pick up the new provider
    retrieval.vector_search = _memory_vector_search  # in-memory retrieval: no Pinecone writes

    rows = []
    for case in cases:
        global _current_chunks
        _current_chunks = _case_chunks(case)
        labs = extract_lab_values(case["report"])
        check_critical(labs)
        start = time.time()
        try:
            res = await run_diagnosis_graph("What do my results mean?", case["id"],
                                            labs=labs, chunks=_current_chunks)
            answer, error = res.get("diagnosis"), None
        except Exception as exc:  # rate limits, invalid keys, network
            res, answer, error = {}, None, f"{type(exc).__name__}: {str(exc)[:120]}"
        rows.append({
            "id": case["id"],
            "named_condition": _mentions(answer, case["expected_top"]) if case["expected_top"] and answer else None,
            "grounded": res.get("grounded"),
            "attempts": res.get("attempts"),
            "latency_s": round(time.time() - start, 2),
            "error": error,
        })
        print(f"  [{provider}] {case['id']:<28} named={rows[-1]['named_condition']} "
              f"grounded={rows[-1]['grounded']} {rows[-1]['latency_s']}s {error or ''}", flush=True)
        if delay:
            await asyncio.sleep(delay)

    ok = [r for r in rows if not r["error"]]
    named = [r for r in ok if r["named_condition"] is not None]
    graded = [r for r in ok if r["grounded"] is not None]
    summary = {
        "provider": provider,
        "model": llm.get_model_label(),
        "cases_run": len(rows),
        "errors": len(rows) - len(ok),
        "condition_named_rate": round(sum(r["named_condition"] for r in named) / len(named), 3) if named else None,
        "grounded_rate": round(sum(r["grounded"] for r in graded) / len(graded), 3) if graded else None,
        "avg_attempts": round(sum(r["attempts"] for r in ok) / len(ok), 2) if ok else None,
        "avg_latency_s": round(sum(r["latency_s"] for r in ok) / len(ok), 2) if ok else None,
    }
    return summary, rows


# ---------------- report ----------------

def compare_on_common_cases(llm_runs):
    """Fair comparison: only cases every provider completed without an error."""
    if len(llm_runs) < 2:
        return []
    common = set.intersection(*[{r["id"] for r in rows if not r["error"]} for _, rows in llm_runs])
    table = []
    for summary, rows in llm_runs:
        subset = [r for r in rows if r["id"] in common]
        n = len(subset)
        table.append({
            "provider": summary["provider"], "model": summary["model"], "cases": n,
            "condition_named": f"{sum(1 for r in subset if r['named_condition'])}/{sum(1 for r in subset if r['named_condition'] is not None)}",
            "grounded": f"{sum(1 for r in subset if r['grounded'])}/{sum(1 for r in subset if r['grounded'] is not None)}",
            "avg_attempts": round(sum(r["attempts"] for r in subset) / n, 2) if n else None,
            "avg_latency_s": round(sum(r["latency_s"] for r in subset) / n, 2) if n else None,
        })
    return table


def write_report(det_summary, det_rows, llm_runs, out_dir=RESULTS_DIR):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    lines = [f"# Evaluation results ({stamp})", "", f"Synthetic cases: {det_summary['cases']}", "",
             "## Deterministic pipeline (no LLM)", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in det_summary.items() if k != "cases"]
    misses = [r for r in det_rows if not r["top1"] or r["false_pos"] or r["false_neg"]
              or r["critical_fired"] != r["critical_expected"]]
    if misses:
        lines += ["", "### Cases with any miss", "", "| Case | Missed labs | Extra labs | Expected top | Ranked |",
                  "|---|---|---|---|---|"]
        lines += [f"| {r['id']} | {', '.join(r['false_neg']) or '—'} | {', '.join(r['false_pos']) or '—'} | "
                  f"{r['expected_top']} | {', '.join(r['ranked']) or '—'} |" for r in misses]
    if llm_runs:
        lines += ["", "## LLM pipeline (LangGraph, grounding check on)", "",
                  "| Provider | Model | Cases | Errors | Condition named | Grounded | Avg attempts | Avg latency (s) |",
                  "|---|---|---|---|---|---|---|---|"]
        for s, _ in llm_runs:
            lines.append(f"| {s['provider']} | {s['model']} | {s['cases_run']} | {s['errors']} | "
                         f"{s['condition_named_rate']} | {s['grounded_rate']} | {s['avg_attempts']} | {s['avg_latency_s']} |")
    common = compare_on_common_cases(llm_runs)
    if common:
        lines += ["", f"### Fair comparison on the {common[0]['cases']} cases every provider completed", "",
                  "| Provider | Model | Condition named | Grounded | Avg attempts | Avg latency (s) |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {c['provider']} | {c['model']} | {c['condition_named']} | {c['grounded']} | "
                  f"{c['avg_attempts']} | {c['avg_latency_s']} |" for c in common]
    errors = [(s["provider"], r["id"], r["error"]) for s, rows in llm_runs for r in rows if r["error"]]
    if errors:
        kinds = sorted({e.split(":")[0] for _, _, e in errors})
        lines += ["", f"_{len(errors)} LLM case(s) failed ({', '.join(kinds)}), e.g. free-tier rate limits; "
                  "they are excluded from rates and from the fair comparison._"]
    md_path = out_dir / f"eval_{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = out_dir / f"eval_{stamp}.json"
    json_path.write_text(json.dumps({
        "deterministic": {"summary": det_summary, "cases": det_rows},
        "llm": [{"summary": s, "cases": rows} for s, rows in llm_runs],
    }, indent=2), encoding="utf-8")
    return md_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate the medical report pipeline")
    parser.add_argument("--llm", action="store_true", help="also run the LLM pipeline (uses API calls)")
    parser.add_argument("--providers", default=os.getenv("LLM_PROVIDER", "groq"),
                        help="comma-separated: groq,gemini")
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases for the LLM run")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between LLM cases (rate limits)")
    parser.add_argument("--from-json", help="rebuild the Markdown report from a saved JSON run (no API calls)")
    args = parser.parse_args(argv)

    if args.from_json:
        saved = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        runs = [(r["summary"], r["cases"]) for r in saved["llm"]]
        print("Report written to", write_report(saved["deterministic"]["summary"],
                                                saved["deterministic"]["cases"], runs))
        return

    det_summary, det_rows = deterministic_metrics()
    print("Deterministic:", json.dumps(det_summary))

    llm_runs = []
    if args.llm:
        cases = CASES[: args.limit] if args.limit else CASES
        for provider in [p.strip() for p in args.providers.split(",") if p.strip()]:
            print(f"LLM run: {provider} on {len(cases)} cases")
            llm_runs.append(asyncio.run(llm_metrics(provider, cases, args.delay)))
            print("  summary:", json.dumps(llm_runs[-1][0]))

    print("Report written to", write_report(det_summary, det_rows, llm_runs))


if __name__ == "__main__":
    main()
