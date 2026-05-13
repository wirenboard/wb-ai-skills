import re

from setuptools import find_packages, setup

with open("wb_cli/__init__.py", encoding="utf-8") as f:
    version = re.search(r'^__version__\s*=\s*"([^"]+)"', f.read(), re.M).group(1)

setup(
    name="wb-cli",
    version=version,
    packages=find_packages(include=["wb_cli*"]),
    entry_points={"console_scripts": ["wb-cli = wb_cli.cli:main"]},
    python_requires=">=3.9",
)
