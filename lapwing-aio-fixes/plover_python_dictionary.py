# vim: set fileencoding=utf-8 :

import typing
import importlib.util
import sys

from plover.steno_dictionary import StenoDictionary


def import_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

class PythonDictionary(StenoDictionary):

    readonly = True

    def __init__(self):
        super().__init__()
        self._mod = None
        self._lookup = None
        self._reverse_lookup = None
        self.readonly = True

    def _load(self, filename):
        dictionary_module = import_from_path("python_dictionary", filename)

        longest_key = getattr(dictionary_module, 'LONGEST_KEY', None)
        if not isinstance(longest_key, int) or longest_key <= 0:
            raise ValueError('missing or invalid `LONGEST_KEY\' constant: %s\n' % longest_key)
        lookup = getattr(dictionary_module, 'lookup', None)
        if not isinstance(lookup, typing.Callable):
            raise ValueError('missing or invalid `lookup\' function: %s\n' % lookup)
        reverse_lookup = getattr(dictionary_module, 'reverse_lookup', lambda x: set())
        if not isinstance(reverse_lookup, typing.Callable):
            raise ValueError('invalid `reverse_lookup\' function: %s\n' % reverse_lookup)
        self._mod = dictionary_module
        self._lookup = lookup
        self._longest_key = longest_key
        self._reverse_lookup = reverse_lookup

    def __contains__(self, key):
        if len(key) > self._longest_key:
            return False
        try:
            self._lookup(key)
        except KeyError:
            return False
        return True

    def __getitem__(self, key):
        if len(key) > self._longest_key:
            raise KeyError
        return self._lookup(key)

    def get(self, key, fallback=None):
        if len(key) > self._longest_key:
            return fallback
        try:
            return self._lookup(key)
        except KeyError:
            return fallback

    def reverse_lookup(self, value):
        return set(self._reverse_lookup(value))
