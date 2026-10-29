# SparkTutor

Interactive Apache Spark 4.2 learning environment: a VS Code extension with Claude-powered tutoring that turns your IDE into a hands-on Spark classroom.

[![Demo](https://img.youtube.com/vi/LMDfyscN9FY/maxresdefault.jpg)](https://www.youtube.com/watch?v=LMDfyscN9FY)

**[Watch the full demo on YouTube](https://www.youtube.com/watch?v=LMDfyscN9FY)**

## What is SparkTutor?

SparkTutor is a learn-by-doing environment for Apache Spark 4.2. Instead of watching videos or reading docs, you write real PySpark code in VS Code with an AI tutor guiding you through structured lessons, from creating your first SparkSession to running a complete bronze-silver-gold pipeline with Spark Declarative Pipelines.

**Key features:**

- **Real code editor**: write PySpark in Monaco with full syntax highlighting, autocomplete, and bracket matching
- **Guided lessons**: courses on Spark fundamentals, Spark Declarative Pipelines (including Spark 4.2 Auto CDC) and what is new in Spark 4.x
- **Depth levels**: beginner (skeleton code + TODOs), intermediate (structural hints), advanced (just the objective)
- **AI-powered feedback**: submit code and get categorized feedback: bugs, conventions, and best practices (via Claude or GitHub Copilot)
- **AI tutor chat**: ask questions about your code or Spark concepts, grounded in official Spark 4.2 documentation
- **Real pipelines**: Declarative Pipelines exercises run with `spark-pipelines run` (or `dry-run`) against a generated project and a bundled sample dataset, and are graded by check datasets inside the pipeline itself
- **Zero-config in Codespaces**: works with GitHub Copilot out of the box, no API key needed
- **Cumulative exercises**: code persists across steps so a SparkSession you build in step 3 is still there in step 7
- **Session resume**: close VS Code, come back later, pick up where you left off

## Architecture

```
┌─ VS Code ──────────────────────────────────────────────────┐
│ ┌─ Activity Bar ─┐ ┌─ Editor ──────┐ ┌─ Lesson Panel ───┐ │
│ │ Courses        │ │ (Monaco)      │ │ (Webview)        │ │
│ │  └ Lesson 1 ✓  │ │ from pyspark  │ │ Step 3/8         │ │
│ │  └ Lesson 2 ●  │ │ df = spark... │ │ Create a DF...   │ │
│ │  └ Lesson 3    │ │ df.show()     │ │                  │ │
│ │                │ │               │ │ [Hint] [Submit]  │ │
│ │                │ │               │ │ ── Ask Tutor ──  │ │
│ │                │ │               │ │ > question_      │ │
│ └────────────────┘ └───────────────┘ └──────────────────┘ │
│ ● Lakehouse │ Step 3/8 │ Beginner │ AI: Claude  Status Bar │
└────────────────────────────────────────────────────────────┘
```

The extension uses a **bridge pattern**: TypeScript spawns a Python JSON-lines server (`python -m sparktutor.server`) that wraps the engine layer. Communication is via stdin/stdout; no HTTP, no ports, no configuration.

## Installation

### Option 1: GitHub Codespaces (zero setup)

Click the button below to launch a fully configured environment in your browser; no local install needed:

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/lisancao/sparktutor?quickstart=1)

The Codespace automatically installs all dependencies, builds the extension, and opens the SparkTutor sidebar. If you have a GitHub Copilot subscription, AI-powered code review and chat work out of the box; no API key required.

### Option 2: Local VS Code install

#### Prerequisites

- VS Code 1.93+
- Python 3.10+
- A JDK: Java 17 or 21 (Java 25 also works). PySpark bundles Spark's jars but not Java;
  check that `java -version` works in a terminal, or set `JAVA_HOME`.
- Node.js 20+ (for building the extension)
- Internet access the first time a lesson needs Delta Lake, Kafka or Spark's test catalog;
  SparkTutor downloads those jars from Maven Central once (see "Connectors" below)

#### Build and install

```bash
# Clone the repo
git clone https://github.com/lisancao/sparktutor.git
cd sparktutor

# Create a virtual environment in the repo (many systems block global pip installs)
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install Python dependencies (PySpark 4.2.0 with Connect and Declarative Pipelines)
pip install -e '.[spark]'

# Build and install the VS Code extension
cd sparktutor-vscode
npm install
bash package-vsix.sh
code --install-extension sparktutor-0.4.0.vsix
```

Then reload VS Code (`Ctrl+Shift+P`, then "Reload Window"). The extension finds the `.venv`
in the repo by itself; if you installed somewhere else, set `sparktutor.pythonPath`.

### Configure

Open VS Code settings (`Ctrl+,`) and search for "SparkTutor":

| Setting | Description |
|---------|-------------|
| `sparktutor.aiProvider` | AI backend: `auto` (default), `anthropic`, or `copilot` |
| `sparktutor.anthropicApiKey` | Anthropic API key (or set `ANTHROPIC_API_KEY` env var) |
| `sparktutor.claudeModel` | Claude model for review/chat (default: `claude-opus-5-5`; also `claude-sonnet-5-5`, `claude-haiku-5-5`) |
| `sparktutor.pythonPath` | Python interpreter with pyspark installed (default: empty, which uses `.venv` in the repo or workspace, else `python3`) |
| `sparktutor.projectPath` | Path to sparktutor repo root (auto-detected if installed via VSIX) |

### AI provider options

SparkTutor supports multiple AI backends for code review and chat:

| Provider | How to enable | Best for |
|----------|--------------|----------|
| **Claude (Anthropic)** | Set `sparktutor.anthropicApiKey` or `ANTHROPIC_API_KEY` env var | Highest quality feedback |
| **GitHub Copilot** | Install the [GitHub Copilot](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot) extension | Codespaces, students with Copilot subscriptions |
| **Local only** | No API key, no Copilot | Syntax/AST checks still work, no AI review |

In `auto` mode (default), SparkTutor uses Claude if an API key is set, falls back to Copilot if available, and runs local-only checks otherwise. The active provider is shown in the status bar.

## Usage

1. Click the SparkTutor icon in the activity bar (left sidebar)
2. Expand a course and click a lesson
3. Choose your depth level (Beginner / Intermediate / Advanced)
4. Read the lesson content in the right panel
5. Write code in the editor on the left
6. Use the buttons or keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+R` | Run code |
| `Ctrl+Shift+S` | Submit for evaluation |
| `Ctrl+Shift+N` | Next step |
| `Ctrl+Shift+B` | Previous step |
| `Ctrl+Shift+H` | Show hint |

## Course Content

All solutions are verified against PySpark 4.2.0 with `scripts/verify_solutions.py`.

### Learning Spark 4.2: From Fundamentals to Production

| # | Lesson | Highlights |
|---|--------|------------|
| 1 | Introduction & Getting Started | SparkSession, Spark 4 platform (Java 17/21/25, ANSI, Arrow), Classic vs Connect |
| 2 | DataFrames & Schemas | DDL schemas, `withColumns`, VARIANT and collations, ANSI casting with `try_*` |
| 3 | Data Sources & Formats | Parquet/CSV/JSON, built-in XML, JSON into VARIANT, Python Data Source API |
| 4 | Complex Types & Higher-Order Functions | arrays, maps, structs, `transform`/`filter`/`aggregate`, `IGNORE NULLS` (4.2) |
| 5 | Spark SQL & the Catalyst Optimizer | pipe syntax, `QUALIFY` (4.2), `time_bucket` (4.2), parameter markers, scripting |
| 6 | Optimization & Tuning | caching, AQE, partitioning, Arrow UDF defaults, the 4.2 Web UI |
| 7 | Join Strategies | broadcast, shuffle hash, sort-merge, skew, `NEAREST BY` (4.2) |
| 8 | Structured Streaming | watermarks, `availableNow`, `transformWithState`, Real-Time Mode (4.2) |
| 9 | Data Lakes & Lakehouses | A real Delta Lake 4.4.1 table: `MERGE`, time travel, history, change data feed; Spark 4.2's CDC API |
| 10 | Machine Learning with MLlib | pipelines, tuning, ML on Spark Connect |
| 11 | Spark Connect | architecture, connection strings, Classic vs Connect differences, 4.2 additions |

### Spark 4.2 Declarative Pipelines

Built on the real `pyspark.pipelines` API and the `spark-pipelines` CLI; every exercise runs as a pipeline.

| # | Lesson | What you build |
|---|--------|---------------|
| 1 | Why Declarative Pipelines | Your first materialized views |
| 2 | Datasets and Flows | Streaming tables, temporary views, `create_streaming_table` + `append_flow` |
| 3 | Pipeline Projects and the CLI | Spec files, `run` / `dry-run` / refresh options, SQL files; fix a broken graph |
| 4 | Bronze: Ingesting Raw Data | Append-only ingestion with explicit schemas and `_metadata` lineage |
| 5 | Silver: Types, Duplicates and Quarantine | `try_cast`, window dedup, silver + quarantine split |
| 6 | Gold: Aggregates for the Business | Running totals, ranks, shares, loop-generated datasets |
| 7 | Auto CDC (Spark 4.2) | SCD Type 1 with `create_auto_cdc_flow`, run against Spark's in-memory test catalog; Delta change feed and Kafka sources |
| 8 | Capstone: Raw Files to Gold | The full pipeline, a JSON sink, and cross-layer reconciliation checks |
| 9 | Under the Hood (optional) | A toy dependency-resolving pipeline runner in plain Python |

### What's New in Apache Spark 4.x

| # | Lesson | Features (version) |
|---|--------|--------------------|
| 1 | Spark 4 at a Glance | ANSI default and error classes (4.0), Connect (4.0), Arrow UDFs by default (4.2) |
| 2 | VARIANT | `parse_json`, `variant_get`, `:` paths (4.0/4.1) |
| 3 | SQL Pipe Syntax and QUALIFY | `|>` (4.0), `|` alias and pipe aggregates, `QUALIFY` (4.2) |
| 4 | SQL Scripting, SQL UDFs and the SQL Path | scripting (4.0/4.1), `SET PATH` (4.2), cursors (4.2, behind an internal flag) |
| 5 | Geospatial Types | `GEOMETRY` / `GEOGRAPHY` and `ST_*` functions (4.2) |
| 6 | Python Data Sources | batch, filter pushdown (4.1), streaming admission control (4.2) |
| 7 | Stateful Streaming with transformWithState | state variables, initial state, Real-Time Mode trigger (4.2) |
| 8 | CDC, NEAREST BY, time_bucket and Metric Views | Spark 4.2 analytics features |

### Messy Data with Apache Spark 4.2: Zero to Internals

Semi-structured, unstructured and multimodal data at three levels, from a first SparkSession to
writing Java connectors and reading Spark's source. Learners need only Python to start; the Java
lessons need a full JDK (`javac`). Sample files are synthetic, deterministic and generated by
`scripts/gen_messy_data.py` (plus one module per data folder in `scripts/messy_gen/`) into
`src/sparktutor/data/messy/`.

**Basics** (follows the chapters of *Learning Spark*)

| # | Lesson | Highlights |
|---|--------|------------|
| 1 | Why Spark for Messy Data, and How It Runs Your Code | driver, executors, tasks, stages, shuffles, where Python runs, the Spark UI |
| 2 | Setup, a First Session and a Tour of the Sample Data | install from zero, first errors, DataFrames and SQL, every sample folder |
| 3 | Schemas for Data You Don't Control | types, nullability, DDL vs `StructType`, inference pitfalls, drift detection |
| 4 | Columns and Expressions: Cleaning Values | ANSI mode and `try_*`, Unicode and collations, dates, money, nulls |
| 5 | Files as Files: binaryFile, Globs and Metadata | `binaryFile`, globs, `_metadata`, magic bytes, duplicates by hash |
| 6 | Text and Logs | `wholetext`, `regexp_extract_all`, stack traces, mixed text and JSON logs |
| 7 | CSV and Delimited Files | headers, quotes and escapes, locales and decimal commas, charsets, fixed width |
| 8 | JSON Drift and Quarantine | parse modes, corrupt-record columns, one schema that absorbs drift |
| 9 | Complex Types and Higher-Order Functions | structs, arrays, maps, lambdas, flattening by walking the schema |
| 10 | VARIANT Basics: Profiling and Nested Data | `:` paths and `::` casts, `variant_explode`, mixed types |
| 11 | XML | attributes and text nodes, "one child or many", `from_xml` |
| 12 | Binary Records: Avro and Protobuf | schema evolution, the Confluent wire format, proto3 defaults |
| 13 | Documents to Rows | e-mail in a UDF, PDF pages with a UDTF, Markdown paragraphs |
| 14 | Images and Audio | the `image` source, WAV parsing, time windows, streaming binary files |
| 15 | Your First Python Data Source | `DataSource`, `DataSourceReader`, partitions, options, testing without Spark |
| 16 | Plans, Partitions and Caching | `explain` field by field, AQE, file partitions, caching, partition pruning |
| 17 | Streaming Files: Your First Structured Streaming Job | triggers, checkpoints, restarts, `foreachBatch`, watermarks |
| 18 | Landing Messy Data in Delta Lake | bronze/silver/quarantine/gold, enforcement, MERGE, time travel, CDF |
| 19 | Text Analytics Without an LLM | TF-IDF search, MinHash near-duplicates |
| 20 | Running a Model over Your Data with pandas UDFs | pandas UDFs, load once per task, `mapInPandas` |
| 21 | What Spark 4.x Adds for Messy Data | geospatial types, collations, UTF-8 functions, TIME, exploration SQL |

**Intermediate** (production tools)

| # | Lesson | Highlights |
|---|--------|------------|
| 22 | Reading a Custom File Format, in Parallel | files as partitions, balancing by bytes, binary headers, user schemas |
| 23 | Reading from an API | pages as partitions, timeouts and retries, VARIANT payloads |
| 24 | Types, Arrow and Performance | type conversion, Arrow `RecordBatch`es, schema mismatch errors |
| 25 | Filter Pushdown | `pushFilters`, what Spark re-checks, the 4.2.0 flag and its traps |
| 26 | A Database Source: Partitions and Pushdown with SQLite | key ranges, filters to parameterized SQL, skew, snapshots |
| 27 | Writers | batch and Arrow writers, commit and abort, save modes |
| 28 | Streaming Readers and Writers | offsets, admission control, `availableNow`, stream writers |
| 29 | Packaging, Registration, Testing and Debugging | `pyspark_` auto-registration, testing readers, worker logs |
| 30 | Python UDTFs in Depth | `analyze()`, table arguments, lateral joins, lifecycle |
| 31 | VARIANT Shredding and Performance | shredded Parquet, when to promote fields to columns |
| 32 | Tuning Python on Spark | Python plan nodes, profilers, batch sizes, skew, output layout |
| 33 | Streaming Messy Data: Drift, Dead Letters and State | dead-letter routing, watermarks and late data, sessions, checkpoint compatibility |
| 34 | Production Ingestion: Quality Rules, Quarantine and Pipelines | rules as data, profiling, quality gates in Delta and Declarative Pipelines |
| 35 | Feature Vectors and Similarity Search | image and audio vectors, exact kNN, MLlib LSH, recall |
| 36 | Deduplication and Entity Resolution | blocking, fuzzy scoring, precision/recall, clustering, golden records |
| 37 | Model Inference in Production | caching by content hash, rate limits, retries, dead letters, idempotency |
| 38 | Capstone: An Unstructured Ingestion Source and a Catalog Pipeline | a Python data source and a Declarative Pipeline for the same catalog |

**Advanced** (inside the engine and extending it)

| # | Lesson | Highlights |
|---|--------|------------|
| 39 | How Catalyst Plans Python | analyzed to physical plans, Python plan nodes, how Python data sources and Connect plans are planned |
| 40 | The Python Worker Protocol | daemon and reuse, the socket protocol byte by byte, closures, worker failures |
| 41 | Memory, Spill and Very Large Files | the memory model, spill, `binaryFile` limits, chunked readers |
| 42 | A DSv2 Connector in Java | predicate, column, limit and aggregate pushdown, partitioning, runtime filters |
| 43 | Catalyst Extensions: Rules and Native Functions | `SparkSessionExtensions`, native expressions, codegen, rewriting Python UDFs |
| 44 | Spark Connect Plugins | relation, expression and command plugins with a Python client |
| 45 | Parquet from the Inside | footers, pages and encodings, statistics, column indexes, bloom filters |
| 46 | The VARIANT Binary Format | decoding and encoding VARIANT bytes, shredded reconstruction |
| 47 | Designing Tables for Blobs | inline vs pointers, content addressing, Delta features for media, deletion |
| 48 | Building LSH and an IVF Vector Index | MinHash banding from built-ins, IVF search, recall vs work |
| 49 | Distributed Connected Components | large-star/small-star, convergence, lineage and checkpoints |
| 50 | Sketches: HLL, Theta and KLL from the Inside | error bounds, merging stored sketches, set operations |
| 51 | Streaming Internals: Checkpoints, State and Real-Time Mode | checkpoint files, the state data source, `transformWithState`, RocksDB |
| 52 | Determinism, Retries and Fault Injection | retries and indeterminate stages, idempotency, chaos runs |
| 53 | Shipping Python Dependencies to a Cluster | `addPyFile`, archives, Connect artifacts, Kubernetes images |
| 54 | Observability: Listeners, Metrics and Profiling Executors | event logs as data, the REST API, profilers, py-spy |
| 55 | From Wrong Results to a Fix: An Upstream Case Study | a 4.2.0 wrong-results bug from repro to a patched build |
| 56 | Final Project: Your Own Connector | a full connector with pushdown, writer, streaming and tests, graded by stage |

### Known Spark 4.2.0 limitations covered in the lessons

Checked in October 2026 against PySpark 4.2.0, Delta Lake 4.4.1 and Iceberg 1.12.0:

- Auto CDC targets need Spark's DSv2 row-level operations. Parquet and Delta 4.4.1 targets are
  rejected, and no Iceberg release supports Spark 4.2 yet, so the Auto CDC exercise writes its
  target into Spark's in-memory test catalog. Sources are not the problem: a Delta change data
  feed and a Kafka topic both work as Auto CDC sources.
- Spark 4.2's `CHANGES` / `changes()` API fails on plain tables. Delta 4.4.1 has a batch-only
  preview behind an internal flag; for Delta, the lessons use its change data feed.
- `spark-pipelines` does not make `--packages` jars visible to pipeline code; use `--jars`.
- Several append flows into one parquet-backed streaming table can race on the file sink's commit
  log and lose rows.
- `drop(...)`, `dropDuplicates(...)` and `dropDuplicatesWithinWatermark(...)` on a pipeline
  dataset fail at flow registration; the lessons use window functions and explicit selects.
- A pipeline that reads a Python data source finishes its run, then `spark-pipelines` exits with
  `UNKNOWN_RESPONSE` (SPARK-59135, fixed in 4.4.0), so the Messy Data course keeps Python data
  sources in scripts.
- With `spark.sql.python.filterPushdown.enabled=true`, scans of the same Python data source DataFrame
  (or a view over it) share one planned read: a later unfiltered query returns the filtered rows, and a
  query that uses the source twice (a self-union or self-join) can be wrong on its first run. Master
  fixes it (SPARK-58551); 4.2.0 and the 4.3 branch don't. The lessons load a fresh DataFrame for each
  reference, and "From Wrong Results to a Fix" walks through the bug and a narrow fix.
- A plain `@udf` (Arrow-optimized by default in 4.2) applied to a column from a Parquet scan, directly
  or through some expressions, can hang forever on 4.2.0 (SPARK-58241, fixed in 4.2.1 and 4.3.0). Setting
  `spark.sql.execution.arrow.pythonUDF.columnarInput.enabled=false` avoids it; the advanced lessons
  "How Catalyst Plans Python" and "The Python Worker Protocol" explain it.
- A filter on a Python UDF's output column evaluates the UDF twice on 4.2.0 (the 4.2 guard covers Scala
  UDFs only; SPARK-59693 extends it to Python in 4.4.0).
- SQL cursors, CONTINUE handlers, the TIME type and streaming source naming sit behind internal
  flags that are off by default; the lessons say so where they mention them.

## How Evaluation Works

SparkTutor uses a two-layer evaluation system:

1. **Local checks (instant)**: syntax validation, AST structural checks, exact match, and for
   exercises that declare `Validation: [execution]`, the result of actually running the code
2. **Claude review (a few seconds)**: deep code review with categorized feedback

Feedback is categorized as:
- **Bug**: code won't work or doesn't satisfy the objective (blocks passing)
- **Convention**: code works but doesn't follow PySpark/Python conventions
- **Best Practice**: optional improvements (shown at intermediate/advanced levels)

Spark 4 error classes (`TABLE_OR_VIEW_NOT_FOUND`, `UNRESOLVED_COLUMN`, `CAST_INVALID_INPUT`,
`USER_RAISED_EXCEPTION`, `AUTOCDC_*`, `PIPELINE_*`) are translated into plain-language feedback.

Each code step has its own file, `~/.sparktutor/workspace/<course>/<lesson>/step_NN.py`, holding
the step's starter code and your work on it. Submitting sends only that file.

### Declarative Pipelines exercises

A file that imports `pyspark.pipelines` is not run with `spark-submit`. The executor lays it out
as a pipeline project (`transformations/exercise.py`, a generated `spark-pipeline.yml`, and the
sample dataset in `data/`) and runs `spark-pipelines run`. A first line of
`# spark-pipelines: dry-run` runs `spark-pipelines dry-run` instead. Exercises embed their checks
as `check_*` materialized views that call `assert_true`, so a successful run means every check
passed; after a run the tutor prints the contents of each table the pipeline wrote.

### Connectors

Delta Lake, Kafka, Spark's Avro and Protobuf modules and Spark's in-memory test catalog are not
part of pyspark. An exercise that needs one starts with a line like `# spark-connectors: delta`
(or `kafka`, `avro`, `protobuf`, `test-catalog`; separate several with commas).
SparkTutor then downloads the jars from Maven Central into `~/.sparktutor/jars` once and passes
them with `--jars` (plus any settings the connector needs) to `spark-submit` or
`spark-pipelines`. The lessons show the equivalent commands for running on your own.

### Exercises that start their own session

An exercise whose first lines include `# spark-run: python` runs as plain `python exercise.py`
instead of under `spark-submit`, so the script can create its own session with static settings
(`spark.jars`, `spark.sql.extensions`, Spark Connect plugin classes). The advanced Java lessons use
it to compile Java with `javac` against pyspark's jars and load the result. It works in local mode
only, and it can't be combined with `# spark-connectors:` (pass jars through `spark.jars` instead).

### Troubleshooting

- **Declarative Pipelines exercises fail to start, or behave strangely.** `spark-pipelines`
  starts a local Spark Connect server, and its client always connects to `localhost:15002`. If
  another Spark Connect server (a Docker container, another notebook) already listens on that
  port, stop it first.
- **`--packages` fails with `download failed` for a jar that exists on Maven Central.** Spark's
  resolver also reads `~/.m2/repository`, and an earlier Maven build can leave a library's
  metadata there without its jar. Delete that library's folder under `~/.m2/repository`.
- **Running a pipeline twice on your own fails with `LOCATION_ALREADY_EXISTS`.** The local
  server's default catalog is in memory and forgets tables between runs. Start from a clean
  project and pass `--conf spark.sql.catalogImplementation=hive` on every run. (SparkTutor runs
  each exercise in a fresh directory, so this only matters outside the tutor.)

## Depth-Aware Scaffolding

The starter code adapts to your level:

**Beginner**: full skeleton with imports, structure, and TODO comments:
```python
from pyspark.sql import SparkSession

# TODO: Create a SparkSession using the builder pattern
# Hint: SparkSession.builder.appName(...)
spark = (SparkSession.builder
    # TODO: set your app name and any configs
    .getOrCreate())
```

**Intermediate**: concept hints showing what APIs to use:
```python
# Create a SparkSession named 'PipelineApp' with shuffle partitions set to 8.
#
# Key APIs/concepts to use:
#   - SparkSession.builder (builder pattern)
#   - .appName(): set application name
#   - .config('spark.sql.shuffle.partitions', ...): configuration key
#   - .getOrCreate(): create or reuse session
```

**Advanced**: just the objective:
```python
# Create a SparkSession named 'PipelineApp' with shuffle partitions set to 8.
```

## Project Structure

```
sparktutor/
├── src/sparktutor/
│   ├── engine/          # Core tutoring engine
│   │   ├── evaluator.py       # Two-layer evaluation (AST + Claude)
│   │   ├── executor.py        # Code execution (lakehouse/local/dry-run)
│   │   ├── lesson_runner.py   # Lesson state machine
│   │   ├── scaffolding.py     # Depth-aware starter code generation
│   │   └── spark_knowledge.py # Curated Spark 4.2 reference
│   ├── server/          # JSON-lines server for VS Code bridge
│   │   ├── handler.py         # RPC method dispatch
│   │   └── protocol.py        # Request/Response/Notification types
│   ├── courses/         # Course content (YAML + starter/solution files)
│   ├── data/            # Sample retail dataset copied into pipeline exercises
│   ├── config/          # Settings (Pydantic models)
│   └── state/           # SQLite progress tracking
├── sparktutor-vscode/   # VS Code extension
│   ├── src/             # TypeScript source
│   ├── media/           # CSS, JS, icons for webview
│   └── package.json     # Extension manifest
├── scripts/
│   └── verify_solutions.py    # Run every lesson solution against local Spark
└── tests/
```

## Development

```bash
# Install the test dependencies too
pip install -e '.[spark,dev]'

# Run tests
PYTHONPATH=src python3 -m pytest tests/ -v

# Run every lesson's solution on local Spark (spark-submit / spark-pipelines)
python scripts/verify_solutions.py
python scripts/verify_solutions.py spark_declarative_pipelines/07_auto_cdc

# Build extension (dev mode)
cd sparktutor-vscode && npm run build

# Launch in dev mode (F5 in VS Code)
# Open sparktutor-vscode/ in VS Code, press F5

# Package VSIX
bash sparktutor-vscode/package-vsix.sh
```

## License

MIT
