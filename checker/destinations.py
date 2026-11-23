"""Destinations testées en plus de celles repérées dans le cache Aviasales, pour les alertes « vers partout ».

Liste de grands aéroports européens et méditerranéens desservis depuis Lyon, Genève ou Paris
(compagnies classiques et low-cost). Les destinations du même pays que le départ sont exclues
d'office (pas de vols intérieurs en destination finale ; une escale en France reste possible). Elle sert de filet : le moteur classe d'abord les destinations
dont Aviasales connaît un prix bas, puis passe sur les autres au fil des passages.
"""

POPULAR = [
    # Espagne / Portugal
    "BCN", "MAD", "PMI", "AGP", "SVQ", "VLC", "ALC", "BIO", "IBZ", "LIS", "OPO", "FAO", "TFS", "LPA",
    # Italie / Malte
    "FCO", "NAP", "VCE", "BLQ", "BRI", "CTA", "PMO", "OLB", "CAG", "MLA",
    # Europe du Nord et centrale
    "AMS", "BER", "PRG", "BUD", "KRK", "VIE", "CPH", "DUB", "EDI", "LGW", "STN", "BRU", "WAW",
    # Grèce, Balkans, Turquie
    "ATH", "SKG", "HER", "DBV", "SPU", "IST", "SAW",
    # Maghreb
    "RAK", "AGA", "TUN", "DJE", "ALG", "ORN", "CMN",
]
