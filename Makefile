# nf-chain — common workflows. Run `make` (or `make help`) to list targets.

VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
BIN     := $(VENV)/bin/nf-chain
PREFIX  ?= $(HOME)/.local
LINK    := $(PREFIX)/bin/nf-chain
FLOW    ?= examples/sra_to_rnaseq.flow
PROFILE ?= docker
FORMAT  ?= mermaid

.DEFAULT_GOAL := help

## help: list targets
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## /  /'

## venv: create the virtualenv and install nf-chain (editable)
venv: $(BIN)
$(BIN): pyproject.toml
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install -q -e . && touch $(BIN)

## install: put a real `nf-chain` command on PATH (symlink into ~/.local/bin)
install: $(BIN)
	@mkdir -p $(PREFIX)/bin
	@ln -sf "$(abspath $(BIN))" "$(LINK)"
	@echo "linked $(LINK) -> $(abspath $(BIN))"
	@case ":$$PATH:" in *":$(PREFIX)/bin:"*) : ;; \
	  *) echo "WARNING: $(PREFIX)/bin is not on your PATH — add it to use \`nf-chain\`" ;; esac
	@command -v nf-chain >/dev/null && echo "ok: $$(command -v nf-chain)" || true

## uninstall: remove the `nf-chain` symlink
uninstall:
	@rm -f "$(LINK)" && echo "removed $(LINK)"

## test: run the test suite (offline)
test: $(BIN)
	@$(PY) -m pytest -q

## explain: resolve and print the chain  (FLOW=... )
explain: $(BIN)
	@$(BIN) explain $(FLOW)

## sync: fetch schemas and write VSCode stubs  (FLOW=... )
sync: $(BIN)
	@$(BIN) sync $(FLOW)

## dag: draw the chain as a graph  (FLOW=... FORMAT=mermaid|dot)
dag: $(BIN)
	@$(BIN) dag $(FLOW) --format $(FORMAT)

## build: generate the Nextflow project  (FLOW=... )
build: $(BIN)
	@$(BIN) build $(FLOW)

## wheel: build an sdist + wheel into dist/ (pip-installable anywhere)
wheel: $(BIN)
	@$(PIP) install -q build && $(PY) -m build

## run: build then run the chain, streaming every task  (FLOW=... PROFILE=docker)
run: $(BIN)
	@$(BIN) run $(FLOW) --profile $(PROFILE)

## clean: remove generated project and caches
clean:
	@rm -rf build_nf .nfchain .pytest_cache .mypy_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "cleaned"

.PHONY: help venv install uninstall test explain sync dag build wheel run clean
