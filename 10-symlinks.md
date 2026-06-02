# 10: Exhaustive Analysis of Symlink Installations and the PEP 517/660 Migration Barrier

This document presents a deep, code-level engineering analysis of the symlink installation paradigm (`--symlink-install`) within `colcon-core` and `colcon-ros`. It investigates the structural mechanics of how Python source modules and non-Python data files are dynamically exposed in the workspace, traces the exact execution patterns of ROS 2 `ament_python` workflows, and examines why modern PEP 517 and PEP 660 packaging standards introduce a fundamental architectural barrier that breaks these workflows.

---

## 1. The Legacy Symlink Architecture in `colcon-core`

To optimize iteration speeds during local development, `colcon` introduced the `--symlink-install` option. This flag shifts the build system from a "copy-on-build" model to a "dynamic-filesystem-link" model. 

Legacy executions achieve this by bifurcating the symlinking task into two distinct workflows: one for Python source modules, and one for non-Python data resources.

```
Source Directory (src/)                      Target Workspace (install/)
  ├── my_module/                             
  │     └── __init__.py <──────[PTH Link]───── lib/python3.10/site-packages/my_module/
  └── share/my_package/
        └── launch.py <──────[OS Symlink]────── share/my_package/launch.py
```

### 1.1 Python Source Code Symlinking via `_symlinks_in_build`
For standard `setup.py` executions, if editable installation is requested, `colcon` must prevent `setuptools` from polluting the user's raw source directory with build artifacts (e.g. `.egg-info` directories and intermediate caches). 
*   **File**: [colcon_core/task/python/build.py](file:///home/fede/github/kmom88/colcon-pep517-migration/src/colcon-core/colcon_core/task/python/build.py#L296-L376)
*   **Method**: `_symlinks_in_build(self, args, setup_py_data)`
*   **Mechanics**:
    1.  `colcon` parses the metadata of the package to locate all defined Python `packages` and `py_modules`.
    2.  Instead of allowing `setuptools` to register the original source directory, `colcon` creates physical OS-level symlinks mapping these package modules from the source directory (`args.path`) into a temporary layout inside the build base (`args.build_base`).
    3.  It then spawns `setup.py develop --editable --build-directory <build_base>/build` pointing to the build base directory.
    4.  `setuptools` registers an editable `.egg-link` or `.pth` entry pointing to the build base, which inherently routes back to the real source files via the generated symlinks.

### 1.2 Non-Python Data File Symlinking via Custom `symlink_data`
Python packages frequently distribute non-Python assets—such as configuration profiles, templates, icons, and schemas. In traditional packaging, these are defined in the `data_files` array of `setup()` and handled by the `install_data` command class, which statically copies files into the installation prefix.

To keep these assets dynamically editable, `colcon` overrides the standard installation process by injecting a custom `distutils` command.
*   **File**: [colcon_core/distutils/commands/symlink_data.py](file:///home/fede/github/kmom88/colcon-pep517-migration/src/colcon-core/colcon_core/distutils/commands/symlink_data.py#L9-L17)
*   **Class**: `symlink_data(install_data)`
*   **Mechanics**:
    1.  `colcon` injects its internal `colcon_distutils_commands` module into the environment's `PYTHONPATH`.
    2.  It appends `symlink_data` to the execution command array:
        ```python
        cmd += ['symlink_data']
        ```
    3.  When executed by `setuptools`, the custom `symlink_data` command intercepts the file list. Instead of copying files using standard file-copy routines (`shutil.copy`), it invokes `os.symlink(src, dst)` to create direct filesystem links from the source repository into the target workspace prefix (`install/`).

---

## 2. Tracing Symlink Mechanics inside `colcon-ros`

`colcon-ros` coordinates workspace compilations for robotic packages. The impact of the symlink paradigm differs completely between C++ (CMake) packages and Python packages.

### 2.1 Toolchain-Level Symlinking for CMake Packages
For CMake-based ROS 2 packages (`ament_cmake` and legacy `catkin`), `colcon-ros` does not manage files directly.
*   **Files**:
    *   [colcon_ros/task/ament_cmake/build.py](file:///home/fede/github/kmom88/colcon-ros/colcon_ros/task/ament_cmake/build.py#L50-L53)
    *   [colcon_ros/task/catkin/build.py](file:///home/fede/github/kmom88/colcon-ros/colcon_ros/task/catkin/build.py#L61-L62)
*   **Mechanics**: If `args.symlink_install` is active, `colcon-ros` passes toolchain-specific definitions directly to CMake:
    *   `-DAMENT_CMAKE_SYMLINK_INSTALL=1`
    *   `-DCATKIN_SYMLINK_INSTALL=ON`
*   **Insight**: The creation of symlinks for libraries, headers, and ROS resource files is completely offloaded to the C++ build macros. This is handled natively inside the CMake generation layer and is **unaffected by changes in Python packaging standards**.

### 2.2 The `ament_python` Task Delegation
ROS 2 packages written in Python utilize the `ament_python` build type. `colcon-ros` implements a dedicated task class to coordinate these builds.
*   **File**: [colcon_ros/task/ament_python/build.py](file:///home/fede/github/kmom88/colcon-ros/colcon_ros/task/ament_python/build.py#L22-L103)
*   **Mechanics**:
    1.  `AmentPythonBuildTask` instantiates the core `PythonBuildTask` extension and sets its context.
    2.  It parses `setup.py` metadata to check if standard ROS 2 markers (e.g. package resource index files and `package.xml` manifests) are explicitly declared in the package's `data_files`.
    3.  If they are not explicitly declared, `colcon-ros` provides a fallback by invoking `colcon_core.task.install()` to place them in the installation prefix:
        ```python
        # Implicit installation of the package manifest
        install(args, 'package.xml', f'share/{self.context.pkg.name}/package.xml')
        ```
    4.  The [colcon_core/task/__init__.py](file:///home/fede/github/kmom88/colcon-core/colcon_core/task/__init__.py#L306-L334) `install` helper inspects `args.symlink_install`. If active, it creates a direct filesystem link:
        ```python
        os.symlink(src, dst)
        ```
    5.  Finally, `AmentPythonBuildTask` delegates the entire compilation and execution process to `colcon-core`'s Python build task:
        ```python
        return await extension.build(additional_hooks=additional_hooks)
        ```

---

## 3. Dissecting the PEP 517/660 Migration Barrier

The transition from legacy direct-script executions to standards-compliant PEP 517 frontends and PEP 660 editable installations introduces a major architectural mismatch that breaks the ability to dynamically link data files.

### 3.1 The "Black Box" Subprocess Barrier
The core paradigm of PEP 517 is **build system isolation**. The frontend (`colcon`) interacts with the backend solely through a standardized, decoupled Python subprocess hook interface (`build_wheel`, `build_editable`).
*   **The Mismatch**: `colcon` can no longer inject custom `distutils` commands (like `symlink_data`) or override command classes on the command line. The build backend operates inside a closed, opaque runtime environment.
*   **The Result**: The frontend receives a finalized, compiled wheel archive (`.whl`). It is the installer tool's job to unpack this archive into the workspace, eliminating any ability to intercept the backend's internal packaging phase.

### 3.2 The Loss of Source-to-Target File Mapping
A compiled wheel archive is a standardized ZIP file defined by **PEP 427**. Within the archive, data files are detached from their original repository structures and organized into a flat layout under a `.data/data/` or `share/` directory.

```
Generated ZIP Wheel Archive
  ├── my_module/
  │     └── __init__.py
  └── my_package-1.0.0.data/
        └── data/
              └── share/
                    └── my_package/
                          └── launch.py  <─── [Original source path lost!]
```

When the wheel is delivered to the frontend, **all context regarding the original filesystem source paths of the data files is lost**. 
*   **The Mismatch**: The wheel only records the target location (`share/my_package/launch.py`). The installer tool cannot know where `launch.py` originally resided in the developer's source tree (e.g. `src/my_package/launch/launch.py` vs `src/my_package/share/launch.py`).
*   **The Result**: Without this source-to-target path mapping, the installation engine is physically unable to create an OS symlink back to the source repository. It has no choice but to write a static copy of the data file during the wheel unpacking phase.

### 3.3 The PEP 660 Data-File Spec Gap
PEP 660 defines standard interfaces (`build_editable`) to support editable installations for Python packages. However, this specification is heavily optimized for Python executable code.
*   **Python Module Editability**: Backends successfully achieve Python code editability by writing standard redirection files (such as `.pth` files pointing to the source directory) or injecting dynamic path hooks into `sys.path_hooks`.
*   **Data File Invisibility**: PEP 660 does not define any standardized mechanism to dynamically link or update non-Python data files.
*   **The Backend Deflection**: Consequently, standard modern backends (such as `setuptools.build_meta`, `hatchling`, or `flit`) treat data files as static resources. When compiling an editable wheel, they package `data_files` directly inside the wheel archive. When the frontend installs the editable wheel, **the data files are copied statically** into the installation directory.

---

## 4. Operational Gaps and Workflow Impact

This technical limitation introduces a severe regression in the rapid-development workflows expected by ROS 2 and robotic system integrators.

### 4.1 The Static-Dynamic Disparity
If a Python-based ROS 2 package is built under a standard PEP 660 pipeline, a confusing, bifurcated developer experience is created:
1.  **Python Sources are Dynamic**: Edits made to Python scripts or class methods inside the package source folder take effect instantly (due to PEP 660 `.pth` redirection).
2.  **Shared Resources are Static**: Edits made to XML/YAML launch scripts, RViz display profiles, URDF robotic description models, or custom configuration parameters do **not** take effect. The workspace continues to execute the stale static files copied into `install/share/` during the initial build.

### 4.2 Critical Workflow Regression
Robotic integration involves frequent, iterative tuning of parameters inside launch and configuration files. 
*   **The Impact**: Developers are forced to run `colcon build` after every single non-Python file modification to push changes to the install space.
*   **Friction**: In complex environments containing dozens of packages, re-running `colcon build` to compile and repackage wheels introduces substantial processing overhead. This degrades iteration speed, directly clashing with the design parameters set by the ROS PMC infrastructure group.

### 4.3 Summary of the Migration Conflict
The fundamental conflict of the modern PEP 517/660 migration roadmap can be summarized as follows:

| Packaging Paradigm | Python Code Editability | Data File Editability | Path Mapping Context |
| :--- | :--- | :--- | :--- |
| **Legacy `setup.py` Flow** | **Dynamic** (registered via `develop`) | **Dynamic** (symlinked via `symlink_data`) | **Preserved** (called directly on filesystem) |
| **Standard PEP 517/660 Flow** | **Dynamic** (registered via `build_editable` `.pth`) | **Static** (copied during wheel install) | **Lost** (files packaged inside ZIP archive) |
