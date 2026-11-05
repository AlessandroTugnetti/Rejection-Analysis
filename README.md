# Rejection Analysis

A local Python analysis of a job search and the rejection emails it produces. The script summarizes when applications and rejections occur, how far applications progress, how long replies take, and how much wording the emails have in common.

[Read the full project story](https://alessandrotugnetti.github.io/projects/rejection-email-analysis/).

The repository contains the analysis code and documentation. The original tracker, correspondence, company records, and analysis outputs are private.

## Run the analysis

Use Python 3.10 or later with an installed IANA timezone database. The script uses only the Python standard library and runs offline.

```bash
python3 analysis.py \
  --applications /path/to/applications.json \
  --emails /path/to/rejection-emails.json \
  --as-of YYYY-MM-DD \
  --timezone Europe/Luxembourg > /path/to/summary.json
```

Set `--as-of` to the date the search is observed. `--timezone` defaults to Europe/Luxembourg and determines how timestamped emails fall into local months, weekdays and hours. `--similarity-threshold` defaults to 0.75. The output is a JSON summary for charts or further analysis. Keep your input and output files outside the checkout.

## Prepare your own inputs

Both inputs are UTF-8 JSON arrays. Review the records for duplicates before running the script. Supply outcomes and progression as known on the observation date. Use ISO dates (`YYYY-MM-DD`) and omit or set `null` for unknown optional dates. For a section you want to skip, its input may be an empty array.

### Applications

Use one record for each application sent.

| Field | Meaning |
| --- | --- |
| `submitted_on` | Required. Date the application is sent. |
| `outcome` | Required. One of `open`, `rejected`, `role_closed`, `withdrawn` or `offer`. |
| `first_reply_on` | Date of the first reply beyond an automatic receipt. A decision or a recruiter question can count. |
| `step_1_on`, `step_2_on` | Dates for documented steps, such as a test request or an interview appointment. Use a consistent basis. Count a rescheduled appointment once. |
| `next_step` | Boolean. Set to true if progression is known even when its date is missing. |
| `interview` | Boolean. The article uses confirmed attendance. If reproducing that comparison, apply the same rule. |
| `rejected_on`, `rejection_date_estimated` | The rejection date and an optional boolean indicating an estimate. A rejection can count even when its date is missing or estimated. |
| `role_groups` | Optional array of short analytical labels assigned from role titles. An application can belong to more than one group. |
| `employer_size`, `employer_key` | Optional verified size band and a stable pseudonymous employer key. Use the same organizational scope when comparing headcounts. |

### Rejection emails

Use one record for each distinct rejection email in the corpus. Leave out receipts and role closures. Use the primary language for a multilingual message.

| Field | Meaning |
| --- | --- |
| `received_at` | Required. ISO timestamp with UTC offset. |
| `language` | Required. A consistent primary-language code such as `en`. |
| `body` | Required. Plain-text message after removing greetings, signatures, legal footers and quoted messages. |
| `mask` | Optional array of recognized names, employers, and role titles to replace before comparison. |
| `employer_key` | Optional pseudonymous employer key for the cross-employer comparison. |
| `reason` | Optional manually coded reason communicated in the email, such as `no_reason` or `other_candidate`. |
| `appreciation` | Optional manually coded boolean for a thank-you or expression of appreciation anywhere in the email. |

## How the measures work

- **Calendar.** Applications and dated rejections are counted in their respective event months. A rejection can appear months after its application. Estimated rejection dates are excluded from the timing measures.
- **Progression and waits.** Each stage counts applications, and stages can overlap. Durations are elapsed calendar days between documented dates. The summaries report how many intervals are available and their median, minimum and maximum.
- **Silence.** At 30, 60, 90 and 180 days, the denominator includes only applications old enough to reach that threshold. The numerator includes applications still open at the snapshot with no documented reply or progression. These are observations at a cutoff, and each age threshold has its own denominator.
- **Arrival patterns.** One rejection email contributes one local month, weekday and hour. The email corpus can cover fewer cases than the broader application log.
- **Similarity.** After normalizing Unicode and case and masking known entities and numeric references, the script builds a set of distinct sequences of three consecutive words per email. The Jaccard score is the share of sequences across both messages that they have in common. Each email is compared with peers in the same language. The summary uses the closest match, and also counts any match at or above the threshold from a different known employer. This measures repeated wording. It does not infer who wrote the message or why the employer rejected the application.
- **Roles and employer size.** The report counts applications and recorded rejections by overlapping role labels and within verified size bands. These are descriptions of a search in progress. Small groups and cases still waiting for an outcome affect the comparison.

The standalone script begins with reviewed records. Email retrieval, deduplication, identification of application matches, and the website presentation are separate from the computation here. If you share results generated from your own data, inspect the aggregate labels and small groups before publishing.
