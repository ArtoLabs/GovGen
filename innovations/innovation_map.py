from typing import Dict, List
from innovations.innovation import ALL_INNOVATIONS, INTERFACE_ICONS, Innovation

# Interface key -> innovations that interface can research, built from the data files.
ROLE_INNOVATION_MAP: Dict[str, List[Innovation]] = {key: [] for key in INTERFACE_ICONS}
for _innovation in ALL_INNOVATIONS.values():
    ROLE_INNOVATION_MAP[_innovation.interface].append(_innovation)
