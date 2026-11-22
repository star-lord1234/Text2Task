# Architecture Diagrams for plan_model.md

One diagram for every design in the plan, so you can choose. **Nothing here is built yet.**

Contents:

0. Overall plan with gates
1. Phase 1: label building
2. Evaluation (Phase 0.2 and 2.1)
3. TASK Option A: token tagging (default)
4. TASK Option B: sentence classifier plus span extraction
5. TASK Option C: sentence-level TASK only
6. TASK Option D: generative extraction
7. Phase 4: model and training refinements
8. PERSON and TEMPORAL branch (used by A, B and C)

---

## 0. Overall plan with gates

```mermaid
flowchart TD
    P0["Phase 0: Decisions and baseline<br/>TASK definition, metrics, targets"]
    G0{"Gate 0:<br/>agreed in writing?"}
    P1["Phase 1: Better labels<br/>map MailEx human labels"]
    G1{"Gate 1:<br/>sample check at least 80% acceptable?"}
    P2["Phase 2: Lenient metrics plus<br/>retrain same tagger on full data"]
    G2{"Gate 2:<br/>TASK lenient F1 meets target?"}
    P3["Phase 3: Change TASK modeling<br/>Option B or C"]
    G3{"Gate 3:<br/>at least +0.10 TASK F1 over Phase 2?"}
    P4["Phase 4: Refinements<br/>cased model, CRF, 3 seeds"]
    G4{"Gate 4:<br/>beats Phase 2 across seeds?"}
    P5["Phase 5: Final test run, once"]

    P0 --> G0
    G0 -- yes --> P1
    G0 -- no --> P0
    P1 --> G1
    G1 -- yes --> P2
    G1 -- no --> P1
    P2 --> G2
    G2 -- "yes, skip Phase 3" --> P4
    G2 -- "PERSON and TEMPORAL fine, TASK low" --> P3
    G2 -- "everything low" --> P1
    P3 --> G3
    G3 -- yes --> P4
    G3 -- "no, revert to Option A" --> P4
    P4 --> G4
    G4 -- yes --> P5
    G4 -- no --> P4
```

---

## 1. Phase 1: label building

```mermaid
flowchart LR
    subgraph SRC["Sources"]
        MX["MailEx human events<br/>data/unified/*.jsonl<br/>original_events"]
        HDR["Email headers<br/>sender, recipients"]
        S2["SILVER-v2 spans<br/>PERSON, TEMPORAL"]
    end

    MX --> MAP["Deterministic mapping<br/>Action in Request and commitment events -> TASK<br/>rule set depends on decision 0.1"]
    MAP --> CHK{"Hand check<br/>40 random emails"}
    CHK -- "under 80% acceptable" --> MAP
    CHK -- "ok" --> TASKL["TASK labels<br/>provenance: human-derived"]

    HDR --> PERL["PERSON labels<br/>provenance: SILVER"]
    S2 --> PERL
    S2 --> TEML["TEMPORAL labels<br/>date and time rules plus SILVER<br/>provenance: SILVER"]

    TASKL --> MERGE["Merge into one BIO layer<br/>overlap rule: shortest span wins,<br/>ties prefer PERSON, TEMPORAL, TASK"]
    PERL --> MERGE
    TEML --> MERGE

    MERGE --> SPLIT["Rebuild splits<br/>same definition in train, validation, test<br/>no thread overlap"]
    SPLIT --> TR[("train")]
    SPLIT --> VA[("validation")]
    SPLIT --> TE[("test<br/>untouched until Phase 5")]
```

---

## 2. Evaluation

```mermaid
flowchart LR
    PRED["Model predictions<br/>BIO tags"] --> DEC["Decode to spans"]
    REF["Reference labels"] --> DEC2["Decode to spans"]
    DEC --> STRICT["Strict F1<br/>exact boundaries and type"]
    DEC2 --> STRICT
    DEC --> LEN["Lenient F1<br/>same type, at least 50% overlap"]
    DEC2 --> LEN
    PRED --> TOK["Token-level F1<br/>per entity type"]
    REF --> TOK
    STRICT --> REP["Report per type<br/>PERSON, TEMPORAL, TASK<br/>plus label provenance"]
    LEN --> REP
    TOK --> REP
    REP --> BASE["Compare with Phase 0 baseline<br/>F1 0.1270 strict"]
```

---

## 3. TASK Option A: token tagging (default, no change in design)

```mermaid
flowchart LR
    EM["Email text"] --> TK["Tokenizer<br/>WordPieces, windows if needed"]
    TK --> ENC["Encoder<br/>DistilBERT, later cased model"]
    ENC --> HEAD["Token classification head<br/>7 labels:<br/>O, B and I for TASK, PERSON, TEMPORAL"]
    HEAD --> DEC["BIO decoding"]
    DEC --> OUT["Spans: TASK, PERSON, TEMPORAL"]
```

Trade-off: one model and no new code. TASK may plateau because meaning, not word shape, decides it.

---

## 4. TASK Option B: sentence classifier plus span extraction

```mermaid
flowchart TD
    EM["Email text"] --> SS["Sentence splitter"]
    SS --> CLS["Sentence classifier<br/>actionable or not<br/>trained on sentence labels from Phase 1"]
    CLS -- "actionable" --> SPAN["Span tagger for TASK<br/>runs only inside actionable sentences"]
    CLS -- "not actionable" --> NONE["No TASK from this sentence"]
    SPAN --> TASKOUT["TASK spans"]

    EM --> PT["PERSON and TEMPORAL tagger<br/>runs over the whole email"]
    PT --> PTOUT["PERSON and TEMPORAL spans"]

    TASKOUT --> MRG["Merge and resolve overlaps"]
    PTOUT --> MRG
    NONE -.-> MRG
    MRG --> OUT["Final spans"]
```

Trade-off: better at request vs past event, fewer false spans. Two or three models to train and keep consistent. An error in the classifier is passed on to the span tagger.

---

## 5. TASK Option C: sentence-level TASK only

```mermaid
flowchart TD
    EM["Email text"] --> SS["Sentence splitter"]
    SS --> CLS["Sentence classifier<br/>actionable or not"]
    CLS -- "actionable" --> TS["TASK = the whole sentence<br/>no boundary prediction"]
    CLS -- "not actionable" --> NONE["No TASK"]

    EM --> PT["PERSON and TEMPORAL tagger"]
    PT --> PTOUT["PERSON and TEMPORAL spans"]

    TS --> LINK["Attach spans found inside the sentence<br/>to that task"]
    PTOUT --> LINK
    LINK --> OUT["Task records:<br/>sentence plus people plus times"]
```

Trade-off: removes the boundary problem and is the simplest to evaluate, but TASK output is coarser. Downstream code must accept sentences, not exact spans.

---

## 6. TASK Option D: generative extraction (not recommended now)

```mermaid
flowchart TD
    EM["Email text"] --> PROMPT["Prompt with schema and examples"]
    PROMPT --> GEN["Generator<br/>LLM or fine-tuned seq2seq"]
    GEN --> JSON["JSON: tasks, people, times"]
    JSON --> VAL{"Schema valid?"}
    VAL -- no --> RETRY["Retry or drop"]
    RETRY --> GEN
    VAL -- yes --> ALIGN["Align strings back to text offsets"]
    ALIGN -- "no exact match" --> DROP["Drop span"]
    ALIGN -- "match" --> OUT["Spans with offsets"]
```

Trade-off: flexible, but the earlier local run took over 4 hours for 44 valid records, and invalid or unaligned outputs are common. Hardest to evaluate.

---

## 7. Phase 4: model and training refinements

```mermaid
flowchart TD
    DATA[("Phase 1 data")] --> BASE["Phase 2 configuration<br/>DistilBERT, 10 to 15 epochs, warmup 0.1,<br/>lr 3e-5 or 5e-5"]

    BASE --> ENC{"Encoder choice"}
    ENC --> E1["distilbert-base-uncased<br/>current"]
    ENC --> E2["roberta-base<br/>cased"]
    ENC --> E3["deberta-v3-base<br/>cased"]

    E1 --> DECODE{"Decoding and loss"}
    E2 --> DECODE
    E3 --> DECODE
    DECODE --> D1["Plain softmax<br/>no class weights"]
    DECODE --> D2["Mild class weights<br/>only if B labels collapse"]
    DECODE --> D3["CRF layer<br/>valid BIO transitions"]

    D1 --> SEEDS["3 seeds per configuration"]
    D2 --> SEEDS
    D3 --> SEEDS
    SEEDS --> PICK["Pick by mean lenient F1<br/>and spread, not best single seed"]
    PICK --> FREEZE["Freeze configuration for Phase 5"]
```

---

## 8. PERSON and TEMPORAL branch

Used by Options A, B and C.

```mermaid
flowchart LR
    EM["Email text"] --> TAG["Token tagger<br/>PERSON and TEMPORAL"]
    HDR["Headers:<br/>sender and recipients"] --> NAMES["Known names list"]
    EM --> RULES["Date and time rules"]

    TAG --> COMB["Combine candidates"]
    NAMES --> COMB
    RULES --> COMB
    COMB --> OUT["PERSON and TEMPORAL spans"]
```

The rules and header lookup are optional helpers. Keep them only if they improve lenient F1 in Phase 2 or 4.
