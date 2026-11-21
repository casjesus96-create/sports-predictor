# NHL historical data source review

**Review date:** 2026-11-21  
**Status:** No external historical dataset approved for ingestion  
**Scope:** Rights/provenance gate for the NHL archive; this is an engineering assessment, not legal advice.

## Decision

Do not bulk-import NHL schedule, score, boxscore, player, goalie, or play-by-play data into Supabase from the sources below until the rights holder or an authorized provider grants clear permission for the intended storage, transformation, and use.

The existence of a public endpoint, downloadable file, repository, or permissive software license is not by itself proof that the underlying NHL data may be copied into a persistent database.

## Candidate review

| Candidate | What the public documentation establishes | Current decision |
|---|---|---|
| NHL official website/API | NHL Terms of Service, last updated 2025-10-29, define NHL Content and restrict copying, distribution, modification, derivative works, and entering NHL Content into a database unless authorized in writing or permitted by applicable law. | **Blocked** for automated bulk collection and persistent archive until written permission or a documented legal basis is obtained. |
| NHLData R package | CRAN lists package version 1.0.0, published 2017-03-08, with a CC0 package license. Its reference manual identifies Hockey-Reference as the source for season score datasets. | **Not approved yet.** CC0 on the package does not independently establish that the packager had authority to waive rights in the upstream source/compilation. Verify the exact packaged seasons, provenance, and upstream reuse terms before any ingestion. |
| SportsDataverse / fastRhockey NHL datasets | The data pipeline describes raw NHL JSON as scraped from NHL API endpoints. The companion repository has an MIT license for its software/repository materials. | **Blocked pending upstream clearance.** MIT on the repository does not resolve NHL upstream data rights or override NHL terms. Do not treat this as a safe alternate source. |
| Hockey Summary Project / historical hockey summaries | A public site citing these records states that the information was obtained free of charge but is copyrighted by The Hockey Summary Project. | **Not approved.** No permission for redistribution or persistent database ingestion has been established. |

## Required evidence before approving a source

A source can move to reviewed only when the project has retained evidence for all applicable items:

1. Identity of the data publisher and the original upstream data owner.
2. Exact dataset/release/version and covered seasons/fields.
3. License or written authorization that covers copying, persistent database storage, transformation, derived statistics, and the project's intended deployment/use.
4. Attribution and notice requirements, including any share-alike or non-commercial restrictions.
5. Whether the source may be refreshed automatically and whether redistribution to application users is allowed.
6. A reproducible sample validation against an independent permitted reference, with missing games, duplicate IDs, score conflicts, and team identity reviewed.
7. Recorded approval by a project maintainer before setting archive provenance to source_terms_status=reviewed.

A software license applies to the software it licenses; do not infer that it automatically licenses data from an upstream league, website, or third party.

## Safe engineering posture while rights remain unresolved

- Keep the NHL archive schema and source-neutral validators; do not populate them from blocked sources.
- Keep the existing NHL public feed integration limited to the current application behavior; do not extend it into a bulk historical importer or persistent archive.
- Do not schedule scraping, bulk API collection, or automated ingestion from NHL endpoints.
- Do not mark records training-eligible based only on technical validity. Provenance and terms approval are separate requirements.
- Continue source-independent work: season/team identity validation, archive integrity tests, model design documents, and synthetic test fixtures clearly labeled as synthetic.
- Do not train or publish an official NHL predictive model until a sufficiently broad, permitted historical dataset and an auditable pregame feature pipeline are available.

## Primary references

- NHL Terms of Service (last updated 2025-10-29): https://www.nhl.com/info/terms-of-service
- CRAN NHLData package metadata (CC0 package license; published 2017-03-08): https://cran.rstudio.com/web/packages/NHLData/
- NHLData reference manual (describes Hockey-Reference as the source): https://mirror.vtti.vt.edu/cran/web/packages/NHLData/refman/NHLData.html
- fastRhockey NHL raw repository (describes raw NHL JSON as scraped from NHL API): https://github.com/sportsdataverse/fastRhockey-nhl-raw
- fastRhockey NHL data repository license (MIT): https://github.com/sportsdataverse/fastRhockey-nhl-data/blob/main/LICENSE.md
- Hockey Summary Project attribution/copyright statement: https://yesterscore.com/references

---

**Reassessment rule:** Revisit this review only when new permission, a source-specific data license, or reliable provenance evidence is available. Do not infer approval from a repository badge or a successful download.
