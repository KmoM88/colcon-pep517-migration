from setuptools import setup, find_packages

setup(
    name="pkg-setup-py",
    version="0.1.0",
    description="A minimal Hello World test package for colcon build with setup.py only",
    packages=find_packages(),
    python_requires=">=3.6",
    entry_points={
        "console_scripts": [
            "hello-py = pkg_setup_py.main:main",
        ]
    }
)
