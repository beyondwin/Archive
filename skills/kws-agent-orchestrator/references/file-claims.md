Source-of-truth: the design document wins when this reference and code disagree.

# File Claims

Modes are `owned`, `shared_append`, `consumes`, `read_only`, and `forbidden`.

Two `owned` claims on the same path conflict. `shared_append` claims may coexist when the runner validates append semantics.
