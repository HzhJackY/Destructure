# Module Owner Registry

| Domain | Formal owner | Allowed responsibility | Forbidden responsibility |
|---|---|---|---|
| Filing identity | Filing Registry | PDF identity, SHA, metadata | Values, members, Capture |
| Discovery | Discovery Service | Bounded candidates/evidence | Certification, final amounts |
| OCR | Conditional OCR Service | Tokens, bbox, topology, cache | Certified amounts |
| Family resolution | Statement Family Resolver | Parent/member/regime | Whole-table extraction |
| Child targeting | Certified Child Link Service | Persistent targets | Final table values |
| Capture | Capture Orchestrator / Library | Whole-table evidence | Research Merge |
| Review | Review Service | Human decision records | Machine evidence overwrite |
| State | CaptureDecisionReducer | Final status derivation | PDF parsing |
| Canonical | Canonical Materializer | Normalized observations | PDF reparsing |
| Merge | Merge Service | Aggregation/conflict policy | OCR/Discovery |
| User export | UserResearchWorkbookExporter | Readable workbook | State mutation |

Compatibility adapters must remain thin and may not own business logic.
