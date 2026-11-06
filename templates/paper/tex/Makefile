# Build the paper: `make` -> main.pdf
# Uses Tectonic when available, otherwise latexmk + pdflatex (as on arXiv).
# No shell-escape is needed or used.

TEX_SRC := main.tex macros.tex refs.bib $(wildcard sections/*.tex) $(wildcard figures/*)
TECTONIC := $(shell command -v tectonic 2>/dev/null)

.PHONY: all clean arxiv check

all: main.pdf

main.pdf: $(TEX_SRC)
ifneq ($(TECTONIC),)
	tectonic --keep-intermediates --keep-logs main.tex
else
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
endif

# LaTeX warnings from the last build.
check: main.pdf
	@grep -E 'Warning|Overfull|Underfull' main.log || echo "no warnings"

# Source bundle for arXiv (includes the generated .bbl).
arxiv: main.pdf arxiv-files.txt build_arxiv.py
	python3 build_arxiv.py

clean:
	rm -f main.pdf main.aux main.log main.out main.bbl main.blg main.toc arxiv.tar.gz
