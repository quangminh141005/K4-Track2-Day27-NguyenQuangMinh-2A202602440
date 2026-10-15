# Reflection

**Which fault types were hardest to catch, and why?**

Small numeric deviations were hardest: volume and amount shifts, runtime changes,
feature skew, and embedding/corpus changes can overlap clean-stream variance.
Published limits describe three-sigma clean bounds, so a real fault can remain
inside them. I kept the calibrated bounds and added a conservative online
median/MAD upper-tail check after 20 observations, with a scale floor and bounded
history. Static outliers are excluded from that history to reduce contamination.
This still needs enough observations and can miss subtle faults during warm-up.

Missing upstream edges were also tricky: an incomplete graph can still have
nonempty upstreams. The defense compares declared expectations when available;
otherwise it learns the most frequent previously observed topology and flags a
strict subset after three matching observations. Multiple legitimate topologies
within the same scope can confuse this fallback, and early faults can contaminate
it. Schema/type violations and orphaned outputs have more direct signals.

Practice caught 33/33 faults with no false positives (score 50.00, cost 180/220).
Public scored 43.84 with TPR 0.9231, FPR 0.0165, and cost 240/220; all four pillars
were rated high. The frozen defense's private attempt scored 31.48 with TPR
0.6296, FPR 0, and no budget overage. I did not retune against private feedback.
The lower catch rate shows that conservative bounds do not cover every subtle
fault; zero false positives alone is not sufficient.

**What would you change about your cost/coverage tradeoff, if you had another pass?**

Each handler uses exactly one paid call; no redundant inspections or look-ahead
are needed. I accepted the public budget penalty to retain coverage because
uninspected events have no reliable numeric evidence. With another pass I would
validate a more sensitive, two-sided robust detector for volume/amount and
combine moderate deviations across related metrics. I would calibrate the
false-positive tradeoff on independent clean observations, keep topology models
scoped to stable transform identities, and compare full inspection against a
budget-aware sampling policy before adopting it. Sampling saves credits but
necessarily loses some observable faults; it should earn its place through
measured score improvements rather than an arbitrary hard spending cap.
