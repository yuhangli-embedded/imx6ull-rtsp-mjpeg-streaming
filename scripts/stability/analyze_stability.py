#!/usr/bin/env python3
"""Describe LP2 resource trends; never declares a hardware Gate or absence of leaks."""
import argparse
import csv
import datetime
import json
import math
import statistics
import sys
from pathlib import Path

from monitor_resources import FIELDS, PHASES, ROOT

RESOURCE_COLUMNS = ("vm_rss_kb", "vm_size_kb", "vm_hwm_kb", "threads", "open_fd_count")


def integer(text, name, minimum=0):
    if not isinstance(text, str) or not text.isascii() or not text.isdigit():
        raise ValueError(name + " must be an unsigned integer")
    value = int(text)
    if value < minimum:
        raise ValueError(name + " is below minimum")
    return value


def finite(text, name):
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise ValueError(name + " must be finite and nonnegative")
    return value


def load_csv(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS:
            raise ValueError("CSV schema mismatch; use monitor_rtsp_resources.sh output")
        for line, row in enumerate(reader, 2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("incomplete or extra CSV fields")
                stamp = datetime.datetime.fromisoformat(row["timestamp_utc"])
                if stamp.tzinfo is None or stamp.utcoffset() != datetime.timedelta(0):
                    raise ValueError("timestamp must include UTC offset")
                row["elapsed_sec"] = finite(row["elapsed_sec"], "elapsed_sec")
                row["sample_index"] = integer(row["sample_index"], "sample_index", 1)
                row["slot_index"] = integer(row["slot_index"], "slot_index")
                if row["phase"] not in PHASES or row["phase_source"] != "manual":
                    raise ValueError("invalid manual phase")
                if row["sample_ok"] not in ("0", "1"):
                    raise ValueError("invalid sample_ok")
                row["sample_ok"] = int(row["sample_ok"])
                if row["sample_ok"]:
                    for key in RESOURCE_COLUMNS + ("pid", "start_ticks"):
                        row[key] = integer(row[key], key, 1 if key in ("pid", "start_ticks", "threads") else 0)
                    if row["vm_hwm_kb"] < row["vm_rss_kb"] or row["vm_size_kb"] < row["vm_rss_kb"]:
                        raise ValueError("inconsistent memory values")
                    if len(row["process_state"]) != 1 or row["process_state"] not in "RSDTtXZxIKWP":
                        raise ValueError("invalid process state")
                    if row["error"] or row["error_kind"]:
                        raise ValueError("successful sample contains an error")
                else:
                    if not row["error_kind"] or not row["error"]:
                        raise ValueError("failed sample needs explicit error fields")
                    if any(row[key] for key in RESOURCE_COLUMNS + ("pid", "start_ticks", "process_state")):
                        raise ValueError("failed sample must not contain normal resource values")
                if rows and any(row[key] <= rows[-1][key] for key in
                                ("elapsed_sec", "sample_index", "slot_index")):
                    raise ValueError("elapsed time/index/slot must increase strictly")
                rows.append(row)
            except (TypeError, ValueError) as error:
                raise ValueError("CSV row {}: {}".format(line, error)) from error
    if not rows:
        raise ValueError("CSV has no sample rows")
    valid = [row for row in rows if row["sample_ok"]]
    if len({(row["pid"], row["start_ticks"]) for row in valid}) > 1:
        raise ValueError("mixed process identities; do not combine restarts into one resource trend")
    return rows


def describe(rows, warmup_sec=0):
    if not rows:
        return None
    result = {"count": len(rows), "first_elapsed_sec": rows[0]["elapsed_sec"],
              "last_elapsed_sec": rows[-1]["elapsed_sec"]}
    for key in RESOURCE_COLUMNS:
        values = [row[key] for row in rows]
        result[key] = dict(initial=values[0], final=values[-1], maximum=max(values),
                           growth=values[-1] - values[0], median=statistics.median(values))
    trend = [row for row in rows if row["elapsed_sec"] >= rows[0]["elapsed_sec"] + warmup_sec]
    slope = None
    if len(trend) >= 3:
        times = [row["elapsed_sec"] for row in trend]
        rss = [row["vm_rss_kb"] for row in trend]
        mean_t, mean_r = statistics.mean(times), statistics.mean(rss)
        denominator = sum((value - mean_t) ** 2 for value in times)
        if denominator:
            slope = 60 * sum((t - mean_t) * (r - mean_r) for t, r in zip(times, rss)) / denominator
    result["rss_slope_kb_per_min_after_warmup"] = slope
    result["rss_trend_sample_count"] = len(trend)
    return result


def analyze(path, warmup_sec=120):
    rows = load_csv(path)
    valid = [row for row in rows if row["sample_ok"]]
    missing_slots = rows[-1]["slot_index"] + 1 - len(rows)
    metadata_path = Path(path).with_name("metadata.json")
    metadata = None
    missing_tail = 0
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != 1:
            raise ValueError("metadata schema mismatch")
        interval = finite(metadata["interval_sec"], "metadata interval")
        duration = finite(metadata["observed_duration_sec"], "metadata duration")
        requested = finite(metadata["requested_duration_sec"], "metadata requested duration")
        if interval <= 0 or requested <= 0:
            raise ValueError("invalid metadata interval/duration")
        if metadata.get("stop_reason") != "running":
            if metadata.get("valid_samples") != len(valid) or metadata.get("attempted_samples") != len(rows):
                raise ValueError("final metadata sample counts disagree with CSV")
            slots_in_observed_window = math.ceil(min(duration, requested) / interval)
            missing_tail = max(0, slots_in_observed_window - rows[-1]["slot_index"] - 1)
    epochs = []
    current = []
    for row in rows:
        if not row["sample_ok"] or (current and row["phase"] != current[-1]["phase"]):
            if current:
                epochs.append({"phase": current[0]["phase"], "summary": describe(current)})
                current = []
        if row["sample_ok"]:
            current.append(row)
    if current:
        epochs.append({"phase": current[0]["phase"], "summary": describe(current)})
    return {
        "sample_count": len(valid), "attempted_rows": len(rows),
        "failed_samples": len(rows) - len(valid),
        "missing_slots": missing_slots + missing_tail,
        "missing_samples": missing_slots + missing_tail + len(rows) - len(valid),
        "elapsed_time_sec": rows[-1]["elapsed_sec"] - rows[0]["elapsed_sec"],
        "valid_sample_span_sec": valid[-1]["elapsed_sec"] - valid[0]["elapsed_sec"] if valid else None,
        "overall": describe(valid, warmup_sec), "warmup_sec": warmup_sec,
        "phases": {phase: describe([row for row in valid if row["phase"] == phase]) for phase in PHASES},
        "phase_epochs": epochs, "metadata": metadata,
        "abnormal_states": [dict(sample_index=row["sample_index"], state=row["process_state"])
                            for row in valid if row["process_state"] in "ZXx"],
        "conclusion": "Resource evidence only; manual phase is not measured session count. No leak-free or Hardware Gate verdict.",
    }


def print_summary(result):
    print("Sample count: {} valid / {} recorded".format(result["sample_count"], result["attempted_rows"]))
    print("Elapsed time: {:.3f} s; valid sample span: {} s".format(
        result["elapsed_time_sec"], result["valid_sample_span_sec"]))
    print("Missing samples: {} (failed={}, missing slots={})".format(
        result["missing_samples"], result["failed_samples"], result["missing_slots"]))
    if result["metadata"]:
        data = result["metadata"]
        print("Monitor duration: {:.3f} s; target={} s; stop={}".format(
            data["observed_duration_sec"], data["requested_duration_sec"], data["stop_reason"]))
    else:
        print("Metadata absent: full observation duration / target coverage unavailable")
    overall = result["overall"]
    if overall:
        for name, key in (("RSS kB", "vm_rss_kb"), ("VmSize kB", "vm_size_kb"),
                          ("VmHWM kB", "vm_hwm_kb"), ("FD", "open_fd_count"), ("Threads", "threads")):
            data = overall[key]
            print("{} initial/final/max: {}/{}/{}; growth={}".format(
                name, data["initial"], data["final"], data["maximum"], data["growth"]))
        print("RSS slope after {} s warmup: {} kB/min ({} samples)".format(
            result["warmup_sec"], overall["rss_slope_kb_per_min_after_warmup"],
            overall["rss_trend_sample_count"]))
    for phase, data in result["phases"].items():
        if data:
            print("Manual {}: n={} RSS median={} kB FD median={} Threads median={}".format(
                phase, data["count"], data["vm_rss_kb"]["median"],
                data["open_fd_count"]["median"], data["threads"]["median"]))
    for number, epoch in enumerate(result["phase_epochs"], 1):
        data = epoch["summary"]
        print("Epoch {} {} [{:.3f},{:.3f}] n={} RSS/FD/Threads median={}/{}/{}".format(
            number, epoch["phase"], data["first_elapsed_sec"], data["last_elapsed_sec"],
            data["count"], data["vm_rss_kb"]["median"], data["open_fd_count"]["median"],
            data["threads"]["median"]))
    print("Abnormal process states: " + str(result["abnormal_states"]))
    print(result["conclusion"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file")
    parser.add_argument("--warmup-sec", type=float, default=120)
    parser.add_argument("--json", action="store_true", help="print complete JSON to stdout")
    args = parser.parse_args()
    if not math.isfinite(args.warmup_sec) or args.warmup_sec < 0:
        parser.error("warmup must be finite and nonnegative")
    path = Path(args.csv_file).resolve()
    if ROOT not in path.parents:
        parser.error("CSV must be inside the current LP2 workspace")
    result = analyze(path, args.warmup_sec)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_summary(result)
    return 0 if result["sample_count"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, KeyError, TypeError, ValueError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
