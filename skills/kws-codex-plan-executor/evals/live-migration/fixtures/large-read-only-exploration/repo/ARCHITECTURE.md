# Architecture

Console calls API; API delegates to Core; Core owns policy and reads through Store. Store is a filesystem adapter.
