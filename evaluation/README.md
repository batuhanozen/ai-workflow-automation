# Synthetic evaluation

`requests.json` contains 18 synthetic English support requests labeled by category and priority. No personal, patient, or confidential source data is included. `mock-results.json` is a real output of the offline evaluation script, not a projected LLM score.

Run `python -m scripts.evaluate` from the repository root. This defaults to the mock even if `.env` enables the live provider. `--live` is the explicit opt-in to potentially paid provider calls.

The four metrics use the full dataset denominator. A fallback counts as incorrect for category and priority and unsuccessful for processing. Schema validity is recorded before business-rule validation so the report can distinguish format success from policy success. The report retains per-case expectations and outputs to make misses inspectable.

Limitations: this is a tiny smoke dataset, not a statistically representative benchmark. Labels involve judgment. Basic cases overlap the mock's keyword vocabulary, so high scores do not demonstrate generalization. The deliberately included token/warehouse paraphrases and resolved-incident example reveal current mock limitations. Schema-success measurements reflect a provider contract, not factual correctness or reliable confidence calibration.

A next evaluation should use independently authored and held-out cases, more classes and severity edge cases, injection and negation attacks, multilingual text, multiple runs for live models, per-class recall, severity-weighted error costs, and confidence calibration. Keep sensitive production data out of the repository.
