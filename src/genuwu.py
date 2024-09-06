import re
import sys
from itertools import chain, zip_longest
from pathlib import Path

import polib

file = Path(__file__).resolve().parent / "c3nav" / "locale" / "en_UW" / "LC_MESSAGES" / "django.po"
if not file.exists():
    print('Run makemessages -l en_UW first!')
    sys.exit(1)

po = polib.pofile(file)

from uwuipy import Uwuipy
uwu = Uwuipy(
    seed=1337,
    stutter_chance=0,
    face_chance=0,
    action_chance=0,
    exclamation_chance=0,
    nsfw_actions=False,
    power=4,
)
uwu_more = Uwuipy(
    seed=1337,
    stutter_chance=0,
    action_chance=0,
    exclamation_chance=0,
    power=4,
)
uwu_most = Uwuipy(
    seed=1337,
    stutter_chance=0,
    action_chance=0.05,
    face_chance=0.1,
    nsfw_actions=False,
    power=4,
)

special_pattern = r'(%%|%(\([^)]*\))?[^a-z]*[a-z]|<[^>]*>|\{[^}]*\})'


def uwuify(owiginal):
    stripped_owiginal = re.sub(special_pattern, '{}', owiginal)
    specials = [item[0] for item in re.findall(special_pattern, owiginal)]
    num_wowds = len(stripped_owiginal.split("(")[0].split())
    if num_wowds >= 8:
        twanslated = uwu_most.uwuify(stripped_owiginal)
    elif num_wowds >= 3:
        twanslated = uwu_more.uwuify(stripped_owiginal)
    else:
        twanslated = uwu.uwuify(stripped_owiginal)
    twanslated = twanslated.replace('***', '*').replace(r'\<', '<').replace(r'\>', '>')
    if specials:
        twanslated = ''.join(chain(*zip(twanslated.split('{}'), specials+[""])))
    return twanslated


po.metadata["Plural-Forms"] = "nplurals=2; plural=(n != 1);"
for entry in po:
    if entry.msgid_plural:
        entry.msgstr_plural[0] = uwuify(entry.msgid)
        entry.msgstr_plural[1] = uwuify(entry.msgid_plural)
    else:
        entry.msgstr = uwuify(entry.msgid)

po.save(file)

