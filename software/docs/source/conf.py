# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Open Beam Interface'
copyright = '2024, Isabel Burgos, Adam McCombs'
author = 'Isabel Burgos, Adam McCombs'
release = '0.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "myst_parser", 
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.linkcode",
    "enum_tools.autoenum",
    "sphinxcontrib.yowasp_wavedrom"
    ]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    'numpy': ('http://docs.scipy.org/doc/numpy/', None),
}

myst_enable_extensions = ["attrs_inline", "colon_fence"]
#enables turning markdown headings into links
myst_heading_anchors = 6 

autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True
}
autodoc_typehints = "description"
#autodoc_typehints_description_target = "documented"

autodoc_preserve_defaults = True
autodoc_inherit_docstrings = False

templates_path = ['_templates']
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'furo'
html_static_path = ['_static']
html_favicon = '_static/favicon.png'
html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#FF4F00",
        "color-brand-content": "#2EA22A",
        "color-brand-visited": "#1F7B1E"
    },
    "dark_css_variables": {
        "color-brand-primary": "#FF4F00",
        "color-brand-content": "#2EA22A",
        "color-brand-visited": "#1F7B1E",
        "color-highlight-on-target": "#0B2B0B",
    },
    "light_logo": "image_scan_drawing_black.svg",
    "dark_logo": "image_scan_drawing_white.svg"
}

html_css_files = [
    'css/custom.css',
]

def linkcode_resolve(domain, info):
    if domain != 'py':
        return None
    if not info['module']:
        return None
    filename = info['module'].replace('.', '/')
    return "https://github.com/nanographs/Open-Beam-Interface/blob/update-main/software/%s.py" % filename
    