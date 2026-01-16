from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from .models import Client  # ← Добавь это!

class BookingAuthForm(forms.Form):
    phone = forms.CharField(label="Телефон", max_length=20)
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Повторить пароль", widget=forms.PasswordInput, required=False)

    def clean(self):
        cleaned_data = super().clean()
        phone = cleaned_data.get('phone')
        password = cleaned_data.get('password')
        password2 = cleaned_data.get('password2')

        if phone and password:
            try:
                client = Client.objects.get(phone=phone)
                user = authenticate(username=client.user.username, password=password)
                if not user:
                    raise forms.ValidationError("Неверный пароль")
            except Client.DoesNotExist:
                if password != password2:
                    raise forms.ValidationError("Пароли не совпадают")
        
        return cleaned_data
    
class ClientProfileForm(forms.Form):
    first_name = forms.CharField(label="Имя", max_length=150)
    email = forms.EmailField(label="Email", required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Красивые классы под твой дизайн
        self.fields["first_name"].widget.attrs.update({
            "class": "form-control bg-dark text-light border-gold",
            "placeholder": "Ваше имя"
        })
        self.fields["email"].widget.attrs.update({
            "class": "form-control bg-dark text-light border-gold",
            "placeholder": "example@mail.com"
        })

        # Подставляем текущие значения
        if user and not self.is_bound:
            self.initial["first_name"] = user.first_name
            self.initial["email"] = user.email

    def save(self):
        """Сохраняем изменения в User."""
        if not self.user:
            return

        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.email = (self.cleaned_data.get("email") or "").strip()
        self.user.save(update_fields=["first_name", "email"])
