#!/usr/bin/env python3
"""Synthetic current-content benchmark. Explicit scratch/output, never user data.

Example: PYTHONPATH=src python scripts/benchmark_content_search.py \
  --scratch /tmp/td-search-synthetic --output /tmp/td-search-results.json
Cold means new process, not purged OS caches. No Bridge/file-index claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
from time import perf_counter, process_time

from threaddesk.core.models import Thread, ThreadContext
from threaddesk.services.search import LocalFileOwnerPolicy, SearchService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261020


def peak_rss():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        return None


def check_budget(args, *, disk=False):
    if (peak_rss() or 0) > args.max_rss_mib * 1024 * 1024:
        raise RuntimeError("synthetic benchmark RSS budget exceeded")
    if disk and sum(p.stat().st_size for p in args.scratch.rglob("*") if p.is_file()) > args.max_disk_mib * 1024 * 1024:
        raise RuntimeError("synthetic benchmark scratch budget exceeded")


def corpus_thread(index):
    size = 65536 if index % 100 == 0 else 8192 if index % 100 < 20 else 2048
    phrase = "The local team reviews current research and records useful progress. Überblick und nächste Schritte bleiben nachvollziehbar. "
    prefix = "notesmarker marigold Überblick " + ("rareword " if index % 137 == 0 else "ordinary ")
    notes = (prefix + phrase * (size // len(phrase.encode()) + 2)).encode()[:size].decode("utf-8", errors="ignore")
    description = ("Current project description with documented observations and a clear next action. " * 3)[:160]
    return Thread(id="bench%012x" % index, title="titlemarker Research %06d" % index,
                  description=description, status="archived" if index % 20 == 0 else "idea",
                  created_at="2026-10-20T00:00:00Z", updated_at="2026-10-20T00:00:00Z",
                  context=ThreadContext(notes=notes, extra={"organization": {"project_id": "project_%d" % (index % 10)}}))


class BenchmarkPolicy(LocalFileOwnerPolicy):
    def can_read_current(self, doc):
        return int(doc.thread_id[5:], 16) % 10 >= 3


def stats(values):
    values = sorted(values)
    return {"samples": len(values), "p50_ms": statistics.median(values),
            "p95_ms": values[min(len(values) - 1, int(len(values) * .95))],
            "p99_ms": values[min(len(values) - 1, int(len(values) * .99))], "max_ms": max(values)}


def sample(search, query, *, project=None, collect_first20=False):
    wall, cpu = perf_counter(), process_time()
    hits, scanned, source_bytes, kernel, cursor, pages = [], 0, 0, 0.0, None, 0
    modes = set()
    while True:
        page = search.search(query, project_id=project, cursor=cursor)
        hits.extend(page.hits)
        modes.add(page.mode)
        scanned += page.scanned
        source_bytes += page.source_bytes
        kernel += page.kernel_seconds
        pages += 1
        cursor = page.next_cursor
        if not collect_first20 or len(hits) >= 20 or cursor is None or pages >= 250:
            break
    elapsed, cpu_elapsed = (perf_counter() - wall) * 1000, (process_time() - cpu) * 1000
    # Validate identity/scope outside the measured interval against deterministic
    # synthetic canonical content, rather than trusting a fast empty response.
    for hit in hits:
        index = int(hit.thread_id[5:], 16)
        expected = corpus_thread(index)
        assert index % 10 >= 3 and expected.status != "archived"
        assert project is None or project == "project_%d" % (index % 10)
        value = getattr(expected.context, "notes") if hit.field == "notes" else getattr(expected, hit.field)
        assert all(term.lower() in value.lower() for term in query.split())
    return {"wall_ms": elapsed, "cpu_ms": cpu_elapsed, "kernel_ms": kernel * 1000,
            "hits": len(hits), "first20_obtained": len(hits) >= 20,
            "pages": pages, "scanned": scanned, "source_bytes": source_bytes, "modes": sorted(modes),
            "continuation_available": cursor is not None,
            "stop": "first20" if len(hits) >= 20 else "exhausted" if cursor is None else "benchmark_page_limit",
            "complete": page.complete, "truncated": page.truncated, "reasons": page.reasons,
            "identity_checksum": hashlib.sha256(json.dumps([(h.thread_id, h.field, h.thread_revision) for h in hits[:20]]).encode()).hexdigest()}


def worker(args):
    if not (args.workspace / ".search-benchmark-synthetic.json").is_file():
        raise SystemExit("Worker accepts only an explicitly marked synthetic corpus")
    if args.stage == "cli":
        import resource
        wall_samples, cpu_samples, observations = [], [], []
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
               "THREADDESK_HOME": str(args.workspace), "THREADDESK_STORAGE": args.backend}
        for _ in range(20):
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            start = perf_counter()
            response = subprocess.run([sys.executable, "-m", "threaddesk.ui.cli", "--lang", "en", "search", "marigold"],
                                      cwd=ROOT, env=env, check=True, text=True, capture_output=True)
            wall_samples.append((perf_counter() - start) * 1000)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu_samples.append((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1000)
            page = json.loads(response.stdout)
            for hit in page["hits"]:
                assert corpus_thread(int(hit["thread_id"][5:], 16)).status != "archived"
            observations.append({"hits": len(page["hits"]), "reasons": page["reasons"],
                                 "mode": page["mode"], "truncated": page["truncated"]})
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        args.output.write_text(json.dumps({"wall": stats(wall_samples), "cpu": stats(cpu_samples),
            "peak_rss_bytes": int(peak if sys.platform == "darwin" else peak * 1024),
            "first20_count": sum(x["hits"] == 20 for x in observations), "observations": observations,
            "first20_wall": stats([wall for wall, row in zip(wall_samples, observations) if row["hits"] == 20]) if any(x["hits"] == 20 for x in observations) else None,
            "scope": "20 actual new CLI processes, one bounded page each; partial first20 counted explicitly; local-file-owner policy; separate child RSS/CPU"}, indent=2) + "\n")
        return
    store = JsonStore(args.workspace) if args.backend == "json" else SQLiteStore(args.workspace)
    search = SearchService(store, BenchmarkPolicy(store.workspace_path))
    if args.stage == "kernel":
        def kernel_sample():
            state = search.status()
            start, cpu = perf_counter(), process_time()
            iterator = search.adapter.candidates(["marigold"], None, False, indexed=state.get("mode") == "fts5")
            count, reason = 0, None
            try:
                for _ in range(20):
                    exact_id, reason = next(iterator)
                    if exact_id is None:
                        break
                    count += 1
            finally:
                iterator.close()
            return {"wall_ms": (perf_counter() - start) * 1000, "cpu_ms": (process_time() - cpu) * 1000,
                    "candidates": count, "pause": reason if count < 20 else None}
        cold = kernel_sample()
        rows = [kernel_sample() for _ in range(args.samples)]
        args.output.write_text(json.dumps({"cold_process": cold, "warm": stats([x["wall_ms"] for x in rows]),
            "warm_cpu": stats([x["cpu_ms"] for x in rows]), "peak_rss_bytes": peak_rss(),
            "warm_20_candidates_count": sum(x["candidates"] == 20 for x in rows),
            "scope": "candidate iteration only; separate process, excludes hydration/policy/snippets"}, indent=2) + "\n")
        search.close()
        if hasattr(store, "connection"):
            store.connection.close()
        return
    cold = sample(search, "marigold", collect_first20=True)
    queries = ["marigold", "notesmarker", "titlemarker", "Überblick"]
    random.Random(SEED).shuffle(queries)
    warm = []
    for index in range(args.samples):
        query = queries[index % len(queries)]
        warm.append(sample(search, query, collect_first20=True))
        check_budget(args)
    categories = {}
    for name, query, project in [
        ("rare_notes", "rareword", None), ("absent", "nonexistentword", None),
        ("project_filter", "marigold", "project_7"),
        ("max_query_bytes", "z" * 512, None),
        ("max_terms", "The local team reviews current research and records useful progress Überblick und nächste Schritte bleiben nachvollziehbar", None),
    ]:
        categories[name] = sample(search, query, project=project, collect_first20=True)
    result = {"backend": args.backend, "index_state": search.status(), "cold_process_service": cold,
              "warm_service": stats([x["wall_ms"] for x in warm]),
              "warm_service_cpu": stats([x["cpu_ms"] for x in warm]),
              "warm_first20_count": sum(x["first20_obtained"] for x in warm),
              "warm_modes": {mode: sum(mode in x["modes"] for x in warm) for mode in {m for x in warm for m in x["modes"]}},
              "warm_first20_latency": stats([x["wall_ms"] for x in warm if x["first20_obtained"]]) if any(x["first20_obtained"] for x in warm) else None,
              "warm_partial_count": sum(x["truncated"] for x in warm),
              "warm_budget_limited_count": sum(any(reason in {"time_budget", "byte_budget", "candidate_budget"}
                                                   for reason in x["reasons"]) for x in warm),
              "warm_consistency_unverified_count": sum("json_external_writers_unverified" in x["reasons"] for x in warm),
              "category_first20_or_exhaustion": categories, "peak_rss_bytes": peak_rss()}
    (args.output.parent / (args.output.stem + "-raw.json")).write_text(json.dumps({"service": warm}))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    search.close()
    if hasattr(store, "connection"):
        store.connection.close()


def run(args):
    args.scratch.mkdir(parents=True, exist_ok=True)
    if any(args.scratch.iterdir()):
        raise SystemExit("Scratch must be a new empty synthetic-data directory")
    if shutil.disk_usage(args.scratch).free < args.max_disk_mib * 1024 * 1024:
        raise SystemExit("insufficient free space for the explicit scratch budget")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    source_paths = list((ROOT / "src/threaddesk").glob("*/search*.py")) + [Path(__file__).resolve()]
    source_paths += [ROOT / "src/threaddesk" / name for name in ["storage/json_store.py", "storage/sqlite_store.py", "ui/cli.py"]]
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    memory = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip() if sys.platform == "darwin" else None
    report = {"scope": "ThreadDesk current title/description/notes; synthetic, no files/Bridge latency",
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "budgets": {"max_rss_mib_per_process": args.max_rss_mib, "max_scratch_mib": args.max_disk_mib,
                          "enforcement": "RSS checked between bounded batches/samples; disk between fixture blocks/profiles"},
              "seed": SEED, "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "environment": {"python": sys.version, "sqlite": sqlite3.sqlite_version, "system": platform.platform(),
                              "machine": platform.machine(), "logical_cpus": os.cpu_count(), "memory_bytes": int(memory) if memory else None},
              "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
              "cold_definition": "new process; OS page cache is not purged", "runs": []}
    for size in args.sizes:
        for backend in ["sqlite", "json"]:
            workspace = args.scratch / (backend + "-" + str(size))
            workspace.mkdir(parents=True)
            (workspace / ".search-benchmark-synthetic.json").write_text(json.dumps({"seed": SEED, "records": size}))
            print("GENERATE", backend, size, flush=True)
            store = JsonStore(workspace) if backend == "json" else SQLiteStore(workspace)
            start, cpu, volume = perf_counter(), process_time(), {"title": 0, "description": 0, "notes": 0}
            for offset in range(0, size, 500):
                with store.transaction():
                    for index in range(offset, min(offset + 500, size)):
                        thread = corpus_thread(index)
                        store.save_thread(thread)
                        for name in volume:
                            value = thread.context.notes if name == "notes" else getattr(thread, name)
                            volume[name] += len(value.encode("utf-8"))
                check_budget(args, disk=offset % 10000 == 0)
                if offset % 10000 == 0:
                    print("GENERATED", backend, offset, flush=True)
            generation = {"wall_seconds": perf_counter() - start, "cpu_seconds": process_time() - cpu}
            source_disk = sum(p.stat().st_size for p in workspace.rglob("*") if p.is_file())
            search = SearchService(store, BenchmarkPolicy(store.workspace_path))
            search.set_enabled(True)
            start, cpu, batches = perf_counter(), process_time(), 0
            while True:
                state = search.rebuild_batch()
                batches += 1
                check_budget(args)
                if state["status"] not in {"cleaning", "building"}:
                    break
                if batches > size // 100 + 50:
                    raise RuntimeError("bounded build unexpectedly failed to finish")
            build = {"wall_seconds": perf_counter() - start, "cpu_seconds": process_time() - cpu, "batches": batches, "state": state}
            search.close()
            if hasattr(store, "connection"):
                store.connection.close()
            modes = [backend] if backend == "json" else ["sqlite", "sqlite_fallback"]
            for mode in modes:
                if mode == "sqlite_fallback":
                    # Make the disposable FTS unavailable; preserve source rows.
                    owned = SQLiteStore(workspace)
                    owned.connection.execute("DROP TABLE search_index")
                    owned.connection.commit()
                    owned.connection.close()
                output = args.scratch / (mode + "-" + str(size) + ".json")
                print("MEASURE", mode, size, flush=True)
                command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--workspace", str(workspace),
                           "--backend", "json" if mode == "json" else "sqlite", "--samples", str(args.samples), "--max-rss-mib", str(args.max_rss_mib), "--output", str(output)]
                stage_results = {}
                for stage in ["service", "kernel", "cli"]:
                    stage_output = output.with_name(output.stem + "-" + stage + ".json")
                    stage_command = command[:-1] + [str(stage_output), "--stage", stage]
                    subprocess.run(stage_command, cwd=ROOT, env=env, check=True)
                    stage_results[stage] = json.loads(stage_output.read_text())
                    if stage_results[stage]["peak_rss_bytes"] > args.max_rss_mib * 1024 * 1024:
                        raise RuntimeError("worker peak RSS budget exceeded")
                result = stage_results["service"]
                result.update(mode=mode, records=size, text_utf8_bytes=volume, source_disk_bytes=source_disk,
                              final_disk_bytes=sum(p.stat().st_size for p in workspace.rglob("*") if p.is_file()),
                              fixture_generation=generation, explicit_build=build,
                              candidate_kernel=stage_results["kernel"], cli=stage_results["cli"])
                check_budget(args, disk=True)
                report["runs"].append(result)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print("RESULT", mode, size, result["warm_service"], flush=True)
    report["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    if report["source_sha256"] != source_hashes:
        raise RuntimeError("source changed during measurement")
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10000, 100000])
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--max-rss-mib", type=int, default=384)
    parser.add_argument("--max-disk-mib", type=int, default=4096)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--stage", choices=["service", "kernel", "cli"], default="service")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--backend", choices=["sqlite", "json"])
    args = parser.parse_args()
    if not args.worker and args.scratch is None:
        parser.error("--scratch required; never reuse a product workspace")
    if not 64 <= args.max_rss_mib <= 1024 or not 128 <= args.max_disk_mib <= 8192:
        parser.error("RSS budget 64..1024 MiB and disk budget 128..8192 MiB required")
    if not 1 <= args.samples <= 1000 or any(not 1 <= size <= 100000 for size in args.sizes):
        parser.error("bounded sizes 1..100000 and samples 1..1000 required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    worker(args) if args.worker else run(args)


if __name__ == "__main__":
    main()
