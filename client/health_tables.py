"""Build Excel-readable tables from one verified band export snapshot."""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import zlib


def write_csv(root, name, rows):
    if not rows:
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with (root / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def local_stamp(ts, offset_minutes):
    if not isinstance(ts, int) or ts <= 0:
        return ""
    zone = timezone(timedelta(minutes=offset_minutes))
    return datetime.fromtimestamp(ts, tz=zone).isoformat()


def clock_status(ts, collected_at):
    if not isinstance(ts, int) or not 1577836800 <= ts <= collected_at + 86400:
        return "设备时间异常"
    return "正常"


def make_tables(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    collected_at = datetime.fromisoformat(manifest["finished_at"]).timestamp()
    tables, ranges = defaultdict(list), defaultdict(set)
    valid_counts, file_types, stage_counts, caveats = Counter(), Counter(), Counter(), Counter()
    abnormal_files = 0
    parsed_files = sorted((root / "decoded").glob("*.json"))
    raw_files = sorted((root / "raw").glob("*.bin"))
    if {p.stem for p in raw_files} != set(manifest["files"]):
        raise ValueError("The captured file set does not match the manifest")
    for path in raw_files:
        raw = path.read_bytes()
        if (raw[:7].hex() != path.stem or len(raw) < 13
                or zlib.crc32(raw[:-4]) != int.from_bytes(raw[-4:], "little")):
            raise ValueError("A saved activity file failed CRC or ID validation")

    for path in parsed_files:
        item = json.loads(path.read_text(encoding="utf-8"))
        fid, kind, data = item["file_id"], item["kind"], item.get("data")
        if fid["hex"] != path.stem or path.stem not in manifest["files"]:
            raise ValueError("A decoded record has the wrong file ID")
        file_types[kind] += 1
        if data is None:
            continue
        offset = fid["utc_offset_min"]
        status = clock_status(fid["ts"], collected_at)
        if status != "正常":
            abnormal_files += 1
        else:
            ranges[kind].add(fid["local_date"])
        source = {"设备时区偏移分钟": offset, "设备时钟": status, "原始文件ID": path.stem}

        for key in ("trailing_bytes", "truncated_tail", "skipped_bytes", "blocks_error", "error"):
            if data.get(key):
                caveats[f"{kind}.{key}"] += 1

        if kind == "daily_details":
            for row in data["records"]:
                stamp = local_stamp(row["ts"], offset)
                timed = {"记录时间": stamp, **source}
                tables["每分钟记录.csv"].append({
                    **timed, "步数": row.get("steps"), "距离米": row.get("distance_m"),
                    "活动热量千卡": row.get("active_calories"),
                    "心率bpm": row.get("heart_rate") or None, "压力": row.get("stress") or None,
                    "血氧百分比": row.get("spo2") or None, "能量原值": row.get("energy"),
                    "光照原值": row.get("light_raw"), "身体活动原值": row.get("body_momentum_raw"),
                })
                for key, name, label in (("heart_rate", "心率.csv", "心率bpm"),
                                         ("stress", "压力.csv", "压力"),
                                         ("spo2", "血氧.csv", "血氧百分比")):
                    if row.get(key):
                        tables[name].append({**timed, label: row[key]})
                        if status == "正常":
                            valid_counts[key] += 1
        elif kind == "daily_summary":
            row = {key: value for key, value in data.items() if not key.endswith("_hex")}
            for key in ("hr_max_ts", "hr_min_ts", "spo2_max_ts", "spo2_min_ts"):
                if key in row:
                    row[key] = local_stamp(row[key], offset)
            tables["每日汇总.csv"].append({"设备日期": fid["local_date"], **source, **row})
        elif kind in ("sleep_details", "sleep_stages"):
            sleep_sources = {"入睡时间": local_stamp(data["bed_time"], offset),
                             "醒来时间": local_stamp(data["wakeup_time"], offset), **source}
            for row in data.get("stages", []):
                duration = row.get("duration_min")
                stage_counts[row["stage"]] += 1
                tables["睡眠阶段.csv"].append({
                    "阶段开始": local_stamp(row["ts"], offset), "阶段": row["stage"],
                    "分钟": duration, "设备阶段代码": row.get("raw"), **sleep_sources,
                })
            summaries = data.get("summaries")
            if summaries is None and not data.get("no_data"):
                summaries = [data]
            for row in summaries or []:
                tables["睡眠汇总.csv"].append({
                    "摘要记录时间": local_stamp(row.get("ts"), offset), **sleep_sources,
                    "睡眠分钟": row.get("sleep_min", row.get("total_min")), "深睡分钟": row.get("deep_min"),
                    "浅睡分钟": row.get("light_min"), "快速眼动分钟": row.get("rem_min"),
                    "清醒分钟": row.get("awake_min"), "醒来次数": row.get("wake_count"),
                    "手环睡眠指数原值": row.get("sleep_index"), "手环睡眠质量原值": data.get("sleep_quality"),
                })
        elif kind == "manual_samples":
            for row in data["samples"]:
                tables["手动测量.csv"].append({
                    "记录时间": local_stamp(row["ts"], offset), "类型": row["type_name"], "值": row["value"], **source,
                })

    for name, rows in tables.items():
        key = next(iter(rows[0]))
        write_csv(root, name, sorted(rows, key=lambda row: row[key]))
    summary = {
        "verified_raw_files": len(raw_files),
        "decoded_files_by_type": dict(file_types),
        "table_rows": {name: len(rows) for name, rows in tables.items()},
        "nonzero_measurements_with_plausible_file_time": dict(valid_counts),
        "sleep_stage_rows": dict(stage_counts),
        "file_dates_by_category_excluding_clock_outliers": {
            kind: {"first": min(dates), "last": max(dates), "recorded_days": len(dates)}
            for kind, dates in ranges.items()
        },
        "abnormal_clock_files": abnormal_files,
        "parser_notes": dict(caveats),
    }
    (root / "导出统计.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
