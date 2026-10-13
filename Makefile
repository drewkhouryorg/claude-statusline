# Everyday tasks. `make` alone lists them.

PYTHON ?= python3

.PHONY: help test snapshots test-linux screenshots preview

help:  ## list the tasks
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 16

test:  ## run every test that can run here
	$(PYTHON) -m unittest discover -s tests

snapshots:  ## re-record the snapshots after a change you meant; then read git diff
	UPDATE_SNAPSHOTS=1 $(PYTHON) -m unittest discover -s tests -p test_scenarios.py

test-linux:  ## run the tests in Alpine (Python 3.8) and Debian (Python 3.13) containers
	docker run --rm -v "$(CURDIR)":/src:ro python:3.8-alpine sh -c 'apk add -q --no-cache git bash make jq >/dev/null && cp -r /src /tmp/r && rm -rf /tmp/r/.private-words /tmp/r/statusline/cache && cd /tmp/r && python3 -m unittest discover -s tests'
	docker run --rm -v "$(CURDIR)":/src:ro python:3.13-slim sh -c 'apt-get -qq update && apt-get -qq install -y git make jq >/dev/null && cp -r /src /tmp/r && rm -rf /tmp/r/.private-words /tmp/r/statusline/cache && cd /tmp/r && python3 -m unittest discover -s tests'

screenshots:  ## redraw docs/images from the scenarios
	uv run --no-project --with pillow --with fonttools python tools/screenshots.py

preview:  ## every scenario in this terminal
	$(PYTHON) tools/preview.py --all
