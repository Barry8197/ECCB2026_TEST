# The story of Session 1

*A one-page narrative of what we do and why. For the detail, see the notebooks.*

## What we want to understand

We want to understand what a biological network is, what a **knowledge graph** is,
and — the part people usually skip — how the two differ. A co-expression network is
*computed* from measurements: correlate every gene against every other gene and keep
what clears a threshold. A knowledge graph is *read out of recorded facts*: somebody
looked at the evidence and wrote down that this gene is implicated in that disease.
They look identical when drawn and they fail in opposite ways, so telling them apart
is the first thing worth learning.

## How we do it

We build a real knowledge graph rather than a toy one. We download two public,
redistributable sources — [Open Targets](https://platform.opentargets.org/) (CC0)
for genes, diseases and gene–disease association scores, and the
[MONDO Disease Ontology](https://mondo.monarchinitiative.org/) (CC BY 4.0) for the
disease hierarchy and for cross-references out to clinical ICD-10 codes — and cut
them down to a breast-cancer-focused subset small enough to read by eye:
**881 nodes** (760 genes, 90 diseases, 31 ICD-10 codes) and **1,768 edges**.

Around breast cancer and its subtypes we add **24 comparison diseases** — other
cancers, autoimmune and inflammatory conditions, neurological and cardiometabolic
disease — so that "which diseases resemble each other?" has a real answer rather
than one big breast-cancer blob.

We then build the graph in NetworkX, with **typed nodes** (gene, disease, ICD-10),
**typed edges** (`associated_with`, `is_a`, `maps_to`) and, crucially, **provenance**:
a separate table splitting every gene–disease edge by the *kind* of evidence
behind it.

## What we connect to what

Two joins do the work.

We connect **clinical vocabulary to molecular vocabulary**, by walking from an
ICD-10 code that a hospital would actually bill, through the MONDO disease
hierarchy, down to genes.

And we connect **the knowledge graph to the omics data** from Session 2. This is why
genes are keyed by Ensembl ID: it is the same identifier space as the TCGA-BRCA
transcriptomics matrix, so a gene list coming out of the multi-omics work can be
looked up in the graph directly.

## What we get out of it

**Breast and ovarian cancer share BRCA1, BRCA2 and BRIP1.** We never told the graph
these two diseases were related — we asked which genes they had in common and
hereditary breast-ovarian cancer syndrome fell out of the structure.

**But they also "share" tubulins.** TUBB, TUBA1B and the topoisomerases show up in
exactly the same list, not because of shared biology but because both cancers are
treated with taxanes and anthracyclines. The overall association score cannot tell
the two apart. Splitting by evidence type can: filter to genetic and somatic
evidence and every tubulin disappears, leaving the real hereditary genes. The
advantage of carrying provenance is that we can ask *what kind of claim is this*,
not just *how strong is it*.

**The diseases group themselves.** Running community detection on shared causal
genes alone recovers the clinical taxonomy — a cancer community, an
autoimmune/inflammatory community, a metabolic one — without ever being told those
categories exist. Structure nobody encoded turns out to be recoverable from
structure somebody did.

**And the gaps teach as much as the findings.** Only 19 of 90 diseases carry an
ICD-10 code, because ICD-10 subdivides breast cancer *anatomically* and has no code
for "triple-negative" — climbing the ontology recovers 82 of 90. Basal-like breast
carcinoma has zero genes, because the evidence was filed under a near-synonym.
Joining the omics matrix without stripping the Ensembl version suffix matches
*nothing at all*.

None of those are bugs. They are what working with real biomedical knowledge is
like, and recognising them is the skill.

## Where it goes next

Sessions 3 and 4 build LLM agents that plan traversals over graphs like this one
and query them from multi-omics profiles. Everything above — the coverage gaps, the
inherited codes, the technically-correct-but-misleading edges — is what those agents
have to get right, and what we need in order to check them.
