# MailEx Unified Conversion Report

## Result

The authoritative MailEx `train`, `dev`, and `test` directories were converted to one JSONL record per annotated email turn. `full_data` was not read or counted as independent data. All **3,936** turns were retained, including the audited non-string-token anomalies.

| Split | Thread files | Turn records | Tokens | Raw metadata aligned | Sender present | Recipients present | Timestamp present | Non-string token turns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 1200 | 3117 | 201535 | 2833 | 2819 | 2805 | 9 | 273 |
| dev | 150 | 414 | 26499 | 389 | 389 | 388 | 1 | 25 |
| test | 150 | 405 | 25448 | 371 | 370 | 366 | 0 | 30 |
| Total | 1500 | 3936 | 253482 | 3593 | 3578 | 3559 | 10 | 328 |

## Representation and preservation

- `tokens` is copied verbatim from the source `sentences[turn_index]`; token order and indices are unchanged.
- `original_events` is copied verbatim from `events["turn_i"]`, preserving triggers, BIO sequences, extras, and all original token-index references.
- `text` is a deterministic readable view using a small punctuation/contraction detokenization policy. It is not a cleaned or boilerplate-stripped representation.
- `token_offsets[i]` is `[start, end]` into `text`, and every `text[start:end]` was verified against the deterministic surface of `tokens[i]`.
- Nested token anomalies are retained. A nested empty-list token has an empty surface and therefore a zero-width offset; it is never discarded.
- `thread_id`, `turn_index`, `thread_context.previous_record_id`, and `thread_context.next_record_id` preserve email boundaries and ordering.
- IDs use `mailex:<split>:<source filename stem>:turn_<zero-padded index>` and are deterministic and unique.
- Sender, recipients, timestamp, and subject are populated only from a raw block aligned at normalized-text similarity ≥ 0.55. Otherwise they are `null`/`[]`.

## Output integrity

All records passed structural, JSON-serialization, offset-boundary, monotonicity, and exact reconstruction checks before writing. Source split/file counts were preserved.

| Output | SHA-256 |
| --- | --- |
| train.jsonl | 0f26ea342453cd5de27edfc917885c27b28e5e53d5c8409b4d577eba03657ba1 |
| dev.jsonl | 3e01b0379074e3abd376623ba2b9c37cf920f38aced6cf19fa5f52000e9db1ab |
| test.jsonl | 777b00a010a600d273aedcf66394c97e9a392d00c0920f0621aa826cf9cd8912 |

The converter version is `1.0.0`. Dataset root: `/Users/biancasawant/ML_Project/data/raw/mailex`. Output directory: `/Users/biancasawant/ML_Project/data/unified`.

## Raw metadata alignment and warnings

Raw files are usually reverse chronological and occasionally have extra or missing delimiter chunks. The converter compares all annotated turns with all raw blocks and accepts a deterministic one-to-one match only above the configured threshold; it does not guess metadata for rejected matches.

| Split | Warnings | Unaligned turns | Threads without raw file |
| --- | --- | --- | --- |
| train | 540 | 284 | 1 |
| dev | 52 | 25 | 0 |
| test | 60 | 34 | 1 |

Normalized raw filename collisions: **0**. Detailed per-file warnings are intentionally summarized here; conversion never drops a turn because raw metadata is missing or ambiguous.

## Manual inspection sample

The following 12 records come from different threads and were selected deterministically across all three splits after conversion:

| Record ID | Source file | Turn | Tokens | Sender? | Text preview |
| --- | --- | --- | --- | --- | --- |
| mailex:train:bass-e_inbox114:turn_0000 | bass-e_inbox114.json | 0 | 333 | yes | For some reason your e-mail to Shanna and I was quarantined by enron b/c of virus issues. What did you send? It looked like links to Fairfi… |
| mailex:train:bass-e_inbox136:turn_0000 | bass-e_inbox136.json | 0 | 383 | yes | Hi Eric, It looks like Enron employees have an enterprising spirit according to the H. Chronicle. Ebay is saturated with Enron goodies. Thi… |
| mailex:train:bass-e_inbox137:turn_0000 | bass-e_inbox137.json | 0 | 6 | yes | Watch the whole thing;) |
| mailex:train:bass-e_inbox195:turn_0000 | bass-e_inbox195.json | 0 | 203 | yes | Send to your group's please. If you feel like drowning your sorrows at the end of the world in some free keg beer, sodas and hard liquor -… |
| mailex:dev:bass-e_inbox152:turn_0000 | bass-e_inbox152.json | 0 | 368 | yes | Hi Eric, Sorry but Dad can't make it Thursday night. Would dinner here on Friday be o.k. with you? Dad suggested games, etc., and I wanted… |
| mailex:dev:blair-l_inbox164:turn_0000 | blair-l_inbox164.json | 0 | 93 | yes | This resource request has been rejected. You can view the details of the request by clicking http: //itcapps.corp.enron.com/srrs/auth/email… |
| mailex:dev:blair-l_inbox94:turn_0000 | blair-l_inbox94.json | 0 | 6 | yes | Here is the Gas Control Report |
| mailex:dev:blair-l_inbox_209:turn_0000 | blair-l_inbox_209.json | 0 | 81 | yes | Mike Bodnar needs a file restored. It seems that the file got corrupted. Mike Bodnar's director will send an email to ETS Sol Center reques… |
| mailex:test:bass-e_inbox100:turn_0000 | bass-e_inbox100.json | 0 | 89 | yes | Since Mr. Bass didn't follow through on our social engagement, I thought I would do so. Is anyone interested in lunch? Is tomorrow too earl… |
| mailex:test:bass-e_inbox124:turn_0000 | bass-e_inbox124.json | 0 | 33 | yes | Please come by 5C2 at your convenience tomorrow as UBS require you to complete missing information on your application form. Kind regards,… |
| mailex:test:bass-e_inbox65:turn_0000 | bass-e_inbox65.json | 0 | 5 | yes | we need a fourth again |
| mailex:test:bass-e_inbox97:turn_0000 | bass-e_inbox97.json | 0 | 371 | yes | I am so happy and relieved to see that Al Sharpton and Jesse Jackson are in town and have joined in the fight to right all the injustices a… |

## Reproduction

```bash
python3 scripts/convert_mailex.py
python3 -m unittest tests/test_convert_mailex.py
```
