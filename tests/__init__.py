"""
This file is needed since we want to import some test utilities from modules in `tests`.
The drawback here is that if there are two packages with `tests/__init__.py` installed inplace,
there will be conflicts.
Hopefully it's just a temporary measure until the utils can be moved to the main package
and gated behind specific features.
"""
