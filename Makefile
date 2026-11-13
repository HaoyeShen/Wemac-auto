PYTHON ?= python3

.PHONY: test demo clean

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -t . -v

demo:
	PYTHONPATH=src $(PYTHON) examples/basic.py --help

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
