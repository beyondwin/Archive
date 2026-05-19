Investigate why the rollout parser drops the final `assistant_message` row when the file ends without a trailing newline.

Steps tried so far:
- read the file with json.loads
- noticed missing last item
