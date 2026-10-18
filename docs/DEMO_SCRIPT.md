# 3-minute demo video script

Record at 1080p, browser zoom 110-125%, dark or light theme (light reads better on video). Use the
**precomputed samples** so nothing waits on a model. Keep the cursor slow. Add captions.
Before recording: open the deployed URL once so the engine is awake, sign in with Google, and click
through the Expense sample so everything is cached in the browser.

| Time | Screen | Say (about) |
|---|---|---|
| 0:00-0:15 | Home page hero | "Software is compiled and tested before it ships. The procedures that are running behind banks, factories and hospitals never are. PolicyC compiles them." |
| 0:15-0:35 | Click **Try it** on *Employee Expense Reimbursement* → workspace opens: document on the left, flowchart in the middle, problems at the bottom, health ring top-left | "Gemini reads the policy PDF into a process model. Every box cites the clause it came from. A deterministic engine, not the model, then tests it." |
| 0:35-1:10 | Click the **Missing branch** problem. Clause 4.1 highlights, the decision node pulses, counterexample chip reads `amount = 10000, requester_role = other` | "Claims below ten thousand and above ten thousand: what about exactly ten thousand? The solver found the gap and proved it with a failing case." |
| 1:10-1:30 | Click the **No eligible approver** problem → **Show trace**: the dot walks to *Approve own claims* and stops red | "The Finance Head approves their own claims, but nobody may approve their own claim. Their claim can never be completed. Every finding is a proof, not an AI opinion." |
| 1:30-2:05 | **Explain & fix** on the gap: plain explanation, diff "below" → "up to and including", **Accept → Apply & recompile**; regression toast "x fixed · 0 new · y remaining"; health ring rises | "Gemini explains the bug and proposes a minimal rewrite. Accept it, and everything recompiles and re-tests, like CI for policies." |
| 2:05-2:25 | Home → *Lockout/Tagout* → the **Mandatory step bypassed** problem; trace shows maintenance reached without verifying zero energy | "It works on any procedure. Here an exception clause lets a worker skip verifying zero energy: the kind of bug that causes accidents." |
| 2:25-2:45 | Flip to *Savings account* in Bahasa sample or the **How it works** page | "Nine sample procedures across banking, safety, HR and IT, including one in Bahasa Indonesia. Gemini translates, the engine proves." |
| 2:45-3:00 | End card: URL, GitHub, "PolicyC: test your procedures before reality does" | |

## Backup lines for judges' questions

* **"Why not just paste the SOP into Gemini?"** A chat answer is an unverifiable opinion. Ours is a
  reproducible witness (a counterexample, a path, a sum) that you can re-run after the document
  changes, with a regression diff.
* **"Does Gemini decide what is a bug?"** Never. It translates language into a model and explains
  proven findings. Findings come from graph search, the Z3 solver and a simulator.
* **"What if Gemini misreads the clause?"** Every element carries a source quote that is checked by
  string equality, the extraction is round-trip checked, and everything the normaliser infers is
  shown dashed as *inferred*.
* **"Can it fix things?"** It proposes a minimal clause rewrite, validated against the document text,
  and shows a fixed / new / remaining diff after recompiling.
