"""Phase 7.5 hybrid NLP refinement: conservative, rule-based post-processing and recovery around the neural entity model.

Nothing here trains or modifies a model. Every stage is individually switchable (RefineConfig), keeps the raw neural output, and labels
what it produced (`origin`: neural | refined | rule) so that neural-only, refined and hybrid runs can be compared."""
