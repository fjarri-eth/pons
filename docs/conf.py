# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
# import os
# import sys
# sys.path.insert(0, os.path.abspath('.'))

import importlib.metadata
import os

import setuptools_scm

# -- Project information -----------------------------------------------------

project = "pons"
copyright = "2022-now, Bogdan Opanchuk"
author = "Bogdan Opanchuk"

# The full version, including alpha/beta/rc tags
try:
    release = importlib.metadata.version(project)
except importlib.metadata.PackageNotFoundError:
    release = setuptools_scm.get_version(relative_to=os.path.abspath("../pyproject.toml"))


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinxcontrib_trio",
    "sphinx.ext.intersphinx",
    "sphinx.ext.doctest",
    "sphinx.ext.viewcode",
]

autoclass_content = "both"
autodoc_member_order = "groupwise"
autodoc_default_options = {
    #'members': True,
    "undoc-members": False,
    #'show-inheritance': True,
}

# Add any paths that contain templates here, relative to this directory.
templates_path = []

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "furo"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []

# Do not prepend module to type names when it can be resolved.
python_use_unqualified_type_names = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "eth_account": ("https://eth-account.readthedocs.io/en/v0.13.0/", None),
    "eth_typing": ("https://eth-typing.readthedocs.io/en/stable/", None),
    "ethereum_rpc": ("https://ethereum-rpc.readthedocs.io/en/v0.1.0", None),
    "alysis": ("https://alysis.readthedocs.io/en/v0.6.0/", None),
    "trio": ("https://trio.readthedocs.io/en/v0.31.0/", None),
}
