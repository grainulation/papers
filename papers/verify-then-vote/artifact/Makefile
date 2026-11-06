# Reproduction targets for the artifact. Run from this directory; see README.md for what each
# target reproduces and its expected output.
#
#   make build                  reducer (release build)
#   make test                   reducer test suite (cargo test --release)
#   make test-quick             property checks + 500 in-memory replays
#   make replay-file            dump, reload and replay 5 topics; tamper rejections
#   make workload               synthetic workload modes (seed 42) into bench-output/workload/
#   make lean                   Lean proofs (fetches the Mathlib cache first)
#   make python-test            Python test suites (needs numpy, bm25s, scipy, pytest)
#   make portable-reanalysis    public v5/v6 reconstruction with a source-built reducer
#   make overturn-reanalysis    OVERTURN reconstruction from the sealed records, compared with results
#   make overturn-certificates  root hashes and certificates of that analysis, compared with the reference
#   make overturn-crosscheck    replay that analysis' reducer calls with a rebuilt binary
#   make secondpool-reanalysis  second-pool (v6) analysis from the sealed records, compared with results
#   make memoryonly-reanalysis  memory-only (v4) analysis from the sealed records, compared with results
#   make freetext-identifiers   identifier recovery on the free-text responses, compared with results

.PHONY: build test test-quick properties replay replay-file baselines replay-variance bench workload \
        lean python-test overturn-reanalysis overturn-certificates overturn-crosscheck secondpool-reanalysis memoryonly-reanalysis freetext-identifiers \
        reproduce clean

SHELL := /bin/bash
OVERTURN = ./overturn/target/release/overturn
SEED ?= 42
PY ?= python3
OUT ?= bench-output

# ── Build ─────────────────────────────────────────────────
build:
	cd overturn && cargo build --release --locked

# ── Reducer test suite: unit, property and equivalence tests ──
test:
	cd overturn && cargo test --release --locked

# ── Quick test: property checks + 100 replays per topic ───
test-quick: build
	$(OVERTURN) --properties --no-color --seed $(SEED)
	$(OVERTURN) --replay --replay-count 100 --no-color --seed $(SEED)

# ── Property checks only ──────────────────────────────────
properties: build
	$(OVERTURN) --properties --no-color --seed $(SEED)

# ── Replay determinism (1000 replays per topic) ───────────
replay: build
	$(OVERTURN) --replay --no-color --seed $(SEED)

# ── File replay: dump sealed artifact, reload, verify, re-reduce ──
REPLAY_DIR = bench-output/replay
REPLAY_N ?= 100

replay-file: build
	@mkdir -p $(REPLAY_DIR)
	@for t in australia pluto tides tcp nutrition; do \
		$(OVERTURN) --dump-artifact $(REPLAY_DIR)/$$t.json --topic $$t --agents $(REPLAY_N) --seed $(SEED) --no-color || exit 1; \
		$(OVERTURN) --replay-from $(REPLAY_DIR)/$$t.json --no-color || exit 1; \
	done
	@# Policy tamper: edit one policy field; replay must exit 4 (POLICY MISMATCH).
	@for edit in '.policy.deadband_threshold = 501' '.policy.weights[0] = 0.36' \
		'.policy.values.incompatible_values.uses.tcp_handshake |= .[:1]'; do \
		python3 -c 'import json,sys; \
f=json.load(open(sys.argv[1])); e=sys.argv[3]; p=f["policy"]; \
exec({".policy.deadband_threshold = 501": "p[\"deadband_threshold\"]=501", \
".policy.weights[0] = 0.36": "p[\"weights\"][0]=0.36", \
".policy.values.incompatible_values.uses.tcp_handshake |= .[:1]": "g=p[\"values\"][\"incompatible_values\"][\"uses\"][\"tcp_handshake\"]; del g[1:]"}[e]); \
json.dump(f, open(sys.argv[2],"w"))' \
			$(REPLAY_DIR)/tcp.json $(REPLAY_DIR)/tcp.policy-tampered.json "$$edit" || exit 1; \
		$(OVERTURN) --replay-from $(REPLAY_DIR)/tcp.policy-tampered.json --no-color; rc=$$?; \
		if [ $$rc -ne 4 ]; then echo "  FAIL policy tamper [$$edit] not rejected as policy mismatch (exit $$rc)"; exit 1; fi; \
		echo "  PASS policy tamper [$$edit] rejected (exit 4)"; \
	done
	@rm -f $(REPLAY_DIR)/tcp.policy-tampered.json
	@# Content ids (bran-artifact/4): edit one claim, keep its id; replay must exit 3.
	@python3 -c 'import json,sys; f=json.load(open(sys.argv[1])); assert f["format"]=="bran-artifact/4"; \
f["artifact"]["contributions"][0]["canonical_form"]["object"]+="x"; json.dump(f, open(sys.argv[2],"w"))' \
		$(REPLAY_DIR)/tcp.json $(REPLAY_DIR)/tcp.claim-tampered.json || exit 1
	@$(OVERTURN) --replay-from $(REPLAY_DIR)/tcp.claim-tampered.json --no-color; rc=$$?; \
	if [ $$rc -ne 3 ]; then echo "  FAIL claim tamper (kept id) not rejected (exit $$rc)"; exit 1; fi; \
	echo "  PASS claim tamper (kept id) rejected (exit 3)"
	@rm -f $(REPLAY_DIR)/tcp.claim-tampered.json
	@# Format tag: /4 content retagged /2; replay must exit 5 (format mismatch).
	@python3 -c 'import json,sys; f=json.load(open(sys.argv[1])); f["format"]="bran-artifact/2"; json.dump(f, open(sys.argv[2],"w"))' \
		$(REPLAY_DIR)/tcp.json $(REPLAY_DIR)/tcp.format-tampered.json || exit 1
	@$(OVERTURN) --replay-from $(REPLAY_DIR)/tcp.format-tampered.json --no-color; rc=$$?; \
	if [ $$rc -ne 5 ]; then echo "  FAIL format retag not rejected as format mismatch (exit $$rc)"; exit 1; fi; \
	echo "  PASS format retag rejected (exit 5)"
	@# Envelope (unhashed metadata): edit topic; replay must exit 6.
	@python3 -c 'import json,sys; f=json.load(open(sys.argv[1])); assert f["envelope_hash"]; f["topic"]="pluto"; json.dump(f, open(sys.argv[2],"w"))' \
		$(REPLAY_DIR)/tcp.json $(REPLAY_DIR)/tcp.envelope-tampered.json || exit 1
	@$(OVERTURN) --replay-from $(REPLAY_DIR)/tcp.envelope-tampered.json --no-color; rc=$$?; \
	if [ $$rc -ne 6 ]; then echo "  FAIL topic edit not rejected as envelope mismatch (exit $$rc)"; exit 1; fi; \
	echo "  PASS topic edit rejected (exit 6)"
	@rm -f $(REPLAY_DIR)/tcp.format-tampered.json $(REPLAY_DIR)/tcp.envelope-tampered.json
	@# --reduce --emit-artifact: sealing the dump's contributions reproduces its sealed set, policy and outputs.
	@python3 -c 'import json,sys; a=json.load(open(sys.argv[1]))["artifact"]; \
json.dump({k: a[k] for k in ("intent","criteria","calibration","id_scheme","contributions")} | {"topic": "tcp"}, open(sys.argv[2],"w"))' \
		$(REPLAY_DIR)/tcp.json $(REPLAY_DIR)/tcp.reduce-in.json || exit 1
	@$(OVERTURN) --reduce $(REPLAY_DIR)/tcp.reduce-in.json --emit-artifact $(REPLAY_DIR)/tcp.emitted.json --no-color > /dev/null || exit 1
	@$(OVERTURN) --replay-from $(REPLAY_DIR)/tcp.emitted.json --require-envelope --json --no-color > /dev/null || { echo "  FAIL emitted artifact does not replay"; exit 1; }
	@python3 -c 'import json,sys; d,e=(json.load(open(p)) for p in sys.argv[1:]); \
assert all(d[k]==e[k] for k in ("format","artifact","policy","policy_hash","outputs")), "emitted artifact differs from dump"' \
		$(REPLAY_DIR)/tcp.json $(REPLAY_DIR)/tcp.emitted.json || exit 1
	@echo "  PASS --reduce --emit-artifact reproduces the dump's sealed set, policy and outputs; replays with envelope"
	@rm -f $(REPLAY_DIR)/tcp.reduce-in.json $(REPLAY_DIR)/tcp.emitted.json
	@# --reduce with id_scheme: reproduces the dump, rejects kept-id edits, drops SYNTHESIS at P3.
	@python3 v2/evidence/content-ids/check_reduce.py $(OVERTURN) $(REPLAY_DIR)/tcp.json $(REPLAY_DIR)/reduce-check || exit 1
	@# Legacy: committed bran-artifact/2 and /3 files still verify, and
	@# --legacy-ids reproduces the committed /2 dumps byte for byte.
	@for d in v2/evidence/replay/dumps/*/*.json v2/evidence/fixtures/tcp-evidence.bran-artifact-3.json; do \
		$(OVERTURN) --replay-from $$d --no-color > /dev/null || { echo "  FAIL legacy replay $$d"; exit 1; }; \
	done; echo "  PASS committed bran-artifact/2 and /3 files replay"
	@for t in australia pluto tides tcp nutrition; do \
		$(OVERTURN) --dump-artifact $(REPLAY_DIR)/$$t.legacy.json --legacy-ids --topic $$t --agents 100 --seed 42 --no-color > /dev/null || exit 1; \
		cmp -s $(REPLAY_DIR)/$$t.legacy.json v2/evidence/replay/dumps/aarch64-apple-darwin/$$t.json || { echo "  FAIL --legacy-ids $$t differs from committed dump"; exit 1; }; \
	done; echo "  PASS --legacy-ids reproduces the committed bran-artifact/2 dumps"
	@rm -rf $(REPLAY_DIR)/*.legacy.json $(REPLAY_DIR)/reduce-check

# ── Baseline comparison ───────────────────────────────────
baselines: build
	$(OVERTURN) --baselines --no-color --seed $(SEED)
	$(OVERTURN) --baselines-scale --no-color --seed $(SEED)

# ── Replay variance (overturn vs baselines) ──────────────────
replay-variance: build
	$(OVERTURN) --replay-variance --no-color --seed $(SEED)

# ── Benchmark suite with text and CSV output in bench-output/ ──
bench: build
	bash bench.sh

# ── Synthetic workload (workload tables, Appendix E); timings vary by machine ──
workload: build
	@mkdir -p $(OUT)/workload
	$(OVERTURN) --stress --no-color --seed $(SEED) > $(OUT)/workload/stress.txt
	$(OVERTURN) --pass-timing --no-color --seed $(SEED) > $(OUT)/workload/pass-timing.txt
	$(OVERTURN) --score-gaps --no-color --seed $(SEED) > $(OUT)/workload/score-gaps.txt
	$(OVERTURN) --baselines --no-color --seed $(SEED) > $(OUT)/workload/baselines.txt
	$(OVERTURN) --ablation --no-color --seed $(SEED) > $(OUT)/workload/ablation.txt
	@echo "wrote $(OUT)/workload/; compare with results/workload/ and v2/evidence/stress/"

# ── Lean proofs ───────────────────────────────────────────
lean:
	cd lean && lake exe cache get && lake build

# ── Python test suites (no models, no network) ────────────
python-test:
	$(PY) -m pytest -q

# ── OVERTURN (v5): re-analysis from the sealed records ────
# Runs the frozen evaluator through the portable wrapper with the original arguments and a
# source-built reducer; checks decisions, statistics, rendered tables and certificates.
V5 = real-agent-eval/v5
V5_OUT = $(abspath $(OUT))/overturn
overturn-reanalysis: build
	$(PY) reproduction/portable.py --study v5 --bin $(OVERTURN) --out $(V5_OUT)

# Compares the root hash, policy hash and certificate of each of the 7,910 reductions of the
# re-analysis with the published reference results/conf/eval/certificates_v5.jsonl.
overturn-certificates:
	cd $(V5) && $(PY) certificates.py --rust-dir $(V5_OUT)/rust --check

# Re-runs every reducer call of the re-analysis (about 220 MB in $(OUT)/overturn/rust) with another
# binary, by default the one `make build` produced, and checks that each output is byte-identical.
CROSS_BIN ?= $(abspath $(OVERTURN))
overturn-crosscheck:
	cd $(V5) && $(PY) replay_reductions.py --rust-dir $(V5_OUT)/rust --bin $(CROSS_BIN)

# ── Second agent pool (v6): re-analysis from the sealed records ──
# Runs the frozen evaluator through the portable wrapper (see FROZEN_REDACTIONS.md)
# and compares per-item decisions and statistical outputs with published results.
V6 = real-agent-eval/v6
V6_OUT = $(abspath $(OUT))/secondpool
secondpool-reanalysis: build
	$(PY) reproduction/portable.py --study v6 --bin $(OVERTURN) --out $(V6_OUT)

# ── Memory-only benchmark (v4): re-analysis from the sealed records ──
memoryonly-reanalysis: build
	$(PY) real-agent-eval/v4/reanalyze.py --out $(abspath $(OUT))/memoryonly --bin $(abspath $(OVERTURN)) --compare
	@rm -rf $(abspath $(OUT))/memoryonly/rust $(abspath $(OUT))/memoryonly/s1_rust

# ── Free-text study: identifier recovery from the v3 responses ──
freetext-identifiers:
	@mkdir -p $(OUT)
	$(PY) -I tools/evidence/extract.py measure --raw-dir real-agent-eval/v3/results/raw \
		--results-dir real-agent-eval/v3/results --json $(OUT)/v3_identifier_recovery.json > /dev/null
	cmp $(OUT)/v3_identifier_recovery.json tools/evidence/results/v3_identifier_recovery.json \
		&& echo "  PASS identifier recovery matches tools/evidence/results/"

# ── Everything that needs no models, no hosted calls and no Docker ──
reproduce: test test-quick replay-file workload lean python-test portable-reanalysis \
           memoryonly-reanalysis freetext-identifiers
	@echo ""
	@echo "=== Reproduction complete ==="

# ── Clean build artifacts ─────────────────────────────────
clean:
	cd overturn && cargo clean
	rm -rf bench-output/

# Portable reconstruction: does not execute or replace the frozen macOS binaries.
.PHONY: portable-reanalysis
portable-reanalysis: build
	$(PY) reproduction/portable.py --study v5 --bin $(OVERTURN) --out $(OUT)/portable-v5
	$(PY) reproduction/portable.py --study v6 --bin $(OVERTURN) --out $(OUT)/portable-v6
