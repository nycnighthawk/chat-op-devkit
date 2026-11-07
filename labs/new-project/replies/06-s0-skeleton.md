````chatop
<<<CHATOP turn=@TURN@>>>
@@summary S0 skeleton: package, pytest config, smoke test
@@test tests/test_smoke.py
import csv2md


def test_version() -> None:
    assert csv2md.__version__ == "0.1.0"
@@end
@@file pyproject.toml
[project]
name = "csv2md"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
csv2md = "csv2md.cli:main"

[tool.pytest.ini_options]
pythonpath = ["src"]
@@end
@@file src/csv2md/__init__.py
__version__ = "0.1.0"
@@end
@@file src/csv2md/py.typed
@@end
@@file .gitignore
__pycache__/
.mypy_cache/
.pytest_cache/
@@end
<<<END>>>
````
