# Build the main paper and its separate supporting material.
# Uses Tectonic when available, otherwise latexmk + pdflatex (as on arXiv).
# Both documents compile independently; no cross-document .aux files are needed.
# No shell-escape is needed or used.

TEX_SRC := preamble.tex macros.tex refs.bib $(wildcard sections/*.tex) \
           $(wildcard figures/*.tex) $(wildcard figures/*.dat)
TECTONIC := $(shell command -v tectonic 2>/dev/null)

.PHONY: all clean figdata arxiv check

all: main.pdf supplement.pdf

main.pdf supplement.pdf: %.pdf: %.tex $(TEX_SRC)
ifneq ($(TECTONIC),)
	tectonic --keep-intermediates --keep-logs $<
else
	latexmk -pdf -interaction=nonstopmode -halt-on-error $<
endif

# Regenerate Figure 4 data from the repository's result CSVs (needs Python 3).
figdata:
	python3 figures/make_fig3_data.py

# LaTeX warnings from the last builds.
check: main.pdf supplement.pdf
	@grep -E 'Warning|Overfull|Underfull' main.log supplement.log || echo "no warnings"

# Source tarball for arXiv (both standalone documents and their generated .bbl).
arxiv: main.pdf supplement.pdf arxiv-files.txt build_arxiv.py
	python3 build_arxiv.py

clean:
	rm -f main.pdf main.aux main.log main.out main.bbl main.blg main.toc \
	      supplement.pdf supplement.aux supplement.log supplement.out \
	      supplement.bbl supplement.blg supplement.toc arxiv.tar.gz
