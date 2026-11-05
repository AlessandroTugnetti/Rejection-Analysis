"""Compute aggregate job-search and rejection-email metrics from reviewed local records."""

import argparse
from calendar import day_name
from collections import Counter, defaultdict
from datetime import date, datetime
from itertools import combinations
import json
from pathlib import Path
import re
from statistics import median
import unicodedata
from zoneinfo import ZoneInfo


OUTCOMES = {"open", "rejected", "role_closed", "withdrawn", "offer"}
THRESHOLDS = (30, 60, 90, 180)
DATE_FIELDS = ("submitted_on", "first_reply_on", "step_1_on", "step_2_on", "rejected_on")
DURATIONS = {
    "submission_to_first_reply": ("submitted_on", "first_reply_on"),
    "submission_to_step_1": ("submitted_on", "step_1_on"),
    "submission_to_step_2": ("submitted_on", "step_2_on"),
    "submission_to_rejection": ("submitted_on", "rejected_on"),
    "step_1_to_rejection": ("step_1_on", "rejected_on"),
    "step_2_to_rejection": ("step_2_on", "rejected_on"),
}


def load_records(path):
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError(f"{path.name} must contain a JSON array of records")
    return records


def application_records(records, as_of):
    for index, source in enumerate(records, 1):
        row = source.copy()
        for field in DATE_FIELDS:
            row[field] = date.fromisoformat(row[field]) if row.get(field) else None
        submitted = row["submitted_on"]
        if row.get("outcome") not in OUTCOMES or submitted is None:
            raise ValueError(f"Application {index} needs a submission date and valid outcome")
        if submitted > as_of:
            continue
        for field in DATE_FIELDS[1:]:
            value = row[field]
            if value is not None and not submitted <= value <= as_of:
                raise ValueError(f"Application {index} has {field} outside the observation window")
        if row["rejected_on"] and row["outcome"] != "rejected":
            raise ValueError(f"Application {index} has a rejection date but another outcome")
        if row.get("rejection_date_estimated"):
            row["rejected_on"] = None
        yield row


def count_by_month(values, months):
    counts = Counter(value.strftime("%Y-%m") for value in values if value is not None)
    return {month: counts[month] for month in months}


def month_range(start, end):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year:04d}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def days_between(row, start, end):
    first, last = row.get(start), row.get(end)
    return (last - first).days if first and last and first <= last else None


def duration_summary(values):
    values = [value for value in values if value is not None]
    return {"count": len(values), "median_days": median(values) if values else None,
            "min_days": min(values, default=None), "max_days": max(values, default=None)}


def outcome_summary(rows):
    return {
        "applications": len(rows),
        "rejections": sum(row["outcome"] == "rejected" for row in rows),
        "rejection_wait": duration_summary(
            days_between(row, "submitted_on", "rejected_on") for row in rows
        ),
    }


def summarize_applications(rows, as_of):
    by_role, by_size = defaultdict(list), defaultdict(list)
    for row in rows:
        for group in set(row.get("role_groups", [])):
            by_role[group].append(row)
        if row.get("employer_size"):
            by_size[row["employer_size"]].append(row)

    months = list(month_range(min((row["submitted_on"] for row in rows), default=as_of), as_of))
    silence = []
    for threshold in THRESHOLDS:
        eligible = [row for row in rows if (as_of - row["submitted_on"]).days >= threshold]
        unanswered = sum(
            row["outcome"] == "open" and not (
                row["first_reply_on"] or row["step_1_on"] or row["step_2_on"]
                or row.get("next_step") or row.get("interview")
            )
            for row in eligible
        )
        silence.append({"minimum_age_days": threshold, "eligible": len(eligible),
                        "still_open_without_reply": unanswered,
                        "share": unanswered / len(eligible) if eligible else None})

    interviewed = [row for row in rows if row.get("interview")]
    return {
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "monthly": {
            "applications": count_by_month((row["submitted_on"] for row in rows), months),
            "rejections": count_by_month((row["rejected_on"] for row in rows), months),
        },
        "stages": {
            "applications": len(rows),
            "dated_replies": sum(row["first_reply_on"] is not None for row in rows),
            "next_steps": sum(bool(row["step_1_on"] or row["step_2_on"] or
                                   row.get("next_step") or row.get("interview")) for row in rows),
            "interviews": len(interviewed),
            "rejections_after_interview": sum(row["outcome"] == "rejected" for row in interviewed),
        },
        "waits": {name: duration_summary(days_between(row, *fields) for row in rows)
                  for name, fields in DURATIONS.items()},
        "rejections_by_interview": {
            "no_interview": outcome_summary([row for row in rows if not row.get("interview")]),
            "interview": outcome_summary(interviewed),
        },
        "silence": silence,
        "role_groups": {name: outcome_summary(group) for name, group in sorted(by_role.items())},
        "employer_size": {
            name: {
                **outcome_summary(group),
                "distinct_employers": len({row["employer_key"] for row in group if row.get("employer_key")}),
            }
            for name, group in sorted(by_size.items())
        },
    }


def trigrams(body, masks):
    body = unicodedata.normalize("NFKC", body).casefold()
    for mask in sorted(masks, key=len, reverse=True):
        normalized = unicodedata.normalize("NFKC", mask).casefold().strip()
        if len(normalized) > 2:
            body = body.replace(normalized, " entity ")
    body = re.sub(r"\b\w*\d\w*\b", " reference ", body)
    tokens = re.findall(r"[^\W\d_]+(?:[’'][^\W\d_]+)?", body)
    return set(zip(tokens, tokens[1:], tokens[2:]))


def summarize_emails(records, as_of, zone, threshold):
    arrivals, reasons, appreciation = [], Counter(), Counter()
    groups = defaultdict(list)
    for index, row in enumerate(records, 1):
        timestamp = row["received_at"]
        received_at = datetime.fromisoformat(timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp)
        if received_at.utcoffset() is None:
            raise ValueError(f"Email {index} needs a time-zone offset")
        local = received_at.astimezone(zone)
        if local.date() > as_of:
            continue
        arrivals.append(local)
        reasons[row.get("reason", "uncoded")] += 1
        language = row["language"].strip().casefold()
        if not language:
            raise ValueError(f"Email {index} needs a primary language")
        if row.get("appreciation"):
            appreciation[language] += 1
        groups[language].append((trigrams(row["body"], row.get("mask", [])), row.get("employer_key")))

    scores = []
    cross_employer_count = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        closest = [0.0] * len(group)
        cross_employer = set()
        for left, right in combinations(range(len(group)), 2):
            a, employer_a = group[left]
            b, employer_b = group[right]
            union_size = len(a | b)
            score = len(a & b) / union_size if union_size else 0.0
            closest[left] = max(score, closest[left])
            closest[right] = max(score, closest[right])
            if score >= threshold and employer_a and employer_b and employer_a != employer_b:
                cross_employer.update((left, right))
        scores.extend(closest)
        cross_employer_count += len(cross_employer)

    weekdays = Counter(day.weekday() for day in arrivals)
    hours = Counter(day.hour for day in arrivals)
    months = list(month_range(min(arrivals).date(), max(arrivals).date())) if arrivals else []
    histogram = Counter(min(9, int(score * 10)) for score in scores)
    return {
        "messages": len(arrivals),
        "arrival_month": count_by_month(arrivals, months),
        "arrival_weekday": {day_name[i]: weekdays[i] for i in range(7)},
        "arrival_hour": {f"{i:02d}:00": hours[i] for i in range(24)},
        "reasons": dict(sorted(reasons.items())),
        "appreciation_by_language": {
            language: {"messages": len(group), "with_appreciation": appreciation[language]}
            for language, group in sorted(groups.items())
        },
        "similarity": {
            "method": "Jaccard on sets of three consecutive words, within language",
            "threshold": threshold,
            "messages_with_peer": len(scores),
            "messages_with_close_match": sum(score >= threshold for score in scores),
            "messages_with_cross_employer_close_match": cross_employer_count,
            "nearest_match_histogram": {f"{i / 10:.1f}": histogram[i] for i in range(10)},
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--applications", type=Path, required=True)
    parser.add_argument("--emails", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--timezone", default="Europe/Luxembourg")
    parser.add_argument("--similarity-threshold", type=float, default=0.75)
    args = parser.parse_args()
    if not 0 < args.similarity_threshold <= 1:
        parser.error("--similarity-threshold must be greater than 0 and at most 1")
    try:
        applications = list(application_records(load_records(args.applications), args.as_of))
        emails = summarize_emails(load_records(args.emails), args.as_of,
                                  ZoneInfo(args.timezone), args.similarity_threshold)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    result = {"as_of": args.as_of.isoformat(), "timezone": args.timezone,
              "applications": summarize_applications(applications, args.as_of), "emails": emails}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
