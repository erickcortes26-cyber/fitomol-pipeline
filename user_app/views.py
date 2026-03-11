from django.shortcuts import render, redirect
from .forms import RegisterForm
from .models import GalaxyProfile
from .utils import validar_api_key
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

def register_view(request):
    if request.user.is_authenticated:
        return redirect("index")
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            api_key = form.cleaned_data["galaxy_api_key"]
            if not validar_api_key(api_key):
                return render(request, "register.html", {
                    "form": form,
                    "error": "La API Key de Galaxy no es válida."
                })
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            profile = GalaxyProfile.objects.get(user=user)
            profile.galaxy_api_key = api_key
            profile.save()
            login(request, user)
            return redirect("index")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect("index")
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("index")
        return render(request, "login.html", {"error": "Credenciales inválidas"})
    return render(request, "login.html")

def logout_view(request):
    logout(request)
    return redirect("login")
