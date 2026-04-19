# orchestrator

`orchestrator` automates, manages, and controls the input, output, and execution of a numerical simulation.

It is a local-only Python framework for driving a black-box Physics executable using only the Python standard library. The project is designed for offline scientific workflows where a text template is filled with case-specific values, the simulation is run locally, the output is parsed, and the results are collected for later analysis.

## Overview

`orchestrator` provides an end-to-end batch execution pipeline for simulations that behave like a black box.

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

The framework supports both:

- Monte Carlo sampling
- deterministic numerical sweeps

It also supports parallel execution with worker threads, per-worker local directories, reproducible random seeds, CSV parsing, and regex-based output extraction.

## Design goals

This project is intentionally simple and opinionated.

The main goals are:

- use only the Python standard library
- support offline execution
- keep simulation runs reproducible
- validate everything before expensive runs begin
- isolate worker files to prevent collisions
- preserve logs for manual inspection
- keep the code easy to split into small modules later
- support both stochastic and deterministic case generation

## Key idea

The Physics executable is treated as a black box.

The Python framework does not try to interpret the Physics model itself. It only:

- prepares the input file
- launches the executable
- observes the output file
- parses result values
- stores the results

The black box is responsible for reading the generated Physics input file and writing the correct output file.

## Template system

The Physics input template is a plain text file with placeholders such as:

- `{{TEMPERATURE}}`
- `{{DISTANCE_1}}`
- `{{TIME_STEP}}`
- `{{OUTPUT_FILENAME}}`

The placeholder format is strict:

- placeholder syntax: `{{VAR_NAME}}`
- variable names must match `^[A-Z][A-Z0-9_]*$`
- only uppercase names are allowed
- substitution is literal, not evaluated

### Why this works well

This convention is practical because it is:

- easy to read
- easy to validate
- safe for offline use
- unlikely to conflict with the Physics syntax
- simple to implement with the standard library

### Template validation

Before any simulation begins, the framework validates that:

- every placeholder in the template is defined in the control file
- every variable in the control file is used by the template
- placeholder syntax is valid
- the template contains no malformed placeholder tokens

This fail-fast behavior prevents wasted simulation time.

## `OUTPUT_FILENAME`

The control file must always define the output result file path in `paths.physics_output_file`.

If the template also contains `{{OUTPUT_FILENAME}}`, the framework fills it with a worker-local path, such as:

```text
tmp/thread_03/output_case_00017.txt
```

This means the Physics input file can direct the black-box executable to write output into the correct isolated worker directory.

The executable itself remains responsible for using the input file and writing the correct output file.

## Control file

The control file is JSON.

It is designed to be easy to parse with `json` and `dataclasses`, and it should remain clean and explicit.

### Recommended top-level structure

- `execution`
- `paths`
- `variables`
- `parsing`

### `execution`

Contains runtime settings such as:

- `mode`
- `max_cases`
- `random_seed`
- `max_cpu_threads`
- `prefer_physical_cores`
- `worker_dir_root`
- `preserve_workdirs`

### `paths`

Contains file and command locations:

- `template_file`
- `generated_input_file`
- `physics_command`
- `physics_output_file`
- `results_file`

### `variables`

Defines the simulation variables.

Each variable includes:

- `name`
- `kind`
- distribution or sweep settings
- optional group information for paired sweep iteration

### `parsing`

Defines how to extract values from output files.

Each rule includes:

- `name`
- `type`
- `target_file`
- extraction details

## Execution modes

### Monte Carlo

Monte Carlo mode generates many cases by sampling variable values from distributions.

Supported distributions:

- uniform
- normal / gaussian
- choice
- truncated normal

Truncated normal is implemented using rejection sampling.

### Sweep

Sweep mode iterates through fixed values or generated ranges.

Supported sweep forms:

- explicit `values`
- `min` / `max` / `step`

Sweep behavior supports:

- Cartesian product across independent variables
- paired iteration for aligned variables

## Parallel execution

The project supports multiple worker threads for running simulations concurrently.

The design is intentionally conservative:

- the control file may request a large number such as `999`
- the framework reduces this to a safe number
- the final worker count is limited by:
  - the user request
  - the number of cases
  - the detected physical CPU cores minus 2

The goal is to avoid oversubscribing the machine.

### Physical core preference

The framework makes a best-effort attempt to prefer physical CPU cores instead of hyperthreads.

This is done using only the standard library. It is not CPU affinity pinning, and it does not require third-party packages.

### Worker directories

Each worker gets its own directory under:

```text
tmp/thread_<N>/
```

This keeps runs isolated and avoids file collisions.

Example:

```text
tmp/thread_01/
tmp/thread_02/
tmp/thread_03/
```

Each case writes its files inside the worker directory, including logs and output files.

### Manual cleanup

Worker directories are preserved by default.

That makes it easier to inspect logs after a run and manually delete only the directories you want to remove later.

## Directory layout example

A typical run may create files like this:

```text
project/
├── control.json
├── physics_template.in
├── physics_case.in
├── tmp/
│   ├── thread_01/
│   │   ├── input_case_00001.in
│   │   ├── output_case_00001.txt
│   │   ├── case_00001.stdout.log
│   │   └── case_00001.stderr.log
│   ├── thread_02/
│   │   ├── input_case_00002.in
│   │   ├── output_case_00002.txt
│   │   ├── case_00002.stdout.log
│   │   └── case_00002.stderr.log
│   └── thread_03/
│       ├── input_case_00003.in
│       ├── output_case_00003.txt
│       ├── case_00003.stdout.log
│       └── case_00003.stderr.log
└── results/
    └── results.json
```

## Components

The project is structured around a small set of focused classes.

### `TemplateLoader`

Reads the template file and extracts placeholder names.

Responsibilities:

- load template text
- extract placeholders
- validate placeholder syntax
- expose the template content in memory

### `CaseGenerator`

Generates all simulation cases.

Responsibilities:

- generate Monte Carlo cases
- generate sweep cases
- support paired and Cartesian sweep behavior
- produce deterministic case dictionaries

### `DistributionSampler`

Samples one value from one distribution definition.

Responsibilities:

- uniform sampling
- normal sampling
- choice sampling
- truncated normal via rejection sampling

### `Renderer`

Substitutes case values into the template.

Responsibilities:

- replace placeholders with case values
- render `OUTPUT_FILENAME`
- enforce strict missing-variable detection

### `SimulationRunner`

Runs the Physics executable.

Responsibilities:

- launch the command locally
- capture stdout and stderr
- store logs in the worker directory
- track return codes

### `OutputParser`

Parses the output file.

Responsibilities:

- parse CSV files with headers
- parse text output with regex rules
- convert values to the expected types
- handle missing matches according to rule settings

### `ResultCollector`

Stores the final results.

Responsibilities:

- collect per-case records
- store parsed values
- store warnings and errors
- write the aggregated results file

### `WorkflowOrchestrator`

Coordinates the full pipeline.

Responsibilities:

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

Monte Carlo mode samples a value for each distribution variable in each case.

Supported example distributions:

- uniform
- normal
- choice
- truncated normal

A single seeded random number generator makes the case set reproducible.

### Sweep generation

Sweep mode generates values either from explicit lists or from `min` / `max` / `step` ranges.

The framework supports:

- simple one-variable sweeps
- paired sweeps where variables advance together
- Cartesian product of independent sweep groups

### Floating-point step handling

Floating-point range generation is handled carefully to avoid drift.

The implementation should generate values by index rather than by repeated addition.

That helps prevent issues like:

- `0.30000000000000004`
- missed end points
- off-by-one errors caused by floating-point accumulation

## Output parsing

The output parser supports exactly two rule types.

### CSV parsing

Use this when the simulation writes structured output with headers.

Behavior:

- read the file with `csv.DictReader`
- map columns to result fields
- convert values to the expected types
- fail clearly on malformed CSV

### Regex parsing

Use this when the output is plain text but predictable.

Behavior:

- search for a starting pattern
- inspect nearby lines
- extract values using capture patterns
- support required and optional fields
- handle missing matches gracefully when allowed

This approach is intentionally simple and works well for text logs and summary blocks.

## Error handling

The project is designed to fail early when possible and record runtime issues per case.

Common validation failures include:

- missing placeholders in the template
- extra variables in the control file
- invalid variable names
- invalid distribution settings
- sweep length mismatch for paired variables
- malformed parsing rules

Common runtime failures include:

- executable returns a nonzero exit code
- output file is missing
- CSV output is malformed
- regex extraction fails
- file creation fails in a worker directory

The framework should keep running remaining cases even if some cases fail.

## Reproducibility

Monte Carlo runs are reproducible.

The same:

- control file
- template file
- random seed

will produce the same generated case list.

Parallel execution does not change the generated cases because case generation happens before worker dispatch.

## Standard library only

The implementation uses only Python’s standard library.

Typical modules include:

- `json`
- `re`
- `csv`
- `random`
- `math`
- `itertools`
- `subprocess`
- `pathlib`
- `dataclasses`
- `typing`
- `copy`
- `os`
- `threading`
- `concurrent.futures`
- `queue`
- `decimal`

No external packages are required.

## Planned project structure

A clean implementation can later be split into separate files.

A possible structure is:

```text
orchestrator/
├── __init__.py
├── config.py
├── template.py
├── sampling.py
├── cases.py
├── render.py
├── runner.py
├── parser.py
├── results.py
└── workflow.py
```

This README assumes the classes may initially live in a smaller number of files and later be split into one class per file or one related class group per file.

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
    "template_file": "templates/physics_template.in",
    "generated_input_file": "generated/physics_case.in",
    "physics_command": "Physics.exe",
    "physics_output_file": "physics_output.txt",
    "results_file": "results/monte_carlo_results.json"
  },
  "variables": [
    {
      "name": "TEMPERATURE",
      "kind": "distribution",
      "distribution": "truncated_normal",
      "mean": 300.0,
      "stddev": 12.5,
      "min": 250.0,
      "max": 350.0,
      "max_tries": 5000
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

## Example control file: sweep with two paired variables

```json
{
  "execution": {
    "mode": "sweep",
    "max_cases": 100,
    "random_seed": 98765,
    "max_cpu_threads": 999,
    "prefer_physical_cores": true,
    "worker_dir_root": "tmp",
    "preserve_workdirs": true
  },
  "paths": {
    "template_file": "templates/physics_template.in",
    "generated_input_file": "generated/physics_case.in",
    "physics_command": "Physics.exe",
    "physics_output_file": "physics_output.txt",
    "results_file": "results/sweep_results.json"
  },
  "variables": [
    {
      "name": "TEMPERATURE",
      "kind": "sweep",
      "iteration": "paired",
      "group": "pair_1",
      "values": [290.0, 300.0, 310.0, 320.0]
    },
    {
      "name": "PRESSURE",
      "kind": "sweep",
      "iteration": "paired",
      "group": "pair_1",
      "values": [1.0, 1.2, 1.4, 1.6]
    }
  ],
  "parsing": [
    {
      "name": "final_metrics",
      "type": "regex",
      "target_file": "physics_output.txt",
      "start_pattern": "^RESULT SUMMARY$",
      "context_before": 0,
      "context_after": 6,
      "required": true,
      "captures": {
        "final_energy": {
          "pattern": "Final Energy\s*=\s*([-+0-9.eE]+)",
          "type": "float"
        },
        "iterations": {
          "pattern": "Iterations\s*=\s*(\d+)",
          "type": "int"
        }
      }
    }
  ]
}
```

## Example output file handling

The framework expects the Physics model to write an output file. The output path used by the executable is set through the template placeholder `{{OUTPUT_FILENAME}}` when present.

Example resolved path for a case:

```text
tmp/thread_03/output_case_00017.txt
```

This file stays inside the worker directory so that the entire run remains isolated and easy to inspect.

## Intended workflow

1. create a JSON control file
2. create a Physics template file with placeholders
3. run `orchestrator`
4. inspect worker directories if needed
5. review the aggregated results file
6. manually delete worker directories after confirming success

## Status

This project is intended as a practical, offline workflow manager for numerical simulation runs.

It is built to be:

- explicit
- reproducible
- easy to validate
- easy to debug
- easy to extend
- easy to split into smaller class files later
