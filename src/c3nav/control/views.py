from django.shortcuts import render


def index(request):
    return render(request, 'control/base.html')

# Create your views here.
