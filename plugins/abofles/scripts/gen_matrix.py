#!/usr/bin/env python3
"""Single source of truth for the abofles topic matrix.

Edit TIERS / TOPICS below, then run:

    python3 scripts/gen_matrix.py

It rewrites the topic index inside skills/abofles/references/topics.md (between
the `<!-- topics:start -->` / `<!-- topics:end -->` markers) and regenerates
skills/abofles/references/matrix.md. `--check` writes nothing and exits 1 when
either file is out of date.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS_MD = ROOT / "skills/abofles/references/topics.md"
MATRIX = ROOT / "skills/abofles/references/matrix.md"

SIDES = ["Read", "Analyse", "Plan", "Work", "Verify"]
SIDE_NAMES = {
    "Read": "Read & Collect",
    "Analyse": "Analyse & Find Gaps",
    "Plan": "Plan & Design",
    "Work": "Act & Work",
    "Verify": "Verify & Review",
}

# Base cell per tier and side. Overrides on a topic replace single cells.
TIERS = {
    1: dict(Read="haiku·low", Analyse="sonnet·low", Plan="sonnet·low", Work="haiku·medium", Verify="haiku·low"),
    2: dict(Read="haiku·low", Analyse="sonnet·medium", Plan="sonnet·medium", Work="sonnet·medium", Verify="sonnet·low"),
    3: dict(Read="haiku·medium", Analyse="opus·medium", Plan="opus·medium", Work="sonnet·high", Verify="sonnet·high"),
    4: dict(Read="sonnet·low", Analyse="opus·high", Plan="opus·xhigh", Work="opus·high", Verify="opus·high"),
}

# Reply cap in lines (status header excluded) per tier and side.
# A topic may override single caps with a 5th tuple element, e.g. {"Read": 120}.
CAPS = {
    1: dict(Read=20, Analyse=10, Plan=25, Work=10, Verify=10),
    2: dict(Read=40, Analyse=20, Plan=50, Work=20, Verify=20),
    3: dict(Read=60, Analyse=35, Plan=90, Work=30, Verify=35),
    4: dict(Read=100, Analyse=50, Plan=150, Work=40, Verify=60),
}

# (group letter, group name, [(topic, tier, overrides, signals[, cap overrides]), ...])
# Numbering is assigned in order, starting at 1.
TOPICS = [
    ("A", "Security & Trust", [
        ("Security & Risk Review", 4, {"Analyse": "fable·medium"},
         "threat model, OWASP, attack surface, vulnerability", {"Analyse": 80}),
        ("Authentication (login, sessions, tokens, MFA)", 4, {},
         "login, JWT, OAuth, session, refresh token, OTP, password reset"),
        ("Authorization, Roles & Permissions", 4, {},
         "RBAC, ACL, policy, scope, admin, ownership check, IDOR"),
        ("Secrets, Keys & Config Security", 4, {"Work": "sonnet·high"},
         ".env, API key, vault, certificate, hard-coded secret"),
        ("Data Privacy, PII & Compliance", 4, {},
         "PII, GDPR, PCI, KYC, data retention, masking, consent"),
        ("Input Validation & Injection", 3, {},
         "SQLi, XSS, SSRF, CSRF, sanitize, escape, file upload"),
        ("Cryptography, Hashing & Signing", 4, {},
         "bcrypt, argon2, HMAC, AES, RSA, signature, nonce, salt"),
        ("Rate Limiting, Abuse & Fraud Prevention", 3, {},
         "throttle, brute force, bot, captcha, velocity check, blacklist"),
        ("Audit Logging & Traceability", 3, {"Work": "sonnet·medium"},
         "audit trail, who did what, immutable log, compliance log"),
        ("Dependency Vulnerabilities (CVE scan)", 3, {"Read": "haiku·low"},
         "npm audit, CVE, Snyk, Dependabot, advisory", {"Read": 60}),
    ]),
    ("B", "Money & Finance", [
        ("Financial & Amount Calculations", 4, {"Analyse": "fable·medium"},
         "amount, decimal, rounding, currency math, totals, precision"),
        ("Revenue Flow & Profit", 4, {},
         "revenue, margin, profit split, payout, settlement"),
        ("Payments & Gateway Integration", 4, {},
         "Stripe, PSP, card, 3DS, payment intent, capture, authorize"),
        ("Pricing, Fees, Commission & Tax", 4, {},
         "price, fee, commission, VAT, tax, discount, coupon, tier pricing"),
        ("Wallets, Balances & Ledger", 4, {},
         "wallet, balance, ledger, double entry, debit, credit, hold"),
        ("Refunds, Chargebacks & Reversals", 4, {},
         "refund, chargeback, dispute, reversal, void, partial refund"),
        ("Reconciliation & Financial Reports", 3, {},
         "reconcile, statement, mismatch, settlement report, export"),
        ("Invoicing & Billing Cycles", 3, {},
         "invoice, subscription, billing period, proration, dunning"),
        ("Multi-currency & Exchange Rates", 4, {},
         "FX, exchange rate, conversion, base currency, IQD, USD"),
    ]),
    ("C", "Business Logic & Workflows", [
        ("Business Logic (domain rules)", 3, {},
         "business rule, domain, eligibility, calculation, policy"),
        ("Status & Workflows (state machines)", 3, {"Analyse": "opus·high"},
         "status, state machine, transition, approval flow, lifecycle"),
        ("Validation Rules & Constraints", 3, {},
         "required field, limit, range, uniqueness, business validation"),
        ("Notifications & Messaging", 2, {},
         "email, SMS, push, template, notification preference"),
        ("Scheduling, Time Zones & Calendars", 3, {},
         "cron, timezone, DST, date math, recurring, booking slot"),
        ("Multi-tenancy & Account Isolation", 4, {},
         "tenant, organization, workspace, data isolation, tenant_id"),
        ("Reporting & Dashboards (business)", 2, {},
         "report, KPI, aggregate, chart data, export CSV, summary"),
        ("Import, Export & Data Migration (business data)", 3, {},
         "CSV import, bulk upload, ETL, data migration, mapping"),
    ]),
    ("D", "Quality & Testing", [
        ("Quality Assurance (strategy & coverage)", 2, {},
         "test plan, coverage, test pyramid, acceptance criteria"),
        ("Unit Test", 2, {},
         "unit test, jest, pytest, xUnit, mock, assert"),
        ("Integration & API Test", 2, {},
         "integration test, API test, supertest, test DB, Postman"),
        ("End to End Test", 2, {"Work": "sonnet·high"},
         "E2E, Playwright, Cypress, Selenium, user journey"),
        ("Test Data, Fixtures & Mocks", 1, {},
         "fixture, factory, seed, faker, stub, mock server"),
        ("Regression & Smoke Check", 1, {},
         "smoke test, regression, sanity check, run the suite"),
        ("Flaky Test Hunting", 2, {},
         "flaky, intermittent, timing, retry, nondeterministic"),
        ("Performance & Load Testing", 3, {},
         "load test, k6, JMeter, latency, throughput, p95, benchmark"),
        ("Contract & Snapshot Tests", 2, {},
         "contract test, Pact, snapshot, schema test, golden file"),
    ]),
    ("E", "Debugging & Incidents", [
        ("Bug Fix & Debugging", 3, {},
         "bug, stack trace, reproduce, fix, regression"),
        ("Incident & Production Debug", 4, {"Analyse": "fable·medium"},
         "outage, prod down, 500s, hotfix, on-call, incident", {"Analyse": 80}),
        ("Root Cause Analysis & Postmortem", 3, {"Analyse": "opus·high"},
         "root cause, RCA, postmortem, timeline, five whys", {"Analyse": 60}),
        ("Log & Trace Investigation", 2, {},
         "logs, trace, correlation id, Sentry, grep logs, span"),
        ("Memory Leaks & Resource Exhaustion", 3, {},
         "memory leak, OOM, file handles, connection pool exhausted"),
        ("Data Corruption & Recovery", 4, {},
         "corrupt data, bad migration, restore, repair script, backfill"),
    ]),
    ("F", "Code Health", [
        ("Clean Code (naming, structure, readability)", 2, {},
         "clean code, naming, readability, small functions, SOLID"),
        ("Refactoring (behavior-preserving)", 3, {},
         "refactor, extract, inline, restructure, no behavior change"),
        ("Lint, Format & Style", 1, {"Work": "haiku·low"},
         "eslint, prettier, black, formatting, style guide, warnings"),
        ("Dead Code & Tech Debt", 2, {},
         "unused, dead code, TODO, deprecated, debt, cleanup"),
        ("Error Handling & Resilience", 3, {},
         "try/catch, exception, retry, fallback, circuit breaker, timeout"),
        ("Logging & Observability (instrumentation)", 2, {},
         "logger, log level, metrics, tracing, OpenTelemetry"),
        ("Code Duplication & Reuse", 2, {},
         "duplicate, DRY, shared helper, copy-paste, utility"),
        ("Type Safety & Static Analysis", 2, {},
         "TypeScript, type error, any, strict mode, mypy, nullability"),
        ("Code Comments & Inline Docs", 1, {},
         "comment, docstring, JSDoc, XML doc, explain code"),
    ]),
    ("G", "Architecture & Design", [
        ("Architecture, Design Pattern & Stack Used", 4, {"Plan": "fable·medium", "Work": "sonnet·high"},
         "architecture, layers, pattern, stack choice, structure, clean architecture", {"Plan": 200}),
        ("Module Boundaries & Dependency Graph", 3, {},
         "coupling, cohesion, circular dependency, module, package layout"),
        ("API Design & Contracts", 3, {},
         "REST, GraphQL, gRPC, endpoint design, versioning, DTO, breaking change"),
        ("Event-driven & Messaging Architecture", 3, {},
         "event, pub/sub, Kafka, RabbitMQ, saga, eventual consistency"),
        ("Microservices vs Monolith Decisions", 4, {"Plan": "fable·medium", "Work": "sonnet·medium"},
         "split service, monolith, bounded context, service boundary"),
        ("Domain Modeling (DDD, entities, aggregates)", 3, {},
         "entity, aggregate, value object, domain model, ubiquitous language"),
        ("Scalability & Capacity Planning", 3, {},
         "scale, horizontal, bottleneck, capacity, sharding, load"),
        ("Framework & Language Migration", 4, {"Work": "sonnet·high"},
         "upgrade framework, migrate from X to Y, rewrite, port, major version", {"Plan": 200}),
    ]),
    ("H", "Data & Storage", [
        ("DB Schema & Migrations", 4, {},
         "migration, schema, table, column, index, ALTER, EF migration"),
        ("Query & DB Performance", 3, {},
         "slow query, N+1, index, EXPLAIN, query plan, ORM"),
        ("Data Integrity & Constraints", 4, {},
         "foreign key, unique, NOT NULL, orphan rows, consistency, cascade"),
        ("Caching Strategy", 3, {},
         "cache, Redis, TTL, invalidation, stale, memoize"),
        ("Concurrency, Locking & Race Conditions", 4, {},
         "race condition, lock, transaction, isolation level, deadlock, atomic"),
        ("Backups, Retention & Archival", 3, {},
         "backup, restore, retention, archive, cold storage, purge"),
        ("Search & Indexing (full-text)", 2, {},
         "search, Elasticsearch, full-text, relevance, tokenizer"),
        ("File Storage & Media Handling", 2, {},
         "S3, blob, upload, image resize, CDN, signed URL"),
    ]),
    ("I", "Integrations & Async", [
        ("3rd-party Integrations & Webhooks", 3, {},
         "webhook, callback, integration, partner API, signature verify"),
        ("Background Jobs & Queues", 3, {},
         "job, worker, queue, Hangfire, Celery, BullMQ, scheduler"),
        ("Real-time (WebSockets, SSE, Push)", 3, {},
         "WebSocket, SignalR, SSE, live update, socket.io"),
        ("External API Clients & SDK Usage", 2, {},
         "HTTP client, SDK, API wrapper, pagination, auth header"),
        ("Idempotency & Retry Logic", 4, {},
         "idempotency key, duplicate request, retry, exactly once, backoff"),
        ("AI / LLM Integration", 2, {"Analyse": "opus·medium"},
         "prompt, LLM, Claude API, tool use, embeddings, agent loop"),
    ]),
    ("J", "Dependencies & DevOps", [
        ("Packages & Libs Updates", 2, {"Analyse": "sonnet·high"},
         "upgrade package, bump version, breaking change, changelog, lockfile"),
        ("CI/CD & Build Pipelines", 2, {},
         "GitHub Actions, pipeline, build, artifact, deploy step"),
        ("Docker, Containers & Orchestration", 3, {},
         "Dockerfile, compose, Kubernetes, image, container"),
        ("Infra as Code & Cloud Config", 3, {},
         "Terraform, IAM, cloud, VPC, bucket policy, serverless config"),
        ("Environment & Config Files", 2, {},
         "appsettings, .env, config, feature config, per-environment"),
        ("Release, Versioning & Changelog", 1, {},
         "release notes, semver, tag, changelog, version bump"),
        ("Monitoring, Alerts & Health Checks", 2, {},
         "health endpoint, alert, uptime, Grafana, dashboard, SLO"),
        ("Feature Flags & Rollouts", 2, {},
         "feature flag, toggle, canary, gradual rollout, A/B"),
    ]),
    ("K", "Frontend & UX", [
        ("UI Components & Styling", 2, {},
         "component, Tailwind, CSS, design system, button, layout"),
        ("UX Flows & Accessibility", 2, {},
         "user flow, a11y, ARIA, keyboard, screen reader, empty state"),
        ("State Management (frontend)", 2, {},
         "store, Redux, Zustand, context, cache, React Query"),
        ("Forms & Client-side Validation", 2, {},
         "form, input, validation message, submit, controlled input"),
        ("Responsive, RTL & Theming", 2, {},
         "responsive, breakpoint, RTL, dark mode, theme tokens"),
        ("Frontend Performance", 2, {},
         "bundle size, lazy load, render, Core Web Vitals, memo"),
        ("Mobile-specific (iOS, Android, cross-platform)", 2, {},
         "SwiftUI, Kotlin, React Native, Flutter, permissions, offline"),
    ]),
    ("L", "Docs & Content", [
        ("Work on Document (README, guides)", 1, {},
         "README, guide, how-to, markdown, wiki, write up"),
        ("Code Match Documents (docs vs code drift)", 2, {},
         "docs out of date, verify docs, spec vs implementation, drift", {"Analyse": 40}),
        ("API Docs (OpenAPI / Swagger)", 1, {},
         "OpenAPI, Swagger, endpoint docs, schema docs, examples"),
        ("Legal & Marketing Content & Translation", 2, {"Analyse": "opus·medium"},
         "terms, privacy policy, landing copy, marketing text, translate"),
        ("i18n & l10n (strings, locales)", 2, {},
         "i18n, locale, translation keys, plural rules, date format"),
        ("Codebase Exploration & Onboarding", 1, {},
         "where is, how does, map the repo, explain module, onboarding", {"Read": 120}),
        ("Architecture Decision Records (ADR)", 2, {},
         "ADR, decision log, why we chose, trade-off record"),
    ]),
    ("M", "Product & Scope", [
        ("Check MVP vs Advance", 3, {"Work": "sonnet·medium", "Verify": "sonnet·low"},
         "MVP, scope cut, nice to have, phase 1, over-engineering"),
        ("Feature Scoping & Requirements", 3, {"Work": "sonnet·medium"},
         "requirements, user story, acceptance criteria, scope, spec"),
        ("Analytics & Tracking Events", 2, {},
         "tracking event, analytics, funnel, Amplitude, GA, event schema"),
        ("User Feedback & Bug Triage", 1, {},
         "triage, prioritize, severity, user report, label issues"),
        ("Competitor & Feature Parity Check", 2, {"Read": "sonnet·low"},
         "competitor, parity, benchmark features, market check"),
    ]),
]


def numbered():
    n = 0
    for letter, group, rows in TOPICS:
        out = []
        for row in rows:
            topic, tier, ov, sig = row[:4]
            capov = row[4] if len(row) > 4 else {}
            n += 1
            out.append((n, topic, tier, ov, sig, capov))
        yield letter, group, out


def cell(tier, ov, side):
    v = ov.get(side, TIERS[tier][side])
    return f"**{v}**" if side in ov else v


def build_index():
    lines = []
    for letter, group, rows in numbered():
        lines.append(f"**{letter}. {group}**")
        for n, topic, tier, ov, _, capov in rows:
            parts = [f"{k}={v}" for k, v in ov.items()]
            parts += [f"cap {k}={v}" for k, v in capov.items()]
            o = (" — " + ", ".join(parts)) if parts else ""
            lines.append(f"- {n}. {topic} · T{tier}{o}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_matrix():
    m = [
        "# Abo Fles — Full Matrix",
        "",
        "Generated by `scripts/gen_matrix.py`. Do not edit by hand.",
        "",
        "Each cell is `model·effort`. **Bold** = override of the tier base. "
        "Caps = reply-cap overrides in lines. Signals = words in the task that point to this topic.",
        "",
        "Sides: " + " · ".join(f"{k} = {v}" for k, v in SIDE_NAMES.items()),
        "",
        "## Tier base",
        "",
        "| Tier | Read | Analyse | Plan | Work | Verify |",
        "|---|---|---|---|---|---|",
    ]
    for t, cells in TIERS.items():
        m.append(f"| T{t} | " + " | ".join(cells[s] for s in SIDES) + " |")
    m += [
        "",
        "## Reply cap base (lines, status header excluded)",
        "",
        "| Tier | Read | Analyse | Plan | Work | Verify |",
        "|---|---|---|---|---|---|",
    ]
    for t, caps in CAPS.items():
        m.append(f"| T{t} | " + " | ".join(str(caps[s]) for s in SIDES) + " |")
    m += [
        "",
        "Never cut a finding to fit a cap. Rank, keep the top ones in full, "
        "end with `+N more: <one line each>`. Caps column below lists only overrides.",
        "",
    ]
    total = 0
    for letter, group, rows in numbered():
        total += len(rows)
        m += [
            f"## {letter}. {group}",
            "",
            "| # | Topic | Tier | Read | Analyse | Plan | Work | Verify | Caps | Signals |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for n, topic, tier, ov, sig, capov in rows:
            capcol = " ".join(f"{k}={v}" for k, v in capov.items()) or "base"
            m.append(
                f"| {n} | {topic} | T{tier} | "
                + " | ".join(cell(tier, ov, s) for s in SIDES)
                + f" | {capcol} | {sig} |"
            )
        m.append("")
    m[2] = f"Generated by `scripts/gen_matrix.py` — {total} topics in {len(TOPICS)} groups. Do not edit by hand."
    return "\n".join(m)


def splice(text, start, end, body):
    i = text.index(start) + len(start)
    j = text.index(end)
    return text[:i] + "\n" + body + text[j:]


if __name__ == "__main__":
    import sys

    new_topics = splice(TOPICS_MD.read_text(), "<!-- topics:start -->", "<!-- topics:end -->", build_index())
    new_matrix = build_matrix()
    if "--check" in sys.argv[1:]:
        stale = [p.name for p, new in ((TOPICS_MD, new_topics), (MATRIX, new_matrix)) if p.read_text() != new]
        if stale:
            print("stale: " + ", ".join(stale) + " (run gen_matrix.py)")
            sys.exit(1)
        print("ok: up to date")
        sys.exit(0)
    TOPICS_MD.write_text(new_topics)
    MATRIX.write_text(new_matrix)
    count = sum(len(r) for _, _, r in TOPICS)
    print(f"ok: {count} topics, {len(TOPICS)} groups -> {TOPICS_MD.name}, {MATRIX.name}")
