# MailEx Dataset Audit

## Executive summary

- The authoritative train/dev/test corpus contains **1,500 thread-file occurrences and 3,936 annotated email turns**. Exact token-structure deduplication leaves **3,393 unique email bodies**.
- `full_data` is an exact duplicate convenience view: its filename set equals the three-split union and all matching files are byte-identical. It is **not** counted as another 1,500 threads.
- Each `sentences[i]` is the token sequence for one email turn, and `events["turn_i"]` contains one or more event-type containers for that same sequence. Every event instance contributes one full-length BIO sequence and one trigger entry.
- There are **8,392 real event occurrences** and **18,149 decoded argument spans**. These are instance/span counts—not labeled-token counts.
- No token/label length mismatches or turn-key mismatches were found in this copy.
- The main annotation anomaly is **234 orphan or role-transition `I-` labels**. Recovering each as a span start produces 18,149 spans versus 17,915 explicit `B-` starts.
- The JSON annotations contain no sender, recipient, subject, timestamp, or explicit thread ID fields. Raw source chunks usually contain From/To/Subject, but timestamps are almost entirely absent and 37 annotated/raw block counts disagree.
- Action extraction is directly supported by `Request_Action`, `Deliver_Action_Data`, and `Amend_Action_Data`; meeting and data events add coordination/information work. There is **no explicit dependency label**, so prerequisite relations require inference from language such as *before*, *after*, *once*, *until*, and *pending*.

## Corpus structure and split integrity

| Split | Thread JSON files | Annotated email turns | Tokens |
| --- | --- | --- | --- |
| train | 1200 | 3117 | 201535 |
| dev | 150 | 414 | 26499 |
| test | 150 | 405 | 25448 |
| Total (authoritative) | 1500 | 3936 | 253482 |

`full_data` contains 1,500 JSON files. Its filename set equals the union of train/dev/test: **True**. Byte mismatches: **0**. Pairwise split filename overlaps are all zero.

The recursive download also contains `raw_threads/` (1,506 files), `prompt_data.txt`, and `.DS_Store`. Of the raw files, 1,498 match annotated thread stems; 2 annotated threads lack a raw file and 8 raw files lack annotated JSON.

## Unique threads, emails, and duplication

- Unique thread filenames: **1,500**.
- Unique byte-level annotated thread contents: **1,495**. There are 2 duplicate-content groups accounting for 5 occurrences beyond the first.
- Exact unique `sentences[i]` token structures: **3,393** of 3,936 turns. There are 161 duplicate-email groups and 543 repeated occurrences beyond the first.
- Cross-split exact duplicates exist: 1 thread-content groups and 59 email-content groups. This matters for leakage-sensitive experiments even though filenames are split-disjoint.

## `sentences[i]` and `events["turn_i"]`

sentences[i] is the token sequence for email turn i; events['turn_i'] contains all event-type containers for that same sequence. Each event instance has a full-length BIO label sequence aligned one-to-one with sentences[i].

Event-type containers are not event counts: a container may hold multiple parallel `labels` sequences. The occurrence count is the number of label/trigger entries. In this copy, label-sequence count always matches trigger count, and each label sequence has exactly the same length as its corresponding token list.

The raw source blocks are predominantly reverse-chronological while `sentences` is chronological. Among equal-length, automatically comparable threads: 1450 strongly favor reversed order, 0 same order, and 11 are unclear under the documented similarity margin.

## Event types and occurrence counts

| Event type | Occurrences | Turn/type containers | Argument spans |
| --- | --- | --- | --- |
| Deliver_Action_Data | 3195 | 1604 | 7139 |
| Deliver_Data | 1820 | 1262 | 3675 |
| Request_Action | 1376 | 1048 | 2509 |
| O | 776 | 776 | 0 |
| Request_Data | 721 | 602 | 1192 |
| Deliver_Meeting_Data | 487 | 409 | 1549 |
| Request_Meeting | 259 | 246 | 847 |
| Request_Action_Data | 233 | 212 | 469 |
| Amend_Data | 193 | 153 | 489 |
| Amend_Meeting_Data | 55 | 53 | 160 |
| Request_Meeting_Data | 50 | 48 | 109 |
| Amend_Action_Data | 3 | 3 | 11 |

`O` is a no-event placeholder, not a semantic event. The total real-event count excludes its 776 placeholder instances.

## Argument labels, BIO prefixes, and spans

BIO prefixes present are `B`, `I`, and `O`. Excluding `O`, labeled token counts are: B = 17,915; I = 88,605. Qualifiers are `Context`, `Revision`, and no qualifier. Case is not fully normalized: for example, both `Deliver Members` and `Deliver members`, and both `Context: Request Members` and `Context: Request members`, occur.

| Qualified argument label | Decoded spans | Labeled tokens |
| --- | --- | --- |
| Action Description | 4657 | 45324 |
| Action Members | 3914 | 5175 |
| Data idString | 1735 | 11524 |
| Data Value | 1384 | 22105 |
| Meeting Members | 1155 | 1925 |
| Context: Data idString | 889 | 6280 |
| Action Date | 760 | 2812 |
| Deliver members | 447 | 447 |
| Context: Request members | 399 | 399 |
| Meeting Agenda | 353 | 2893 |
| Meeting Date | 342 | 938 |
| Context: Action Description | 238 | 1607 |
| Deliver Members | 209 | 256 |
| Meeting Time | 199 | 537 |
| Context: Action Members | 182 | 209 |
| Meeting Name | 170 | 559 |
| Meeting Location | 157 | 720 |
| Context: Amend Members | 123 | 132 |
| Revision: Data Value | 119 | 837 |
| Action Time | 115 | 318 |
| Context: Request Members | 75 | 112 |
| Context: Meeting Members | 71 | 91 |
| Context: Data Value | 59 | 266 |
| Context: Meeting Name | 40 | 108 |
| Request Members | 38 | 45 |
| Data Type | 37 | 46 |
| Revision: Meeting Time | 34 | 95 |
| Context: Request Date | 29 | 114 |
| Revision: Meeting Date | 27 | 77 |
| Deliver Date | 26 | 88 |
| Context: Meeting Date | 22 | 60 |
| Context: Amend Date | 17 | 37 |
| Context: Meeting Agenda | 17 | 89 |
| Revision: Meeting Location | 15 | 52 |
| Data Owner | 12 | 14 |
| Revision: Data idString | 11 | 34 |
| Context: Action Date | 10 | 35 |
| Context: Meeting Location | 10 | 16 |
| Context: Meeting Time | 9 | 20 |
| Context: Request Time | 9 | 18 |
| Revision: Meeting Members | 9 | 13 |
| Deliver Time | 8 | 14 |
| Context: Amend Time | 5 | 21 |
| Context: Data Owner | 3 | 3 |
| Context: Action Time | 2 | 8 |
| Revision: Meeting Agenda | 2 | 26 |
| Context: Data Type | 1 | 13 |
| Request Time | 1 | 1 |
| Revision: Action Date | 1 | 4 |
| Revision: Action Members | 1 | 2 |
| Revision: Action Time | 1 | 1 |

The machine-readable CSV gives split × event × qualifier × argument × BIO counts and separate event-occurrence and span rows.

## Action-item relevance and examples

- Direct action: `Request_Action`, `Deliver_Action_Data`, `Amend_Action_Data`.
- Coordination/action context: `Request_Meeting`, `Deliver_Meeting_Data`, `Amend_Meeting_Data`.
- Information work: `Request_Data`, `Deliver_Data`, `Amend_Data`, plus action/meeting-data request types.
- `Action Description`, action/delivery members, and action/delivery date/time slots map naturally to task, assignee, and deadline candidates. MailEx does not distinguish requester from assignee consistently enough to use member slots without event-aware interpretation.
- Dependencies are not annotated as relations or slots.

Examples with action descriptions, people, and date/time arguments:

- `dev/donoho-l_inbox_junk_file332.json turn_2` — Action Members = “We”; Action Description = “create the substance”; Action Date = “before it 's ready for prettying up”
- `train/mclaughlin-e_inbox5.json turn_1` — Action Members = “you”; Action Members = “Joey”; Action Description = “show me how to load the price curve”; Action Date = “when you get a chance”
- `test/parks-j_inbox_147.json turn_3` — Action Members = “you guys”; Action Description = “go around and contact these customers to logoff”; Action Date = “tonight”
- `dev/sager-e_inbox819.json turn_1` — Action Members = “we”; Action Description = “check this with credit”; Action Date = “before inking it.”
- `dev/ybarbo-p_inbox483.json turn_0` — Action Members = “I”; Action Description = “send the TW tariff updates for Paul to you in EB1343”; Action Date = “until you both have permanent offices”

Prerequisite-like language examples (lexical candidates, not gold dependency annotations):

- `train/buy-r_inbox925.json turn_0` (after, until, upon, depend): “El Paso BOD killed due to capital sourcing uncertainty . They have asked for an option until the midle of Feb. Makes sense to evaluate versus an auction . In the meantime we do need to send a call notice for their LP interest on Monday . I believe that an auction will likely result in more litigation from Brazos but t…”
- `train/mann-k_inbox309.json turn_2` (before, once, until, upon): “Please provide final GSA so that I can forward to Jode . Tasking Letter is not processed until GSA is executed and language has been agreed upon . I will process once I received the executed GSA from Jode . Kay , I have a note that you would like to see if before I added to the approval process . Thanks and best regar…”
- `train/kaminski-v_inbox426.json turn_0` (before, after, until): “Gas Weather Group Special needs : 1 . 2 Met Boxes ( Linux ) must be up 1st thing in the morning Monday . Details : MET1 - Must have static IP address . Adam will supply MAC address to us in order to get the static IP for ECS assigned before move . Connects to 2 monitors on Adam 's station . MET2 - DHCP Connected to 1…”
- `train/keiser-k_inbox13.json turn_0` (before, once, as_soon_as): “I just wanted to keep you posted on the information that I know so far about the move . Of course , it could change with in the next five minutes so it 's not written in stone . As of now , the move for the 6 th floor is scheduled for Friday ( 2/8 ) . Notexactly sure what time this is going to take place yet . Please…”
- `train/corman-s_inbox_archives445.json turn_0` (after, upon): “Night - 7:30 Terrell / Gina As you may or may not be aware , The Dicks , Kudlas and Erbs are all going to the Aeros game Friday night after practice . The kids were given Aeros tickets for good grades . We also stumbled upon four additional tickets ( thru work ) and were wondering if you and your family would like to…”
- `train/nemec-g_inbox856.json turn_0` (before, as_soon_as): “Team , Here is an update on Oakhill : 1 . Ricki said he is sending us a T & D only contract first thing tomorrow morning , he will try to send it before 9 AM but can not guarantee it . This document will include a T & D price . When asked if this document will be executable , Ricki said `` He thinks so , he 'll check…”

## Email length and boilerplate

- Email token length: min 1, median 37, p90 159, p95 232, p99 379.65, max 721; mean 64.4.
- Thread length: min 2, median 2, p90 4, max 11 email turns; mean 2.62.
- Signature-like turns by split: {'dev': 126, 'test': 115, 'train': 1011} (heuristic: closing/contact terms in the last 60 tokens).
- Embedded quoted-reply-like turns by split: {'dev': 1, 'train': 13} (conservative; raw messages are often already separated into blocks).
- Repeated disclaimer categories by email-turn presence: {'confidential_or_privileged': 96, 'intended_recipient': 80, 'property_of_enron': 61, 'unauthorized_review_or_use': 4, 'virus_or_security_notice': 4}.

Long tails are substantial and include corporate disclaimers, signatures/contact details, forwarded material, and quoted content. Models should not assume short sentence-like inputs even though the field is named `sentences`.

## Metadata completeness

The annotated JSON has no sender, recipient, subject, timestamp, or explicit thread-id fields. Filename is the only thread identifier. The raw-source header audit below covers 3,963 delimiter-separated blocks from the 1,498 matching raw files.

| Raw header | Present | Non-empty | Non-empty share |
| --- | --- | --- | --- |
| FROM | 3921 | 3918 | 98.9% |
| TO | 3913 | 3893 | 98.2% |
| SUBJECT | 3901 | 3810 | 96.1% |
| DATE | 12 | 12 | 0.3% |
| SENT | 1 | 1 | 0.0% |
| CC | 0 | 0 | 0.0% |

`DATE`/`SENT` is only a syntactic header heuristic and can include body-like fields, so timestamp availability is at most the reported value. Raw block counts disagree with annotated turn counts in 37 threads. Consequently, the authoritative email count for modeling is the 3,936 annotated turns, not the 3,963 raw delimiter chunks.

## Annotation anomalies

| Check | Count |
| --- | --- |
| structural anomalies | 328 |
| turn key mismatches | 0 |
| token label length mismatches | 0 |
| label trigger instance count mismatches | 0 |
| malformed label values | 0 |
| embedded event type mismatches | 0 |
| orphan i transitions | 234 |
| trigger anomalies excluding noncontiguous and empty | 0 |
| noncontiguous trigger indices | 195 |
| empty trigger indices | 19 |
| raw annotated turn count mismatches | 37 |

Structural anomaly samples:

- `train/bass-e_inbox195.json turn_2`: non_string_tokens ([['']])
- `train/bass-e_inbox290.json turn_1`: non_string_tokens ([['']])
- `train/bass-e_inbox39.json turn_4`: non_string_tokens ([['']])
- `train/bass-e_inbox88.json turn_1`: non_string_tokens ([['']])
- `train/bass-e_inbox89.json turn_1`: non_string_tokens ([['']])
- `train/bass-e_inbox89.json turn_2`: non_string_tokens ([['']])
- `train/beck-s_inbox272.json turn_2`: non_string_tokens ([['']])
- `train/beck-s_inbox5.json turn_2`: non_string_tokens ([['']])
- `train/blair-l_inbox268.json turn_1`: non_string_tokens ([['']])
- `train/blair-l_inbox_284.json turn_3`: non_string_tokens ([['']])

Notable details:

- **327 turns across 282 threads** encode empty content as a nested list token (`[[""]]`) instead of a string token. One additional turn ends with a nested empty token after normal string tokens. These account for all 328 structural anomalies.
- 234 `I-` transitions occur without a matching active span; downstream BIO decoders must choose whether to reject them or recover them as starts.
- 195 triggers use non-contiguous token indices, and 19 real triggers have empty index lists. Parsed, in-range trigger words otherwise match their indexed tokens in this copy.
- Label capitalization variants should be normalized only in a derived preprocessing layer, never by changing the raw files.

## Reproducibility

Run from the project root:

```bash
python3 scripts/audit_mailex.py
```

The script reads only `data/raw/mailex/`, counts train/dev/test as authoritative, verifies `full_data`, and rewrites the three report files deterministically. Input SHA-256 aggregate digests and exact counting policies are recorded in `mailex_audit.json`.
