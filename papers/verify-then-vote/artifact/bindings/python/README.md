# overturn-arbiter

When several LLM agents disagree, `overturn-arbiter` picks one answer per conflict
the same way every time. The pick is a pure function of what the agents
said and the policy. Each decision comes with a certificate and can be sealed
into an artifact that anyone can replay and verify later. It is the Python
front end to the overturn reducer (Rust), from the paper *Verify, Then Vote:
Overturning Wrong Majorities in Multi-Agent LLMs*.

Status: pre-release (0.1.0). The package is distributed with the paper's artifact as source in
this directory; you build a wheel from it (see "Building a wheel"). The distribution name is
`overturn-arbiter` (the name `overturn` on PyPI belongs to an unrelated project); the import package
is `overturn_arbiter`.

## Generic arbitration quickstart

This first example uses the generic policy, **not** the paper's verified-overturn gate. URL citations alone are unverified. `verify()` checks artifact integrity and deterministic replay; it does not establish that an answer or cited passage is true.

```python
from overturn_arbiter import seal, verify
from overturn_arbiter.adapters import answers_to_contributions, summarize

q = "What is the capital of Australia?"
answers = {"llama": {"answer": "Canberra", "citations": ["https://en.wikipedia.org/wiki/Canberra"]},
           "mistral": "Sydney", "gemma": "Canberra", "phi": "Melbourne", "qwen": "Sydney"}
artifact = seal(answers_to_contributions(q, answers), intent=q)   # arbitrate + seal
result = summarize(q, artifact.decision)
print(result.winner_text, result.winner_agent, artifact.certificate)
assert verify(artifact).ok                                        # replay: hashes + outputs
```

Run the longer versions with `python examples/quickstart.py` and
`python examples/langgraph_debate.py`.

## Verify, then vote

Run `python examples/verify_then_vote.py` after installation for a self-contained, offline gate example. It seals a captured passage and a `supports` record, accepts that record's checker ID with `Policy.verify_then_vote(...)`, and overturns a two-agent majority. With the checker excluded, the same inputs preserve the majority. Both artifacts pass replay verification.

The example labels its passage and checker records as synthetic demonstration data. In an application, supply actual captured passages and support labels from a checker you have validated and explicitly accepted; the reducer makes no model calls and cannot determine whether that checker is truthful. `evidence_store` supplies the capture/support records referenced by each contribution's evidence. The example shows their schema and content hashes, and the test suite exercises both accepted and rejected checker paths.

## Install

Build a wheel as described in [Building a wheel](#building-a-wheel), then install it:

```
pip install dist/overturn_arbiter-0.1.0-*.whl                          # platform wheel bundles the reducer binary
pip install "dist/overturn_arbiter-0.1.0-py3-none-<platform>.whl[langgraph]"  # + LangGraph adapter
```

The reducer binary is looked up in this order: `OVERTURN_BIN`, then the copy
bundled in the wheel (`overturn_arbiter/_bin/`), then `overturn` on `PATH`. On a
platform with no wheel, build the crate (`cargo build --release` in `overturn/`)
and set `OVERTURN_BIN`.

## API

| Name | What it does |
|---|---|
| `Claim(subject, predicate, object, polarity)` | A canonical triple. Functional predicates (`is`, `has`, `has_capital`, ...) give one slot per (subject, predicate). |
| `Evidence(type, source, weight, ...)` | Evidence item (`CITATION`, `TOOL_RESULT`, `EMPIRICAL`, `AUTHORITY`, `REASONING`). |
| `Contribution(agent_id, claim, confidence, ...)` | One agent output. `seq` = arrival order, or the list position when omitted. |
| `Policy()` / `Policy.order_free()` | `Policy()` is the reducer default (hash `dd8d36e6def3a6d598765e82d461a473`). `order_free()` is the paper's recommendation: recency weight 0, recency removed from the Schulze voters, ties broken by content id. |
| `Policy.verify_then_vote(accepted_checkers, ...)` | Activates the verified-overturn gate using precomputed support records from accepted checker IDs; see the offline example. |
| `Policy.generic(order_free=False)` | The reducer default without the TCP demo's `values.incompatible_values` groups (Rust `--preset generic`, hash `b905878f08e54d92b5a6f1e73f0682f2`). The recommended base for your own claims: the default's groups only make sense for the paper's TCP demo topic. |
| `Policy(functional_predicates=[...])` | Extra predicates treated as functional (one slot per subject and predicate), on top of the built-in list. |
| `arbitrate(contributions, policy=None, ...) -> Decision` | Winner per slot, quantized scores, deadband flag, certificate, policy and root hashes, and the rejected ids with reasons. Uses `Policy.generic(order_free=True)` when `policy` is omitted: the order-free settings without the TCP demo's value groups. |
| `seal(...) -> Artifact` | `arbitrate` plus a replayable version-4 artifact file (`artifact.save(path)`), sealed by the reducer itself (`overturn --reduce IN --emit-artifact OUT`). It carries an `envelope_hash` over the metadata the other hashes do not cover (`topic`, `agents`, `seed`, `labels`). The artifact is replayed once before it is returned. |
| `verify(artifact or path) -> VerifyResult` | Checks the format tag, the root hash, the content ids, the policy hash, the re-reduced outputs, and the envelope hash when present. `reason` names what failed: `format` (exit 5), `artifact_hash` (3), `policy_hash` (4), `output` (1), `envelope` (6), `parse` (2). |
| `policy_hash(policy)` | The reducer's hash of a policy (`overturn --print-policy`). |
| `check_reducer()` | Checks the reducer binary's `--version`: its reducer-constants id must equal `REDUCER_CONSTANTS_ID`, otherwise policy hashes would differ from this package's. |
| `adapters.answers_to_contributions(question, answers)` | Turns plain answer strings, plus optional citations, into contributions. |
| `adapters.arbiter_node(...)` | A LangGraph node: `state["agent_outputs"]` goes in, `state["arbitration"]` comes out. |
| `adapters.build_debate_graph(agents)` | Builds a fan-out graph, START -> agents -> arbiter -> END (needs the `[langgraph]` extra). |

Determinism: equal inputs and policy give byte-identical `Decision.to_json()`
and `Artifact.to_json()`. Contribution ids are content-addressed, so reordering the input list never changes a
decision. Under `Policy.order_free()`, a change in arrival order also leaves
the winner and scores unchanged. Only the root hash and certificate move,
because `seq` is sealed.

Backends: the API calls a `Backend` (`reduce`, `assign_ids`, `seal`,
`default_policy`, `replay`; optionally `print_policy`, `version`). Today `SubprocessBackend` runs the binary. A
PyO3 backend can be swapped in with `set_default_backend`.

## Building a wheel

The `--cargo` route below requires the **full repository checkout**, including `artifact/overturn/`. A standalone Python source distribution (sdist) contains the front end, not the Rust crate. From an extracted sdist, use `python scripts/build_wheel.py --pure` and set `OVERTURN_BIN` to a separately built reducer, or pass that reducer with `--bin PATH` to bundle it. A normal PEP 517 build from the sdist also produces a pure wheel.

```
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/build_wheel.py --cargo    # remapped release build, separate target dir
.venv/bin/python -m pip install --force-reinstall --no-deps dist/*.whl
OVERTURN_TEST_INSTALLED=1 .venv/bin/python -m pytest
```

To reuse an already remapped release binary, use `scripts/build_wheel.py --bin PATH`. The default without `--cargo` looks in `../../overturn/target/release/overturn`; an ordinary development build there may be rejected for embedded workstation paths.

`--cargo` remaps workstation, temporary and Cargo source prefixes in compiled diagnostics. Externally supplied binaries must also be free of workstation paths: use a release build with equivalent Rust `--remap-path-prefix` flags. The builder rejects binaries with such paths before executing them, and the wheel hook scans every uncompressed archive member before accepting the final wheel. To recheck a distributable, run `python scripts/check_wheel.py dist/*.whl`.

A wheel with a bundled binary is tagged `py3-none-<platform>`. A wheel
without one is `py3-none-any` and requires an externally built reducer.

Bundled builds currently support native 64-bit macOS (arm64/x86_64) and Linux (aarch64/x86_64). The builder checks executable architecture, reducer constants, and macOS minimum OS version, and rejects cross-architecture binaries. Linux wheels receive a conservative `linux_<arch>` tag, not an inferred manylinux guarantee; build and test them on the target distribution. ABI/platform overrides that claim broader compatibility are rejected. Windows bundled-wheel builds are not supported. CI installs the wheel and runs the gate example and package tests with `OVERTURN_TEST_INSTALLED=1`, which checks that tests import the installed package and execute its bundled reducer.

## Citing

If you use overturn, please cite the paper:

```bibtex
@misc{grainulation2026verify,
  author       = {{Grainulation}},
  title        = {Verify, Then Vote: Overturning Wrong Majorities in Multi-Agent {LLMs}},
  year         = {2026},
  howpublished = {\url{https://github.com/grainulation/papers/tree/main/papers/verify-then-vote}}
}
```

## License

Apache License 2.0. See `LICENSE`.

Serialized format identifiers retain the frozen study spellings for exact replay; see the [compatibility boundary](../../COMPATIBILITY.md). They are not package or command names.
