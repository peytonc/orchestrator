# Python Class Review and README Consistency Check

## Scope
Reviewed all Python modules in `orchestrator/` plus `README.md` for:
- implementation defects
- robustness issues
- maintainability improvements
- consistency with documented behavior

## File-by-file findings

### 1) `orchestrator/config.py`
- **Status:** Mostly solid structure and validation.
- **Defects / risks:**
  - `ControlConfig.validate_against_template()` enforces an exact placeholder-variable match. This is strict and good for safety, but it requires explicit exclusion of reserved placeholders (like `OUTPUT_FILENAME`) in orchestration code. Consider moving reserved-placeholder awareness into config/template validation to avoid duplicated policy.
- **Recommended modifications:**
  1. Add optional `reserved_placeholders: set[str]` parameter to `validate_against_template()`.
  2. Add duplicate-name detection for `variables` and `parsing` names.

### 2) `orchestrator/template.py`
- **Status:** Contains a **hard failure defect**.
- **Defects / risks:**
  - In `extract_placeholders()`, malformed-token validation uses `if not .match(token):`, which is invalid Python and prevents import/compilation.
  - `validate()` type annotation references `ControlConfig` without importing it.
- **Recommended modifications:**
  1. Replace `if not .match(token):` with `if not VALID_NAME_RE.match(token):`.
  2. Import `ControlConfig` (or use `TYPE_CHECKING` to avoid circular imports).
  3. Consider returning malformed tokens in error messages with surrounding `{{...}}` context for easier debugging.

### 3) `orchestrator/render.py`
- **Status:** Good core rendering logic, but has import-time defect risk.
- **Defects / risks:**
  - `Renderer.__init__` calls `TemplateLoader.extract_placeholders(...)` but `TemplateLoader` is not imported in this file.
  - Duplicates `TemplateError` class already present in `template.py`; multiple exception classes with same name can fragment error handling.
- **Recommended modifications:**
  1. Import `TemplateLoader` from `orchestrator.template`.
  2. Reuse a single `TemplateError` definition from one module.
  3. Optionally precompile placeholder substitution map for large templates.

### 4) `orchestrator/sampling.py`
- **Status:** Sampling behavior is reasonable, but module appears incomplete.
- **Defects / risks:**
  - Uses `VariableSpec` and `ControlError` without importing them.
  - Several imports are unused (`dataclass`, `Decimal`, `product`, `Path`, etc.), suggesting copy/paste drift.
- **Recommended modifications:**
  1. Import `VariableSpec` and `ControlError` from `config.py`.
  2. Remove unused imports.
  3. Consider adding optional deterministic rounding/quantization options for Monte Carlo outputs where downstream tools require fixed precision.

### 5) `orchestrator/cases.py`
- **Status:** Strong design overall; includes notable implementation bugs.
- **Defects / risks:**
  - References `ControlConfig`, `DistributionSampler`, `VariableSpec`, and `ControlError` without imports.
  - Reads `iteration = ...` but never uses it (dead variable / misleading API).
  - In Monte Carlo mode, only distribution variables are included. If template placeholders include sweep variables (or constants) this will fail later unless prevented elsewhere.
- **Recommended modifications:**
  1. Add missing imports from sibling modules.
  2. Remove or implement `iteration` behavior explicitly.
  3. Validate mode-variable compatibility early (e.g., forbid sweep vars in Monte Carlo unless explicitly supported).

### 6) `orchestrator/parser.py`
- **Status:** Parsing logic is thoughtful; module hygiene is weak.
- **Defects / risks:**
  - References `ControlError` without import.
  - Unused imports (`dataclass`, `re` is used, but `subprocess` and some typing imports are not).
  - `_parse_csv()` reads only first row; this may diverge from user expectations unless documented.
- **Recommended modifications:**
  1. Import `ControlError` from `config.py`.
  2. Remove unused imports.
  3. Add `row_index` option (default 0) for CSV extraction to support non-first-row parsing.

### 7) `orchestrator/runner.py`
- **Status:** Core subprocess usage is acceptable; some model inconsistencies.
- **Defects / risks:**
  - Defines `RunResult` dataclass but returns `Dict[str, Any]` from `run()`; type contract inconsistency.
  - If `physics_command` includes spaces/flags, current `cmd = [self.physics_command, str(input_path)]` treats it as executable name only.
- **Recommended modifications:**
  1. Either return `RunResult` or remove the dataclass.
  2. Support command tokenization (e.g., configurable argv list) instead of a single string.
  3. Optionally expose timeout and environment override in config.

### 8) `orchestrator/results.py`
- **Status:** Works, but has cleanup opportunities.
- **Defects / risks:**
  - Many unused imports (`dataclass`, `csv`, `re`, `subprocess`, etc.).
- **Recommended modifications:**
  1. Remove unused imports.
  2. Add optional stable sort by `case_id` before write to guarantee deterministic output order when records are added concurrently.

### 9) `orchestrator/system_resources.py`
- **Status:** Functional approach, but module has unrelated imports.
- **Defects / risks:**
  - Unused imports from concurrency/dataclasses/json/shutil etc.
  - Linux physical-core detection via `/proc/cpuinfo` may fail on containerized/heterogeneous environments; fallback handles this, but logging/traceability is absent.
- **Recommended modifications:**
  1. Remove unused imports.
  2. Add optional debug diagnostics for detected method/result.

### 10) `orchestrator/workflow.py`
- **Status:** Orchestration flow is clear, but import defects are critical.
- **Defects / risks:**
  - References many classes/exceptions without imports (`ControlConfig`, `TemplateLoader`, `Renderer`, `CaseGenerator`, `SimulationRunner`, `OutputParser`, `ResultCollector`, `SystemResourceDetector`, `ControlError`).
  - Catches broad `Exception` while parsing and execution paths; acceptable for batch robustness, but should preserve traceback in logs.
- **Recommended modifications:**
  1. Add explicit imports for all referenced symbols.
  2. Record traceback details into stderr log or structured error payload.
  3. Optionally add per-case timeout/cancellation handling.

### 11) `orchestrator/__init__.py`
- **Status:** Empty; acceptable but not ideal for package UX.
- **Recommended modifications:**
  1. Export stable public API symbols via `__all__`.
  2. Add package version metadata if this will be distributed.

## README consistency review

### Consistent with implementation
- README describes placeholder format and strict variable naming, aligned with regexes used in code.
- README describes Monte Carlo + sweep, worker directories, and output parsing support; these concepts exist in modules.

### Inconsistent / overstated vs current code
1. **Project currently does not import cleanly** due syntax/import defects (`template.py` invalid syntax; multiple modules missing symbol imports).
2. **`prefer_physical_cores` is documented as execution behavior**, but `recommended_worker_count()` currently does not receive/use that flag from orchestration.
3. README implies polished end-to-end pipeline; implementation is architecturally close but not production-ready until import/syntax/type consistency issues are fixed.

## Priority fix order
1. Fix syntax error in `template.py`.
2. Fix all missing cross-module imports.
3. Remove unused imports and dead variables.
4. Align type contracts (`RunResult` vs dict).
5. Reconcile README claims with implemented flags/behavior.
