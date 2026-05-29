# Exhaustive Engineering Analysis: PEP 660 & Editable Installs in colcon

## 1. The Legacy colcon Symlink Mechanism (`--symlink-install`)

Currently, `colcon-core`'s python build task natively implements the symlink-install paradigm by deeply manipulating both the filesystem and `setuptools` internal commands.

### 1.1 The Source-to-Build Symlink Bridge
When `colcon build --symlink-install` is invoked, `colcon_core.task.python.build.PythonBuildTask` prevents `setup.py develop` from polluting the user's source tree (e.g., creating `.egg-info` directly in the source directory).
Instead, it invokes the `_symlinks_in_build()` routine:
1. It parses the legacy `setup_py_data` to extract `packages`, `py_modules`, `data_files`, and `scripts`.
2. It generates physical OS symlinks from the source tree (`args.path`) into the build base (`args.build_base`) for every identified asset.

### 1.2 The `setup.py develop` Invocation
Once the build space dynamically mirrors the source space via symlinks, colcon executes:
```bash
python setup.py develop --editable --build-directory <build_base>/build --no-deps
```
**Execution directory**: `<build_base>`. 
This triggers `setuptools` to create an `easy-install.pth` that points to the build base (which inherently routes back to the real source space via the symlinks).

### 1.3 The `symlink_data` Custom Command
To handle non-Python data files (which are crucial for ROS 2 `ament_index` markers, `launch` files, and `package.xml`), `colcon` injects its own custom distutils command: `symlink_data`.
Colcon prepends its internal `colcon_distutils_commands` path to `PYTHONPATH`. When `setup.py symlink_data` is invoked, this custom command symlinks the data files from the source tree directly into the installation prefix (`args.install_base/share/...`), completely bypassing static copying. This allows developers to edit a launch file and instantly execute it without rebuilding.

---

## 2. Adapting colcon-core for PEP 660 (`build_editable`)

PEP 517 explicitly treats the build backend as an isolated black box, eliminating the ability to inject custom distutils commands or assume the presence of `setup.py develop`. PEP 660 restores the concept of editable installs via the `build_editable` hook.

### 2.1 The Architectural Shift
To support PEP 660, `colcon-core` must transition from an invasive file-manipulator to a compliant standards-based frontend:
1. **Hook Discovery**: Colcon must use `AsyncHookCaller.list_hooks()` to determine if the backend supports the `build_editable` hook.
2. **Hook Invocation**: If supported, it calls `AsyncHookCaller.call_hook('build_editable', wheel_directory=...)` to request the backend to generate an "editable `.whl`".
3. **Wheel Installation**: The frontend must then parse the resulting `.whl` and install its contents into the `install_base`. (Typically implemented via `installer` or standard `pip`).

### 2.2 Relinquishing Symlink Control
By relying on `build_editable`, `colcon-core` completely drops the `_symlinks_in_build()` and custom `symlink_data` logic. The generation of the `.pth` files or custom `sys.path_hooks` is entirely delegated to the backend's implementation (e.g., `setuptools.build_meta`, `hatchling`, or `flit-core`).

---

## 3. Major Ecosystem Risks: Data Files & ROS 2

The shift from the legacy `--symlink-install` to PEP 660 `build_editable` introduces a massive, workflow-breaking risk for the ROS 2 ecosystem regarding **non-Python data files** (launch files, RViz configs, URDFs, `package.xml`, and ament markers).

### 3.1 The PEP 660 Standard Gap
The PEP 660 specification is heavily optimized for Python code (modules and packages). It specifies how backends should expose `.py` files dynamically. However, it leaves the handling of data files ambiguous, generally falling back to standard static wheel `.data/data` semantics.

### 3.2 Static Data Files in Editable Wheels
When a standard build backend generates an editable wheel via `build_editable`, it packages the `data_files` directly inside the wheel archive. When the frontend (`colcon`) unpacks and installs this wheel, it statically copies these data files from the `.data` directory into the installation prefix (`install_base/share/...`).

**The Resulting Broken Workflow**:
- Python code (`.py`) remains dynamically editable via the backend's `.pth` injection.
- **Data files are no longer symlinked.** They are statically copied at build time.
- If a developer edits a `launch` file, an XML configuration, or an ament marker in the source directory, **the changes will not be reflected in the workspace environment**. 
- The user will execute stale, outdated configurations unless they manually run `colcon build --symlink-install` again.

### 3.3 Mitigation Strategies
To preserve the expected ROS 2 rapid-development experience, standard PEP 660 editable installs are insufficient for `data_files`. Mitigation will require:
1. **Backend-Specific Decorators**: Using the `HookCallerDecoratorExtensionPoint` (from PR #732) to intercept the `build_editable` hook when using `setuptools.build_meta`. The decorator must manually extract the `data_files` layout and recreate colcon's legacy `symlink_data` logic entirely outside of the standard hook.
2. **Upstream Backend Collaboration**: Collaborating with upstream backends (like `hatchling` and `setuptools`) to propose standard extensions for symlinking data files during editable wheel generation.
