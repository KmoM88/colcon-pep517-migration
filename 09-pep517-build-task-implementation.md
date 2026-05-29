# 09: PEP 517 Build Task Implementation and Multi-Backend Verification

This document details the concrete implementation, technical mechanics, testing strategy, and multi-backend verification of Phase 2 / PR #2 (PEP 517 Standard Build/Install Task) of the colcon PEP 517 migration.

---

## 1. Architectural Details of the Build Task Implementation

With the foundational package identification and feature gating successfully integrated in PR #1, PR #2 refactored the build execution layer (`PythonBuildTask` inside `colcon-core/colcon_core/task/python/build.py`) to fully support building PEP 517 compliant projects.

### 1.1 Gating and Detection
The build pipeline dynamically branches into the PEP 517 compilation path when:
*   A `pyproject.toml` configuration is present in the package root.
*   No legacy `setup.py` script exists in the package root.

```python
# Check if the package is built via PEP 517 (no setup.py, but has pyproject.toml)
setup_py = Path(args.path) / 'setup.py'
pyproject_toml = Path(args.path) / 'pyproject.toml'
is_pep517 = pyproject_toml.is_file() and not setup_py.is_file()

if is_pep517:
    return await self._build_pep517(pkg, args, env, additional_hooks)
```

### 1.2 Isolated Wheel Generation
Inside the asynchronous `_build_pep517` helper, we use the `AsyncHookCaller` to cleanly interface with the backend build system:
1.  **Backend hook initialization**: Dynamically load PEP 517 configuration requirements using `get_hook_caller(pkg, env=env)`.
2.  **Wheel generation**: Call the standard `build_wheel` PEP 517 hook, generating a binary wheel (`.whl`) within the isolated `<build_base>/wheel` workspace directory.

### 1.3 Target-Redirect Wheel Unpacking
To cleanly unpack and register the generated package files into `install/` without requiring external setup scripts or exposing complex runtime libraries (e.g. `installer`), the task executes the virtual environment's pip inside a subprocess:
```python
pip_cmd = [
    sys.executable,
    '-m',
    'pip',
    'install',
    '--no-index',
    '--no-deps',
    '--target',
    python_lib,
    wheel_path,
]
```
This hermetically unpacks package files directly into the target `site-packages` directory of the workspace, completely bypassing external package index queries or dependency lookups.

### 1.4 Automatic Console Script Wrappers
Since isolated pip installations under `--target` do not automatically write wrapper scripts for CLI entry points defined in the project, `colcon` dynamically parses the package's `.dist-info/entry_points.txt` configuration:
1.  Locate `[console_scripts]` definitions in the unpacked `.dist-info/` directory.
2.  Construct a standard, executable python script inside `<install_base>/bin/` utilizing the correct `sys.executable` interpreter path.
3.  Add executable permissions (`0o755`) to allow native shell invocation.

---

## 2. Integrated Unit Testing

A comprehensive unit test case `test_build_pep517` was introduced inside `src/colcon-core/test/test_build_python.py`:
*   **Targeted Verification**: Dynamically creates a mock PEP 517 package with a `pyproject.toml` (using the standard `setuptools.build_meta` build system), source module, and console script definition.
*   **Execution Verification**: Runs `PythonBuildTask.build` and asserts that execution completes with return code `0`.
*   **Output Registration**: Verifies that the source module, `.dist-info` metadata, `entry_points.txt`, and executable shell scripts are correctly compiled, unpacked, and created inside the virtual install directory.

Additionally, `chmod` was added in alphabetical order to `src/colcon-core/test/spell_check.words` to satisfy style checkers.

---

## 3. Local Multi-Backend Verification

Verification was executed against three standard mock packages utilizing modern, diverse build backends:

1.  **`pkg_pep517_setuptools`**: Using the modern `setuptools.build_meta` build-system.
2.  **`pkg_pep517_hatchling`**: Using the standard `hatchling.build` build-system.
3.  **`pkg_pep517_flit`**: Using the modern `flit_core.buildapi` build-system.

### 3.1 Namespace Package Alignment & `__init__.py` Fixes
During initial verification, some backends failed because the mock packages lacked an explicit `__init__.py` in their python source subdirectories. Empty `__init__.py` files were created inside the package directories to guarantee standardized multi-backend compatibility:
*   [pkg_pep517_setuptools/pkg_pep517_setuptools/__init__.py](file:///home/fede/github/kmom88/colcon-pep517-migration/test_packages/pkg_pep517_setuptools/pkg_pep517_setuptools/__init__.py)
*   [pkg_pep517_hatchling/pkg_pep517_hatchling/__init__.py](file:///home/fede/github/kmom88/colcon-pep517-migration/test_packages/pkg_pep517_hatchling/pkg_pep517_hatchling/__init__.py)
*   [pkg_pep517_flit/pkg_pep517_flit/__init__.py](file:///home/fede/github/kmom88/colcon-pep517-migration/test_packages/pkg_pep517_flit/pkg_pep517_flit/__init__.py)

### 3.2 Compilation and Execution Results
The local workspace was successfully bootstrapped from source using the new PEP 517 build task, compiling all three mock packages:

```bash
# Sourcing the bootstrapped colcon environment
source install/local_setup.sh

# Compiling all mock packages successfully
colcon build --paths test_packages/pkg_pep517_setuptools test_packages/pkg_pep517_hatchling test_packages/pkg_pep517_flit

# Executing all three CLI console scripts successfully
hello-pep517-setuptools
# Output: Hello from PEP 517 setuptools package!

hello-pep517-hatchling
# Output: Hello from PEP 517 hatchling package!

hello-pep517-flit
# Output: Hello from PEP 517 flit package!
```

---

## 4. Verification and Status Matrix

| Verification Level | Scope | Status | Result |
| :--- | :--- | :--- | :--- |
| **Local Unit Tests** | `pytest test_build_python.py` | **PASS** | All 13 tests passed successfully in 8.48s |
| **Local Bootstrapped Build** | `colcon build --paths test_packages/*` | **PASS** | Standard wheels compiled and unpacked perfectly |
| **Local Executable Run** | Shell CLI invocation of compiled entry points | **PASS** | All console scripts successfully executed |

---

## 5. Next Steps

With Phase 2 successfully verified, the next steps include:
1.  **Commit and Push Fork Changes**: Push current modifications to the development fork repository.
2.  **Update Root CI Pipeline**: Add full build and run validations for PEP 517 packages inside the root CI workflows.
3.  **Support Editable Installations (Phase 3)**: Investigate and integrate PEP 660 (`build_editable`) editable installation hooks to support `--symlink-install` workflows.
