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
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from django import template
import os



register = template.Library()

@register.filter
def multiply(value, arg):
    """
    Умножает значение на аргумент
    Использование: {{ total_price|multiply:0.3 }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''


def home(request):
    return render(request, "core/home.html")


# views.py
def services(request):
    master_id = request.GET.get('master')
    selected_master = None
    if master_id:
        try:
            selected_master = Master.objects.get(id=master_id)
            request.session['selected_master_id'] = master_id  # сохраняем
        except Master.DoesNotExist:
            pass

    context = {
        'services': Service.objects.all(),
        'selected_master': selected_master,
    }
    return render(request, 'core/services.html', context)

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
def book_confirm(request):
    if request.method != "POST":
        return redirect("home")

    # Получаем данные из формы
    service_id = request.POST.get("service_id")
    master_id = request.POST.get("master_id")
    date = request.POST.get("date")
    time = request.POST.get("time")
    client_name = request.POST.get("client_name")
    client_phone = request.POST.get("client_phone")
    client_email = request.POST.get("client_email", "")
    agree_offer = request.POST.get("agree_offer")  # чекбокс оферты
    prepayment = request.POST.get("prepayment") == "on"  # чекбокс предоплаты

    # Проверки
    if not all([service_id, master_id, date, time, client_name, client_phone]):
        messages.error(request, "Заполните все обязательные поля!")
        return redirect("book_datetime_multi")

    if not agree_offer:
        messages.error(request, "Необходимо согласиться с публичной офертой!")
        return redirect("book_datetime_multi")

    service = get_object_or_404(Service, id=service_id)
    master = get_object_or_404(Master, id=master_id)

    # Рассчитываем предоплату (30% от суммы всех услуг)
    total_price = sum(service.price for service in Service.objects.filter(id__in=request.POST.getlist("service_ids")))
    prepayment_amount = total_price * 0.3 if prepayment else 0

    # Создаём запись
    appointment = Appointment.objects.create(
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email,
        master=master,
        date=date,
        time=time,
        status="new",
        prepayment_amount=prepayment_amount,
        prepayment_paid=prepayment,  # пока просто True/False
        prepayment_method="Kaspi Pay (имитация)" if prepayment else "",
    )
    appointment.service.add(service)
    appointment.save()

    # Безопасно очищаем сессию (если ключ есть)
    if 'selected_master_id' in request.session:
        del request.session['selected_master_id']

    # Отправка email клиенту
    try:
        send_mail(
            "Ваша запись в BladeMaster подтверждена!",
            f"Здравствуйте, {client_name}!\n\n"
            f"Вы записаны на {service.name} к мастеру {master.full_name}\n"
            f"Дата: {date} {time}\n"
            f"Сумма: {total_price} ₸\n"
            f"Предоплата: {'Да, ' + str(prepayment_amount) + ' ₸' if prepayment else 'Нет'}\n\n"
            f"Ссылка для отмены: http://127.0.0.1:8000/appointment/{appointment.id}/cancel/\n\n"
            f"Спасибо, что выбрали нас!",
            "admin@blademaster.kz",
            [client_email] if client_email else [],
            fail_silently=False,
        )
    except Exception as e:
        print(f"Ошибка отправки email клиенту: {e}")

    # Уведомление мастеру (email)
    if master.email:
        try:
            send_mail(
                "Новая запись в BladeMaster",
                f"Клиент {client_name} ({client_phone}) записался на {date} {time}\n"
                f"Услуги: {service.name}\n"
                f"Сумма: {total_price} ₸\n"
                f"Предоплата: {'Да' if prepayment else 'Нет'}",
                "admin@blademaster.kz",
                [master.email],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Ошибка отправки email мастеру: {e}")

    # Уведомление в консоль
    print(f"НОВАЯ ЗАПИСЬ! ID: {appointment.id}")
    print(f"Клиент: {client_name}, {client_phone}, {client_email}")
    print(f"Услуга: {service.name}")
    print(f"Мастер: {master.full_name}")
    print(f"Дата и время: {date} {time}")
    print(f"Предоплата: {'Да, ' + str(prepayment_amount) + ' ₸' if prepayment else 'Нет'}")

    # Сообщение пользователю
    if prepayment:
        messages.success(request, f"Предоплата {prepayment_amount} ₸ успешно внесена (имитация). Запись подтверждена!")
    else:
        messages.success(request, "Ваша запись успешно создана! Мы ждём вас в BladeMaster 💈")

    return redirect("book_success", appointment.id)

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
    master_id = request.POST.get('master_id') or request.session.get('selected_master_id')
    if master_id:
        return redirect(reverse('book_datetime_multi') + '?master=' + str(master_id))
    
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
        master_id = request.GET.get('master') or request.session.get('selected_master_id')
        if master_id:
            master = get_object_or_404(Master, id=master_id)
    # используй master в контексте/логике ниже
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

    # Регистрируем шрифт Arial (твой путь)
    font_path = os.path.join(settings.BASE_DIR, "core", "static", "fonts", "Arial.ttf")
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('Arial', font_path))
        pdfmetrics.registerFont(TTFont('Arial-Bold', font_path))  # Для жирного, если нужно
    else:
        print("Шрифт Arial.ttf не найден — PDF будет без кастомного шрифта")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="schet_{appointment.id}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=2.5*cm,
        leftMargin=2.5*cm,
        topMargin=3*cm,
        bottomMargin=2.5*cm
    )

    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        fontName='Arial',
        fontSize=22,
        textColor=colors.black,
        spaceAfter=18,
        alignment=1,
        leading=26
    )
    header_style = ParagraphStyle(
        'Header',
        fontName='Arial',
        fontSize=14,
        textColor=colors.darkgoldenrod,
        spaceAfter=8,
        alignment=1
    )
    normal_style = ParagraphStyle(
        'Normal',
        fontName='Arial',
        fontSize=11,
        textColor=colors.black,
        leading=13,
        spaceAfter=6
    )
    fontName = 'Arial-Bold' if 'Arial-Bold' in pdfmetrics.getRegisteredFontNames() else 'Arial'
    bold_style = ParagraphStyle(
        'Bold',
        fontName=fontName,  # ← только один раз!
        fontSize=11,
        textColor=colors.black,
        leading=13,
        spaceAfter=6
        )

    # Логотип (добавь свой файл в core/static/images/logo.png)
    logo_path = os.path.join(settings.BASE_DIR, "core", "static", "images", "logo.png")
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=8*cm, height=3*cm)
        logo.hAlign = 'CENTER'
        elements.append(logo)
        elements.append(Spacer(1, 0.8*cm))

    # Заголовок
    elements.append(Paragraph("СЧЁТ НА ОПЛАТУ № " + str(appointment.id), title_style))
    elements.append(Spacer(1, 0.6*cm))

    # Информация
    info_data = [
        [Paragraph("<b>Дата выставления:</b>", bold_style), Paragraph(appointment.date.strftime('%d.%m.%Y'), normal_style)],
        [Paragraph("<b>Клиент:</b>", bold_style), Paragraph(appointment.client_name, normal_style)],
        [Paragraph("<b>Телефон:</b>", bold_style), Paragraph(appointment.client_phone, normal_style)],
    ]
    if appointment.client_email:
        info_data.append([Paragraph("<b>Email:</b>", bold_style), Paragraph(appointment.client_email, normal_style)])

    info_table = Table(info_data, colWidths=[6*cm, 11*cm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,-1), 'Arial'),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('LEFTPADDING', (0,0), (0,-1), 12),
        ('RIGHTPADDING', (1,0), (1,-1), 12),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 1.2*cm))

    # Услуги
    elements.append(Paragraph("Услуги:", header_style))
    elements.append(Spacer(1, 0.4*cm))

    service_data = [["№", "Наименование услуги", "Стоимость (₸)"]]
    total = 0
    for idx, service in enumerate(appointment.service.all(), 1):
        service_data.append([
            str(idx),
            service.name,
            f"{service.price:,.0f}"
        ])
        total += service.price

    service_data.append(["", Paragraph("<b>ИТОГО К ОПЛАТЕ:</b>", bold_style), f"<b>{total:,.0f} ₸</b>"])

    service_table = Table(service_data, colWidths=[1.5*cm, 11.5*cm, 5*cm])
    service_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkgoldenrod),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Arial'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-2), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,1), (0,-1), 'CENTER'),
        ('ALIGN', (2,1), (2,-1), 'RIGHT'),
        ('FONTNAME', (0,1), (-1,-1), 'Arial'),
        ('FONTSIZE', (0,1), (-1,-1), 11),
        ('TEXTCOLOR', (2,-1), (2,-1), colors.darkgreen),
        ('LINEBELOW', (0,-1), (-1,-1), 1.5, colors.darkgoldenrod),
    ]))
    elements.append(service_table)
    elements.append(Spacer(1, 1.8*cm))

    # Благодарность и подпись
    elements.append(Paragraph("Спасибо за выбор BladeMaster! Мы ценим ваше доверие и ждём вас снова. 💈", normal_style))
    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph("Подпись исполнителя: _______________________________", normal_style))

    doc.build(elements)
    return response

def generate_act_pdf(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    if appointment.status != "completed":
        messages.error(request, "Акт доступен только для выполненных услуг.")
        return redirect("book_success", appointment_id)

    # Регистрируем шрифт ТОЛЬКО здесь
    font_path = os.path.join(settings.BASE_DIR, "core", "static", "fonts", "arial.ttf")
    pdfmetrics.registerFont(TTFont('Arial', font_path))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="act_{appointment.id}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        fontName='Arial',
        fontSize=24,
        textColor=colors.black,
        spaceAfter=12,
        alignment=1
    )
    normal_style = ParagraphStyle(
        'Normal',
        fontName='Arial',
        fontSize=12,
        textColor=colors.black,
        leading=14,
        spaceAfter=8
    )
    header_style = ParagraphStyle(
        'Header',
        fontName='Arial',
        fontSize=14,
        textColor=colors.darkgoldenrod,
        spaceAfter=6,
        alignment=1
    )
    signature_style = ParagraphStyle(
        'Signature',
        fontName='Arial',
        fontSize=12,
        textColor=colors.black,
        alignment=0,
        spaceAfter=20
    )

    # Заголовок
    elements.append(Paragraph("АКТ ВЫПОЛНЕННЫХ РАБОТ", title_style))
    elements.append(Spacer(1, 0.8*cm))

    # Информация
    info_data = [
        [Paragraph(f"<b>Номер акта:</b> {appointment.id}", normal_style),
         Paragraph(f"<b>Дата выполнения:</b> {appointment.date.strftime('%d.%m.%Y')}", normal_style)],
        [Paragraph(f"<b>Клиент:</b> {appointment.client_name}", normal_style),
         Paragraph(f"<b>Мастер:</b> {appointment.master.full_name}", normal_style)],
    ]

    info_table = Table(info_data, colWidths=[9*cm, 9*cm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,-1), 'Arial'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 1*cm))

    # Услуги
    elements.append(Paragraph("Выполненные услуги:", header_style))
    elements.append(Spacer(1, 0.4*cm))

    service_data = [["№", "Услуга"]]
    for idx, service in enumerate(appointment.service.all(), 1):
        service_data.append([
            str(idx),
            service.name
        ])

    service_table = Table(service_data, colWidths=[1.5*cm, 15.5*cm])
    service_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkgoldenrod),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Arial'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('FONTNAME', (0,1), (-1,-1), 'Arial'),
        ('FONTSIZE', (0,1), (-1,-1), 11),
    ]))
    elements.append(service_table)
    elements.append(Spacer(1, 1*cm))

    # Сумма
    elements.append(Paragraph(f"<b>Сумма выполненных услуг:</b> {appointment.total_price()} ₸", normal_style))
    elements.append(Spacer(1, 1.5*cm))

    # Подписи
    elements.append(Paragraph("Подпись мастера: _______________________________", signature_style))
    elements.append(Paragraph("Подпись клиента: _______________________________", signature_style))

    # Нижний колонтитул
    elements.append(Spacer(1, 2*cm))
    elements.append(Paragraph("Услуги выполнены в полном объёме и без претензий.", normal_style))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("Спасибо, что выбрали BladeMaster! 💈", normal_style))

    doc.build(elements)
    return response

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
        username = request.POST.get("username")
        password = request.POST.get("password")
        role = request.POST.get("role")

        # Дебажный print — смотри в консоли, что приходит
        print(f"Попытка входа: role={role}, username='{username}'")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if hasattr(user, "master_profile"):
                messages.success(request, f"Добро пожаловать, мастер {user.master_profile.full_name}!")
                return redirect("master_dashboard")
            else:
                messages.success(request, "Добро пожаловать в личный кабинет!")
                return redirect("cabinet_dashboard")
        else:
            messages.error(request, "Неверный логин или пароль.")
            print("Authenticate failed")

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
    return redirect('cabinet_login')


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

    return redirect('cabinet_login')


def master_logout(request):
    auth_logout(request)
    return redirect('cabinet_login')


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
    show_completed = request.GET.get('show_completed') == '1'  # чекбокс включён?
    
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    
    appointments = Appointment.objects.filter(master=master)
    
    # Фильтр по дате
    if filter_type == 'today':
        appointments = appointments.filter(date=today)
    elif filter_type == 'tomorrow':
        appointments = appointments.filter(date=tomorrow)
    
    # По умолчанию скрываем завершённые/отменённые/не пришедшие
    if not show_completed:
        appointments = appointments.exclude(status__in=['completed', 'no_show', 'cancelled'])
    
    appointments = appointments.order_by('-date', 'time')
    
    # Статистика для сегодня (для примера, можно убрать если не нужно)
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
        'show_completed': show_completed,  # передаём в шаблон
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
