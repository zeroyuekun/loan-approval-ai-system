# Senior Engineer / Hiring Manager Portfolio Signals — Research Report

**Retrieval date:** 2026-04-15
**Scope:** What senior software engineers, engineering managers, and recruiters actually weight when reviewing a candidate's portfolio repo on GitHub in 2024–2026.
**Tooling constraint:** `WebFetch` was denied in this sandbox, so all evidence below is drawn from `WebSearch` result snippets and summaries. Where a snippet paraphrases a source, claims are marked accordingly.

---

## 1. What senior engineers actually evaluate

**Time budget is brutally short.** Multiple 2025–2026 sources converge on a 45–90 second first scan. "Recruiters spend an average of 90 seconds scanning your GitHub, and a recruiter may dismiss impressive technical projects in 45 seconds if the purpose and value aren't clearly communicated." (https://www.kula.ai/blog/github-beginners-guide-source-candidates, retrieved 2026-04-15). Similar 90-second figure at https://medium.com/@kanhaaggarwal/as-a-hiring-manager-here-are-the-3-things-i-actually-look-for-on-your-github-eb73594d1558 (retrieved 2026-04-15).

**Senior reviewers look for architectural thinking, not feature count.** "Senior engineers leave distinct traces on GitHub by making architectural decisions that show up as large-scale refactors or new system designs, writing more deletion commits (experienced engineers simplify), … and having commit messages that reference design trade-offs, not just what changed." (https://riem.ai/blog/github-recruiting-guide, retrieved 2026-04-15).

**3–5 deep projects beat 20 shallow ones.** "Deep, thoughtful contributions matter more than rapid-fire commits, and 3-5 well-documented, complete projects are better than 20 incomplete ones." (https://www.reczee.com/blog/evaluating-github-profiles-a-recruiters-guide, retrieved 2026-04-15). Echoed at https://cyberpath.net/how-to-build-github-portfolio-that-gets-you-hired-2025/ (retrieved 2026-04-15).

**Dissenting note — GitHub is often just a tiebreaker.** Ben Frederickson's widely cited piece argues GitHub activity is a weak hiring signal because most working engineers' work is private (https://www.benfrederickson.com/github-wont-help-with-hiring/, retrieved 2026-04-15) [stale: 2018, but still re-referenced in 2024–2026 discussions]. Reinforced in community threads: "some senior engineers report only looking at GitHub projects as a tiebreaker or when a project was mentioned in the resume." (https://www.freecodecamp.org/news/i-reviewed-fifty-portfolios-on-reddit-and-this-is-what-i-learned-e5d2b43150bc/, retrieved 2026-04-15).

**Candidate-specific note:** If the repo is the PRIMARY evidence (no current employer, job-seeking), it gets scrutinised harder. Frederickson's caveat doesn't apply to your situation.

---

## 2. Specific signals that swing decisions

### Signals that HELP

- **README that states the problem and shows the outcome before the stack.** "Always include a README.md that explains your decisions, known limitations, and what you'd improve with more time. It's often the difference between yes and no." (https://dev.to/profydev/this-survey-among-60-hiring-managers-reveals-don-t-waste-your-time-on-a-react-portfolio-website-17ge, retrieved 2026-04-15).
- **Live demo / deployed link.** "A live link beats a GitHub repo for most recruiters." (https://docs.bswen.com/blog/2026-03-29-github-portfolio-hiring-help/, retrieved 2026-04-15). "Even a small AWS/GCP/Azure deployment signals production readiness." (https://medium.com/@santosh.rout.cr7/ml-engineer-portfolio-projects-that-will-get-you-hired-in-2025-98df2b04478f, retrieved 2026-04-15).
- **Meaningful tests.** "Even a small test suite signals you think like a professional." (https://www.reczee.com/blog/what-do-hiring-managers-see-on-my-github-profile, retrieved 2026-04-15).
- **Descriptive commit messages.** "Descriptive commit messages like 'feat: Add user login' are much better than vague ones like 'fixed stuff', signaling a developer's professionalism and attention to detail." (https://medium.com/@kanhaaggarwal/as-a-hiring-manager-here-are-the-3-things-i-actually-look-for-on-your-github-eb73594d1558, retrieved 2026-04-15). Compass/Ben Hoyt: commit message quality is a senior-engineer habit (https://medium.com/compass-true-north/writing-good-commit-messages-fc33af9d6321, retrieved 2026-04-15) [stale: 2017 but referenced frequently].
- **Reproducibility artifacts.** "Reproducibility Essentials include: A Makefile with targets for make data, make train, make test, and make deploy; a .env.example file …; seeded random states everywhere …; and a README.md that lets anyone clone and run your project in three commands." (https://www.interviewnode.com/post/ml-engineer-portfolio-projects-that-will-get-you-hired-in-2025, retrieved 2026-04-15).
- **Secret hygiene.** "Remove any secrets, personal data, or sensitive credentials… never store them in the repo and use .gitignore to protect sensitive data… demonstrates you practice what you preach." (https://cybersecurityjobs.tech/career-advice/portfolio-projects-that-get-you-hired-for-cyber-security-jobs-with-real-github-examples-, retrieved 2026-04-15).
- **Screenshots/GIF in the README.** "A screenshot or demo GIF in your README can immediately show what your UI looks like." (https://medium.com/@kanhaaggarwal/as-a-hiring-manager-here-are-the-3-things-i-actually-look-for-on-your-github-eb73594d1558, retrieved 2026-04-15).

### Signals that HURT

- **Fake contribution graphs.** "Faking the contribution calendar graph with private contributions or dummy commits without relevant content serves as a big red flag." (https://medium.com/@sohail_saifi/i-analyzed-100-tech-lead-portfolios-these-5-projects-are-red-flags-to-recruiters-04d03303d445, retrieved 2026-04-15).
- **Trend-stacking / technology-for-its-own-sake.** "Projects that use excessive trendy technologies (like a content management system with React, Redux, GraphQL, microservices, Kubernetes, Elasticsearch, Kafka, and blockchain) suggest the candidate prioritizes fashionable technologies over selecting the right tool for the job." (https://medium.com/@sohail_saifi/i-analyzed-100-tech-lead-portfolios-these-5-projects-are-red-flags-to-recruiters-04d03303d445, retrieved 2026-04-15).
- **Over-engineering simple problems.** "Almost three-quarters of rejected tech lead candidates had some version of an absurdly over-engineered todo list or note-taking application." (same source).
- **Inactive or job-hunt-only graphs.** "A contribution graph that's only green one week per year, right around job-hunting season, suggests someone who treats GitHub as a portfolio prop rather than a work tool." (https://riem.ai/blog/github-recruiting-guide, retrieved 2026-04-15).
- **Projects that stop at notebook-accuracy.** "Projects that stop at offline accuracy and never reach API/demo stage signals a 'research-only' mindset, not engineering readiness." (https://medium.com/@santosh.rout.cr7/ml-engineer-portfolio-projects-that-will-get-you-hired-in-2025-98df2b04478f, retrieved 2026-04-15).
- **Inconsistent formatting, bad names, god-functions.** "Code that appears to have little thought put into it—inconsistent spacing/tabbing, terrible variable names, or failure to use functions when appropriate—can result in immediate rejection." (https://blog.alishahnovin.com/2023/04/portfolio-red-flags.html, retrieved 2026-04-15) [stale: 2023].
- **A poor profile is worse than none.** "A poor GitHub profile is worse than no GitHub profile at all — when reviewed, most were disqualifying rather than beneficial." (https://www.freecodecamp.org/news/i-reviewed-fifty-portfolios-on-reddit-and-this-is-what-i-learned-e5d2b43150bc/, retrieved 2026-04-15).

---

## 3. What is OVERRATED in candidate mental models

- **Raw test-coverage %.** No source in the 2024–2026 set endorses coverage numbers as a hiring signal. What reviewers repeatedly praise is "a small test suite" that "signals you think like a professional" (reczee.com above). The emphasis is existence + meaningfulness, not percentage. The HROasis 2025 assessments study found "zero correlation between algorithmic puzzle performance and subsequent job success metrics" — suggesting metrics-chasing generally is a poor proxy (https://hroasis.com/technical-assessments-it-recruitment-guide/, retrieved 2026-04-15).
- **Shiny UI / React portfolio websites.** Profy's survey of 60+ hiring managers: "you don't need a personal website to get a job. On the contrary, it can even backfire." (https://profy.dev/article/portfolio-websites-survey, retrieved 2026-04-15) [stale: 2021, but widely cited in 2024–2026 discussions]. README screenshots/GIF are cited as sufficient.
- **Microservices / K8s / event sourcing on small projects.** Explicit red flags in Saifi 2025 and Medium's "Why Over-Engineering Is a Junior Developer Habit" (https://dev.to/lessonsfromproduction/why-over-engineering-is-a-junior-developer-habit-39j0, retrieved 2026-04-15).
- **Huge repo count.** "Thousands of repos but no depth (no stars, no forks, no README files) often indicates auto-generated or tutorial-following activity." (https://riem.ai/blog/github-recruiting-guide, retrieved 2026-04-15).
- **Algorithmic puzzle solutions.** 2025 HROasis study (above) shows zero correlation with on-the-job success.

---

## 4. Domain-specific signals for ML / data / fintech

**For ML / applied scientist roles:**
- Deployed service + quantified business impact + architecture diagram are the "three things" reviewers scan for in <90s (https://medium.com/@santosh.rout.cr7/ml-engineer-portfolio-projects-that-will-get-you-hired-in-2025-98df2b04478f, retrieved 2026-04-15).
- Reproducibility stack: `Makefile`, `.env.example`, seeded RNG, 3-command setup (same source).
- Monitoring + drift: "Compliance-ready ML systems require continuous validation, drift monitoring, thorough documentation, audit trails, stress tests, fallback strategies, and real human oversight." (https://www.index.dev/blog/ai-in-fintech-compliant-ml-talent, retrieved 2026-04-15).
- Reproducibility is now a recognised research and hiring theme — Wiley AI Magazine 2025 review (https://onlinelibrary.wiley.com/doi/10.1002/aaai.70002, retrieved 2026-04-15).

**For fintech specifically:**
- "Regulation-aware ML engineers" are the scarce hybrid profile: "part-coder, part-compliance officer, part-risk manager." (index.dev, above).
- Fraud/credit-scoring projects are flagged as among the most hireable fintech portfolio choices (https://medium.com/@santosh.rout.cr7/ml-engineer-portfolio-projects-that-will-get-you-hired-in-2025-d1f2e20d6c79, retrieved 2026-04-15).
- Supervisors "expect explainability, fairness, and robust governance for AI models—talent with model risk management and AI governance skills is now as valuable as pure modelling expertise." (https://www.harringtonstarr.com/resources/blog/the-fintech-ai-recruitment-gap--why-the-next-wave-of-innovation-depends-on-talent/, retrieved 2026-04-15).
- "Strong grasp of backend, encryption, and regulatory awareness signals key competencies for fintech or healthtech jobs." (https://techotlist.com/blogs/job-search/side-projects-that-impress-hiring-managers, retrieved 2026-04-15).

**Implication for this project:** A model card per ModelVersion, bias-detection agent output, an audit trail, and explicit AU-lending regulatory framing (NCCP — but per project rule, reference NCCP only in docs/ADRs, never in denial emails) are exactly the scarce signals fintech reviewers describe.

---

## 5. AU / APAC market signals

Direct AU-specific material on portfolio review was thin. What surfaced:

- Nucamp 2025 Australia guide emphasises Python, cloud (AWS/Azure), Kubernetes, AI agents, and emphasises "soft skills… emotional intelligence and adaptability" (https://www.nucamp.co/blog/coding-bootcamp-australia-aus-getting-a-job-in-tech-in-australia-in-2025-the-complete-guide, retrieved 2026-04-15).
- SEEK profiles let you attach GitHub/portfolio; having it is table-stakes in Australia ("GitHub or Behance profiles linked through SEEK increase credibility") (https://australiajobly.com/seek-jobs-sydney/, retrieved 2026-04-15).
- FinTech Australia runs a dedicated board (https://jobs.fintechaustralia.org.au/jobs, retrieved 2026-04-15) — AU-fintech tribe is small enough that a compliance-literate loan-approval repo will stand out.
- No AU-specific evidence that signals differ meaningfully from global norms. **Treat global signals as authoritative and layer AU-lending domain framing on top.**

---

## 6. Validating the candidate's prior claims (the 10 hypotheses)

| # | Prior claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Tests that document invariants, not coverage % | **Holds** | Sources praise test existence + meaningfulness; none praise coverage %. (reczee, HROasis) |
| 2 | Visible reasoning trail (docs, ADRs, model cards, specs) | **Holds strongly** | ADRs are endorsed by AWS, Microsoft, Fowler, Joel Parker Henderson. Reviewers specifically scan for "architectural decisions" and "design trade-offs." (riem.ai, adr.github.io, learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record) |
| 3 | README opens with problem, not stack | **Holds, with nuance** | Strong README is universally cited, but tech stack + setup steps + screenshots are also expected. Problem-first framing is one good pattern; it is not uniformly required. (profy, medium/kanhaaggarwal) |
| 4 | One compelling demo loop (<60s) | **Holds** | "45-second" dismissal window, GIF/screenshot in README, live demo link all cited as high-leverage. (kula.ai, kanhaaggarwal) |
| 5 | Observability on show (structured logs, health endpoint, dashboard) | **Holds for ML/fintech specifically** | Drift monitoring, audit trails, continuous validation are named. For generalist SWE roles the evidence is weaker — it is ML/fintech-specific. (index.dev) |
| 6 | Model card per ModelVersion | **Holds for ML roles** | Explainability + governance + documentation are named as scarce fintech-ML competencies. (harringtonstarr, index.dev) |
| 7 | Clean CI badge | **Partially holds** | CI badges are mentioned as quality indicators but no source treats the badge itself as decisive. The underlying fact (CI exists and passes) matters; the badge is decoration. (github.com/marketplace/actions/ci-badges) |
| 8 | Commit history that reads like a story | **Holds** | Descriptive commits, deletion commits, trade-off references all named by senior reviewers. (riem.ai, kanhaaggarwal, hoyt) |
| 9 | Domain-specific thinking (AU lending) | **Holds** | Fintech reviewers specifically look for regulation-aware engineers. AU framing differentiates among a very small pool. (index.dev, harringtonstarr) |
| 10 | Things that DON'T matter: shiny UI, 100% coverage, microservices, K8s | **Holds, mostly** | Shiny UI: supported (profy, 60 hiring managers). 100% coverage: supported. Microservices: strongly supported as RED FLAG on small projects (saifi, dev.to/lessonsfromproduction). K8s: same. Caveat — a modest UI that acts as the demo loop still helps; "no UI at all" is NOT what sources recommend. |

**Summary of corrections to your ranking:**

- Claim #7 ("clean CI badge") is **over-weighted** — downgrade. The badge is decoration; what matters is that CI actually runs and tests actually pass. Spend effort on meaningful tests (#1), not on polishing badge layout.
- Claim #3 ("README opens with problem, not stack") is **right in spirit but too prescriptive** — sources describe a README that covers problem, decisions, limitations, setup, and a demo GIF. Problem-first is one good structure among several. Don't over-optimise on headline order.
- Claim #10 says "shiny UI … doesn't matter." **Adjust:** a demo GIF/screenshot of the UI matters a lot. What doesn't matter is React boilerplate, landing-page animations, design-system flex. The distinction is demo-loop utility vs decoration.
- Everything else holds. Ranking #1 (tests-as-invariants), #2 (reasoning trail), #4 (demo loop), #6 (model card), #8 (commit story), #9 (AU domain) are all strongly supported.

---

## 7. Contradictions / dissenting views

- **GitHub helps vs. GitHub is mostly irrelevant.** Frederickson (https://www.benfrederickson.com/github-wont-help-with-hiring/, retrieved 2026-04-15) [stale: 2018] argues employed engineers' real work is private, so GitHub is a poor filter. Riem.ai, Reczee, Kula (all 2025–2026) argue the opposite: GitHub is a primary screen, particularly for candidates without recent employer signal. **Resolution:** Frederickson applies to senior candidates with strong résumés; for job-seeking junior-to-mid, GitHub is load-bearing.
- **Portfolio websites: waste of time vs. credibility boost.** Profy survey (https://profy.dev/article/portfolio-websites-survey, retrieved 2026-04-15) says backfire risk; Australian SEEK guidance says linked portfolio "increases credibility." **Resolution:** A plain portfolio *website* is low-ROI. The portfolio *repo* is high-ROI. Don't build a site; polish the repo.
- **Side projects: huge plus vs. "that's cool."** HN Ask threads (https://news.ycombinator.com/item?id=14420802, https://news.ycombinator.com/item?id=29108881, retrieved 2026-04-15) show range from "doesn't move the needle" to "got me hired." **Resolution:** Generic CRUD/todo side-project = noise. Domain-specific, deployed, instrumented project = differentiator. Your loan-approval repo is in the second bucket if the ML/fintech signals are actually visible.
- **Microservices: red flag vs. "portfolio using microservices" is a respectable learning exercise** (https://valeriia-protsko.medium.com/my-journey-of-building-a-portfolio-using-microservices-and-solid-architecture-part-1-728d5e6f25b9, retrieved 2026-04-15) [stale: unclear date]. **Resolution:** Microservices as a *learning artefact* labelled as such is fine; microservices as the default architecture for a CRUD app is a red flag. Your monolithic Django + Celery worker split is defensible and should be justified in an ADR.
- **Is AU market different? Evidence is thin.** No AU source contradicts global signals. Treat this as "no dissent found, so assume parity."

---

*End of report.*
