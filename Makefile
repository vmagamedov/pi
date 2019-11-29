.PHONY: requires.txt

__default__:
	@echo "Please specify a target to make"

requires.txt:
	pip-compile requires.in

requires:
	rm -rf pi/_requires/*
	touch pi/_requires/__init__.py
	pip3 install --disable-pip-version-check --no-deps -t pi/_requires -r requires.txt
	rm -rf pi/_requires/*.{egg-info,dist-info}
	python3 -c "import sys; from lib2to3.main import main; sys.exit(main('fixers'))" --no-diffs -f imports -w -n pi/_requires

	# fix Jinja2 import in compiled code
	sed -i.bak 's/from jinja2\./from pi\._requires\.jinja2\./g' pi/_requires/jinja2/compiler.py
	rm pi/_requires/jinja2/compiler.py.bak

	# fix hacky optimization in Jinja2
	sed -i.bak -e '48,53d' pi/_requires/jinja2/lexer.py
	rm pi/_requires/jinja2/lexer.py.bak

	rm -rf pi/_requires/bin
	rm -rf pi/_requires/h11/tests

release: requires
	python setup.py sdist
