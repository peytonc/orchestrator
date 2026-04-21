# Critical Python Code Review

## Scope and method
- Reviewed `README.md` requirements and all Python modules under `orchestrator/`.
- Focused on correctness, software defects, and consistency with the README-described behavior.

## Executive summary
- The project structure and major component boundaries match the README.
- Several high-impact defects exist that can break realistic workflows, especially around template validation and path handling.
- Most defects are fixable with small targeted changes.

## README consistency check

### Consistent with README
- Planned project structure in README matches repository modules.
- Placeholder syntax and naming regex are implemented.
- Monte Carlo and sweep generation are both implemented.
- CSV and regex parsing modes are implemented.
- Worker directory isolation and per-case log files are implemented.
- Worker-count throttling logic includes reserve cores behavior.

### Inconsistent or partially implemented
1. **Reserved placeholder `OUTPUT_FILENAME` handling is inconsistent between validation and rendering.**
   - Workflow validation correctly treats `OUTPUT_FILENAME` as reserved.
   - Renderer still requires exact placeholder equality, causing it to reject valid templates unless all non-template values are removed before render.
2. **`paths.physics_output_file` target selection in parsing is not aligned with README’s `target_file` concept.**
   - Parser always reads the single output file path passed in from workflow.
   - `target_file` in parsing rules is parsed but not actually used to select a per-rule file.
3. **Physics executable input path may be wrong relative to worker cwd.**
   - Runner sets `cwd=worker_dir` and passes a path that already includes the worker dir prefix; this can produce duplicate directory segments.
4. **Template malformed token detection misses unterminated placeholders.**
   - Current validation catches bad names in `{{...}}`, but not unmatched starts like `{{NAME`.

## Per-file review

### `orchestrator/__init__.py`
- Status: OK.
- Exports are coherent and complete for the package API.

### `orchestrator/config.py`
- Strengths:
  - Strong top-level schema checks and duplicate name detection.
  - Enforces variable-name regex as documented.
- Defects / risks:
  1. `VariableSpec.from_dict` stores the original object including `name` and `kind` redundantly in `data`; this is low risk but creates possible ambiguity if downstream code references conflicting keys.
  2. `PathsConfig.from_dict` does not validate non-empty string paths for file fields (only command is checked), which can defer errors to runtime.

### `orchestrator/template.py`
- Strengths:
  - Correct placeholder extraction regex for uppercase identifiers.
  - Validates malformed placeholder tokens like lowercase names.
- Defects:
  1. Does not detect unmatched/open placeholder starts (`{{...` missing `}}`).
  2. `validate()` does not pass reserved placeholders, unlike workflow-level validation. This is currently harmless because workflow uses direct config validation, but the method is inconsistent and easy to misuse.

### `orchestrator/render.py`
- Strengths:
  - Strict missing/extra variable enforcement helps fail fast.
  - Numeric formatting is reasonable for simulation input text.
- Critical defect:
  1. Strict `extra` check can reject valid runtime dictionaries containing metadata keys unless caller pre-filters exactly. This interacts badly with reserved placeholder behavior and is likely to cause false failures in future integrations.

### `orchestrator/sampling.py`
- Strengths:
  - Distribution support matches README (`uniform`, `normal/gaussian`, `choice`, `truncated_normal`).
  - Good numeric and bound validation.
- Defects / risks:
  1. No explicit NaN/inf rejection for numeric fields.
  2. `int(float(text))` conversion strategy used elsewhere can silently coerce non-integer numeric strings; a similar strictness question applies to sampling input fields if JSON contains unusual numeric text.

### `orchestrator/cases.py`
- Strengths:
  - Clear separation between Monte Carlo and sweep.
  - Decimal-indexed sweep generation avoids floating point accumulation drift, aligning with README intent.
  - Paired-group length mismatch is validated.
- Defects / risks:
  1. Grouping currently pairs all variables sharing `group` regardless of explicit `iteration` mode. README examples include `iteration: paired`; that field is ignored.
  2. Sweep values from JSON are not type-normalized; mixed numeric/string values are accepted without validation.

### `orchestrator/runner.py`
- Strengths:
  - Captures stdout/stderr logs per case.
- Critical defect:
  1. Potential path bug: `subprocess.run(..., cwd=worker_dir)` while passing `input_path` as a path rooted at `worker_dir`. If `input_path` is relative (e.g., `tmp/thread_01/...`), executable resolves it relative to `cwd`, yielding `tmp/thread_01/tmp/thread_01/...`.
  2. Exceptions from `subprocess.run` (e.g., executable not found) are not converted into structured run errors here; workflow catches broad exceptions later, but no runner-local stdout/stderr files are produced in this path.

### `orchestrator/parser.py`
- Strengths:
  - Implements both CSV and regex parsing styles.
  - Good regex compile error handling and typed conversion map.
- Defects:
  1. `target_file` in rule specs is ignored; parser always reads the file passed by workflow. This is inconsistent with README rule schema semantics.
  2. CSV parser reads only first data row; README wording may imply extraction generally, but this behavior is not documented in code-level API and may surprise users.
  3. `int(float(text))` for integer conversion can silently truncate values like `"1.9"`.

### `orchestrator/results.py`
- Status: Mostly OK.
- Risk:
  - Mutable list references (`warnings`, `errors`) are inserted directly; currently safe due to call patterns, but defensive copying would be better.

### `orchestrator/system_resources.py`
- Strengths:
  - Cross-platform best-effort physical-core detection with safe fallback.
  - Conservative worker recommendation aligns with README’s avoid-oversubscription goal.
- Risk:
  - Broad exception swallowing (`except Exception`) can hide platform regressions; acceptable for fallback behavior but weak for diagnostics.

### `orchestrator/workflow.py`
- Strengths:
  - Good orchestration shape and parallel execution model.
  - Per-worker slot queue provides bounded reuse of worker directories.
- Critical/major defects:
  1. Injected `OUTPUT_FILENAME` is absolute/relative string for the generated case output path, but parser/runner logic still assumes one configured output path pattern; rule-level `target_file` remains unintegrated.
  2. On pre-run failures in `_execute_case_in_worker_slot`, stdout/stderr paths in returned record may not exist, violating expectations for downstream tooling.

## Severity-ranked defect list

### Critical
1. Runner argument path resolution can fail due to `cwd` + prefixed input path interaction.
2. `target_file` in parsing rules is ignored, so per-rule file selection from README schema is not implemented.

### Major
1. Reserved placeholder flow (`OUTPUT_FILENAME`) is not consistently enforced across validation and rendering APIs.
2. Template validator misses unmatched placeholder starts.

### Minor
1. Integer conversion permissiveness (`int(float(...))`) can hide malformed data.
2. Weak diagnostics in platform core-detection fallbacks.
3. Optional config fields may defer validation until runtime.

## Project-level conclusion
- **Partially compliant with README functionality.**
- Core orchestration exists and the module architecture matches the README.
- However, there are correctness gaps that materially affect real runs, especially path handling and parser rule semantics.
- Recommendation: address the two critical defects first, then the major placeholder/validation consistency issues.

## Suggested priority fix order
1. Fix runner input-path invocation to pass worker-local filename (or absolute path) consistently.
2. Implement `target_file` semantics in workflow/parser (support per-rule file paths, resolved relative to worker dir when appropriate).
3. Harmonize template validation + renderer behavior for reserved placeholders.
4. Add unmatched placeholder-token detection and stricter integer conversion validation.
