# Template: Technical Concept

Use this template for pages explaining a method, algorithm, theory, or technical concept.

---

## Notion Structure

```
# [Project] — [Concept Name]

[/callout — grey, ℹ️]
Prerequisites: [what the reader should understand first]
Related: → [Page 1] | → [Page 2] | → [Page 3]
[/end callout]

---

## The Problem

1–2 paragraphs. What limitation or challenge motivates this concept.
Use specific numbers and concrete examples, not abstractions.

---

## The Insight

1 paragraph. The core idea in plain language before any math.
If you can explain it in one sentence, do so.

---

## Formulation

The rigorous definition. Use /equation blocks for all math.

[/equation block]
$$[core equation]$$
[/equation]

Where:
- $[variable]$ = [meaning]
- $[variable]$ = [meaning]

[/toggle: "Full derivation"]
  Step-by-step derivation from first principles.
  Every step gets its own equation block.
[/end toggle]

---

## Why It Matters

Practical impact. Performance numbers, accuracy improvements,
what this enables that wasn't possible before.

[Comparison table if applicable]
| Property | Without [concept] | With [concept] |
|----------|-------------------|----------------|
| ... | ... | ... |

---

## Implementation

Brief reference to how this is implemented in the codebase.
File paths, class names, function names. Link to relevant code.

[/toggle: "Code walkthrough"]
  Key code snippets or architectural description of the implementation.
[/end toggle]

---

## References

- [Author, Title, Year — link if available]
- [Related Notion pages]
```
