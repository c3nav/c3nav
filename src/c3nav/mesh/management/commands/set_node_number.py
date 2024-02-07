from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from c3nav.mesh.models import MeshNode

names = {
    1: "Alpheratz",
    2: "Ankaa",
    3: "Schedar",
    4: "Diphda",
    5: "Achernar",
    6: "Hamal",
    7: "Acamar",
    8: "Menkar",
    9: "Mirfak",
    10: "Aldebaran",
    11: "Rigel",
    12: "Capella",
    13: "Bellatrix",
    14: "Elnath",
    15: "Alnilam",
    16: "Betelgeuse",
    17: "Canopus",
    18: "Sirius",
    19: "Adhara",
    20: "Procyon",
    21: "Pollux",
    22: "Avior",
    23: "Suhail",
    24: "Miaplacidus",
    25: "Alphard",
    26: "Regulus",
    27: "Dubhe",
    28: "Denebola",
    29: "Gienah",
    30: "Acrux",
    31: "Gacrux",
    32: "Alioth",
    33: "Spica",
    34: "Alkaid",
    35: "Hadar",
    36: "Menkent",
    37: "Arcturus",
    38: "Rigil Kentaurus",
    39: "Zubenelgenubi",
    40: "Kochab",
    41: "Alphecca",
    42: "Antares",
    43: "Atria",
    44: "Sabik",
    45: "Shaula",
    46: "Rasalgethi",
    47: "Eltanin",
    48: "Kaus Australis",
    49: "Vega",
    50: "Nunki",
    51: "Altair",
    52: "Peacock",
    53: "Deneb",
    54: "Enif",
    55: "Alnair",
    56: "Fomalhaut",
    57: "Markab",
    58: "Mimosa",
    59: "Toliman",
    60: "Alnitak",
    61: "Wezen",
    62: "Sargas",
    63: "Menkalinan",
    64: "Alhena",
    65: "Polaris",
    66: "Castor",
    67: "Mirzam",
    68: "Alsephina",
    69: "Saiph",
    70: "Rasalhague",
    71: "Algol",
    72: "Almach",
    73: "Tiaki",
    74: "Aspidiske",
    75: "Naos",
    76: "Mizar",
    77: "Sadr",
    78: "Mintaka",
    79: "Caph",
    80: "Dschubba",
    81: "Larawag",
    82: "Merak",
    83: "Izar",
    84: "Phecda",
    85: "Scheat",
    86: "Alderamin",
    87: "Aludra",
    88: "Acrab",
    89: "Markeb",
    90: "Zosma",
    91: "Arneb",
    92: "Ascella",
    93: "Algieba",
    94: "Zubeneschamali",
    95: "Unukalhai",
    96: "Sheratan",
    97: "Kraz",
    98: "Mahasim",
    99: "Phact",
    100: "Ruchbah",
    101: "Muphrid",
    102: "Hassaleh",
    103: "Lesath",
    104: "Kaus Media",
    105: "Tarazed",
    106: "Athebyne",
    107: "Yed Prior",
    108: "Porrima",
    109: "Imai",
    110: "Zubenelhakrabi",
    111: "Cebalrai",
    112: "Cursa",
    113: "Kornephoros",
    114: "Rastaban",
    115: "Hatysa",
    116: "Nihal",
    117: "Paikauhale",
    118: "Kaus Borealis",
    119: "Algenib",
    120: "Tureis",
    121: "Alcyone",
    122: "Deneb Algedi",
    123: "Vindemiatrix",
    124: "Tejat",
    125: "Albaldah",
    126: "Cor Caroli",
    127: "Fang",
    128: "Gomeisa",
    129: "Fawaris",
    130: "Alniyat",
    131: "Sadalsuud",
    132: "Matar",
    133: "Algorab",
    134: "Sadalmelik",
    135: "Tianguan",
    136: "Zaurak",
    137: "Alnasl",
    138: "Okab",
    139: "Aldhanab",
    140: "Pherkad",
    141: "Xamidimura",
    142: "Furud",
    143: "Almaaz",
    144: "Seginus",
    145: "Albireo",
    146: "Dabih",
    147: "Mebsuta",
    148: "Tania Australis",
    149: "Altais",
    150: "Sarin",
}


class Command(BaseCommand):
    help = 'set node number of non-named node'

    def add_arguments(self, parser):
        parser.add_argument('number', type=int, help=_('number to set'))

    def handle(self,  *args, **options):
        number = options["number"]
        try:
            name = names[options["number"]]
        except KeyError:
            print('number without name')
            return

        if MeshNode.objects.filter(name__startswith=f"{number} – ").exists():
            print('number is already taken')
            return

        unnamed_nodes = list(MeshNode.objects.filter(name__isnull=True))

        if not unnamed_nodes:
            print('no unnamed nodes')
            return

        if len(unnamed_nodes) > 1:
            print('more than on unnamed node')
            return

        node = unnamed_nodes[0]
        node.name = f"{number} – {name}"
        node.save()
        print('done')
