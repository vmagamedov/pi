import os.path

from lib2to3.pygram import python_symbols
from lib2to3.fixer_util import Name
from lib2to3.fixes.fix_imports import FixImports as BaseFixImports, alternates


PATH = '{}/../pi/_requires'.format(os.path.dirname(__file__))

LIBS = [i.rstrip('.py') for i in os.listdir(PATH)
        if not i.startswith('_') and not i.endswith(('.pyc', '.pyo'))]


def build_pattern(mapping):
    mod_list = ' | '.join(["module_name='%s'" % key for key in mapping])
    dotted_mod_list = ' | '.join(["module_name=dotted_name<'{}' ('.' NAME)*>"
                                  .format(key)
                                  for key in mapping])
    bare_names = alternates(mapping.keys())

    yield """name_import=import_name< 'import' ((%s) |
               multiple_imports=dotted_as_names< any* (%s) any* >) >
          """ % (dotted_mod_list, dotted_mod_list)
    yield """import_from< 'from' (%s) 'import' ['(']
              ( any | import_as_name< any 'as' any > |
                import_as_names< any* >)  [')'] >
          """ % dotted_mod_list
    yield """import_name< 'import' (dotted_as_name< (%s) 'as' any > |
                   multiple_imports=dotted_as_names<
                     any* dotted_as_name< (%s) 'as' any > any* >) >
          """ % (dotted_mod_list, dotted_mod_list)

    yield """name_import=import_name< 'import' ((%s) |
               multiple_imports=dotted_as_names< any* (%s) any* >) >
          """ % (mod_list, mod_list)
    yield """import_from< 'from' (%s) 'import' ['(']
              ( any | import_as_name< any 'as' any > |
                import_as_names< any* >)  [')'] >
          """ % mod_list
    yield """import_name< 'import' (dotted_as_name< (%s) 'as' any > |
                   multiple_imports=dotted_as_names<
                     any* dotted_as_name< (%s) 'as' any > any* >) >
          """ % (mod_list, mod_list)

    # Find usages of module members in code e.g. thread.foo(bar)
    yield "power< bare_with_attr=(%s) trailer<'.' any > any* >" % bare_names


class FixImports(BaseFixImports):
    mapping = {"{}".format(lib): 'pi._requires.{}'.format(lib)
               for lib in LIBS}

    def build_pattern(self):
        return "|".join(build_pattern(self.mapping))

    def transform(self, node, results):
        import_mod = results.get("module_name")
        if import_mod and import_mod.type == python_symbols.dotted_name:
            mod_name = import_mod.children[0].value
            new_name = self.mapping[mod_name]
            tail = ''.join(child.value for child in import_mod.children[1:])
            import_mod.replace(Name(new_name + tail, prefix=import_mod.prefix))
            if "name_import" in results:
                self.replace[mod_name] = new_name
            if "multiple_imports" in results:
                results = self.match(node)
                if results:
                    self.transform(node, results)
        else:
            return super().transform(node, results)
