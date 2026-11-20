# Kinetik: install from source.
#   make install                       -> /usr/local (needs sudo)
#   make install PREFIX=$HOME/.local   -> just for you, no sudo
#   make uninstall PREFIX=...          -> remove again (use the same PREFIX)
#   make test | make run | make dist
PREFIX  ?= /usr/local
DESTDIR ?=
NAME    := kinetik
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' kinetik/__init__.py)
PYTHON  ?= python3

BINDIR  := $(DESTDIR)$(PREFIX)/bin
PKGDIR  := $(DESTDIR)$(PREFIX)/share/$(NAME)
APPDIR  := $(DESTDIR)$(PREFIX)/share/applications
HICOLOR := $(DESTDIR)$(PREFIX)/share/icons/hicolor
ICONDIR := $(HICOLOR)/scalable/apps
ICON_SIZES := 16 22 24 32 48 64 128 256
DOCDIR  := $(DESTDIR)$(PREFIX)/share/doc/$(NAME)
SOURCES := $(shell find kinetik -name '*.py' -o -name '*.svg' | sort)

.PHONY: all install uninstall test run dist

all:
	@echo "Targets: install, uninstall, test, run, dist (see README.md)"

install:
	@test -n "$(PREFIX)" || { echo "PREFIX must not be empty"; exit 1; }
	install -d $(BINDIR) $(APPDIR) $(ICONDIR) $(DOCDIR)
	for f in $(SOURCES); do install -D -m 644 "$$f" "$(PKGDIR)/$$f"; done
	printf '#!/bin/sh\n# Kinetik launcher\nexport PYTHONPATH="%s$${PYTHONPATH:+:$$PYTHONPATH}"\nexec %s -m kinetik "$$@"\n' \
		"$(PREFIX)/share/$(NAME)" "$(PYTHON)" > $(BINDIR)/$(NAME)
	chmod 755 $(BINDIR)/$(NAME)
	sed 's|^Exec=$(NAME)|Exec=$(PREFIX)/bin/$(NAME)|' data/$(NAME).desktop > $(APPDIR)/$(NAME).desktop
	chmod 644 $(APPDIR)/$(NAME).desktop
	install -m 644 kinetik/assets/$(NAME).svg $(ICONDIR)/$(NAME).svg
	for s in $(ICON_SIZES); do install -D -m 644 data/icons/$$s.png $(HICOLOR)/$${s}x$${s}/apps/$(NAME).png; done
	-touch $(HICOLOR)
	install -m 644 README.md LICENSE $(DOCDIR)/

# Removes exactly the files `make install` created (no recursive deletes).
uninstall:
	@test -n "$(PREFIX)" || { echo "PREFIX must not be empty"; exit 1; }
	for f in $(SOURCES); do rm -f "$(PKGDIR)/$$f"; done
	-find "$(PKGDIR)" -depth -type d -empty -delete
	rm -f $(BINDIR)/$(NAME) $(APPDIR)/$(NAME).desktop $(ICONDIR)/$(NAME).svg
	for s in $(ICON_SIZES); do rm -f $(HICOLOR)/$${s}x$${s}/apps/$(NAME).png; done
	rm -f $(DOCDIR)/README.md $(DOCDIR)/LICENSE
	-rmdir $(DOCDIR)

test:
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m unittest discover -v

run:
	$(PYTHON) -m kinetik

dist:
	mkdir -p dist
	tar --exclude-vcs --exclude='__pycache__' --exclude=./dist --exclude=./build \
		--transform 's,^\.,$(NAME)-$(VERSION),' -czf dist/$(NAME)-$(VERSION).tar.gz .
	@echo "dist/$(NAME)-$(VERSION).tar.gz"

