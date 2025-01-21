PREFIX := `if test -d ".venv"; then echo ".venv/bin/"; else echo ""; fi`
SOURCE_FILES := "hishel tests"

default:
  @echo "\"just publish\"?"

check:
  {{PREFIX}}ruff format {{SOURCE_FILES}} --diff
  {{PREFIX}}ruff check {{SOURCE_FILES}}
  {{PREFIX}}mypy {{SOURCE_FILES}}
  {{PREFIX}}python unasync.py --check

test: check
  {{PREFIX}}coverage run -m pytest tests
  {{PREFIX}}coverage report --show-missing --skip-covered --fail-under=100

lint:
  {{PREFIX}}ruff check --fix {{SOURCE_FILES}}
  {{PREFIX}}ruff format {{SOURCE_FILES}}
  {{PREFIX}}python unasync.py

install:
  rm -rf .venv
  pip install uv
  uv venv
  source .venv/bin/activate
  uv pip install -r requirements.txt

publish:
  hatch publish -u __token__ -a $HISHEL_PYPI

publish-docs:
  mkdocs gh-deploy --force
