DOMAIN   = print_ease
SRCDIR   = src/$(DOMAIN)
LOCALEDIR = $(SRCDIR)/locale
LANGUAGES = de en fr es it pl pt nl cs ro ja sv da nb fi hu sk hr sr bg el tr zh_CN zh_TW ar hi th vi id uk ru he fa

.PHONY: pot mo clean

pot:
	xgettext --language=Python --keyword=_ \
	  --output=$(LOCALEDIR)/$(DOMAIN).pot \
	  --package-name=PrintEase --package-version=0.1.2 \
	  --copyright-holder="MrHaku81" \
	  --msgid-bugs-address="haku81.kk@gmail.com" \
	  $(shell find $(SRCDIR) -name "*.py" | sort)

mo:
	@for lang in $(LANGUAGES); do \
	  msgfmt $(LOCALEDIR)/$$lang/LC_MESSAGES/$(DOMAIN).po \
	    -o $(LOCALEDIR)/$$lang/LC_MESSAGES/$(DOMAIN).mo; \
	  echo "Compiled $$lang"; \
	done

clean:
	find $(LOCALEDIR) -name "*.mo" -delete
