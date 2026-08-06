# Session 1 - generated knowledge graph data

These files are **generated**. Do not edit them by hand - rerun
`../data-prep/build_kg_data.py` instead.

| File | Contents |
|------|----------|
| `kg_nodes.csv` | `id`, `type` (gene / disease / icd10), `name`, `extra` |
| `kg_edges.csv` | `source`, `target`, `type` (associated_with / is_a / maps_to), `weight`, `evidence` |
| `kg_evidence.csv` | `source`, `target`, `datatype`, `weight`, `evidence` - the same gene-disease edges split by *kind* of evidence |
| `icd10_map.csv` | MONDO id to ICD-10 code and label |

## Sources and licences

- **Open Targets Platform** - gene entities, disease entities and ontology
  hierarchy, gene-disease association scores.
  Licensed [CC0 1.0](https://platform-docs.opentargets.org/licence) (public
  domain), so redistribution here is unrestricted.
- **MONDO Disease Ontology** - MONDO to ICD-10 cross references.
  Licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/);
  attribution is given here.

Genes are keyed by **Ensembl gene ID (`ENSG...`)**, matching the identifier space
of the TCGA-BRCA transcriptomics matrix used in Session 2, so gene lists produced
by the multi-omics work can be looked up in this graph directly.
