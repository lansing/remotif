ASSETS_DIR := assets
BACKDROPS_DIR := $(ASSETS_DIR)/backdrops
PALETTES_DIR := $(ASSETS_DIR)/palettes
NSCDE_REPO := https://github.com/NsCDE/NsCDE
OUTPUT_DIR := output

.PHONY: fetch-assets preview generate clean

fetch-assets:
	@mkdir -p $(ASSETS_DIR)
	@echo "Fetching NsCDE assets (tarball, no git history)..."
	@curl -sL $(NSCDE_REPO)/archive/refs/heads/master.tar.gz | \
		tar xz --strip-components=2 -C $(ASSETS_DIR) \
		NsCDE-master/data/backdrops NsCDE-master/data/palettes
	@echo "Fetched $$(ls $(BACKDROPS_DIR) | wc -l | tr -d ' ') backdrops, $$(ls $(PALETTES_DIR) | wc -l | tr -d ' ') palettes"

preview:
	uv run python preview.py

generate:
	@mkdir -p $(OUTPUT_DIR)
	uv run python generate.py $(ARGS)

clean:
	rm -rf $(OUTPUT_DIR)
