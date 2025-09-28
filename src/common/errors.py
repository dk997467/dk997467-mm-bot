import re


ALLOWED_PREFIXES = (
    'E_CFG_', 'E_BT_LOADER_', 'E_PROFILE_', 'E_SOAK_', 'E_HA_', 'E_EDGE_', 'E_FINOPS_', 'E_REGION_'
)


def one_line(msg: str, code: str) -> str:
    c = str(code).strip()
    # Normalize code prefix
    if not any(c.startswith(p) for p in ALLOWED_PREFIXES):
        c = 'E_CFG_' + c
    # Normalize message: collapse whitespace and strip newlines
    m = str(msg)
    m = m.replace('\r', ' ')
    m = m.replace('\n', ' ')
    m = re.sub(r'\s+', ' ', m).strip()
    return f"{c}: {m}"


def raise_one_line(code: str, msg: str) -> None:
    raise ValueError(one_line(msg, code))


