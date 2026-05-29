# PEP 517 Migration Roadmap for colcon

## Executive Summary
This document outlines the engineering strategy and technical roadmap to modernize `colcon`'s Python build infrastructure. The goal is to fully support PEP 517 (`pyproject.toml`) build backends, driven by upstream deprecations in Linux distributions (e.g., Fedora 43) and `setuptools`. The migration is structured in three distinct phases to ensure stability, maintain backward compatibility during the transition, and eventually achieve strict separation of concerns.

---

## Phase 1: Current State Baseline

### Architectural Overview
Currently, `colcon-core` is deeply coupled with legacy Python packaging standards:
1. **Native `setup.cfg` Support**: `colcon-core` contains hardcoded, static parsing logic for `setup.cfg` to identify and augment Python packages (`colcon_core.package_identification.python` and `colcon_core.package_augmentation.python`). It leverages `setuptools.config.read_configuration`.
2. **`setup.py` Support**: Handled via an external extension, `colcon-python-setup-py`, which spawns isolated `sys.executable -c` processes to query `distutils.core.run_setup`.
3. **Execution**: The build and test tasks (`colcon_core.task.python.build` and `colcon_core.task.python.test`) rely on direct invocations of `setup.py build`, `setup.py install`, and `setup.py develop` (for `--symlink-install`).

### Bootstrap Mechanism
The developer bootstrap script (`src/colcon-core/bin/colcon`) mocks the core extension loading mechanism at runtime by manipulating `sys.path` and injecting core task extensions (e.g., `PythonBuildTask`). When bootstrapping, `colcon-core` builds itself using the native `setup.cfg` static parsing logic.

---

## Phase 2: The Intermediate State (Transitional)

In Phase 2, `colcon-core` will introduce full support for PEP 517 backend hooks while retaining legacy `setup.cfg` support alongside it. This ensures a safe transition period.

### 2.1 PEP 517 Integration
1. **Hook Caller Foundation**: Merge and refine PR #732 (`AsyncHookCaller` and decorators) to establish the IPC subprocess transport for interacting with PEP 517 build backends.
2. **Package Identification**: Update `colcon_core.package_identification.python.PythonPackageIdentification` to detect `pyproject.toml` and parse it using `tomllib` (with `tomli`/`toml` fallbacks).
3. **Package Augmentation**: Update `colcon_core.package_augmentation.python.PythonPackageAugmentation` to use the `AsyncHookCaller`. It will invoke `prepare_metadata_for_build_wheel` or `get_requires_for_build_wheel` to dynamically extract dependencies.
4. **Build Task**: Refactor `colcon_core.task.python.build.PythonBuildTask` to support a PEP 517 execution path:
   - Invoke `build_wheel` via `AsyncHookCaller`.
   - Implement wheel installation logic (e.g., using `installer` or standard `pip install`).

### 2.2 Legacy Fallback & Gating
Because the new PEP 517 infrastructure will be untested in the wild, the existing `setup.cfg` logic must remain intact.
- **Feature Flag**: Introduce an environment variable (e.g., `COLCON_ENABLE_LEGACY_SETUP_CFG`) to explicitly control `setup.cfg` parsing if `pyproject.toml` is absent or incomplete.
- **Priority**: If both files exist, `pyproject.toml` will take precedence unless the feature flag forces legacy behavior.

### 2.3 Bootstrapping Adaptation
The bootstrap script (`src/colcon-core/bin/colcon`) must be adapted to support building `colcon-core` via PEP 517:
- `colcon-core`'s own repository must be updated to use `pyproject.toml` (e.g., using `hatchling`, `flit-core`, or `setuptools.build_meta`).
- The mocked extension loader in the bootstrap script must register the new PEP 517 identification and augmentation logic to ensure `colcon-core` can correctly identify and build its own source tree during the bootstrap phase.

---

## Phase 3: The Target State (Strict Separation)

Once the PEP 517 integration has been battle-tested in production, `colcon-core` will purge all legacy `setup.cfg` and `setup.py` specific logic.

### 3.1 Extraction of Legacy Logic
1. **New Extension Repository**: Create a new, standalone extension package: `colcon-python-setup-cfg`.
2. **Migration**: Move the static `setup.cfg` parsing logic from `colcon-core` to `colcon-python-setup-cfg`. This new extension will implement `PackageIdentificationExtensionPoint` and `PackageAugmentationExtensionPoint` specifically for `setup.cfg` files.
3. **Deprecation**: Remove the `COLCON_ENABLE_LEGACY_SETUP_CFG` flag and all associated `setup.cfg` code from `colcon-core`.

### 3.2 Pure Standards-Based Core
`colcon-core` will become strictly standards-based, relying exclusively on PEP 517, PEP 518, and PEP 621 (`pyproject.toml`). Packages still relying on `setup.py` or `setup.cfg` will require the installation of `colcon-python-setup-py` and `colcon-python-setup-cfg`, respectively.

### 3.3 CI/CD & Testing Matrix
- Ensure CI pipelines test `colcon-core` bootstrapping using purely `pyproject.toml`.
- Validate the new `colcon-python-setup-cfg` extension against legacy ROS 2 repositories to ensure no regressions occur for users who have not yet migrated their packages.
