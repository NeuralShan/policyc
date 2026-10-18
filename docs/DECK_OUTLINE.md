# Deck outline (export to PDF, 12 slides)

Fill the bracketed numbers from the README "Evaluation" table before exporting. Use real screenshots
from the deployed app (home, workspace, fix dialog, trace) rather than mock-ups.

1. **Title.** PolicyC: a compiler and debugger for business procedures. One line: *"Software is
   tested before it ships. The procedures that are running behind banks, factories and hospitals never are."*
   Team, links (live URL, GitHub, video).
2. **The problem.** Procedures are programs executed by people, and they have bugs. Three tiny
   examples: the gap at exactly INR 10,000; the Finance Head who must approve their own claim; a
   safety exception that skips zero-energy verification. Found today by customers, auditors, accidents.
3. **Why existing approaches fail.** Manual review does not scale. Pasting an SOP into a chatbot gives
   an unverifiable, unrepeatable opinion that may hallucinate or miss real defects.
4. **The idea.** Treat the SOP like source code: compile → analyse → test → explain → fix → recompile.
   Pipeline graphic (docs/ARCHITECTURE.md): Lexer (ingest) → Parser (extract) → Linker → Type checker
   (static analysis) → Test suite → Runtime (simulator) → Profiler (reality check) → Diagnostics.
5. **Core principle: "Gemini translates, the engine proves."** Two-column table (Gemini: language →
   model, vision cross-check, explain, patch / Engine: reachability, Z3 coverage and overlap,
   segregation of duties, deadline arithmetic, simulation).
6. **Demo: problems → proof.** Workspace screenshot: document ↔ flowchart ↔ problems; the
   counterexample chip; health ring.
7. **Demo: animated failing trace + Explain & fix.** Trace screenshot and the word-level diff dialog.
8. **Fix → recompile → regression.** "[x] fixed · [0] new · [y] remaining", health [before] → [after].
9. **Trust by construction.** Source quotes verified by string equality; round-trip check; flow
   normaliser that never fixes the SOP and marks what it infers; guards on model output;
   fingerprints so findings are comparable across revisions.
10. **Results.** Planted-bug recall table over nine SOPs ([hits]/[planted] overall; expense [7/7],
    clean control [errors]), tests ([n] passing), solve time, languages incl. Bahasa Indonesia.
    Be candid about the weaker samples and why.
11. **Built on Google.** Gemini API (symbols, structure, flow pass, vision cross-check, explain &
    patch), Firebase Hosting + Firebase Auth (Google sign-in), model-agnostic gateway with caching
    and rate limiting. Architecture diagram with the deployment split.
12. **Impact & roadmap.** Compliance, safety, operations teams across JAPAC; multilingual SOPs; CI for
    policies (compile on every Word/Docs edit); regulation-to-invariant mapping; process mining against
    real case history (the Reality Check layer already exists). Team + links.
