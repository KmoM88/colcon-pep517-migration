# Colcon Python Build Internals & Bootstrapping Dissection

This document provides a low-level, code-level analysis of how the `colcon` build system discovers, parses, bootstraps, and builds Python packages in a workspace. This dissection is critical as preparation for transitioning from legacy `setup.py` / `setup.cfg` structures to modern PEP 517 build backends.

---

## 1. The Bootstrapping Flow

Bootstrapping `colcon` from source allows developers to build and run the build system using development checkouts of its various component repositories. This process avoids depending on system-wide or pre-installed versions of `colcon`.

### 1.1 Prerequisites & Workspace Setup Steps

Below is the step-by-step breakdown of how the workspace is prepared and populated with all the necessary `colcon` packages:

1. **Create and Activate a Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
   * **Why**: This isolates the development environment. It guarantees that the bootstrapped `colcon` instance and its dependency packages do not interfere with system-level Python packages, and vice versa.

2. **Install `vcstool`**
   ```bash
   pip install vcstool
   ```
   * **Why**: `vcstool` is a command-line tool designed to manage workspaces with multiple version control repositories (git, mercurial, etc.) defined in a single file. We use it to batch-clone the various repos that make up the `colcon` ecosystem.

3. **Retrieve the Repositories Config (`colcon.repos`)**
   ```bash
   curl --output colcon.repos https://raw.githubusercontent.com/colcon/colcon.readthedocs.org/main/colcon.repos
   ```
   * **Why**: Downloads a list (`colcon.repos`) that enumerates all core repositories and plugins (such as `colcon-core`, `colcon-package-selection`, `colcon-python-setup-py`, etc.) along with their source URLs and branches.

4. **Retrieve the Third-Party Requirements (`requirements.txt`)**
   ```bash
   curl --output requirements.txt https://raw.githubusercontent.com/colcon/colcon.readthedocs.org/main/requirements.txt
   ```
   * **Why**: Downloads the standard `requirements.txt` file listing external libraries (like `distlib`, `pytest`, `setuptools`, etc.) that `colcon` needs at runtime.

5. **Install Third-Party Dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   * **Why**: Installs all required external Python packages into our virtual environment, preparing the interpreter to run `colcon-core`'s bootstrapping scripts.

6. **Create a Source Directory and Import Repositories**
   ```bash
   mkdir src
   vcs import src < colcon.repos
   ```
   * **Why**: Creates a `src` directory and instructs `vcstool` to clone every repository specified in `colcon.repos` into `src/`. This populates the workspace with the raw source code of the `colcon` suite.

---

### 1.2 The First Build (Bootstrap Execution)

To compile the packages in `src/`, we run:
```bash
./src/colcon-core/bin/colcon build --paths src/*
```

#### Why we must call the script directly:
Because `colcon` is not yet installed in the active virtual environment, standard entry points (i.e. console scripts registered in `egg-info` or `dist-info` directories) do not exist. Standard import-based discovery via `importlib.metadata.entry_points()` would fail to find `colcon` or any of its extension points.

To bypass this chicken-and-egg problem, the entry point script at `./src/colcon-core/bin/colcon` mocks the core extension loading mechanism at runtime. It manually constructs a static dictionary of available plugins in `src/` and feeds it to the discovery APIs (see [Section 1.4](#14-runtime-bootstrapping-code-mechanics) below).

> [!NOTE]
> **Registration**: During this first build, each package's build process generates metadata inside the `install/` directory. The installation of these packages is registered locally in the build workspace.

---

### 1.3 Sourcing and Subsequent Builds

Once the first build completes, we hook the newly compiled workspace into our active shell environment:

1. **Source the Workspace Setup Script**
   ```bash
   . install/local_setup.sh
   ```
   * **Why**: The generated `local_setup.sh` script updates system environment variables (specifically adding built scripts to `PATH` and package roots to `PYTHONPATH`). It registers the `colcon` executable and all newly compiled extension entry points in the current shell context.

2. **Execute Subsequent Builds**
   ```bash
   colcon build
   ```
   * **Why**: Since `local_setup.sh` has registered `colcon` in the active environment, we no longer need to invoke the source script path (`./src/colcon-core/bin/colcon`). We can run `colcon build` globally from anywhere in our workspace, and the shell will successfully find and execute the installed binary.

---

### 1.4 Runtime Bootstrapping Code Mechanics

When the bootstrap script `./src/colcon-core/bin/colcon` is invoked during the first build, it performs the following Python-level operations:

1. **Executing the script**: The Python interpreter executes the entry point file [bin/colcon](./src/colcon-core/bin/colcon).
2. **sys.path manipulation** (lines 16-17):
   ```python
   pkg_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
   sys.path.insert(0, pkg_root)
   ```
   This inserts the local checkouts of the package root directory directly at the beginning of the python path, allowing standard `import colcon_core` calls to succeed.
3. **Mocking extension point discovery** (lines 20-37):
   The script overrides the `load_extension_points` function in the `colcon_core.extension_point` module *before* any other core modules are imported:
   ```python
   from colcon_core import extension_point
   
   custom_extension_points = {}
   
   def custom_load_extension_points(group_name, *, excludes=None):
       assert group_name in custom_extension_points, \
           f"get_extension_points() not overridden for group '{group_name}'"
       return {
           k: v for k, v in custom_extension_points[group_name].items()
           if excludes is None or k not in excludes}
   
   extension_point.load_extension_points = custom_load_extension_points
   ```
4. **Populating Static Extensions** (lines 40-144):
   The script directly imports and registers all base classes and essential plugins from `colcon_core` into the `custom_extension_points` dictionary. For example:
   * **Verbs**: `BuildVerb` (from `colcon_core.verb.build`) and `TestVerb` (from `colcon_core.verb.test`).
   * **Package Discovery**: `PathPackageDiscovery` (from `colcon_core.package_discovery.path`).
   * **Package Identification**: `IgnorePackageIdentification` (from `colcon_core.package_identification.ignore`) and `PythonPackageIdentification` (from `colcon_core.package_identification.python`).
   * **Task Executors**: `SequentialExecutor` (from `colcon_core.executor.sequential`).
   * **Tasks**: `PythonBuildTask` (from `colcon_core.task.python.build`) and `PythonTestTask` (from `colcon_core.task.python.test`).
5. **Execution Hand-off** (lines 146-149):
   It imports the standard `main` command runner from `colcon_core.command` and invokes it:
   ```python
   from colcon_core.command import main
   if __name__ == '__main__':
       sys.exit(main() or 0)
   ```

Because `load_extension_points` is mocked, when the core command parser asks for verbs, package identification steps, or executors, the local python classes are returned directly. This allows colcon to identify that all packages in `src/` (which use a standard `setup.cfg` layout) are `'python'` packages, topological sort them, and compile them using `PythonBuildTask` in sequential/parallel queues.

---

## 2. Native `setup.cfg` Support in Core

`colcon-core` contains hardcoded, built-in logic to handle standard Python packages that define their properties in `setup.cfg`. This logic is separated into **Package Identification** (discovery) and **Package Augmentation** (metadata parsing).

### Package Identification: `PythonPackageIdentification`
* **File Path**: [python.py](./src/colcon-core/colcon_core/package_identification/python.py)
* **Class**: `PythonPackageIdentification` (subclass of `PackageIdentificationExtensionPoint`)
* **API Entry**: `identify(self, desc)`
* **Conditions for Matching**:
  1. `desc.type` must be `None` or `'python'`.
  2. The package directory must contain both a `setup.py` and a `setup.cfg` file.
  3. **The setup.py check**: The function `is_reading_cfg_sufficient(setup_py)` reads the text of `setup.py` and checks that the `setup()` function is called with no arguments or *only* a `cmdclass`.
     ```python
     def is_reading_cfg_sufficient(setup_py):
         setup_py_content = setup_py.read_text()
         return 'setup()' in setup_py_content or \
             'setup(cmdclass=cmdclass)' in setup_py_content
     ```
     If any other arguments are passed to the `setup()` function in `setup.py`, the core package identification step skips the package, letting external plugins (like `colcon-python-setup-py`) handle the more complex/dynamic script.
* **Parsing Metadata**:
  If the check passes, `get_configuration(setup_cfg)` (lines 78-110) imports the standard `read_configuration` utility from `setuptools`:
  ```python
  from setuptools.config.setupcfg import read_configuration  # fallback to setuptools.config
  config = read_configuration(str(setup_cfg))
  ```
  It retrieves the package name via `config['metadata']['name']` and marks `desc.type = 'python'` and `desc.name = name`.

### Package Augmentation: `PythonPackageAugmentation`
* **File Path**: [python.py](./src/colcon-core/colcon_core/package_augmentation/python.py)
* **Class**: `PythonPackageAugmentation` (subclass of `PackageAugmentationExtensionPoint`)
* **API Entry**: `augment_package(self, desc, *, additional_argument_names=None)`
* **Dependency Extraction**:
  The helper function `extract_dependencies(options)` parses dependencies from the parsed `options` dict of `setup.cfg` using `distlib.util.parse_requirement` and builds `DependencyDescriptor` instances:
  * `setup_requires` is mapped to `build` dependencies.
  * `install_requires` is mapped to `run` dependencies.
  * `tests_require` and `extras_require` (keys `'test'`, `'tests'`, and `'testing'`) are mapped to `test` dependencies.
* **Registering Options Getter**:
  Crucially, it attaches a getter function under `desc.metadata['get_python_setup_options']`:
  ```python
  def getter(env):
      return options
  desc.metadata['get_python_setup_options'] = getter
  ```
  This is a static getter—it simply returns the pre-parsed dictionary from `setup.cfg` without needing to spawn a subprocess.

---

## 3. Tasks and Testing in Core

Once a package is identified as type `'python'` (either natively via `setup.cfg` or externally via `setup.py`), the execution of the build and test procedures is handled by core task classes.

### The Build Task: `PythonBuildTask`
* **File Path**: [build.py](./src/colcon-core/colcon_core/task/python/build.py)
* **Class**: `PythonBuildTask` (subclass of `TaskExtensionPoint`)
* **API Entry**: `build(self, *, additional_hooks=None)`
* **Underlying subprocess commands constructed**:
  If `--symlink-install` is **not** specified:
  ```python
  [
      sys.executable,
      '-W', 'ignore:setup.py install is deprecated',
      '-W', 'ignore:easy_install command is deprecated',
      'setup.py',
      'egg_info', '--egg-base', '<relative_path_to_build_base>',
      'build', '--build-base', '<build_base>/build',
      'install',
      '--record', '<build_base>/install.log',
      '--single-version-externally-managed'
  ]
  ```
  If `--symlink-install` is specified, it creates symlinks mapping all package elements (folders, scripts, data files) from the source space into `args.build_base`, and runs `setup.py develop` inside the build directory to keep the source workspace clean of build artifacts:
  ```python
  [
      sys.executable,
      '-W', 'ignore:setup.py install is deprecated',
      '-W', 'ignore:easy_install command is deprecated',
      'setup.py',
      'develop',
      '--editable',
      '--build-directory', '<build_base>/build',
      '--no-deps'
  ]
  ```

### The Test Task: `PythonTestTask`
* **File Path**: [__init__.py](./src/colcon-core/colcon_core/task/python/test/__init__.py)
* **Class**: `PythonTestTask` (subclass of `TaskExtensionPoint`)
* **API Entry**: `test(self, *, additional_hooks=None)`
* **Delegation to Testing Steps**:
  `PythonTestTask` is a coordinating task. It queries registered extensions under the entry point group `colcon_core.python_testing`. The two standard testing step classes are:
  1. **Pytest step (`PytestPythonTestingStep`)**:
     * **File**: [pytest.py](./src/colcon-core/colcon_core/task/python/test/pytest.py)
     * **Match**: Matches if the package has a test dependency on `pytest` (`has_test_dependency(setup_py_data, 'pytest')`).
     * **Subprocess Call**:
       ```python
       [sys.executable, '-m', 'pytest']
       # Along with arguments in PYTEST_ADDOPTS, e.g.:
       # --tb=short --junit-xml=<build_base>/pytest.xml --junit-prefix=<package_name>
       ```
  2. **Setuppy/Unittest step (`SetuppyPythonTestingStep`)**:
     * **File**: [setuppy_test.py](./src/colcon-core/colcon_core/task/python/test/setuppy_test.py)
     * **Match**: Always returns `True` as a fallback.
     * **Subprocess Call**:
       ```python
       [sys.executable, '-m', 'unittest', '-v']
       ```

---

## 4. The External `setup.py` Extension (`colcon-python-setup-py`)

When packages utilize dynamic logic in their `setup.py` (e.g. executing scripts to fetch versions or computing lists of dependencies inside python code), static parsing of `setup.cfg` is insufficient. The external extension repository `colcon-python-setup-py` provides dynamic execution capability.

### Differences in Package Identification & Augmentation
* **Files**: [python_setup_py.py](./src/colcon-python-setup-py/colcon_python_setup_py/package_identification/python_setup_py.py) and [package_augmentation/python_setup_py.py](./src/colcon-python-setup-py/colcon_python_setup_py/package_augmentation/python_setup_py.py).
* **Classes**: `PythonPackageIdentification` and `PythonPackageAugmentation`.
* **The parsing strategy**: 
  Unlike core's native parser which statically reads `setup.cfg`, `colcon-python-setup-py` executes `setup.py` inside a isolated **Python subprocess**.
  
  Specifically, it constructs a short Python program that imports and invokes `distutils.core.run_setup`:
  ```python
  from distutils.core import run_setup
  dist = run_setup('setup.py', script_args=('--dry-run',), stop_after='config')
  ```
  The `--dry-run` script argument prevents setuptools/distutils from attempting to install or write local output files. The `stop_after='config'` prevents setuptools from carrying out execution commands.
  
  The script then dumps a serialized representation of `dist.__dict__` (excluding non-serializable fields like methods, display options, and private fields) to standard output. The parent process captures this and evaluates it using `ast.literal_eval`.

### Subprocess Invocation Traces (Comparison)

Below is an explicit comparison of the subprocess operations and execution contexts between the native core (`setup.cfg`) flow and the dynamic setup extension (`colcon-python-setup-py`) flow:

| Phase | Native `colcon-core` (`setup.cfg`) | Extension `colcon-python-setup-py` (`setup.py`) |
| :--- | :--- | :--- |
| **Package Identification** | **No Subprocess Spawned.**<br/>Runs purely in the main Python thread using setuptools configuration config parser API (`read_configuration`). | **Subprocess Spawned.**<br/>Runs command: `[sys.executable, '-c', '<python_loader_script>']`<br/>Invokes `run_setup('setup.py', script_args=('--dry-run',), stop_after='config')` to evaluate the script. |
| **Package Augmentation (Options Getter)** | **No Subprocess Spawned.**<br/>Registers a static callable that returns the pre-parsed options dict directly: `lambda env: options`. | **Subprocess Spawned.**<br/>Registers a dynamic callable that spawns the isolated `run_setup` script to retrieve configuration under the task's environment: `lambda env: get_setup_information(setup_py, env=env)`. |
| **Build Execution** | **Task: `PythonBuildTask`** (from `colcon-core`) | **Task: `PythonBuildTask`** (from `colcon-core`) |
| **Test Execution** | **Task: `PythonTestTask`** (from `colcon-core`) | **Task: `PythonTestTask`** (from `colcon-core`) |

> [!IMPORTANT]
> **Key Insight**: `colcon-python-setup-py` does **NOT** contain any task-level build or test runner classes. It exists purely to *identify* and *augment* packages that cannot be statically parsed. Once `colcon-python-setup-py` successfully identifies a package and sets `desc.type = 'python'`, `colcon-core` routes it to the exact same built-in `PythonBuildTask` and `PythonTestTask` pipelines.
