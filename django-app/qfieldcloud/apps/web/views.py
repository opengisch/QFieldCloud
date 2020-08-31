from django.http import HttpResponse
from django.views.generic import TemplateView
from django.contrib.auth import login, authenticate
from django.shortcuts import render, redirect

from .forms import SignUpForm


class IndexView(TemplateView):
    template_name = "index.html"


def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)
            login(request, user)
            return redirect('registered')
    else:
        form = SignUpForm()
    return render(request, 'signup.html', {'form': form})


def registered(request):
    return HttpResponse("Well done, you are registered")
