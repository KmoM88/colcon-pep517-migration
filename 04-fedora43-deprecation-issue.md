# [RFC] Strategic Migration to PEP 517 Build Backends & setup.cfg Deprecation

## Background & Motivation
The Python packaging ecosystem is rapidly standardizing around PEP 517 (`pyproject.toml`) and aggressively deprecating legacy `setuptools` and `setup.py` workflows. Upstream Linux distributions are forcing this transition. For example, Fedora 43 is scheduled to remove legacy Python build macros by early 2026. 

To ensure `colcon` remains compatible with modern Python environments and upcoming OS releases, we must modernize `colcon-core`'s Python build infrastructure. Currently, `colcon-core` contains hardcoded logic for parsing `setup.cfg` and relies heavily on direct `setup.py` invocations.

## Proposed 3-Phase Roadmap

To achieve strict standards compliance while maintaining stability for the community, we propose the following 3-phase migration plan:

### Phase 1: Current State Baseline (Where we are)
- `colcon-core` relies entirely on static `setup.cfg` parsing for bootstrapping and identifying Python packages.
- Dynamic `setup.py` parsing is handled via the standalone `colcon-python-setup-py` extension.
- Build tasks invoke legacy `setup.py build`/`install`/`develop` commands.

### Phase 2: The Intermediate State (Transitional)
- **Integrate PEP 517**: Merge foundational PRs (e.g., PR #732) and integrate the `AsyncHookCaller` into core package identification, augmentation, and build tasks. `colcon-core` will learn to build wheels via backend hooks (e.g., `build_wheel`).
- **Safeguard Legacy Code**: Legacy `setup.cfg` support will remain inside `colcon-core` alongside the new PEP 517 logic. We will gate the legacy behavior with a feature flag (e.g., `COLCON_ENABLE_LEGACY_SETUP_CFG=1`) to allow users to opt-out of PEP 517 during the transition if issues arise.
- **Self-Hosting**: Migrate `colcon-core`'s own repository to `pyproject.toml` and adapt the `bin/colcon` bootstrap script to build itself using the new PEP 517 logic.

### Phase 3: The Target State (Strict Separation)
- **Purge Legacy Core**: Completely remove `setup.cfg` static parsing from `colcon-core`.
- **Standalone Extension**: Extract the legacy `setup.cfg` logic into a new, retroactive extension: `colcon-python-setup-cfg`.
- **Standards Compliance**: `colcon-core` becomes strictly standards-based (PEP 517/518/621). Users with legacy packages will simply rely on `colcon-python-setup-py` and the new `colcon-python-setup-cfg` plugins.

## Request for Comments
We are seeking feedback from maintainers and the community on:
1. The feasibility of the Phase 2 transition and bootstrapping adaptations.
2. The naming and default behavior of the `COLCON_ENABLE_LEGACY_SETUP_CFG` feature flag.
3. The timeline for Phase 3 (extraction of `setup.cfg` into `colcon-python-setup-cfg`), particularly regarding coordination with downstream users like ROS 2 distributions.

Please share your thoughts below!
