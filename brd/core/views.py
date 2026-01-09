from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.mail import send_mail
from .models import Service, Master, Appointment, Review, User, Client
from django.utils import timezone
from django.conf import settings
from datetime import datetime, timedelta, time as dtime
from django.http import JsonResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from .forms import BookingAuthForm
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import user_passes_test

import os


def home(request):
    return render(request, "core/home.html")


def services(request):
    services = Service.objects.all()
    return render(request, "core/services.html", {"services": services})


def masters(request):
    masters = Master.objects.all()
    return render(request, "core/masters.html", {"masters": masters})


# Шаг 1: Выбор мастера для выбранной услуги
def book_step1_master(request, service_id):
    service = get_object_or_404(Service, id=service_id)
    masters = Master.objects.all()
    return render(
        request,
        "core/book_step1_master.html",
        {
            "service": service,
            "masters": masters,
        },
    )


def book_step2_datetime(request, service_id, master_id):
    service = get_object_or_404(Service, id=service_id)
    master = get_object_or_404(Master, id=master_id)

    # Генерируем слоты времени: 10:00–22:00 каждые 30 мин
    times = []
    start_time = datetime.strptime("10:00", "%H:%M").time()
    end_time = datetime.strptime("22:00", "%H:%M").time()
    current = datetime.combine(datetime.today(), start_time)
    end = datetime.combine(datetime.today(), end_time)

    while current.time() <= end_time:
        times.append(current.time().strftime("%H:%M"))
        current += timedelta(minutes=30)

    # Даты: следующие 30 дней
    today = timezone.now().date()
    dates = [today + timedelta(days=i) for i in range(30)]

    # Получаем все занятые слоты для этого мастера
    booked_appointments = Appointment.objects.filter(master=master)
    booked_slots = {}
    for app in booked_appointments:
        date_str = app.date.strftime("%Y-%m-%d")
        time_str = app.time.strftime("%H:%M")
        if date_str not in booked_slots:
            booked_slots[date_str] = []
        booked_slots[date_str].append(time_str)

    return render(
        request,
        "core/book_step2_datetime.html",
        {
            "service": service,
            "master": master,
            "dates": dates,
            "times": times,
            "booked_slots": booked_slots,  # Передаём в шаблон
        },
    )


# Шаг 3: Форма подтверждения и сохранение записи
def book_confirm(request):
    if request.method == "POST":
        service_id = request.POST["service_id"]
        master_id = request.POST["master_id"]
        date = request.POST["date"]
        time = request.POST["time"]
        client_name = request.POST["client_name"]
        client_phone = request.POST["client_phone"]
        client_email = request.POST.get("client_email", "")

        service = get_object_or_404(Service, id=service_id)
        master = get_object_or_404(Master, id=master_id)

        # Создаём запись
        appointment = Appointment.objects.create(
            client_name=client_name,
            client_phone=client_phone,
            client_email=client_email,
            master=master,
            date=date,
            time=time,
            status="new",
        )
        appointment.service.add(service)
        appointment.save()

        try:
            send_mail(
                "Ваша запись в BladeMaster подтверждена!",
                f"Здравствуйте, {client_name}!\n\nВы записаны на {service.name} к мастеру {master.full_name}\nДата: {date} {time}\nСумма: {service.price} ₸\n\nСсылка для отмены: http://127.0.0.1:8000/appointment/{appointment.id}/cancel/\n\nСпасибо, что выбрали нас!",
                "admin@blademaster.kz",
                [client_email] if client_email else [],
                fail_silently=False,
            )
        except:
            pass  # В dev падает, если нет SMTP
        return redirect("book_success", appointment.id)
        # После appointment.save()
        return render(request, "core/book_success.html", {"appointment": appointment})

        # Уведомление в консоль (как email)
        print(f"НОВАЯ ЗАПИСЬ!")
        print(f"Клиент: {client_name}, {client_phone}, {client_email}")
        print(f"Услуга: {service.name}")
        print(f"Мастер: {master.full_name}")
        print(f"Дата и время: {date} {time}")

        messages.success(
            request, "Ваша запись успешно создана! Мы ждём вас в BladeMaster 💈"
        )
        return redirect("home")

    return redirect("home")


# Отмена записи по ID (с проверкой за 2 часа)
def cancel_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    # Проверка: можно отменить только если до записи больше 2 часов
    appointment_datetime = timezone.make_aware(
        datetime.combine(appointment.date, appointment.time)
    )
    if timezone.now() + timedelta(hours=2) >= appointment_datetime:
        messages.error(request, "Отмена возможна только за 2 часа до записи!")
        return redirect("home")

    appointment.status = "cancelled"
    appointment.save()

    # Уведомление в консоль (потом email)
    print(f"ЗАПИСЬ ОТМЕНЕНА: #{appointment.id} — {appointment.client_name}")

    messages.success(
        request,
        "Ваша запись успешно отменена. Жаль, что не увидимся — ждём вас в другой раз!",
    )
    return redirect("home")


# Страница успеха с кнопкой отмены
def book_success(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)
    return render(request, "core/book_success.html", {"appointment": appointment})


def book_select_master(request):
    if request.method == "POST":
        service_ids = request.POST.getlist("services")

        if not service_ids:
            messages.error(request, "Выберите хотя бы одну услугу!")
            return redirect("services")

        services = Service.objects.filter(id__in=service_ids)
        masters = Master.objects.all()
        total_price = sum(s.price for s in services)
        total_duration = sum(s.duration for s in services)

        return render(
            request,
            "core/book_step1_master_multi.html",
            {
                "services": services,
                "masters": masters,
                "total_price": total_price,
                "total_duration": total_duration,
            },
        )

    return redirect("services")


def book_datetime_multi(request):
    if request.method == "POST":
        # Первый POST: выбор мастера
        if "master" in request.POST:
            service_ids = request.POST.getlist("services")
            master_id = request.POST["master"]

            if not service_ids or not master_id:
                messages.error(request, "Ошибка выбора. Начните заново.")
                return redirect("services")

            services = Service.objects.filter(id__in=service_ids)
            master = get_object_or_404(Master, id=master_id)
            total_price = sum(s.price for s in services)
            total_duration = sum(s.duration for s in services)

            # Генерация слотов (твой код — оставляем)
            start_str = "10:00"
            end_str = "22:00"
            start_time = datetime.strptime(start_str, "%H:%M")
            end_time = datetime.strptime(end_str, "%H:%M")
            slot_step = 30

            all_slots = []
            current = start_time
            while current <= end_time:
                all_slots.append(current.strftime("%H:%M"))
                current = current + timedelta(minutes=slot_step)

            # Занятые слоты
            appointments = Appointment.objects.filter(
                master=master, status__in=["new", "confirmed"]
            )

            occupied_slots = set()
            for app in appointments:
                app_start = datetime.strptime(app.time.strftime("%H:%M"), "%H:%M")
                app_duration = sum(s.duration for s in app.service.all())
                app_end = app_start + timedelta(minutes=app_duration)

                slot_time = app_start
                while slot_time < app_end:
                    time_str = slot_time.strftime("%H:%M")
                    if time_str in all_slots:
                        occupied_slots.add(time_str)
                    slot_time += timedelta(minutes=slot_step)

            free_slots = [slot for slot in all_slots if slot not in occupied_slots]

            today = timezone.now().date()
            dates = [today + timedelta(days=i) for i in range(30)]

            return render(
                request,
                "core/book_datetime_multi.html",
                {
                    "services": services,
                    "master": master,
                    "total_price": total_price,
                    "total_duration": total_duration,
                    "dates": dates,
                    "free_slots": free_slots,
                },
            )

        # Второй POST: подтверждение + авторизация
        elif "date" in request.POST:
            date_str = request.POST["date"]
            time_str = request.POST["time"]
            client_name = request.POST["client_name"]
            phone = request.POST["phone"]
            client_email = request.POST.get("client_email", "")

            service_ids = request.POST.getlist("service_ids")
            master_id = request.POST["master_id"]

            services = Service.objects.filter(id__in=service_ids)
            master = get_object_or_404(Master, id=master_id)

            # Проверка на занятость
            if Appointment.objects.filter(
                master=master,
                date=date_str,
                time=time_str,
                status__in=["new", "confirmed"],
            ).exists():
                messages.error(request, "Это время уже занято!")
                return redirect("services")

            # Если залогинен — используем данные из профиля
            if request.user.is_authenticated:
                try:
                    client = request.user.client
                    phone = client.phone
                    client_name = request.user.first_name or client_name
                    client_email = request.user.email or client_email
                except Client.DoesNotExist:
                    messages.error(request, "Ошибка профиля. Выйдите и войдите заново.")
                    return redirect("services")
            else:
                # Для нового клиента — пароль из формы
                password = request.POST["password"]
                password2 = request.POST["password2"]
                if password != password2:
                    messages.error(request, "Пароли не совпадают.")
                    return redirect("services")

                # Создаём нового
                # Создаём нового
                user = User.objects.create_user(
                    username=phone,
                    password=password,
                    first_name=client_name,
                    email=client_email,
                )
                Client.objects.create(user=user, phone=phone)
                user = authenticate(request, username=phone, password=password)
                login(request, user)

            # Создаём запись
            appointment = Appointment.objects.create(
                client_name=client_name,
                client_phone=phone,
                client_email=client_email,
                master=master,
                date=date_str,
                time=time_str,
                status="new",
            )
            appointment.service.set(services)
            appointment.save()

            messages.success(request, "Запись успешно создана!")
            return redirect("book_success", appointment.id)

    return redirect("services")


def get_free_slots(request, master_id, date_str):
    master = get_object_or_404(Master, id=master_id)

    print(f"Запрос слотов для мастера {master_id}, дата: {date_str}")  # Дебаг в консоли

    # Парсим дату с обработкой ошибки
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        print("Ошибка парсинга даты:", e)
        return JsonResponse({"error": "Неверный формат даты"}, status=400)

    # Все возможные слоты (строки "10:00")
    all_slots = []
    start_time = datetime.strptime("10:00", "%H:%M")
    end_time = datetime.strptime("22:00", "%H:%M")
    current = start_time
    while current <= end_time:
        all_slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)

    # Записи на эту дату
    appointments = Appointment.objects.filter(
        master=master, date=selected_date, status__in=["new", "confirmed"]
    )

    occupied_slots = set()
    for app in appointments:
        print(
            f"Найдена запись: {app.time} , длительность услуг: {sum(s.duration for s in app.service.all())} мин"
        )
        app_start = app.time  # Это объект time
        app_duration = sum(s.duration for s in app.service.all())

        # Преобразуем time в datetime для расчёта
        app_start_dt = datetime.combine(selected_date, app_start)
        app_end_dt = app_start_dt + timedelta(minutes=app_duration)

        slot_dt = app_start_dt
        while slot_dt < app_end_dt:
            slot_time_str = slot_dt.strftime("%H:%M")
            if slot_time_str in all_slots:
                occupied_slots.add(slot_time_str)
            slot_dt += timedelta(minutes=30)

    free_slots = [slot for slot in all_slots if slot not in occupied_slots]

    print("Свободные слоты:", free_slots)

    return JsonResponse({"free_slots": free_slots})


def generate_invoice_pdf(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="schet_{appointment.id}.pdf"'
    )

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    # Используем Arial
    p.setFont("Arial", 18)
    p.drawCentredString(width / 2, height - 3 * cm, "СЧЁТ НА ОПЛАТУ")

    p.setFont("Arial", 12)
    p.drawString(3 * cm, height - 5 * cm, f"Номер счёта: {appointment.id}")
    p.drawString(
        3 * cm, height - 6 * cm, f"Дата: {appointment.date.strftime('%d.%m.%Y')}"
    )
    p.drawString(3 * cm, height - 7 * cm, f"Клиент: {appointment.client_name}")
    p.drawString(3 * cm, height - 8 * cm, f"Телефон: {appointment.client_phone}")
    if appointment.client_email:
        p.drawString(3 * cm, height - 9 * cm, f"Email: {appointment.client_email}")

    p.drawString(3 * cm, height - 11 * cm, f"Мастер: {appointment.master.full_name}")
    p.drawString(
        3 * cm,
        height - 12 * cm,
        f"Дата и время услуги: {appointment.date.strftime('%d.%m.%Y')} {appointment.time.strftime('%H:%M')}",
    )

    p.drawString(3 * cm, height - 14 * cm, "Услуги:")
    y = height - 15 * cm
    for service in appointment.service.all():
        p.drawString(4 * cm, y, f"• {service.name} — {service.price} ₸")
        y -= 0.8 * cm

    p.setFont("Arial", 14)
    p.drawString(3 * cm, y - 1 * cm, f"ИТОГО К ОПЛАТЕ: {appointment.total_price()} ₸")

    p.setFont("Arial", 10)
    p.drawString(3 * cm, 3 * cm, "Спасибо, что выбрали BladeMaster! 💈")

    p.showPage()
    p.save()

    return response


def generate_act_pdf(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    if appointment.status != "completed":
        messages.error(request, "Акт доступен только для выполненных услуг.")
        return redirect("book_success", appointment_id)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="act_{appointment.id}.pdf"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    p.setFont("Arial", 18)
    p.drawCentredString(width / 2, height - 3 * cm, "АКТ ВЫПОЛНЕННЫХ РАБОТ")

    p.setFont("Arial", 12)
    p.drawString(3 * cm, height - 5 * cm, f"Номер акта: {appointment.id}")
    p.drawString(
        3 * cm,
        height - 6 * cm,
        f"Дата выполнения: {appointment.date.strftime('%d.%m.%Y')}",
    )
    p.drawString(3 * cm, height - 7 * cm, f"Клиент: {appointment.client_name}")
    p.drawString(3 * cm, height - 8 * cm, f"Мастер: {appointment.master.full_name}")

    y = height - 10 * cm
    p.drawString(3 * cm, y, "Выполненные услуги:")
    y -= 1 * cm
    for service in appointment.service.all():
        p.drawString(4 * cm, y, f"• {service.name}")
        y -= 0.8 * cm

    p.setFont("Arial", 14)
    p.drawString(3 * cm, y - 1 * cm, f"Сумма: {appointment.total_price()} ₸")

    p.setFont("Arial", 10)
    p.drawString(3 * cm, 4 * cm, "Услуги выполнены в полном объёме.")
    p.drawString(3 * cm, 3 * cm, "Подпись мастера: _____________________")
    p.drawString(3 * cm, 2 * cm, "Подпись клиента: _____________________")

    p.showPage()
    p.save()

    return response


# Регистрация шрифта Arial с поддержкой русского
pdfmetrics.registerFont(
    TTFont("Arial", os.path.join(settings.BASE_DIR, "static", "fonts", "Arial.ttf"))
)


@login_required  # Опционально, но пока без авторизации — любой может
def add_review(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    # Проверка, есть ли уже отзыв
    if hasattr(appointment, "review"):
        messages.info(request, "Вы уже оставили отзыв.")
        return redirect("book_success", appointment_id)

    if request.method == "POST":
        rating = request.POST.get("rating")
        comment = request.POST.get("comment", "")

        if rating:
            Review.objects.create(
                appointment=appointment, rating=int(rating), comment=comment
            )
            messages.success(
                request, "Спасибо за отзыв! Он появится на странице мастера."
            )
        else:
            messages.error(
                request, "Пожалуйста, выберите оценку (кликните на звёздочки)."
            )

        return redirect("book_success", appointment_id)

    return redirect("book_success", appointment_id)


def cabinet_login(request):
    if request.method == "POST":
        username = request.POST.get("username")  # Может быть телефон или логин мастера
        password = request.POST.get("password")

        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)

                # Определяем, кто зашёл
                if hasattr(user, "master_profile"):
                    messages.success(
                        request,
                        f"Добро пожаловать, мастер {user.master_profile.full_name}!",
                    )
                    return redirect("master_dashboard")
                else:
                    messages.success(request, "Добро пожаловать в личный кабинет!")
                    return redirect("cabinet_dashboard")
            else:
                messages.error(request, "Неверный логин или пароль.")
        else:
            messages.error(request, "Заполните все поля.")

    return render(request, "core/cabinet_login.html")


def cabinet_dashboard(request):
    if not request.user.is_authenticated:
        return redirect("cabinet_login")

    try:
        client = request.user.client
    except:
        messages.error(request, "Ошибка профиля.")
        return redirect("cabinet_login")

    appointments = Appointment.objects.filter(client_phone=client.phone).order_by(
        "-date", "-time"
    )

    # Добавляем флаг can_cancel для каждой записи
    now = timezone.now()
    for app in appointments:
        if app.status in ["new", "confirmed"]:
            app_datetime = timezone.make_aware(datetime.combine(app.date, app.time))
            if now + timedelta(hours=2) < app_datetime:
                app.can_cancel = True
            else:
                app.can_cancel = False
        else:
            app.can_cancel = False

    return render(
        request,
        "core/cabinet_dashboard.html",
        {
            "appointments": appointments,
        },
    )


def cabinet_cancel_appointment(request, appointment_id):
    if not request.user.is_authenticated:
        return redirect("cabinet_login")

    try:
        client = request.user.client
    except:
        messages.error(request, "Ошибка профиля.")
        return redirect("cabinet_login")

    appointment = get_object_or_404(
        Appointment, id=appointment_id, client_phone=client.phone
    )

    if appointment.status not in ["new", "confirmed"]:
        messages.error(request, "Эту запись нельзя отменить.")
        return redirect("cabinet_dashboard")

    appointment_datetime = timezone.make_aware(
        datetime.combine(appointment.date, appointment.time)
    )
    if timezone.now() + timedelta(hours=2) >= appointment_datetime:
        messages.error(request, "Отмена возможна только за 2 часа до записи.")
        return redirect("cabinet_dashboard")

    appointment.status = "cancelled"
    appointment.save()

    messages.success(request, "Запись успешно отменена.")
    return redirect("cabinet_dashboard")


def cabinet_logout(request):
    logout(request)
    messages.info(request, "Вы вышли из личного кабинета.")
    return redirect("home")


def is_master(user):
    return hasattr(user, "master_profile")


@user_passes_test(is_master, login_url="master_login")
def master_dashboard(request):
    master = request.user.master_profile
    appointments = Appointment.objects.filter(master=master).order_by("-date", "-time")

    return render(
        request,
        "core/master_dashboard.html",
        {
            "master": master,
            "appointments": appointments,
        },
    )


def master_login(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)
        if user is not None and is_master(user):
            auth_login(request, user)
            return redirect("master_dashboard")
        else:
            messages.error(request, "Неверный логин или пароль, или вы не мастер.")

    return render(request, "core/master_login.html")


def master_logout(request):
    auth_logout(request)
    return redirect("master_login")


@user_passes_test(is_master, login_url="master_login")
def master_change_status(request, appointment_id, new_status):
    appointment = get_object_or_404(
        Appointment, id=appointment_id, master=request.user.master_profile
    )

    if new_status in ["confirmed", "completed", "no_show"]:
        appointment.status = new_status
        appointment.save()
        messages.success(
            request, f'Статус изменён на "{appointment.get_status_display()}"'
        )
    else:
        messages.error(request, "Недопустимый статус.")

    return redirect("master_dashboard") @ login_required


@login_required
def master_dashboard(request):
    if not hasattr(request.user, 'master_profile') or not request.user.master_profile:
        messages.error(request, 'Доступ запрещён.')
        return redirect('cabinet_logout')
    
    master = request.user.master_profile
    
    filter_type = request.GET.get('filter', 'all')
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    
    if filter_type == 'today':
        appointments = Appointment.objects.filter(master=master, date=today).order_by('time')
    elif filter_type == 'tomorrow':
        appointments = Appointment.objects.filter(master=master, date=tomorrow).order_by('time')
    else:
        appointments = Appointment.objects.filter(master=master).order_by('-date', 'time')
    
    # Статистика для сегодня
    appointments_today = Appointment.objects.filter(master=master, date=today)
    total_today = sum(app.total_price() for app in appointments_today)
    appointments_new = appointments_today.filter(status='new')
    
    context = {
        'master': master,
        'appointments': appointments,
        'appointments_today': appointments_today,
        'total_today': total_today,
        'appointments_new': appointments_new,
        'today': today,
        'tomorrow': tomorrow,
    }
    
    return render(request, 'core/master_dashboard.html', context)


@login_required
def master_change_status(request, appointment_id, new_status):
    if not hasattr(request.user, "master_profile") or not request.user.master_profile:
        messages.error(request, "Доступ запрещён.")
        return redirect("cabinet_logout")

    appointment = get_object_or_404(
        Appointment, id=appointment_id, master=request.user.master_profile
    )

    if new_status in ["confirmed", "completed", "no_show"]:
        old_status = appointment.get_status_display()
        appointment.status = new_status
        appointment.save()
        messages.success(
            request,
            f"Статус записи изменён: {old_status} → {appointment.get_status_display()}",
        )
    else:
        messages.error(request, "Недопустимый статус.")

    return redirect("master_dashboard")
