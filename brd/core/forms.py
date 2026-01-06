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