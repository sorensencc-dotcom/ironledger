# IronLedger rule drift governance specification

- **Document ID**: `IL-GOV-DRIFT-001`
- **Status**: Ratified
- **Domain**: Machine Learning / Rule Categorization Reliability, Drift Detection, and Quality Assurance
- **Enforcement Level**: Invariant / Threshold Policy

---

## 1. Mathematical definition of Hit Confidence Trend (HCT)

Rule drift tracks how reliably a learned categorization rule predicts account assignment over time. As payees change descriptions or transaction behaviors shift, rules may experience accuracy degradation.

For a rule $R$, let:
- $N_{\text{total}}$: Total match opportunities (hits).
- $N_{\text{recent}}$: Hits occurring within the rolling 30-day window.
- $N_{\text{overrides}}$: Instances where an operator manually changed the rule's suggested account.

### Metrics:

1. **Override Rate ($\mathcal{O}_R$)**:
   $$\mathcal{O}_R = \frac{N_{\text{overrides}}}{N_{\text{total}}}$$

2. **Hit Confidence Trend ($\text{HCT}_R$)**:
   $$\text{HCT}_R = \max\Big(0.0, 1.0 - (\mathcal{O}_R \times 1.5) - \text{DecayFactor}(t)\Big)$$

---

## 2. Drift classification thresholds

The system evaluates $\text{HCT}_R$ and $\mathcal{O}_R$ into discrete health tiers:

| Tier | Status | Criteria | Action required |
|---|---|---|---|
| **Tier 1** | `healthy` | $\text{HCT} \ge 0.80$ and $\mathcal{O}_R < 0.05$ | Automated matching and bulk approval allowed. |
| **Tier 2** | `warning` | $0.50 \le \text{HCT} < 0.80$ or $0.05 \le \mathcal{O}_R < 0.15$ | Visual amber alert in Inspector; automated approval disabled. |
| **Tier 3** | `stale` / `critical` | $\text{HCT} < 0.50$ or $\mathcal{O}_R \ge 0.15$ | Rule flagged for operator review/deprecation; exact matching gated. |

---

## 3. UI and automation enforcement

1. **Real-Time Heatmap in Inspector**:
   - The workbench Inspector sidecar (`InspectorSidecar.tsx`) renders a continuous gradient bar representing $\text{HCT}_R$ whenever a transaction matches a rule.

2. **Automated Gating in Compile & Match**:
   - Rules in `warning` or `stale` state are strictly excluded from automated bulk-approval operations.
