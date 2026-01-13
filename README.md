# BladeMaster — онлайн-запись в премиум барбершоп (Алматы)

## Стек
Django 5.1.7 • Bootstrap 5 • flatpickr • reportlab • IMask

## Возможности
- Комбо-услуги
- Динамические свободные слоты с учётом длительности
- Авторизация по телефону
- ЛК клиента + мастера
- Отзывы, рейтинги, PDF счета/акты

## Быстрый старт
```bash
git clone https://github.com/ramzess667/blademaster.git
cd blademaster
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # и заполни SECRET_KEY, DEBUG и т.д.
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
