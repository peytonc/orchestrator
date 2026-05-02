# orchestrator

`orchestrator` automates, manages, and controls the input, output, and execution of a numerical simulation.

It is a local-only Python framework for driving a black-box Physics executable using only the Python standard library. The project is designed for offline scientific workflows where a text template is filled with case-specific values, the simulation is run locally, the output is parsed, and the results are collected for later analysis.

## Overview

`orchestrator` provides an end-to-end batch execution pipeline for simulations that behave like a black box. The framework supports Monte Carlo sampling and deterministic numerical sweeps. It also supports parallel execution with worker threads, per-worker local directories, reproducible random seeds, CSV parsing, and regex-based output extraction.

It handles the full workflow:

1. load a JSON control file
2. read the Physics template input file
3. validate placeholders
4. generate simulation cases
5. render a per-case input file
6. create isolated worker directories
7. run the executable locally
8. parse the output file
9. collect results
10. write an aggregated results file


## Quick start (for simulation users)

1. Prepare your executable so it accepts **one input file path as its final CLI argument**.
2. Create `template.txt` with placeholders like `{{TEMPERATURE}}`.
3. Create `control.json` (examples below).
4. Run:

```bash
python -m orchestrator.main control.json
```

Useful options:

- `--timeout SECONDS` sets a per-case execution timeout.

The run writes:

- per-case input/output/log files under `execution.worker_dir_root/thread_XX/`
- aggregated JSON results at `paths.results_file`

## Design goals

This project is intentionally simple and opinionated. The main goals are:

- use only the Python standard library
- support offline execution
- keep simulation runs reproducible
- validate everything before expensive runs begin
- isolate worker files to prevent collisions
- preserve logs for manual inspection
- keep the code easy to split into small modules later
- support both stochastic and deterministic case generation

## Template system

The Physics input template is a plain text file with placeholders such as:

- `{{TEMPERATURE}}`
- `{{DISTANCE_1}}`
- `{{TIME_STEP}}`

The placeholder format is strict:

- placeholder syntax: `{{VAR_NAME}}`
- variable names must match `^[A-Z][A-Z0-9_]*$`
- only uppercase names are allowed
- substitution is literal, not evaluated

### Template validation

Before any simulation begins, the framework validates that:

- every placeholder in the template is defined in the control file
- every variable in the control file is used by the template
- placeholder syntax is valid
- the template contains no malformed placeholder tokens

## Control file reference (all supported fields)

The control file is JSON with four top-level sections: `execution`, `paths`, `variables`, and `parsing`.

### Top-level structure

- `execution` (object, required): runtime behavior.
- `paths` (object, required): input/output paths and executable command.
- `variables` (array, required, non-empty): case-generation definitions.
- `parsing` (array, required, may be empty): output extraction rules.

### `execution` fields

- `mode` (required): `"monte_carlo"` or `"sweep"`.
- `max_cases` (required): positive integer; hard limit on generated/run cases.
- `random_seed` (optional): integer seed for reproducible Monte Carlo sampling (defaults to `0`).
- `max_cpu_threads` (optional): positive integer worker cap (defaults to `1`).
- `prefer_physical_cores` (optional): `true`/`false`; prefers physical-core count when sizing workers (defaults to `true`).
- `worker_dir_root` (optional): directory root for per-worker files (defaults to `"tmp"`).
- `preserve_workdirs` (optional): keep worker directories after run (defaults to `true`).

### `paths` fields

- `template_file` (required): template input file path.
- `generated_input_file` (required): base filename used for generated per-case inputs.
- `physics_command` (required): string or string array command. The framework always appends the rendered input file path as the final argument.
- `physics_output_file` (required): base filename expected from the physics program.
- `results_file` (required): aggregated JSON output path.

### `variables` fields

Each item requires:

- `name`: placeholder variable name (example: `TEMPERATURE`).
- `kind`: `"distribution"` (Monte Carlo) or `"sweep"` (deterministic sweep).

For `kind: "distribution"`:

- `distribution` (required): `"uniform"`, `"normal"`/`"gaussian"`, `"choice"`, or `"truncated_normal"`.
- `uniform`: requires `min`, `max`.
- `normal`/`gaussian`: requires `mean`, `stddev`.
- `choice`: requires `values` (non-empty array).
- `truncated_normal`: requires `mean`, `stddev`, `min`, `max`.

For `kind: "sweep"`:

- Either `values` (explicit list), or all three of `min`, `max`, and `step`.

Mode compatibility:

- `monte_carlo` mode supports only `distribution` variables.
- `sweep` mode supports only `sweep` variables.

### `parsing` fields

Each rule requires:

- `name`: unique rule name.
- `type`: `"csv"` or `"regex"`.
- `target_file`: output filename to parse.

For `type: "csv"`:

- `columns` (required): mapping of result-field names to `{ "column": <header>, "type": <value_type> }`.

For `type: "regex"`:

- `start_pattern` (required): regex used to locate parse region start.
- `captures` (required): mapping of result-field names to `{ "pattern": <regex>, "type": <value_type>, ... }`.
- Optional: `context_before`, `context_after`, `required`.

Supported value types:

- `int`
- `float`
- `text`
- `bool`

## Execution modes

### Monte Carlo

Monte Carlo mode generates many cases by sampling variable values from distributions. Supported distributions:

- uniform
- normal / gaussian
- choice
- truncated_normal

### Sweep

Sweep mode iterates through fixed values or generated ranges. Supported sweep forms:

- explicit `values` list
- `min` / `max` / `step` range

Sweep behavior supports:

- Single variable iterates through every value of that variable in order.
- Nested for-loop produces the full Cartesian product.

## Parallel execution

The project supports multiple worker threads for running simulations concurrently. The design is intentionally conservative:

- the control file may set maximum thread count
- the framework reduces this to a safe number
- the final worker count is limited by:
  - the user request
  - the number of cases
  - the detected physical CPU cores minus 2

### Physical core preference

The framework makes a best-effort attempt to prefer physical CPU cores instead of hyperthreads. This is done using only the standard library. It is not CPU affinity pinning, and it does not require third-party packages.

### Worker directories

Each case writes its files inside the worker directory, including logs and output files. Each worker gets its own directory under:

```text
tmp/thread_<N>/
```

### Manual cleanup

Worker directories are preserved by default. That makes it easier to inspect logs after a run and manually delete only the directories you want to remove later.

## Directory layout example

A typical run may create files like this:

```text
project/
├── control.json
├── template.txt
├── results.json
├── tmp/
    ├── thread_01/
    │   ├── input_case_00001.txt
    │   ├── output_case_00001.txt
    │   ├── case_00001.stdout.log
    │   └── case_00001.stderr.log
    ├── thread_02/
    │   ├── input_case_00002.txt
    │   ├── output_case_00002.txt
    │   ├── case_00002.stdout.log
    │   └── case_00002.stderr.log
    └── ...
```

## Components

The project is structured around a small set of focused classes.

### `TemplateLoader`

Reads the template file and extracts placeholder names. Responsibilities:

- load template text
- extract placeholders
- validate placeholder syntax
- expose the template content in memory

### `CaseGenerator`

Generates all simulation cases. Responsibilities:

- generate Monte Carlo cases
- generate sweep cases
- support Cartesian sweep behavior based on variable order
- produce deterministic case dictionaries

### `DistributionSampler`

Samples one value from one distribution definition. Responsibilities:

- uniform sampling
- normal sampling
- choice sampling
- truncated_normal

### `Renderer`

Substitutes case values into the template. Responsibilities:

- replace placeholders with case values
- enforce strict missing-variable detection

### `SimulationRunner`

Runs the Physics executable. Responsibilities:

- launch the command locally
- capture stdout and stderr
- store logs in the worker directory
- track return codes

### `OutputParser`

Parses the output file. Responsibilities:

- parse CSV files with headers
- parse text output with regex rules
- convert values to the expected types
- handle missing matches according to rule settings

### `ResultCollector`

Stores the final results. Responsibilities:

- collect per-case records
- store parsed values
- store warnings and errors
- write the aggregated results file

### `WorkflowOrchestrator`

Coordinates the full pipeline. Responsibilities:

- load and validate the config
- validate template placeholders
- detect available physical cores
- compute worker count
- assign cases to workers
- execute cases in parallel
- collect results
- write final output

## Case generation details

### Monte Carlo generation

Monte Carlo mode samples a value for each distribution variable in each case. A single seeded random number generator makes the case set reproducible. Supported example distributions:

- uniform
- normal
- choice
- truncated_normal

### Sweep generation

Sweep mode generates values either from explicit lists or from `min` / `max` / `step` ranges.

The framework supports:

- simple one-variable sweeps
- Cartesian product of all sweep variables

## Output parsing

The output parser supports exactly two rule types.

### CSV parsing

Use this when the simulation writes structured output with headers. Behavior:

- read the file with `csv.DictReader`
- map columns to result fields
- convert values to the expected types
- fail clearly on malformed CSV

### Regex parsing

Use this when the output is plain text but predictable. Behavior:

- search for a starting pattern
- inspect nearby lines
- extract values using capture patterns
- support required and optional fields
- handle missing matches gracefully when allowed

This approach is intentionally simple and works well for text logs and summary blocks.

## Example control file: Monte Carlo

```json
{
  "execution": {
    "mode": "monte_carlo",
    "max_cases": 1000,
    "random_seed": 12345,
    "max_cpu_threads": 999,
    "prefer_physical_cores": true,
    "worker_dir_root": "tmp",
    "preserve_workdirs": true
  },
  "paths": {
    "template_file": "template.txt",
    "generated_input_file": "physics_input.txt",
    "physics_command": ["physics.exe"],
    "physics_output_file": "physics_output.txt",
    "results_file": "results.json"
  },
  "variables": [
    {
      "name": "TEMPERATURE",
      "kind": "distribution",
      "distribution": "truncated_normal",
      "mean": 300.0,
      "stddev": 12.5,
      "min": 250.0,
      "max": 350.0
    },
    {
      "name": "DISTANCE_1",
      "kind": "distribution",
      "distribution": "uniform",
      "min": 0.5,
      "max": 2.0
    },
    {
      "name": "TIME_STEP",
      "kind": "distribution",
      "distribution": "choice",
      "values": [0.001, 0.002, 0.005]
    }
  ],
  "parsing": [
    {
      "name": "summary_csv",
      "type": "csv",
      "target_file": "physics_output.txt",
      "columns": {
        "energy": { "column": "Energy", "type": "float" },
        "peak": { "column": "Peak", "type": "float" },
        "status": { "column": "Status", "type": "text" }
      }
    }
  ]
}
```

## Example control file: nested sweep

This example is equivalent to the loop:

```
for X_POS = 1.0 to 10.0 step 0.5
    for Y_POS = 1.0 to 5.0 step 0.25
    end
end
```

```json
{
  "execution": {
    "mode": "sweep",
    "max_cases": 100000,
    "random_seed": 98765,
    "max_cpu_threads": 999,
    "prefer_physical_cores": true,
    "worker_dir_root": "tmp",
    "preserve_workdirs": true
  },
  "paths": {
    "template_file": "template.txt",
    "generated_input_file": "physics_input.txt",
    "physics_command": ["physics.exe"],
    "physics_output_file": "physics_output.txt",
    "results_file": "results.json"
  },
  "variables": [
    {
      "name": "X_POS",
      "kind": "sweep",
      "min": 1.0,
      "max": 10.0,
      "step": 0.5
    },
    {
      "name": "Y_POS",
      "kind": "sweep",
      "min": 1.0,
      "max": 5.0,
      "step": 0.25
    }
  ],
  "parsing": [
    {
      "name": "final_metrics",
      "type": "regex",
      "start_pattern": "^RESULT SUMMARY$",
      "context_before": 0,
      "context_after": 6,
      "required": true,
      "captures": {
        "final_energy": {
          "pattern": "Final Energy\\s*=\\s*([-+0-9.eE]+)",
          "type": "float"
        },
        "iterations": {
          "pattern": "Iterations\\s*=\\s*(\\d+)",
          "type": "int"
        }
      }
    }
  ]
}
```
