# MailEx Conservative Cleaning Report

## Result

All **3,936** unified MailEx records were processed without changing split membership, record IDs, original token arrays, or MailEx event annotations. Cleaning is deterministic and token-aware; no LLM rewriting, summarization, or paraphrasing was used.

| Split | Records | Reliable clean alignment | Raw fallback | With operations | Flagged for review | Quoted context |
| --- | --- | --- | --- | --- | --- | --- |
| train | 3117 | 3117 | 0 | 1003 | 945 | 2 |
| dev | 414 | 414 | 0 | 120 | 110 | 0 |
| test | 405 | 405 | 0 | 117 | 111 | 0 |
| Total | 3936 | 3936 | 0 | 1240 | 1166 | 2 |

## Safety policy

- Original reconstructed text is retained as `text_raw`; original offsets are retained as `token_offsets_raw`.
- Cleaned text is stored separately as `text`.
- `token_offsets` remains indexed by original token position. Safely removed tokens receive `null`; retained tokens reconstruct exactly from `text`.
- All MailEx non-`O` argument labels and trigger indices are protected. A candidate overlapping any protected token is retained and flagged, never silently deleted.
- If input or clean alignment validation fails, `text` falls back to `text_raw`, original offsets are restored, and `training_text_source` is set to `text_raw`.
- High-confidence trailing legal boilerplate and explicit quoted-history blocks can be removed. Ambiguous signatures, whole-message forwards, and uncertain encoding artifacts are preserved for review.
- Quoted/forwarded evidence is stored separately in `quoted_context`, including exact raw character/token spans and whether it was removed from the clean text.
- Names, negation, punctuation, temporal expressions, and token order are never paraphrased.

## Operations

| Operation and action | Count |
| --- | --- |
| email_signature_preserved_for_review | 1158 |
| email_signature_removed | 29 |
| legal_disclaimer_preserved_for_review | 9 |
| legal_disclaimer_removed | 62 |
| quoted_or_forwarded_block_removed | 2 |

## Duplicate analysis

- Exact raw-text duplicate groups: **161** covering 704 records.
- Conservative near-duplicate groups: **12** covering 25 records.
- Near-duplicate rule: token 3-gram Jaccard ≥ 0.85, length ratio ≥ 0.75, with deterministic SimHash band candidate generation. Short emails under eight normalized words are exact-match-only.
- Candidate pairs evaluated: 514; verified near pairs: 13; oversized buckets skipped: 0.
- Duplicate records are annotated in `duplicate_info`; none are removed or moved between splits.

## Output integrity

| Output | SHA-256 |
| --- | --- |
| train.jsonl | b82f4f1ef4bc68d851107d492ae2802837165e955e05cc65fd31fc8cdab15fd0 |
| dev.jsonl | db8a9959aa262173eacd4fac8dbdf0072eddc4ed4b7b8c13cf8821c97fd34fc1 |
| test.jsonl | a014073482d98783fe72ff5479e6a5cb7154021f19568f45bb851ad9d09a641e |

Cleaning version: `1.0.0`. Input: `/Users/biancasawant/ML_Project/data/unified`. Output: `/Users/biancasawant/ML_Project/data/cleaned`.

## Before/after examples with exact removed spans

### Example 1: `mailex:dev:bass-e_inbox152:turn_0000`

Removed spans:

- `legal_disclaimer` raw chars `[293, 1392]`, tokens `[73, 368]`: "* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * *"

Before:

```text
Hi Eric, Sorry but Dad can't make it Thursday night. Would dinner here on Friday be o.k. with you? Dad suggested games, etc., and I wanted to bake a birthday cake. We can either order in or I would love to cook anything you would like. It's up to you. Let me know. Have a great day. Love, Mom * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the bas…
```

After:

```text
Hi Eric, Sorry but Dad can't make it Thursday night. Would dinner here on Friday be o.k. with you? Dad suggested games, etc., and I wanted to bake a birthday cake. We can either order in or I would love to cook anything you would like. It's up to you. Let me know. Have a great day. Love, Mom
```
### Example 2: `mailex:dev:blair-l_inbox_209:turn_0000`

Removed spans:

- `email_signature` raw chars `[396, 461]`, tokens `[72, 81]`: "Thanks! Lupita Cantu ETS Information Risk Management 713-853-3876"

Before:

```text
Mike Bodnar needs a file restored. It seems that the file got corrupted. Mike Bodnar's director will send an email to ETS Sol Center requesting the restoration. Path: \\gthou-dv01\common\mkt\oma\sumdec01.xls. Please restore it from 12/28/01 tape backup and restore it to the same location. A high priority Remedy ticket #37225 has been opened. If you have any questions, please call me at x33876 Thanks! Lupita Cantu ETS Information Risk Management 713-853-3876
```

After:

```text
Mike Bodnar needs a file restored. It seems that the file got corrupted. Mike Bodnar's director will send an email to ETS Sol Center requesting the restoration. Path: \\gthou-dv01\common\mkt\oma\sumdec01.xls. Please restore it from 12/28/01 tape backup and restore it to the same location. A high priority Remedy ticket #37225 has been opened. If you have any questions, please call me at x33876
```
### Example 3: `mailex:dev:buy-r_inbox322:turn_0000`

Removed spans:

- `email_signature` raw chars `[563, 644]`, tokens `[111, 124]`: "Thank you. Laura Valencia Executive Assistant Tel: 713-853-6485 Fax: 713/853-2534"

Before:

```text
As you are aware, we are in the process of rescheduling the Enron Corp. Board of Directors meeting. Due to the proximity of the Holidays we will hold committee meetings and Board meeting on the same day. Therefore, please let us know today the minimum amount of time you would need for your respective committee meetings. Please be aware that some of our Directors will be joining the meeting via teleconference and we will therefore need to do all mail outs at least one week in advance. As soon as we have a firm date for the Board meeting, we will advise you. Thank you. Laura Valencia Executive Assistant Tel: 713-853-6485 Fax: 713/853-2534
```

After:

```text
As you are aware, we are in the process of rescheduling the Enron Corp. Board of Directors meeting. Due to the proximity of the Holidays we will hold committee meetings and Board meeting on the same day. Therefore, please let us know today the minimum amount of time you would need for your respective committee meetings. Please be aware that some of our Directors will be joining the meeting via teleconference and we will therefore need to do all mail outs at least one week in advance. As soon as we have a firm date for the Board meeting, we will advise you.
```
### Example 4: `mailex:dev:hernandez-j_inbox16:turn_0000`

Removed spans:

- `legal_disclaimer` raw chars `[71, 1170]`, tokens `[17, 312]`: "* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * *"

Before:

```text
is mommy in houston. i'm thinking about visiting her. what's the deal? * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * *
```

After:

```text
is mommy in houston. i'm thinking about visiting her. what's the deal?
```
### Example 5: `mailex:dev:rapp-b_inbox_16:turn_0000`

Removed spans:

- `email_signature` raw chars `[201, 266]`, tokens `[34, 43]`: "Thanks! Lupita Cantu ETS Information Risk Management 713-853-3876"

Before:

```text
Emmanuel, Please schedule the Outlook migration for Bill Rapp for 10/22. He is transferring from EES to ETS. This is his info: LoginIDbrapp FirstName=Bill LastNameRapp Business UnitETS Date of Move/22 Thanks! Lupita Cantu ETS Information Risk Management 713-853-3876
```

After:

```text
Emmanuel, Please schedule the Outlook migration for Bill Rapp for 10/22. He is transferring from EES to ETS. This is his info: LoginIDbrapp FirstName=Bill LastNameRapp Business UnitETS Date of Move/22
```
### Example 6: `mailex:dev:sager-e_inbox121:turn_0001`

Removed spans:

- `email_signature` raw chars `[109, 144]`, tokens `[23, 27]`: "Thanks Elizabeth Sager 713-853-6349"

Before:

```text
Sure just let me know conference room and I'll be there. Alice can you make sure we have final presentation. Thanks Elizabeth Sager 713-853-6349
```

After:

```text
Sure just let me know conference room and I'll be there. Alice can you make sure we have final presentation.
```
### Example 7: `mailex:dev:steffes-j_inbox255:turn_0000`

Removed spans:

- `legal_disclaimer` raw chars `[83, 1182]`, tokens `[20, 315]`: "* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * *"

Before:

```text
Hi Jim, What's your calendar look like next week? Can you get lunch one day? Shane * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * *
```

After:

```text
Hi Jim, What's your calendar look like next week? Can you get lunch one day? Shane
```
### Example 8: `mailex:dev:taylor-m_inbox_ev2:turn_0000`

Removed spans:

- `legal_disclaimer` raw chars `[125, 1224]`, tokens `[28, 323]`: "* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * *"

Before:

```text
I was curious if any of these LIDOs are selling. IS there a back order or do you have a ready supply of them? Michael Taylor * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * …
```

After:

```text
I was curious if any of these LIDOs are selling. IS there a back order or do you have a ready supply of them? Michael Taylor
```
### Example 9: `mailex:dev:tycholiz-b_inbox558:turn_0000`

Removed spans:

- `legal_disclaimer` raw chars `[153, 1502]`, tokens `[28, 370]`: "This email and any files transmitted with it from Mastio & Company are confidential and intended solely for the use of the individual or entity to whom they are addressed. If you have received this email in error please notify the sender. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any of its affiliates) and the intended recipient or any other party, and may not be relied on by anyone as the basis of a contract by estoppel or otherwise. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * *"

Before:

```text
Barry, Here is the questionnaire I look forward to discussing this next week (Thursday, 8th at 2:00 pm). Bart _________________________ Bart Thedinger * This email and any files transmitted with it from Mastio & Company are confidential and intended solely for the use of the individual or entity to whom they are addressed. If you have received this email in error please notify the sender. Thank you. * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * This e-mail is the property of Enron Corp. and/or its relevant affiliate and may contain confidential and privileged material for the sole use of the intended recipient (s). Any review, use, distribution or disclosure by others is strictly prohibited. If you are not the intended recipient (or authorized to receive for the recipient), please contact the sender or reply to Enron Corp. at enron.messaging.administration @ enron.com and delete all copies of the message. This e-mail (and any attachments hereto) are not intended to be an offer (or an acceptance) and do not create or evidence a binding and enforceable contract between Enron Corp. (or any o…
```

After:

```text
Barry, Here is the questionnaire I look forward to discussing this next week (Thursday, 8th at 2:00 pm). Bart _________________________ Bart Thedinger *
```
### Example 10: `mailex:dev:watson-k_inbox499:turn_0001`

Removed spans:

- `email_signature` raw chars `[338, 370]`, tokens `[66, 70]`: "Thanks Earl Chanley 505-625-8031"

Before:

```text
PT Can you follow up with the marketing on this? I contacted Mr. Bradly for the locations and vols. Volume 200 mcfd Press may need compression unknowned at this time line TG385 Three well at first for above volume location WCRR BLK 1 SEC 30 Would you let me know if marketing contact Mr. Bradly and if there is anything I can assist with Thanks Earl Chanley 505-625-8031
```

After:

```text
PT Can you follow up with the marketing on this? I contacted Mr. Bradly for the locations and vols. Volume 200 mcfd Press may need compression unknowned at this time line TG385 Three well at first for above volume location WCRR BLK 1 SEC 30 Would you let me know if marketing contact Mr. Bradly and if there is anything I can assist with
```

## Reproduction

```bash
python3 scripts/clean_mailex.py
python3 -m unittest tests/test_clean_emails.py
```
