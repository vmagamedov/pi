.PHONY: requires.txt

__default__:
	@echo "Please specify a target to make"

requires.txt:
	pip-compile requires.in

requires:
	rm -rf ./*.egg-info
	rm -rf pi/_requires/*
	touch pi/_requires/__init__.py
	pip3 install --disable-pip-version-check --no-deps -t pi/_requires -r requires.txt
	rm -rf pi/_requires/*.{egg-info,dist-info}
	python3 -c "import sys; from lib2to3.main import main; sys.exit(main('fixers'))" --no-diffs -f imports -w -n pi/_requires

	# fix Jinja2 import in compiled code
	sed -i.bak 's/from jinja2\.runtime/from pi\._requires\.jinja2\.runtime/g' pi/_requires/jinja2/compiler.py
	rm pi/_requires/jinja2/compiler.py.bak

	# fix hacky optimization in Jinja2
	sed -i.bak "s/name_re = _make_name_re()/name_re = re.compile(r'\\\\b[a-zA-Z_][a-zA-Z0-9_]*\\\\b')/g" pi/_requires/jinja2/lexer.py
	rm pi/_requires/jinja2/lexer.py.bak

	# fix hacky backward compatibility in Requests
	> pi/_requires/requests/packages.py

	# fix transitive import in Requests
	echo "chardet = pi._requires.chardet" >> pi/_requires/requests/compat.py

release: requires
	python setup.py sdist
