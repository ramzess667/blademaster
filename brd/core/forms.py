from django import forms
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from .models import Client

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
            # Проверяем, существует ли пользователь
            try:
                client = Client.objects.get(phone=phone)
                user = client.user
                if not user.check_password(password):
                    raise forms.ValidationError("Неверный пароль")
            except Client.DoesNotExist:
                # Новый клиент — проверяем совпадение паролей
                if password != password2:
                    raise forms.ValidationError("Пароли не совпадают")
        
        return cleaned_data