import random

from django.forms.fields import BooleanField
from django.utils.translation import gettext_lazy as _

from django.conf import settings


login_options = (
    _('I am not affiliated with Automattic in any way, financially or otherwise.'),
    _('I am not Anish Kapoor, i am in no way affiliated to Anish Kapoor, I am not signing in on behalf of '
      'Anish Kapoor or an associate of Anish Kapoor. To the best of my knowledge, information and belief, this account '
      'will not make its way into the hands of Anish Kapoor.'),
    _('I do not use generative AI to create cheap assets for my talk slides.'),
    _('I have not checked this checkbox.'),
    _('I will not harm any human being, catgirl or similar creature nor through inaction permit any such creature '
      'to be harmed.'),
    _('I am not a robot or i am at least a cute one.'),
    _('I am a robot.'),
    _('I am a cat. meow meow mew :3'),
    _('I am a doggo. wruff!'),
    _('I am cute and will not say otherwise.'),
    _('Trans rights!'),
    _('Be excellent to each other.'),
    _('I acknowledge that any checkboxes shown under this form are optional, non-mandatory serving suggestions.'),
    _('Chaos™ is a registered trademark of Chaos Computer Club Veranstaltungsgesellschaft mbH.'),
    _('We and our %d partners value your privacy.'),
)


def get_random_checkbox_message() -> str:
    msg: str = random.choice(login_options)
    msg = msg.replace('%d', str(random.randint(1000, 3000)))
    return msg


def add_compliance_checkbox(form):
    if settings.COMPLIANCE_CHECKBOX:
        form.fields["check"] = BooleanField(required=False, label=get_random_checkbox_message(),
                                            help_text=_('If you do not like this checkbox, reload to get another one.'))


class ComplianceCheckboxFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_compliance_checkbox(self)
