# Python-to-Rust MLOps Package Migration Plan (v2 — Decisions Finalized)

> **Goal:** Migrate the `mlops-python-package` (a regression model template with DDD architecture, MLflow integration, Kafka controller, and CI/CD) to an idiomatic Rust implementation in `mlops-rust-package`, preserving all functionality while leveraging Rust's type system, performance, and safety guarantees.

---

## Resolved Design Decisions

All five open questions from v1 have been answered. These decisions are **final** and drive every component below.

| # | Question | Decision | Impact |
|---|----------|----------|--------|
| 1 | **Random Forest** — `linfa-trees` (pure Rust) vs `pyo3`→scikit-learn? | **Pure Rust** — `BaselineLinfoModel` using `linfa-trees::RandomForestRegressor`. No Python dependency. | Results will NOT be bit-identical to Python; acceptable trade-off for zero FFI complexity. |
| 2 | **MLflow compatibility** — ONNX / PyFunc wrapper for Python ecosystem? | **Custom binary format** — Models serialized with `bincode` (or `serde`-derived binary), uploaded as MLflow artifacts via REST API 2.0. No ONNX, no PyFunc. | Models are Rust-only; Python ecosystem cannot load them directly. MLflow serves as experiment tracker + artifact store only. |
| 3 | **SHAP values** — Native Rust vs Python sidecar? | **Native Rust** — Custom `TreeExplainer` implementation, scoped strictly to `RandomForestRegressor` trees. | Significant implementation effort (~500–800 LoC); no Python sidecar needed. |
| 4 | **Parquet data** — Copy vs shared reference? | **Polars native** — `polars::io::parquet` for read/write. Data files will live in `data/` inside the Rust project (copied from Python project). | No pandas dependency; Polars handles all DataFrame operations. |
| 5 | **OpenTelemetry** — Full OTEL vs `tracing` only? | **Full OTEL stack** — `tracing` + `tracing-subscriber` + `tracing-opentelemetry` + `opentelemetry-otlp`. Replaces Loguru + Python OTEL SDK. | Same observability level as Python; distributed tracing and structured logging preserved. |

---

## Source Project Analysis

The Python project (`mlops-python-package`) is a full MLOps pipeline structured with Domain-Driven Design:

| Layer | Python Module | Purpose |
|-------|-------------|---------|
| **Domain** | `core/schemas.py` | DataFrame schemas (Pandera): `InputsSchema`, `TargetsSchema`, `OutputsSchema`, `SHAPValuesSchema`, `FeatureImportancesSchema` |
| **Domain** | `core/models.py` | Abstract `Model` + `BaselineSklearnModel` (RandomForest pipeline with OneHotEncoder) |
| **Domain** | `core/metrics.py` | Abstract `Metric` + `SklearnMetric` (MSE, R², etc.) + `Threshold` |
| **Application** | `jobs/base.py` | Abstract `Job` with context manager (logger, alerts, mlflow services) |
| **Application** | `jobs/training.py` | Full train pipeline: read → split → fit → score → sign → save → register |
| **Application** | `jobs/evaluations.py` | Load registered model → evaluate with thresholds |
| **Application** | `jobs/inference.py` | Load model → batch predict → write outputs |
| **Application** | `jobs/tuning.py` | Grid search CV hyperparameter optimization |
| **Application** | `jobs/explanations.py` | Feature importances + SHAP values |
| **Application** | `jobs/promotion.py` | Set MLflow model alias (Champion/Challenger) |
| **Infrastructure** | `io/services.py` | `LoggerService` (loguru+OTEL), `AlertsService` (plyer), `MlflowService` |
| **Infrastructure** | `io/datasets.py` | `ParquetReader`/`ParquetWriter` with MLflow lineage |
| **Infrastructure** | `io/registries.py` | `Saver`, `Loader`, `Register` for MLflow model registry |
| **Infrastructure** | `io/configs.py` | OmegaConf YAML config parsing & merging |
| **Infrastructure** | `io/osvariables.py` | Env vars via `pydantic-settings` (Singleton) |
| **Interface** | `controller/kafka_app.py` | FastAPI + Kafka consumer/producer for real-time predictions |
| **Interface** | `scripts.py` | CLI entry point (argparse → config → settings → job.run()) |
| **Utilities** | `utils/splitters.py` | `TrainTestSplitter`, `TimeSeriesSplitter` |
| **Utilities** | `utils/searchers.py` | `GridCVSearcher` (sklearn GridSearchCV) |
| **Utilities** | `utils/signers.py` | `InferSigner` (MLflow model signatures) |

---

## User Review Required

> [!IMPORTANT]
> **ML Library Strategy (DECIDED)**: Pure Rust with `linfa-trees`. Results will not be bit-identical to Python scikit-learn. This is the accepted trade-off for a zero-FFI, fully native architecture.

> [!IMPORTANT]
> **MLflow Integration (DECIDED)**: All MLflow interaction via REST API 2.0 (`reqwest`). Models stored as custom binary artifacts (`bincode`). The Rust models are **not** loadable from Python MLflow. MLflow is used as experiment tracker and artifact store only.

> [!WARNING]
> **SHAP TreeExplainer (DECIDED)**: Custom Rust implementation scoped to `RandomForestRegressor` only. This is the highest-risk component (~500–800 LoC of non-trivial tree traversal logic). It will be implemented in Phase 2 with extensive property-based testing.

> [!WARNING]
> **Kafka Controller**: The Python version uses `confluent-kafka` + FastAPI + uvicorn. The Rust version will use `rdkafka` + `axum` + `tokio`, which is a full rewrite of the real-time serving layer.

---

## Proposed Changes

### Rust Crate Architecture (Workspace)

The project will be structured as a **Cargo workspace** with multiple crates, directly mapping DDD layers:

```
mlops-rust-package/
├── Cargo.toml                    # Workspace root
├── Cargo.lock
├── .github/
│   └── workflows/
│       ├── check.yml
│       └── publish.yml
├── confs/                        # YAML job configs (identical format)
│   ├── training.yaml
│   ├── evaluations.yaml
│   ├── inference.yaml
│   ├── tuning.yaml
│   ├── explanations.yaml
│   └── promotion.yaml
├── data/                         # Parquet data files (copied from Python project)
│   ├── inputs_train.parquet
│   └── targets_train.parquet
├── Dockerfile
├── docker-compose.yml
├── README.md
├── LICENCE.txt
├── .env
│
├── crates/
│   ├── domain/                   # Pure domain logic (no external deps except serde)
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── schemas.rs        # Typed DataFrame schemas (Polars validation)
│   │       ├── models.rs         # Model trait + BaselineLinfoModel (linfa-trees)
│   │       ├── metrics.rs        # Metric trait + native MSE/R²/MAE
│   │       └── explainers.rs     # Custom TreeExplainer (SHAP)
│   │
│   ├── application/              # Use cases / jobs
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── base.rs           # Job trait with service lifecycle (Drop-based)
│   │       ├── training.rs
│   │       ├── evaluations.rs
│   │       ├── inference.rs
│   │       ├── tuning.rs
│   │       ├── explanations.rs
│   │       └── promotion.rs
│   │
│   ├── infrastructure/           # External integrations
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── services/
│   │       │   ├── mod.rs
│   │       │   ├── logger.rs     # tracing + tracing-opentelemetry + opentelemetry-otlp
│   │       │   ├── alerts.rs     # Desktop notifications (notify-rust) / stdout
│   │       │   └── mlflow.rs     # MLflow REST API 2.0 client (reqwest)
│   │       ├── datasets/
│   │       │   ├── mod.rs
│   │       │   ├── reader.rs     # Parquet reader (polars)
│   │       │   └── writer.rs     # Parquet writer (polars)
│   │       ├── registries/
│   │       │   ├── mod.rs
│   │       │   ├── saver.rs      # bincode serialize + MLflow artifact upload
│   │       │   ├── loader.rs     # MLflow artifact download + bincode deserialize
│   │       │   └── register.rs   # MLflow model registration via REST
│   │       ├── configs.rs        # YAML config parsing (serde_yaml + recursive merge)
│   │       └── env.rs            # Environment variables (envy + dotenvy + once_cell)
│   │
│   ├── interface/                # External-facing APIs
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── cli.rs            # CLI (clap derive)
│   │       └── kafka_app.rs      # Axum + rdkafka + tokio
│   │
│   └── utils/                    # Cross-cutting utilities
│       ├── Cargo.toml
│       └── src/
│           ├── lib.rs
│           ├── splitters.rs      # Train/test splitting (rand-based)
│           ├── searchers.rs      # Grid search CV (rayon parallel)
│           └── signers.rs        # Model signature generation (JSON)
│
└── tests/                        # Integration tests
    ├── common/
    │   └── mod.rs                # Shared test fixtures
    ├── core_tests.rs
    ├── io_tests.rs
    ├── jobs_tests.rs
    └── utils_tests.rs
```

---

### Component 1: Domain Layer (`crates/domain`)

#### [NEW] Cargo.toml
- Dependencies: `serde`, `serde_json`, `thiserror`, `polars`, `linfa`, `linfa-trees`, `ndarray`, `bincode`
- No framework dependencies — pure domain logic

#### [NEW] schemas.rs
Migrates `schemas.py`:
- Replace Pandera `DataFrameModel` with Polars `DataFrame` + Rust validation structs
- `InputsSchema` → Rust struct with typed validation methods matching all 15 columns
- `TargetsSchema` → `instant` (index, u32), `cnt` (u32, ≥0)
- `OutputsSchema` → `instant` (index, u32), `prediction` (u32, ≥0)
- `SHAPValuesSchema` → dynamic columns (f32), no strict column check
- `FeatureImportancesSchema` → `feature` (String), `importance` (f64)

```rust
pub struct InputsSchema;
pub type Inputs = DataFrame;
pub type Targets = DataFrame;
pub type Outputs = DataFrame;
pub type SHAPValues = DataFrame;
pub type FeatureImportances = DataFrame;

impl InputsSchema {
    pub fn check(df: &DataFrame) -> Result<DataFrame, SchemaError>;
}
```

#### [NEW] models.rs
Migrates `models.py`:

**Decision 1: Pure Rust `linfa-trees`**

- `Model` abstract class → `Model` trait
- `BaselineSklearnModel` → `BaselineLinfoModel` using `linfa-trees::RandomForestRegressor`
- Column transformer → **manual one-hot encoding with Polars `to_dummies()`**
- Model serialization → `bincode` + `serde::Serialize/Deserialize` (Decision 2)

```rust
pub trait Model: Send + Sync {
    fn fit(&mut self, inputs: &Inputs, targets: &Targets) -> Result<(), ModelError>;
    fn predict(&self, inputs: &Inputs) -> Result<Outputs, ModelError>;
    fn explain_model(&self) -> Result<FeatureImportances, ModelError>;
    fn explain_samples(&self, inputs: &Inputs) -> Result<SHAPValues, ModelError>;
    fn get_params(&self) -> Params;
    fn set_params(&mut self, params: &Params) -> Result<(), ModelError>;
}

#[derive(Serialize, Deserialize)]
pub struct BaselineLinfoModel {
    pub max_depth: Option<usize>,
    pub n_estimators: usize,
    pub random_state: Option<u64>,
    fitted_forest: Option<FittedRandomForestRegressor>,
    feature_names: Vec<String>,
    categoricals: Vec<String>,
    numericals: Vec<String>,
}

#[derive(Serialize, Deserialize)]
pub enum ModelKind {
    BaselineLinfoModel(BaselineLinfoModel),
}
```

#### [NEW] explainers.rs

**Decision 3: Custom Rust TreeExplainer**

- Tree Path-dependent Shapley value computation
- Scoped strictly to `RandomForestRegressor`
- ~500–800 LoC estimated
- Property-based testing with `proptest`

```rust
pub struct TreeExplainer<'a> {
    forest: &'a FittedRandomForestRegressor,
    baseline: f64,
}

impl<'a> TreeExplainer<'a> {
    pub fn new(forest: &'a FittedRandomForestRegressor, training_data: &Inputs) -> Self;
    pub fn shap_values(&self, inputs: &Inputs) -> Result<SHAPValues, ExplainerError>;
    pub fn feature_importances(&self) -> Result<FeatureImportances, ExplainerError>;
}
```

#### [NEW] metrics.rs
Migrates `metrics.py`:
- Manual implementations: `MeanSquaredError`, `R2Score`, `MeanAbsoluteError`
- `Threshold` struct with `min_value` / `max_value`

---

### Component 2: Infrastructure Layer (`crates/infrastructure`)

#### [NEW] configs.rs
- OmegaConf → `serde_yaml` + custom recursive merge logic

#### [NEW] env.rs
- `pydantic-settings` → `envy` + `dotenvy` + `once_cell::sync::Lazy`

#### [NEW] services/logger.rs

**Decision 5: Full OTEL stack**

- `tracing` + `tracing-subscriber` + `tracing-opentelemetry` + `opentelemetry-otlp`
- OTEL logging via `opentelemetry-appender-tracing`
- Resource: `service.name = "Regression Model"`
- `OtelGuard` with `Drop` for flushing

#### [NEW] services/alerts.rs
- `notify-rust` for Linux desktop notifications
- Fallback to `println!`

#### [NEW] services/mlflow.rs

**Decision 2: REST API only**

- Full MLflow REST API 2.0 client via `reqwest`
- `RunGuard` RAII pattern (create on `new`, FINISHED on `Drop`)
- Metric/param logging, batch logging

#### [NEW] datasets/reader.rs & writer.rs

**Decision 4: Polars native**

- `polars::io::parquet` for all Parquet I/O

#### [NEW] registries/

**Decision 2: Custom binary format**

| Python Component | Rust Replacement |
|-----------------|-----------------|
| `CustomSaver` (PyFunc) | `BincodeSaver` — serialize + upload artifact |
| `BuiltinSaver` | **Removed** |
| `CustomLoader` (PyFunc) | `BincodeLoader` — download + deserialize |
| `BuiltinLoader` | **Removed** |
| `MlflowRegister` | `RestRegister` — REST API |

---

### Component 3: Application Layer (`crates/application`)

#### [NEW] base.rs
- `Job` trait + `JobContext` RAII struct with `Drop`

#### [NEW] training.rs
- Full pipeline: read → validate → lineage → split → fit → predict → score → sign → save → register → notify

#### [NEW] evaluations.rs
- Custom evaluation loop + REST metric logging + threshold validation

#### [NEW] inference.rs, tuning.rs, explanations.rs, promotion.rs
- Equivalent logic using Rust components

---

### Component 4: Interface Layer (`crates/interface`)

#### [NEW] cli.rs
- `clap` derive API, same interface as Python

#### [NEW] kafka_app.rs
- `axum` + `rdkafka` + `tokio`
- Same endpoints: `POST /predict`, `GET /health`

---

### Component 5: Utilities (`crates/utils`)

#### [NEW] splitters.rs — `rand`-based train/test split
#### [NEW] searchers.rs — `rayon`-parallel GridSearchCV
#### [NEW] signers.rs — Model signature → JSON

---

### Component 6: Build, CI/CD & DevOps

#### [NEW] Cargo.toml (workspace root)
```toml
[workspace]
members = ["crates/*"]
resolver = "2"

[workspace.package]
version = "2.0.0"
edition = "2024"
authors = ["lgcorzo"]
license = "MIT"

[workspace.dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
serde_yaml = "0.9"
bincode = "1"
polars = { version = "0.48", features = ["parquet", "lazy", "dtype-u8", "pivot"] }
linfa = "0.7"
linfa-trees = "0.7"
ndarray = "0.16"
reqwest = { version = "0.12", features = ["json", "multipart"] }
tokio = { version = "1", features = ["full"] }
axum = "0.8"
rdkafka = { version = "0.36", features = ["cmake-build"] }
clap = { version = "4", features = ["derive"] }
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }
tracing-opentelemetry = "0.30"
opentelemetry = { version = "0.28", features = ["trace", "logs"] }
opentelemetry_sdk = { version = "0.28", features = ["rt-tokio"] }
opentelemetry-otlp = { version = "0.28", features = ["http-proto", "logs"] }
opentelemetry-appender-tracing = "0.28"
notify-rust = "4"
thiserror = "2"
anyhow = "1"
dotenvy = "0.15"
envy = "0.4"
once_cell = "1"
rand = "0.8"
rayon = "1"
rstest = "0.25"
proptest = "1"
```

#### [NEW] Dockerfile — Multi-stage build
#### [NEW] .github/workflows/check.yml — fmt + clippy + test + tarpaulin

---

## Key Python → Rust Dependency Mapping

| Python Library | Rust Equivalent | Notes |
|---------------|----------------|-------|
| `pandas` | `polars` | Decision 4 |
| `pandera` | Custom validation | Struct-based |
| `scikit-learn` | `linfa` + `linfa-trees` | Decision 1 |
| `shap` | Custom `TreeExplainer` | Decision 3 |
| `mlflow` | `reqwest` + REST API 2.0 | Decision 2 |
| `mlflow.pyfunc` | `bincode` | Decision 2 |
| `loguru` | `tracing` + `tracing-subscriber` | Decision 5 |
| `opentelemetry-*` | `tracing-opentelemetry` + `opentelemetry-otlp` | Decision 5 |
| `plyer` | `notify-rust` | |
| `confluent-kafka` | `rdkafka` | |
| `fastapi` + `uvicorn` | `axum` + `tokio` | |
| `numpy` | `ndarray` | |
| `argparse` | `clap` | |
| `pytest` | `rstest` + `cargo test` | |
| `coverage` | `cargo-tarpaulin` | |
| `ruff` | `rustfmt` | |
| `mypy` | Rust compiler | Built-in |
| `bandit` | `cargo-audit` | |

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| **SHAP TreeExplainer correctness** | 🔴 High | Property-based testing; hand-computed test cases; cross-validate against Python SHAP |
| **linfa-trees feature gaps** | 🟡 Medium | Verify support for `max_depth`, `n_estimators`, `random_state`. Fallback: fork or wrap. |
| **MLflow REST API coverage** | 🟡 Medium | Test against MLflow 2.x server. |
| **One-hot encoding correctness** | 🟢 Low | Polars `to_dummies()` well-tested. Ensure column ordering consistency. |
| **bincode versioning** | 🟡 Medium | Pin version. Include format version byte header. |

---

## Verification Plan

### Automated Tests
```bash
cargo fmt --all -- --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --workspace
cargo tarpaulin --workspace --out Html
cargo audit
```

### Manual Verification
- Run all 6 jobs with same YAML configs against copied Parquet data
- Compare metrics (within 5% tolerance)
- Verify MLflow tracking UI
- Confirm bincode round-trip
- Test Kafka/HTTP endpoints
- Benchmark Rust vs Python

---

## Implementation Order (Phases)

### Phase 1: Foundation (Weeks 1–2)
1. Workspace scaffolding + CI
2. `schemas.rs`, `metrics.rs`
3. `configs.rs`, `env.rs`
4. `datasets/reader.rs`, `datasets/writer.rs`
5. `splitters.rs`
6. Copy Parquet data files

### Phase 2: ML Core + SHAP (Weeks 3–5)
7. `models.rs` — BaselineLinfoModel
8. `explainers.rs` — TreeExplainer ⚠️
9. `searchers.rs`, `signers.rs`
10. **Milestone**: End-to-end training + prediction + explanation in tests

### Phase 3: Infrastructure Services (Weeks 5–6)
11. `services/logger.rs` (full OTEL)
12. `services/alerts.rs`
13. `services/mlflow.rs`
14. `registries/`
15. **Milestone**: MLflow artifact round-trip

### Phase 4: Application Layer (Weeks 7–8)
16. `base.rs`
17. All 6 job modules
18. **Milestone**: All jobs run programmatically

### Phase 5: Interface + Polish (Weeks 9–10)
19. `cli.rs`, `kafka_app.rs`
20. Dockerfile, docker-compose
21. CI/CD, README
22. Coverage 95%, benchmarks
