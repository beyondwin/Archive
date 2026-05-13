"""parse_duration: convert duration strings like '1h30m' to total seconds."""


def parse_duration(s):
    if not s.strip():
        raise ValueError("empty")

    s = s.strip().lower()
    s = s.replace(" ", "")

    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    total = 0
    i = 0
    while i < len(s):
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        num_str = s[i:j] or "0"
        if j >= len(s):
            raise ValueError(f"missing unit: {s[i:]}")
        unit = s[j]
        if unit not in units:
            raise ValueError(f"unknown unit: {unit}")
        try:
            value = int(num_str)
        except ValueError:
            value = int(float(num_str))
        total += value * units[unit]
        i = j + 1
    return total
