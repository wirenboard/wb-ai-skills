# Codestyle for WB-targeted code

## C++

Canonical reference: <https://github.com/wirenboard/codestyle/blob/main/C%2B%2B.ru.md>

Base: [Google C++ Style Guide](https://google.github.io/styleguide/cppguide.html).

**Naming:**

- Classes: `TModbusClient` (T-prefix), base classes end with `Base`: `TModbusClientBase`, interfaces: `IException`
- Methods: `CamelCase` starting with a verb: `GetValue`, `SetEnabled`
- Class fields: start with capital letter
- Local variables: `camelCase` or `snake_case` (never mix in one file)
- Abbreviations keep only first capital: `TMqttClient`
- Macros: avoid; use C++ constructs instead

**Formatting:** use `.clang-format` from <https://github.com/wirenboard/codestyle>. Apply before every commit.

```bash
# Check formatting
find src -name '*.cpp' -o -name '*.h' | xargs clang-format --dry-run --Werror -style=file

# Apply formatting
find src -name '*.cpp' -o -name '*.h' | xargs clang-format -i -style=file
```

## Python

Canonical reference: <https://github.com/wirenboard/codestyle/blob/main/python.ru.md>

Base: PEP8. Key differences:

- Max line length: **110** characters (not 78)
- **Double quotes** for strings: `"string"` (not `'string'`)
- Type annotations required
- Trailing comma after last element in multi-line collections
- Docstrings are **always multi-line**, even for a one-sentence text: nothing on the line after the opening `"""`, text starts on the next line, closing `"""` on its own line. Not enforced by the linters — reviewers check it

**Tools — run before every commit:**

```bash
# Install
pip install black isort pylint

# Check (dry-run)
python3 -m black --config pyproject.toml --check --diff $(../codestyle/python/ci/find-python-files)
python3 -m isort --settings-file pyproject.toml --check --diff $(../codestyle/python/ci/find-python-files)
python3 -m pylint $(../codestyle/python/ci/find-python-files)

# Autoformat
python3 -m black --config pyproject.toml $(../codestyle/python/ci/find-python-files)
python3 -m isort --settings-file pyproject.toml $(../codestyle/python/ci/find-python-files)
```

`pyproject.toml` and `find-python-files` are taken from the [codestyle repo](https://github.com/wirenboard/codestyle).

## Go

Canonical reference: <https://github.com/wirenboard/codestyle/blob/main/go.en.md>

```bash
go fmt ./...

# Static analysis
go mod vendor
staticcheck -go 1.13 ./...
```
