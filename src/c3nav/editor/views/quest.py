from functools import cached_property

from django.http import Http404
from django.urls import reverse_lazy
from django.views.generic.edit import FormView

from c3nav.mapdata.quests.base import get_quest_for_request
from c3nav.site.views import close_response


class QuestFormView(FormView):
    template_name = "editor/quest_form.html"
    success_url = reverse_lazy("editor.thanks")

    @cached_property
    def quest(self):
        quest = get_quest_for_request(request=self.request,
                                      quest_type=self.kwargs["quest_type"],
                                      identifier=self.kwargs["identifier"])
        if quest is None:
            raise Http404
        return quest

    def get_form_class(self):
        return self.quest.get_form_class()

    def get_form_kwargs(self):
        return {
            "request": self.request,
            **super().get_form_kwargs(),
            **self.quest.get_form_kwargs(request=self.request),
        }

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            "title": self.quest.quest_type_label,
            "description": self.quest.quest_description,
        }

    def form_valid(self, form):
        form.save()
        if self.request.user_permissions.impolite_quests:
            return close_response(self.request)
        return super().form_valid(form)