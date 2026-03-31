# Sphinx configuration for biardtz
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
import shutil

# -- Path setup --------------------------------------------------------------

__location__ = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(__location__, "../src"))

# -- Run sphinx-apidoc -------------------------------------------------------

try:
    from sphinx.ext import apidoc
except ImportError:
    from sphinx import apidoc

output_dir = os.path.join(__location__, "api")
module_dir = os.path.join(__location__, "../src/biardtz")

try:
    shutil.rmtree(output_dir)
except FileNotFoundError:
    pass

try:
    import sphinx
    cmd_line = f"sphinx-apidoc --implicit-namespaces -f -o {output_dir} {module_dir}"
    args = cmd_line.split(" ")
    if tuple(sphinx.__version__.split(".")) >= ("1", "7"):
        args = args[1:]
    apidoc.main(args)
except Exception as e:
    print(f"Running `sphinx-apidoc` failed!\n{e}")

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.coverage",
    "sphinx.ext.doctest",
    "sphinx.ext.ifconfig",
    "sphinx.ext.mathjax",
    "sphinx.ext.napoleon",
]

templates_path = ["_templates"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "index"

project = "biardtz"
copyright = "2026, Kevin Steptoe"

try:
    from biardtz import __version__ as version
except ImportError:
    version = ""

if not version or version.lower() == "unknown":
    version = os.getenv("READTHEDOCS_VERSION", "unknown")

release = version

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", ".venv"]

pygments_style = "sphinx"

todo_emit_warnings = True

# -- MyST-Parser configuration -----------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "tasklist",
]
myst_heading_anchors = 3

# -- Options for HTML output -------------------------------------------------

html_theme = "alabaster"

html_theme_options = {
    "sidebar_width": "300px",
    "page_width": "1200px",
}

html_static_path = ["_static"]

htmlhelp_basename = "biardtz-doc"

# -- Options for LaTeX output ------------------------------------------------

latex_elements = {}

latex_documents = [
    ("index", "user_guide.tex", "biardtz Documentation", "Kevin Steptoe", "manual")
]

# -- External mapping --------------------------------------------------------

python_version = ".".join(map(str, sys.version_info[0:2]))
intersphinx_mapping = {
    "sphinx": ("https://www.sphinx-doc.org/en/master", None),
    "python": ("https://docs.python.org/" + python_version, None),
    "setuptools": ("https://setuptools.pypa.io/en/stable/", None),
    "pyscaffold": ("https://pyscaffold.org/en/stable", None),
}

print(f"loading configurations for {project} {version} ...", file=sys.stderr)
