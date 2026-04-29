# Applications Log

## FDJ UNITED

- Role: Senior DevOps Engineer
- JD file: [input_job_descriptions/sample_jd.txt](/Users/dtrid8/development/resume_updator/input_job_descriptions/sample_jd.txt)
- Outcome: Rejected
- Response: Standard rejection email with no specific feedback

### Likely Resume vs JD Differences

- The JD asks for direct experience with agentic workflows, RAG, and external API chains. The resume shows AI systems and LLM-adjacent work, but not strong production evidence for RAG or multi-step agent orchestration.
- The JD explicitly mentions LLM provider integrations such as OpenAI and Anthropic. The resume shows Hugging Face and Qwen experience, which is relevant but not the same signal.
- The JD lists `Python, TypeScript` and workflow tooling such as `n8n` or `UiPath`. The resume strongly shows Python, but not TypeScript, `n8n`, or `UiPath`.
- The role emphasizes reusable CI/CD patterns, Golden Path enablement, and platform-as-a-service guidance across teams. The resume is aligned on platform engineering, but could show more explicit “internal platform” or “golden path” ownership examples.
- The resume still has relatively few quantified impact bullets compared with the JD’s emphasis on reliability, zero downtime, and delivery acceleration.

### What Was Already Strong

- Kubernetes, CI/CD, GitLab, Jenkins, ArgoCD, Prometheus, and Grafana are all represented well.
- Platform engineering, observability, automation, and multi-cloud alignment were strong matches.
- The updated ATS audit for this JD shows no missing high-signal keywords.

### Best Next Improvements

- Add only real, interview-defensible examples of AI workflow integration, LLM provider usage, or agent orchestration if you have them.
- Strengthen recent bullets with measurable reliability, deployment, or developer-velocity outcomes.
- Where accurate, make internal platform enablement more explicit in recent experience.

---

## Flightradar24

- Role: Senior Platform and Infrastructure Engineer
- JD file: [input_job_descriptions/Flightradar24.txt](/Users/dtrid8/development/resume_updator/input_job_descriptions/Flightradar24.txt)
- Outcome: Rejected
- Response: Standard rejection email from CTO Mina Boström Nakicenovic, no specific feedback
- Audit report: [output/ResumeAudit_Deepak_Tripathi_Flightradar24.md](/Users/dtrid8/development/resume_updator/output/ResumeAudit_Deepak_Tripathi_Flightradar24.md)

### Audit Scores

- Overall: 82%
- Keyword: 100%
- Required terms: 100%
- Role alignment: 100%
- Impact: 10%

### Likely Resume vs JD Differences

- The audit shows 100% keyword and role alignment — all required terms (Kubernetes, AWS, Terraform, CI/CD, Docker, observability) and role tracks (platform engineering, DevOps) are present. The resume was not rejected for missing technical keywords.
- **Impact score is critically low at 10% (3/31 bullets have visible metrics).** This is the standout weakness. Flightradar24 processes billions of database entries per month and serves 50M+ monthly users — they likely expect candidates to demonstrate quantified scale, reliability, and performance outcomes.
- The JD specifically asks to "own database infrastructure, incl. provisioning, migrations, backups, replication, performance tuning." The resume has no explicit database ownership, DBA-adjacent work, or database operations experience (MySQL/MariaDB/Postgres, Redis, DynamoDB are all listed in the JD).
- The JD requires hands-on experience with streaming/messaging (Kafka, RabbitMQ). While Kafka appears in older role tools lists (Bank of America, DealerSocket), no bullet describes hands-on streaming platform work.
- The JD emphasizes "build and operate an internal developer platform that provides reproducible environments." The resume mentions platform engineering conceptually but lacks a concrete bullet describing internal developer platform ownership or reproducible dev environments.
- The role requires comfort working "within an existing codebase and architecture" — this signals they want someone who can ramp fast on legacy systems, not just greenfield. The resume is largely greenfield-oriented.
- Location requirement: "must be able to work in Stockholm" with no relocation offered. Resume lists Sweden but Sodertalje — this is close enough and unlikely a factor.

### What Was Already Strong

- All high-signal technical keywords matched (platform engineering, devops, kubernetes, docker, terraform, aws, ci/cd, observability, python, bash, automation, security).
- Role alignment was perfect — platform engineering + devops tracks both present.
- AWS + Kubernetes + Terraform + CI/CD stack alignment is strong.

### Best Next Improvements

- **Top priority: Rewrite experience bullets with quantified impact.** Add deployment frequency, uptime percentages, scale numbers, cost savings, or latency improvements wherever defensible. 3/31 bullets with metrics is critically low.
- Add explicit database infrastructure experience if real — provisioning, migrations, replication, performance tuning for SQL/NoSQL systems.
- Surface Kafka/messaging experience from older roles into concrete bullets rather than just tools lists.
- Add a bullet describing internal developer platform work with reproducible environments (if accurate from Scania/Alten work).
- Frame experience to show comfort operating and improving existing systems, not only building new ones.

---

## Tandem Health

- Role: Platform Engineer
- JD file: [input_job_descriptions/tandemhealth.txt](/Users/dtrid8/development/resume_updator/input_job_descriptions/tandemhealth.txt)
- Outcome: Rejected
- Response: Personalized rejection email, no specific feedback. "We have decided to proceed with other candidates."
- Audit report: [output/ResumeAudit_Deepak_Tripathi_Tandem.md](/Users/dtrid8/development/resume_updator/output/ResumeAudit_Deepak_Tripathi_Tandem.md)

### Audit Scores

- Overall: 99%
- Keyword: 100%
- Required terms: 100%
- Role alignment: 100%
- Impact: 97%

### Likely Resume vs JD Differences

- The automated audit scores are near-perfect (99% overall). All required terms (Kubernetes, AWS, GCP, Azure, Terraform, CI/CD, Helm, observability, AI) are present. All role tracks matched. This rejection is **not explainable by keyword gaps or weak bullets** — the cause is likely beyond ATS/resume content.
- **Healthcare / regulated industry experience is missing.** The JD explicitly calls out "healthcare-grade security requirements," PHI handling, and gives bonus points for "experience working in regulated industries (healthtech, finance, etc.), especially Medical Device Regulation." The resume shows financial services (Bank of America) but zero healthcare or MDR experience.
- **Encryption and key management is absent.** The JD specifically asks to "implement and manage robust encryption and key management systems." The resume has no bullets mentioning encryption, PKI, key management, secrets management, or similar.
- **The JD signals a small, senior, hands-on team** ("small, highly skilled team") in a fast-scaling startup context. The resume leans enterprise/corporate (Scania, Volvo, IKEA, Bank of America). Tandem likely prioritized candidates with startup or scale-up experience who can wear multiple hats.
- **Azure is preferred.** While the resume lists Azure, all recent quantified bullets emphasize AWS and GCP. Tandem's "Azure preferred" may have favored candidates with deeper Azure-primary experience.
- **Software engineering background** is listed as bonus. The resume shows this (Java/Spring Boot roles at Epsilon, DealerSocket, Hexaware, TCS), but it's buried in older roles. The framing doesn't emphasize the "engineer who became a platform engineer" narrative that this JD rewards.

### What Was Already Strong

- All high-signal keywords matched perfectly (Kubernetes, Terraform, AWS, Azure, GCP, CI/CD, Helm, observability, scalable systems, automation, security, AI).
- Impact bullets are now quantified across all roles (30/31 with metrics).
- Platform engineering, DevOps, and infrastructure-as-code alignment are strong.
- DevSecOps experience at Alten (Volvo CE, IKEA) is relevant to the security focus.

### Best Next Improvements

- Add explicit mention of encryption, key management, or secrets management (e.g., HashiCorp Vault, AWS KMS, Azure Key Vault) if you have real experience.
- Highlight the Bank of America role as regulated industry experience more explicitly (compliance, audit, data security).
- For healthtech/regulated roles, consider adding a skills line for compliance/regulatory awareness (SOC2, ISO 27001, HIPAA, MDR) if applicable.
- Reframe the career narrative to show the software engineer → platform engineer progression — this is a strong signal for roles that want "hands-on programming experience."
- For startup-stage roles, emphasize breadth and autonomy (wearing multiple hats, building from scratch) rather than scale of existing enterprise systems.

---

## Assessio

- Role: Senior DevOps Engineer
- JD file: [input_job_descriptions/assessio.txt](/Users/dtrid8/development/resume_updator/input_job_descriptions/assessio.txt)
- Outcome: **Proceeding — invited to assessment round**
- Response: Invited to complete personality, motivation, and problem-solving ability tests via the Assessio Platform.
- Audit report: [output/ResumeAudit_Deepak_Tripathi_Assessio.md](/Users/dtrid8/development/resume_updator/output/ResumeAudit_Deepak_Tripathi_Assessio.md)
- Next step: Complete Assessio assessment (cognitive ability, personality, motivation — ~50 minutes)

### Audit Scores

- Overall: 99%
- Keyword: 100%
- Required terms: 100%
- Role alignment: 100%
- Impact: 97%

### Why This One Likely Worked

- Strong alignment across all dimensions: Kubernetes, AWS, Terraform, CI/CD, observability, automation, security, AI — all present and quantified.
- The JD asks for GenAI/LLM usage in DevOps processes — the resume's AI/ML skills section and the Resume Updater project demonstrate this directly.
- European SaaS company valuing agile, collaboration, and infrastructure-as-code — closely mirrors the Scania and Alten experience profile.
- The JD values a mix of cloud providers (Scaleway, AWS) and microservices — the multi-cloud + Kubernetes + CI/CD narrative is a natural fit.
- Master's degree in Cloud Computing and AI from IIT matches the "Bachelor's or master's in CS/Engineering" requirement.
- Sweden-based role with international team — location and English fluency are a match.

### What to Prepare for Next Round

- The assessment is science-backed (psychometric): cognitive ability, personality, and motivation. This is Assessio's own product — they practice what they sell.
- Review their process: https://careers.assessio.com/pages/our-recruitment-process
- Be authentic on personality/motivation portions — they're looking for alignment with their culture (collaboration, growth, learning).
- For the cognitive ability assessment, expect logical reasoning, numerical, and verbal aptitude questions under time pressure.

---

## Lovable

- Role: Platform Engineer - Developer Experience
- JD file: [input_job_descriptions/Loveable.txt](/Users/dtrid8/development/resume_updator/input_job_descriptions/Loveable.txt)
- Outcome: Rejected
- Response: Standard rejection email from Lovable Hiring Team, no specific feedback
- Audit report: [output/ResumeAudit_Deepak_Tripathi_Lovable.md](/Users/dtrid8/development/resume_updator/output/ResumeAudit_Deepak_Tripathi_Lovable.md)

### Audit Scores

- Overall: 99%
- Keyword: 100%
- Required terms: 100%
- Role alignment: 100%
- Impact: 97%

### Likely Resume vs JD Differences

- Audit scores are near-perfect again (99%). Like Tandem Health, this rejection is **not a keyword or bullet quality issue** — it's a profile/tech-stack mismatch.
- **Tech stack mismatch: Golang, Rust, TypeScript, React are core.** Lovable's backend is Golang and Rust, frontend is React/TypeScript. The resume shows Python, Bash, and Java — none of Lovable's primary languages. This is likely the dealbreaker.
- **AI-native product company vs. infrastructure background.** Lovable is an AI-first product (AI-powered code generation). They want platform engineers who can "integrate tools for AI-driven development" and work "across the whole stack" of an AI product. The resume shows infrastructure/DevOps with AI as an adjacent skill, not core product work.
- **"Talent-dense" startup, on-site 5 days/week in Stockholm.** Lovable is a small, hyper-selective team building a generation-defining product. They likely prioritize candidates from similar high-velocity AI startups or scale-ups.
- **Data stack gap.** JD lists Clickhouse, Firestore, Spanner, BigQuery — the resume has no experience with any of these specific data technologies.
- **Local tooling: Nix, DevEnv** — niche tools not on the resume. Signals they want someone already in the modern developer tooling ecosystem.
- **Observability ownership.** JD asks to "own and develop our observability stack, from code instrumentation through ingestion to presentation." The resume shows Prometheus/Grafana usage but not full-stack o11y ownership including code instrumentation (OTEL).
- **Application framework experience.** JD wants someone to "integrate or build application frameworks to support a growing engineering org." This is software engineering work, not traditional DevOps.

### What Was Already Strong

- All required infra terms matched (Kubernetes, AWS, GCP, Terraform, CI/CD, Docker, observability, Grafana).
- Platform engineering narrative and developer experience language align well.
- Quantified impact bullets are strong.

### Best Next Improvements

- For AI-native companies, the resume needs explicit Golang, Rust, or TypeScript experience — or these roles are likely not a fit.
- Add OpenTelemetry (OTEL) to skills/bullets if you have instrumentation experience.
- For "Developer Experience" roles specifically, emphasize internal tooling you've built (CLIs, SDKs, frameworks) not just infrastructure provisioning.
- Consider whether AI-product companies are realistic targets vs. infrastructure-heavy companies where the profile is a natural fit.

---

## Aimo Park

- Role: Cloud Operations Engineer
- JD file: [input_job_descriptions/aimo.txt](/Users/dtrid8/development/resume_updator/input_job_descriptions/aimo.txt)
- Outcome: Paused — recruitment process on hold, intending to resume later in 2026
- Response: Personalized email indicating the role is paused, not a rejection of the candidate specifically
- Audit report: [output/ResumeAudit_Deepak_Tripathi_Aimo.md](/Users/dtrid8/development/resume_updator/output/ResumeAudit_Deepak_Tripathi_Aimo.md)

### Audit Scores

- Overall: 99%
- Keyword: 100%
- Required terms: 100%
- Role alignment: 100%
- Impact: 97%

### Analysis

- This is **not a rejection** — the company paused the entire recruitment process. No candidate assessment was made.
- Audit scores are perfect. The role (AWS, Kubernetes, CI/CD, GitLab, IaC, monitoring, incident management) is a strong natural fit for the profile.
- Aimo specifically mentions Datadog for observability — the resume shows Prometheus/Grafana/ELK/Loki but not Datadog. Minor gap.
- MongoDB listed as a plus — not on the resume.
- Worth re-applying when the process reopens later in 2026.

---

## Doktor.se

- Role: Senior Platform Engineer
- JD file: [processed_jds/Doktor_se.txt](/Users/dtrid8/development/resume_updator/processed_jds/Doktor_se.txt)
- Outcome: Applied on 2026-04-28 via Teamtailor
- Application confirmation: "Tack for din ansokan" confirmation page shown after submit
- Resume: [output/Resume_Deepak_Tripathi_Doktorse.pdf](/Users/dtrid8/development/resume_updator/output/Resume_Deepak_Tripathi_Doktorse.pdf)
- Cover letter: [output/CoverLetter_Deepak_Tripathi_Doktorse.pdf](/Users/dtrid8/development/resume_updator/output/CoverLetter_Deepak_Tripathi_Doktorse.pdf)
- Audit report: [output/ResumeAudit_Deepak_Tripathi_Doktorse.md](/Users/dtrid8/development/resume_updator/output/ResumeAudit_Deepak_Tripathi_Doktorse.md)

### Audit Scores

- Overall: 99%
- Keyword: 100%
- Required terms: 100%
- Role alignment: 100%
- Impact: 97%

### Notes

- Form answers submitted: authorized to work in Sweden = Yes; okay with 4 days/week from central Stockholm office = Yes.
- Future job offers consent was left unchecked.
- Teamtailor form accepted CV upload only; no separate cover-letter upload field was visible.

---

## H&M

- Role: Lead Platform Engineer
- JD file: Not saved (no JD file in workspace)
- Outcome: Rejected
- Response: Personalized rejection from Talent Acquisition team. "We think that you have a strong background, but for this process we have decided to move forward with another candidate."

### Analysis

- No JD file available to run an audit — cannot assess keyword/term alignment.
- The rejection language ("strong background" but "move forward with another candidate") suggests the resume passed initial screening but lost in final candidate comparison. This is a competitiveness rejection, not a qualification rejection.
- **"Lead" title** — this is a leadership-level role at a major retail enterprise. H&M likely prioritized candidates with explicit platform team leadership experience (managing engineers, setting technical vision, stakeholder management at scale). The resume shows Tech Lead experience but in smaller teams/contexts, not leading a platform organization.
- H&M is a massive enterprise (retail/fashion) with likely complex multi-region infrastructure. Candidates with direct experience at comparable-scale consumer-facing companies may have been preferred.
- Without the JD, specific technical gap analysis isn't possible.

### Best Next Improvements

- For "Lead" roles, emphasize team leadership, hiring, mentoring, and cross-org influence more explicitly.
- Consider saving JD text at application time to enable post-rejection analysis.
- H&M invited to follow on LinkedIn for future roles — worth monitoring.
