# POC Implementation Specification & PR Blueprint: colcon PEP 517 Integration

This document defines the exact technical steps, file modifications, and Pull Request boundaries required to implement Phase 2 (the intermediate state) of the PEP 517 migration within `colcon-core`.

## 1. The Feature Gate Layout & Control Flow

During Phase 2, `colcon-core` must support both the new PEP 517 standards and the legacy `setup.cfg` parsing logic to avoid breaking workflows. This requires careful feature gating.

### Environment Variable Control
We introduce `COLCON_ENABLE_LEGACY_SETUP_CFG` to control the fallback behavior. 

### Control Flow (Pseudo-Code)
Within `colcon_core/package_identification/python.py` (`PythonPackageIdentification.identify`), the detection flow will be updated as follows:

```python
def identify(self, desc):
    # 1. Check for PEP 517 pyproject.toml first
    pyproject_toml = desc.path / 'pyproject.toml'
    if pyproject_toml.is_file():
        try:
            # Parse pyproject.toml
            config = toml_loads(pyproject_toml.read_text())
            if 'build-system' in config or 'project' in config:
                # Proceed with PEP 517 package identification
                self._identify_pep517(desc, config)
                return
        except Exception as e:
            logger.warning(f"Failed to parse pyproject.toml: {e}")

    # 2. Check Feature Gate for Legacy setup.cfg fallback
    enable_legacy = os.environ.get('COLCON_ENABLE_LEGACY_SETUP_CFG', '1').lower() in ('1', 'true', 'on')
    
    # 3. Fallback to Legacy logic
    if enable_legacy:
        setup_cfg = desc.path / 'setup.cfg'
        setup_py = desc.path / 'setup.py'
        if setup_cfg.is_file() and setup_py.is_file() and is_reading_cfg_sufficient(setup_py):
            self._identify_legacy_setup_cfg(desc, setup_cfg)
```

## 2. Proof of Concept (POC) Minimum Scope

To achieve a successful POC where `colcon build` can compile a pure PEP 517 package (e.g., using `hatchling` or `flit-core`) via standard frontend tools, we must:
1. Successfully identify the package type as `python` by reading `pyproject.toml`.
2. Augment the package by resolving its dependencies using the `AsyncHookCaller` (specifically `get_requires_for_build_wheel` / `prepare_metadata_for_build_wheel` or static parsing of `project.dependencies`).
3. Modify the build task to invoke `build_wheel` via the hook caller and install the resulting `.whl` file into the `install_base`.

## 3. Pull Request Decomposition

The POC implementation will be divided into 3 reviewable Pull Requests.

---

### PR #1: Foundational PEP 517 Identification and Feature Gating
**Goal:** Enable `colcon-core` to identify and augment PEP 517 packages without breaking its own bootstrap loop.

**Target Files:**
* `colcon_core/package_identification/python.py`
* `colcon_core/package_augmentation/python.py`
* `colcon-core/setup.cfg` -> Migrate to `pyproject.toml`
* `bin/colcon` (The bootstrap script)

**Architectural Logic:**
1. **Identification**: Modify `PythonPackageIdentification` to incorporate the feature gating logic detailed above. Use `colcon_core.python_project.spec.toml_loads` to parse `pyproject.toml` and extract `project.name`.
2. **Augmentation**: Modify `PythonPackageAugmentation` to use `AsyncHookCaller` to fetch dependencies dynamically if they are not statically declared in `pyproject.toml`.
3. **Bootstrapping**: Convert `colcon-core`'s own repository structure to use a `pyproject.toml` (e.g., `setuptools.build_meta` or `hatchling`). Update `bin/colcon` to mock the new PEP 517 logic alongside the existing classes so the system can bootstrap itself from source.

**Test Matrix (Local Verification):**
```bash
# Verify bootstrapping still works
./src/colcon-core/bin/colcon build --packages-select colcon-core

# Verify identification of a test workspace
./src/colcon-core/bin/colcon info --packages-select <mock_pep517_package>
```

---

### PR #2: PEP 517 Standard Task Execution (Non-Editable)
**Goal:** Implement the execution mechanics to build and install standard wheels for PEP 517 packages, bypassing `setup.py install`.

**Target Files:**
* `colcon_core/task/python/build.py`

**Architectural Logic:**
1. **Task Modification**: Refactor `PythonBuildTask.build()`. It must inspect the package descriptor. If it was identified via PEP 517 (no `setup.py`), it must branch into a new PEP 517 build pipeline.
2. **Wheel Generation**: Use `AsyncHookCaller` to invoke the `build_wheel` hook of the declared build backend, outputting the `.whl` to the `<build_base>`.
3. **Wheel Installation**: Invoke a standard frontend tool (e.g., `installer` module or a subprocess call to `python -m pip install --no-index --no-deps --prefix <install_base> <wheel_path>`) to unpack the wheel into the installation directory.

**Test Matrix (Local Verification):**
```bash
# Build a pure PEP 517 package (non-editable)
./src/colcon-core/bin/colcon build --packages-select <mock_pep517_package>

# Verify artifacts are in the install/ directory
ls -la install/<mock_pep517_package>/lib/python*/site-packages/
```

---

### PR #3: Experimental PEP 660 Editable Hook Integration
**Goal:** Address the symlink deficiency by integrating the `build_editable` hook, allowing `--symlink-install` to work natively with PEP 660 compliant backends.

**Target Files:**
* `colcon_core/task/python/build.py`
* `colcon_core/python_project/hook_caller_decorator/` (New decorator classes)

**Architectural Logic:**
1. **Hook Discovery**: When `--symlink-install` is specified, `PythonBuildTask` must use `AsyncHookCaller.list_hooks()` to verify the backend supports `build_editable`.
2. **Fallback Logic**: If `build_editable` is not supported, log a warning and fall back to the standard `build_wheel` pipeline (PR #2).
3. **Editable Build**: If supported, call `build_editable(wheel_directory=...)`.
4. **Decorator Injection (Mitigation)**: Implement a custom `HookCallerDecoratorExtensionPoint` for `setuptools.build_meta` that intercepts the hook to manually recreate colcon's data file symlinking logic. This bridges the PEP 660 specification gap for ROS 2 `data_files`.

**Test Matrix (Local Verification):**
```bash
# Build the package in editable mode
./src/colcon-core/bin/colcon build --packages-select <mock_pep517_package> --symlink-install

# Verify source-to-install symlinks (Python code)
cat install/<mock_pep517_package>/lib/python*/site-packages/*.pth

# Edit a source file and verify the change reflects without rebuilding
echo "print('symlink works')" >> src/<mock_pep517_package>/module.py
python -c "import module" # Should print the new line
```
