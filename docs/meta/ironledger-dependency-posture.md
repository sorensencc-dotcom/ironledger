# IronLedger Dependency Posture

This document records the dependency posture, rationale, and runtime boundaries for IronLedger.

## Phase 3 Dependency Posture: Beancount & bean-check Subprocess Invocation

Phase 3 introduces the compilation of approved staged transactions into human-readable, deterministic Beancount journal files.

### 1. Zero Direct Python Import Boundary

- `beancount` is **never imported** directly into the IronLedger Python runtime core (`import beancount` is forbidden across `src/ironledger/`).
- The Python codebase renders canonical, deterministic plaintext Beancount syntax using native string formatting and templating rules defined in `ironledger.compile.render`.
- Validation of generated journals is executed solely via subprocess invocation of the pinned external `bean-check` CLI binary (`ironledger.compile.beancheck`).

### 2. Subprocess Invocation & PATH Assumptions

- `bean-check` is invoked with a strict execution timeout (default 10 seconds) via `subprocess.run`.
- The pinned tooling version is `beancount==3.2.3` (optional extra `dev` in `pyproject.toml`). That package ships the `bean-check` console script. It is not a runtime dependency of IronLedger.
- When `bean-check` is not present on the host system `PATH`:
  - Compiler invocations fail closed and raise `BeanCheckUnavailableError`.
  - Non-compilation subsystems (ingest, review, rule management, migrations, CLI queries) remain fully functional.
  - Integration tests requiring the live binary (`@pytest.mark.integration`) skip cleanly when `bean-check` is absent.

### 3. Binary Extension Posture & Determinism

- The output format produced by IronLedger Phase 3 is strictly byte-deterministic across environments, independent of external C-extensions or Python minor versions.
- All timestamps, float-to-decimal representations, account sorts, and postings adhere strictly to the locked Phase 1 and Phase 3 specifications.

### 4. Lockfile & Environment Management

- Development and CI environments pin `beancount` tooling via the `dev` extra (`beancount==3.2.3`). The runtime lockfile (`requirements.lock`) still pins only `ofxtools==1.1.1`.
- Changes to compiler output schemas, ledger file layouts, or `bean-check` validation rules require a formal design amendment and exit gate review.
