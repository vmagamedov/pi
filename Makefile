__default__:
	@echo "Please specify a target to make"

requires:
	rm -rf pi/_requires/*
	touch pi/_requires/__init__.py
	pip3 install --disable-pip-version-check --no-deps -t pi/_requires -r requires.txt
	rm -rf pi/_requires/*.{egg-info,dist-info}
	python -c "import sys; from lib2to3.main import main; sys.exit(main('fixers'))" --no-diffs -f imports -w -n pi/_requires
	sed -i '' 's/from jinja2\.runtime/from pi\._requires\.jinja2\.runtime/g' pi/_requires/jinja2/compiler.py
