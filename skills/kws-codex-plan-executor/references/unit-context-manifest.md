# Task Packet Contract

An executable task packet contains:

- task ID, title, dependencies, and risk/operator-review markers;
- allowed and forbidden file claims;
- acceptance commands or an honest substitute;
- explicit spec section refs when a spec exists;
- attempt kind and fixed route eligibility;
- evidence requirements and context budget;
- relevant prior decisions and dependency evidence refs.

The packet is immutable evidence for the attempt. A human-readable derivative
may be rendered, but it cannot add scope or override the JSON packet. Missing
required fields, path escape, ambiguous scope, or unresolved spec mapping blocks
before dispatch.
