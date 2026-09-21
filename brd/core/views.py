from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.mail import send_mail
from .models import Service, Master, Appointment, Review, User, Client, BlockedSlot
from django.utils import timezone
from django.conf import settings
from datetime import datetime, timedelta, time as dtime
from django.http import JsonResponse
from decimal import Decimal
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from .forms import BookingAuthForm, ClientProfileForm
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import user_passes_test
from reportlab.lib import colors
from django.db.models import Q
import requests
from django.urls import reverse

from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from django import template
from .models import WorkingHours
from reportlab.lib.units import mm
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from django.db.models import Count, Sum, F, IntegerField, ExpressionWrapper
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)



import os


def send_telegram(text: str):
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass



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
        return ""


def home(request):
    masters = Master.objects.all()  # или .filter(...), или [:4] для первых 4
    context = {
        "masters": masters,  # ← имя переменной должно быть 'masters' (с маленькой буквы!)
        # ... другие переменные ...
    }
    return render(request, "core/home.html", context)


# views.py
def services(request):
    master_id = request.GET.get("master")
    selected_master = None
    if master_id:
        try:
            selected_master = Master.objects.get(id=master_id)
            request.session["selected_master_id"] = master_id
        except Master.DoesNotExist:
            pass

    q = (request.GET.get("q") or "").strip()

    services_qs = Service.objects.all()
    if q:
        words = q.split()

        for word in words:
            services_qs = services_qs.filter(
                Q(name__icontains=word) |
                Q(description__icontains=word) |
                Q(category__icontains=word)
            )
    context = {
        "services": services_qs,
        "selected_master": selected_master,
        "q": q,  # чтобы сохранить текст в поле поиска
    }
    return render(request, "core/services.html", context)


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

def book_confirm(request):
    if request.method != "POST":
        return redirect("home")

    # Данные из формы (multi)
    master_id = request.POST.get("master_id")
    date_str = request.POST.get("date")
    time_str = request.POST.get("time")

    client_name = (request.POST.get("client_name") or "").strip()
    client_phone = (request.POST.get("client_phone") or "").strip()
    client_email = (request.POST.get("client_email") or "").strip()

    service_ids = request.POST.getlist("service_ids")

    agree_offer = request.POST.get("agree_offer")
    prepayment_checked = request.POST.get("prepayment") == "on"

    # Проверки обязательных
    if not all([master_id, date_str, time_str, client_name, client_phone]) or not service_ids:
        messages.error(request, "Заполните все обязательные поля и выберите услуги!")
        return redirect("services")

    if not agree_offer:
        messages.error(request, "Необходимо согласиться с публичной офертой!")
        return redirect("services")

    master = get_object_or_404(Master, id=master_id)
    services = Service.objects.filter(id__in=service_ids)

    if not services.exists():
        messages.error(request, "Не удалось получить выбранные услуги. Начните заново.")
        return redirect("services")

    # Защита от занятости (только new/confirmed блокируют слот)
    if Appointment.objects.filter(
        master=master,
        date=date_str,
        time=time_str,
        status__in=["new", "confirmed"],
    ).exists():
        messages.error(request, "Это время уже занято! Выберите другое.")
        return redirect("services")

    # Суммы
    total_price = sum(Decimal(str(s.price)) for s in services)
    prepayment_amount = (total_price * Decimal("0.30")).quantize(Decimal("0.01")) if prepayment_checked else Decimal("0.00")

    # ---- СПОСОБ ОПЛАТЫ (заглушка) ----
    payment_method = request.POST.get("payment_method", "cash")

    payment_map = {
        "cash": "Наличными",
        "card": "Картой",
        "kaspi_qr": "Kaspi QR",
    }

    method_text = "Kaspi Pay (имитация)" if prepayment_checked else payment_map.get(payment_method, "Наличными")

    # Создаём запись
    appointment = Appointment.objects.create(
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email or None,
        master=master,
        date=date_str,
        time=time_str,
        status="new",
        prepayment_amount=prepayment_amount,
        prepayment_paid=prepayment_checked,  # имитация: если чекбокс — значит "оплачено"
        prepayment_method=method_text,
    )
    appointment.service.set(services)
    appointment.save()

  # время как строка (без падений)
    time_text = appointment.time.strftime("%H:%M") if hasattr(appointment.time, "strftime") else str(appointment.time)

    # список услуг
    services_list = []
    total_price = 0
    total_duration = 0

    for s in appointment.service.all():
        services_list.append(f"• {s.name} — {s.price} ₸ ({s.duration} мин)")
        total_price += int(s.price)
        total_duration += int(s.duration)

    services_text = "\n".join(services_list) if services_list else "—"

    send_telegram(
    "📌 <b>Новая запись</b>\n"
    f"✂️ Мастер: <b>{appointment.master.full_name}</b>\n"
    f"📅 Дата: <b>{appointment.date}</b>\n"
    f"🕒 Время: <b>{time_text}</b>\n"
    f"👤 Клиент: <b>{appointment.client_name}</b>\n"
    f"📞 Тел: <b>{appointment.client_phone}</b>\n"
    "\n"
    "🧾 <b>Услуги:</b>\n"
    f"{services_text}\n"
    "\n"
    f"⏱ <b>Длительность:</b> {total_duration} мин\n"
    f"💰 <b>Итого:</b> {total_price} ₸"
)

    # очищаем выбранного мастера в сессии (если был)
    if "selected_master_id" in request.session:
        del request.session["selected_master_id"]

    # Email клиенту
    if client_email:
        try:
            send_mail(
                "Ваша запись в BladeMaster подтверждена!",
                (
                    f"Здравствуйте, {client_name}!\n\n"
                    f"Мастер: {master.full_name}\n"
                    f"Дата и время: {date_str} {time_str}\n"
                    f"Услуги: {', '.join([s.name for s in services])}\n"
                    f"Сумма: {total_price} ₸\n"
                    f"Предоплата: {prepayment_amount} ₸\n"
                    f"Способ оплаты: {method_text}\n\n"
                    f"Спасибо, что выбрали нас!"
                ),
                "admin@blademaster.kz",
                [client_email],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Ошибка отправки email клиенту: {e}")

    # Email мастеру — у тебя уже есть правильная логика через master.user.email в другом куске
    master_email = ""
    if getattr(master, "user", None) and master.user.email:
        master_email = master.user.email.strip()

    if master_email:
        try:
            send_mail(
                "Новая запись в BladeMaster",
                (
                    f"Клиент: {client_name}\n"
                    f"Телефон: {client_phone}\n"
                    f"Дата и время: {date_str} {time_str}\n"
                    f"Услуги: {', '.join([s.name for s in services])}\n"
                    f"Сумма: {total_price} ₸\n"
                    f"Предоплата: {'Да' if prepayment_checked else 'Нет'}\n"
                    f"Способ оплаты: {method_text}"
                ),
                "admin@blademaster.kz",
                [master_email],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Ошибка отправки email мастеру: {e}")

    # Сообщение пользователю
    if prepayment_checked:
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

    # время как строка (без падений)
    time_text = appointment.time.strftime("%H:%M") if hasattr(appointment.time, "strftime") else str(appointment.time)

    services_list = []
    total_price = 0
    total_duration = 0

    for s in appointment.service.all():
        services_list.append(f"• {s.name} — {s.price} ₸ ({s.duration} мин)")
        total_price += int(s.price)
        total_duration += int(s.duration)

    services_text = "\n".join(services_list) if services_list else "—"

    who = request.user.first_name or request.user.username if request.user.is_authenticated else "гость"


    send_telegram(
        "❌ <b>Отмена записи</b>\n"
        f"👤 Кто отменил: <b>{who}</b>\n"
        f"✂️ Мастер: <b>{appointment.master.full_name}</b>\n"
        f"📅 Дата: <b>{appointment.date}</b>\n"
        f"🕒 Время: <b>{time_text}</b>\n"
        f"👤 Клиент: <b>{appointment.client_name}</b>\n"
        f"📞 Тел: <b>{appointment.client_phone}</b>\n"
        "\n"
        "🧾 <b>Услуги:</b>\n"
        f"{services_text}\n"
        "\n"
        f"⏱ <b>Длительность:</b> {total_duration} мин\n"
        f"💰 <b>Сумма:</b> {total_price} ₸"
    )



    # Уведомление в консоль (потом email)
    print(f"ЗАПИСЬ ОТМЕНЕНА: #{appointment.id} — {appointment.client_name}")

    messages.success(
        request,
        "Ваша запись успешно отменена. Жаль, что не увидимся — ждём вас в другой раз!",
    )
    return redirect("home")


def book_success(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    total_price = appointment.total_price()
    prepay = appointment.prepayment_amount or Decimal("0.00")
    remaining = (Decimal(str(total_price)) - Decimal(str(prepay)))

    if remaining < 0:
        remaining = Decimal("0.00")

    return render(
        request,
        "core/book_success.html",
        {
            "appointment": appointment,
            "remaining_amount": remaining,
        }
    )

def book_select_master(request):
    # 1) Если мастер уже выбран (на странице мастеров нажали "Далее")
    if request.method == "POST" and request.POST.get("master_id"):
        master_id = request.POST.get("master_id")

        # сохраняем выбранного мастера
        request.session["selected_master_id"] = int(master_id)

        # важно: услуги должны уже лежать в session
        if not request.session.get("selected_service_ids"):
            messages.error(request, "Сначала выберите услуги.")
            return redirect("services")

        return redirect(f"/book/datetime/?master={master_id}")

    # 2) Первый шаг: пришли услуги с /services/ → показываем выбор мастера
    if request.method == "POST":
        service_ids = request.POST.getlist("services")

        if not service_ids:
            messages.error(request, "Выберите хотя бы одну услугу!")
            return redirect("services")

        # сохраняем услуги в session, чтобы не терялись после редиректов
        request.session["selected_service_ids"] = [int(x) for x in service_ids]

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
    """
    Шаг 2: показать страницу выбора даты/времени после выбора мастера и услуг.
    Здесь НЕ создаём Appointment — это делает book_confirm.
    """

    if request.method != "POST":
        return redirect("services")

    # Первый POST: выбор мастера + услуг (приходит из step1)
    if "master" not in request.POST:
        messages.error(request, "Ошибка: мастер не выбран. Начните заново.")
        return redirect("services")

    service_ids = request.POST.getlist("services")
    master_id = request.POST.get("master")

    if not service_ids or not master_id:
        messages.error(request, "Ошибка выбора. Начните заново.")
        return redirect("services")

    services = Service.objects.filter(id__in=service_ids)
    if not services.exists():
        messages.error(request, "Услуги не найдены. Начните заново.")
        return redirect("services")

    master = get_object_or_404(Master, id=master_id)

    total_price = sum(s.price for s in services)
    total_duration = sum(s.duration for s in services)

    # Генерация слотов (как у тебя)
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

    # Занятые слоты (new/confirmed занимают)
    appointments = Appointment.objects.filter(
        master=master, status__in=["new", "confirmed"]
    ).prefetch_related("service")

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

    today = timezone.localdate()
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
    # Берём рабочие часы из админки
    working_hours = WorkingHours.objects.first()

    if working_hours:
        start_time = datetime.combine(selected_date, working_hours.start_time)
        end_time = datetime.combine(selected_date, working_hours.end_time)
    else:
        # fallback, если админ не задал часы
        start_time = datetime.combine(
            selected_date, datetime.strptime("10:00", "%H:%M").time()
        )
        end_time = datetime.combine(
            selected_date, datetime.strptime("22:00", "%H:%M").time()
        )

    current = start_time
    while current < end_time:
        all_slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)

    # Записи на эту дату
    appointments = Appointment.objects.filter(
        master=master, date=selected_date, status__in=["new", "confirmed"]
    )
        # --- Блокировки времени (BlockedSlot) ---
    # 1) блокировки конкретного мастера
    # 2) общие блокировки (master=None) — для всех мастеров
    blocks = BlockedSlot.objects.filter(
        date=selected_date
    ).filter(
        Q(master=master) | Q(master__isnull=True)
    )

    # Если есть блокировка "весь день" — сразу пусто
    if blocks.filter(time_from__isnull=True, time_to__isnull=True).exists():
        return JsonResponse({"free_slots": []})

    blocked_slots = set()

    for b in blocks:
        # пропускаем "кривые" записи: указано только одно время
        if (b.time_from and not b.time_to) or (b.time_to and not b.time_from):
            continue

        if b.time_from and b.time_to:
            b_start = datetime.combine(selected_date, b.time_from)
            b_end = datetime.combine(selected_date, b.time_to)

            # если админ случайно поставил наоборот — поменяем местами
            if b_start > b_end:
                b_start, b_end = b_end, b_start

            slot_dt = b_start
            while slot_dt < b_end:
                t_str = slot_dt.strftime("%H:%M")
                if t_str in all_slots:
                    blocked_slots.add(t_str)
                slot_dt += timedelta(minutes=30)


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

    free_slots = [slot for slot in all_slots if slot not in occupied_slots and slot not in blocked_slots]


    print("Свободные слоты:", free_slots)

    return JsonResponse({"free_slots": free_slots})


def generate_invoice_pdf(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    # Регистрируем шрифт Arial (твой путь)
    font_path = os.path.join(settings.BASE_DIR, "core", "static", "fonts", "Arial.ttf")
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont("Arial", font_path))
        pdfmetrics.registerFont(
            TTFont("Arial-Bold", font_path)
        )  # Для жирного, если нужно
    else:
        print("Шрифт Arial.ttf не найден — PDF будет без кастомного шрифта")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="schet_{appointment.id}.pdf"'
    )

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=2.5 * cm,
        leftMargin=2.5 * cm,
        topMargin=3 * cm,
        bottomMargin=2.5 * cm,
    )

    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        fontName="Arial",
        fontSize=22,
        textColor=colors.black,
        spaceAfter=18,
        alignment=1,
        leading=26,
    )
    header_style = ParagraphStyle(
        "Header",
        fontName="Arial",
        fontSize=14,
        textColor=colors.darkgoldenrod,
        spaceAfter=8,
        alignment=1,
    )
    normal_style = ParagraphStyle(
        "Normal",
        fontName="Arial",
        fontSize=11,
        textColor=colors.black,
        leading=13,
        spaceAfter=6,
    )
    fontName = (
        "Arial-Bold" if "Arial-Bold" in pdfmetrics.getRegisteredFontNames() else "Arial"
    )
    bold_style = ParagraphStyle(
        "Bold",
        fontName=fontName,  # ← только один раз!
        fontSize=11,
        textColor=colors.black,
        leading=13,
        spaceAfter=6,
    )

    # Логотип (добавь свой файл в core/static/images/logo.png)
    logo_path = os.path.join(settings.BASE_DIR, "core", "static", "images", "logo.png")
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=8 * cm, height=3 * cm)
        logo.hAlign = "CENTER"
        elements.append(logo)
        elements.append(Spacer(1, 0.8 * cm))

    # Заголовок
    elements.append(Paragraph("СЧЁТ НА ОПЛАТУ № " + str(appointment.id), title_style))
    elements.append(Spacer(1, 0.6 * cm))

    # Информация
    info_data = [
        [
            Paragraph("<b>Дата выставления:</b>", bold_style),
            Paragraph(appointment.date.strftime("%d.%m.%Y"), normal_style),
        ],
        [
            Paragraph("<b>Клиент:</b>", bold_style),
            Paragraph(appointment.client_name, normal_style),
        ],
        [
            Paragraph("<b>Телефон:</b>", bold_style),
            Paragraph(appointment.client_phone, normal_style),
        ],
    ]
    if appointment.client_email:
        info_data.append(
            [
                Paragraph("<b>Email:</b>", bold_style),
                Paragraph(appointment.client_email, normal_style),
            ]
        )

    info_table = Table(info_data, colWidths=[6 * cm, 11 * cm])
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, -1), "Arial"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("LEFTPADDING", (0, 0), (0, -1), 12),
                ("RIGHTPADDING", (1, 0), (1, -1), 12),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 1.2 * cm))

    # Услуги
    elements.append(Paragraph("Услуги:", header_style))
    elements.append(Spacer(1, 0.4 * cm))

    service_data = [["№", "Наименование услуги", "Стоимость (₸)"]]
    total = 0
    for idx, service in enumerate(appointment.service.all(), 1):
        service_data.append([str(idx), service.name, f"{service.price:,.0f}"])
        total += service.price

    service_data.append(
        ["", Paragraph("<b>ИТОГО К ОПЛАТЕ:</b>", bold_style), f"<b>{total:,.0f} ₸</b>"]
    )

    service_table = Table(service_data, colWidths=[1.5 * cm, 11.5 * cm, 5 * cm])
    service_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkgoldenrod),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Arial"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -2), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("FONTNAME", (0, 1), (-1, -1), "Arial"),
                ("FONTSIZE", (0, 1), (-1, -1), 11),
                ("TEXTCOLOR", (2, -1), (2, -1), colors.darkgreen),
                ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.darkgoldenrod),
            ]
        )
    )
    elements.append(service_table)
    elements.append(Spacer(1, 1.8 * cm))

    # Благодарность и подпись
    elements.append(
        Paragraph(
            "Спасибо за выбор BladeMaster! Мы ценим ваше доверие и ждём вас снова. 💈",
            normal_style,
        )
    )
    elements.append(Spacer(1, 1 * cm))
    elements.append(
        Paragraph("Подпись исполнителя: _______________________________", normal_style)
    )

    doc.build(elements)
    return response


def generate_act_pdf(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    if appointment.status != "completed":
        messages.error(request, "Акт доступен только для выполненных услуг.")
        return redirect("book_success", appointment_id)

    # Регистрируем шрифт ТОЛЬКО здесь
    font_path = os.path.join(settings.BASE_DIR, "core", "static", "fonts", "Arial.ttf")
    pdfmetrics.registerFont(TTFont("Arial", font_path))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="act_{appointment.id}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        fontName="Arial",
        fontSize=24,
        textColor=colors.black,
        spaceAfter=12,
        alignment=1,
    )
    normal_style = ParagraphStyle(
        "Normal",
        fontName="Arial",
        fontSize=12,
        textColor=colors.black,
        leading=14,
        spaceAfter=8,
    )
    header_style = ParagraphStyle(
        "Header",
        fontName="Arial",
        fontSize=14,
        textColor=colors.darkgoldenrod,
        spaceAfter=6,
        alignment=1,
    )
    signature_style = ParagraphStyle(
        "Signature",
        fontName="Arial",
        fontSize=12,
        textColor=colors.black,
        alignment=0,
        spaceAfter=20,
    )

    # Заголовок
    elements.append(Paragraph("АКТ ВЫПОЛНЕННЫХ РАБОТ", title_style))
    elements.append(Spacer(1, 0.8 * cm))

    # Информация
    info_data = [
        [
            Paragraph(f"<b>Номер акта:</b> {appointment.id}", normal_style),
            Paragraph(
                f"<b>Дата выполнения:</b> {appointment.date.strftime('%d.%m.%Y')}",
                normal_style,
            ),
        ],
        [
            Paragraph(f"<b>Клиент:</b> {appointment.client_name}", normal_style),
            Paragraph(f"<b>Мастер:</b> {appointment.master.full_name}", normal_style),
        ],
    ]

    info_table = Table(info_data, colWidths=[9 * cm, 9 * cm])
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, -1), "Arial"),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 1 * cm))

    # Услуги
    elements.append(Paragraph("Выполненные услуги:", header_style))
    elements.append(Spacer(1, 0.4 * cm))

    service_data = [["№", "Услуга"]]
    for idx, service in enumerate(appointment.service.all(), 1):
        service_data.append([str(idx), service.name])

    service_table = Table(service_data, colWidths=[1.5 * cm, 15.5 * cm])
    service_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkgoldenrod),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Arial"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("FONTNAME", (0, 1), (-1, -1), "Arial"),
                ("FONTSIZE", (0, 1), (-1, -1), 11),
            ]
        )
    )
    elements.append(service_table)
    elements.append(Spacer(1, 1 * cm))

    # Сумма
    elements.append(
        Paragraph(
            f"<b>Сумма выполненных услуг:</b> {appointment.total_price()} ₸",
            normal_style,
        )
    )
    elements.append(Spacer(1, 1.5 * cm))

    # Подписи
    elements.append(
        Paragraph("Подпись мастера: _______________________________", signature_style)
    )
    elements.append(
        Paragraph("Подпись клиента: _______________________________", signature_style)
    )

    # Нижний колонтитул
    elements.append(Spacer(1, 2 * cm))
    elements.append(
        Paragraph("Услуги выполнены в полном объёме и без претензий.", normal_style)
    )
    elements.append(Spacer(1, 0.5 * cm))
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
            print("Authenticate failed")

    return render(request, "core/cabinet_login.html")


def cabinet_dashboard(request):
    if not request.user.is_authenticated:
        return redirect("cabinet_login")

    try:
        client = request.user.client
    except Exception:
        messages.error(request, "Ошибка профиля.")
        return redirect("cabinet_login")

    tab = request.GET.get("tab", "upcoming")
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)

    qs = Appointment.objects.filter(client_phone=client.phone)

    # --- ФИЛЬТРЫ ---
    if tab == "upcoming":
        # Предстоящие: сегодня и дальше, кроме отменённых
        qs = qs.filter(date__gte=today).exclude(status="cancelled")
        qs = qs.order_by("date", "time")
    elif tab == "past":
        # Прошедшие: до сегодня (можно оставить completed/no_show и т.д.)
        qs = qs.filter(date__lt=today).exclude(status="cancelled")
        qs = qs.order_by("-date", "-time")
    elif tab == "cancelled":
        qs = qs.filter(status="cancelled").order_by("-date", "-time")
    else:
        # all
        qs = qs.order_by("-date", "-time")

    appointments = list(qs)  # чтобы можно было навесить can_cancel

    # --- can_cancel ---
    now = timezone.now()
    for app in appointments:
        app.can_cancel = False

        if app.status in ["new", "confirmed"]:
            # app.time может быть time-объектом или строкой — подстрахуемся
            app_time = app.time
            if isinstance(app_time, str):
                try:
                    app_time = datetime.strptime(app_time, "%H:%M").time()
                except ValueError:
                    app_time = None

            if app_time is not None:
                app_datetime = timezone.make_aware(datetime.combine(app.date, app_time))
                # отмена возможна, если до записи больше 2 часов
                app.can_cancel = (now + timedelta(hours=2) < app_datetime)

    return render(
        request,
        "core/cabinet_dashboard.html",
        {
            "appointments": appointments,
            "today": today,
            "tomorrow": tomorrow,
            "tab": tab,
        },
    )

def cabinet_profile(request):
    if not request.user.is_authenticated:
        return redirect("cabinet_login")

    try:
        client = request.user.client
    except:
        messages.error(request, "Ошибка профиля.")
        return redirect("cabinet_login")

    if request.method == "POST":
        form = ClientProfileForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Профиль обновлён ✅")
            return redirect("cabinet_profile")
        else:
            messages.error(request, "Проверьте поля формы.")
    else:
        form = ClientProfileForm(user=request.user)

    return render(request, "core/cabinet_profile.html", {
        "form": form,
        "client": client,
    })


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

  # --- Telegram: отмена из кабинета ---
    time_text = appointment.time.strftime("%H:%M") if hasattr(appointment.time, "strftime") else str(appointment.time)

    services_list = []
    total_price = 0
    total_duration = 0

    for s in appointment.service.all():
        services_list.append(f"• {s.name} — {s.price} ₸ ({s.duration} мин)")
        total_price += int(s.price)
        total_duration += int(s.duration)

    services_text = "\n".join(services_list) if services_list else "—"

    who = request.user.first_name or request.user.username

    send_telegram(
        "❌ <b>Отмена записи</b>\n"
        f"👤 Кто отменил: <b>{who}</b>\n"
        f"✂️ Мастер: <b>{appointment.master.full_name}</b>\n"
        f"📅 Дата: <b>{appointment.date}</b>\n"
        f"🕒 Время: <b>{time_text}</b>\n"
        f"👤 Клиент: <b>{appointment.client_name}</b>\n"
        f"📞 Тел: <b>{appointment.client_phone}</b>\n"
        "\n"
        "🧾 <b>Услуги:</b>\n"
        f"{services_text}\n"
        "\n"
        f"⏱ <b>Длительность:</b> {total_duration} мин\n"
        f"💰 <b>Сумма:</b> {total_price} ₸"
    )



    messages.success(request, "Запись успешно отменена.")
    return redirect("cabinet_dashboard")


def cabinet_logout(request):
    logout(request)
    messages.info(request, "Вы вышли из личного кабинета.")
    return redirect("cabinet_login")


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

    return redirect("cabinet_login")


def master_logout(request):
    auth_logout(request)
    return redirect("cabinet_login")


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

    return redirect("master_dashboard")


@login_required
def master_dashboard(request):
    # доступ только мастеру
    if not hasattr(request.user, "master_profile") or not request.user.master_profile:
        messages.error(request, "Доступ запрещён.")
        return redirect("cabinet_logout")

    master = request.user.master_profile

    # GET-параметры
    filter_type = request.GET.get("filter", "all")    # today / tomorrow / all
    status_filter = request.GET.get("status", "all")  # new / confirmed / all
    show_completed = request.GET.get("show_completed") == "1"

    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)

    # основной queryset
    appointments = (
        Appointment.objects
        .filter(master=master)
        .prefetch_related("service")  # важно для total_price()
    )

    # по умолчанию скрываем завершённые/отменённые/не пришёл
    if not show_completed:
        appointments = appointments.exclude(status__in=["completed", "no_show", "cancelled"])

    # фильтр по дате
    if filter_type == "today":
        appointments = appointments.filter(date=today)
    elif filter_type == "tomorrow":
        appointments = appointments.filter(date=tomorrow)

    # фильтр по статусу
    if status_filter in ["new", "confirmed"]:
        appointments = appointments.filter(status=status_filter)

    # сортировка: ближайшее сверху
    if filter_type in ["today", "tomorrow"]:
        appointments = appointments.order_by("time")
    else:
        appointments = appointments.order_by("date", "time")

    # ---- статистика ----
    appointments_today = (
        Appointment.objects
        .filter(master=master, date=today)
        .exclude(status="cancelled")
        .prefetch_related("service")
    )

    today_count = appointments_today.count()
    total_today = sum(app.total_price() for app in appointments_today)

    new_count = Appointment.objects.filter(master=master, status="new").count()

    context = {
        "master": master,
        "appointments": appointments,
        "today": today,
        "tomorrow": tomorrow,
        "show_completed": show_completed,

        # для нового шаблона
        "stats": {
            "today_count": today_count,
            "today_revenue": int(total_today),
            "new_count": new_count,
        },

        # оставляю твои старые переменные на всякий
        "appointments_today": appointments_today,
        "total_today": int(total_today),
        "appointments_new": Appointment.objects.filter(master=master, date=today, status="new"),
    }

    return render(request, "core/master_dashboard.html", context)

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


def offer_view(request):
    return render(request, "core/offer.html")


def offer_pdf(request):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="offer_blademaster.pdf"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    # ✅ ТВОЙ ШРИФТ: core/static/fonts/Arial.ttf
    # settings.BASE_DIR обычно указывает на корень проекта, где лежит папка core/
    font_path = os.path.join(settings.BASE_DIR, "core", "static", "fonts", "Arial.ttf")

    try:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont("ArialCustom", font_path))
            p.setFont("ArialCustom", 12)
        else:
            # fallback на случай если путь неправильный
            p.setFont("Helvetica", 12)
    except Exception:
        p.setFont("Helvetica", 12)

    y = height - 25 * mm
    line_h = 7 * mm

    lines = [
        "Публичная оферта BladeMaster",
        "",
        "1. Общие положения",
        "1.1. Настоящая оферта определяет условия оказания услуг барбершопа «BladeMaster».",
        "1.2. Оформляя запись, клиент подтверждает согласие с условиями оферты.",
        "",
        "2. Предмет оферты",
        "2.1. Исполнитель оказывает услуги барбершопа согласно выбранным услугам и времени записи.",
        "",
        "3. Порядок записи и отмены",
        "3.1. Запись осуществляется через сайт.",
        "3.2. Отмена записи возможна не позднее чем за 2 часа до времени визита.",
        "",
        "4. Стоимость и оплата",
        "4.1. Стоимость услуг определяется прайс-листом на сайте.",
        "4.2. Предоплата (если выбрана) рассчитывается автоматически.",
        "",
        "5. Прочие условия",
        "5.1. Исполнитель вправе изменять оферту, размещая актуальную версию на сайте.",
    ]

    for line in lines:
        if y < 20 * mm:
            p.showPage()
            y = height - 25 * mm
            try:
                if os.path.exists(font_path):
                    p.setFont("ArialCustom", 12)
                else:
                    p.setFont("Helvetica", 12)
            except Exception:
                p.setFont("Helvetica", 12)

        p.drawString(20 * mm, y, line)
        y -= line_h

    p.showPage()
    p.save()
    return response

@staff_member_required
def admin_reports(request):
    """
    Отчёты:
    A) Плановая нагрузка: всё кроме cancelled
    B) Факт выполнено: только completed
    """

    today = timezone.localdate()
    default_from = today - timedelta(days=30)
    default_to = today

    date_from_str = request.GET.get("from")
    date_to_str = request.GET.get("to")

    try:
        date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date() if date_from_str else default_from
    except ValueError:
        date_from = default_from

    try:
        date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date() if date_to_str else default_to
    except ValueError:
        date_to = default_to

    qs_all = Appointment.objects.filter(date__gte=date_from, date__lte=date_to)

    # A) План: всё кроме отменённых
    qs_plan = qs_all.exclude(status="cancelled")

    # B) Факт: только выполненные
    qs_fact = qs_all.filter(status="completed")

    def calc_master_stats(qs):
        stats = []
        masters = Master.objects.all()
        for m in masters:
            m_apps = qs.filter(master=m)
            total_minutes = 0
            for app in m_apps.prefetch_related("service"):
                total_minutes += sum(s.duration for s in app.service.all())
            stats.append({
                "master": m,
                "appointments_count": m_apps.count(),
                "total_minutes": total_minutes,
                "total_hours": round(total_minutes / 60, 1),
            })
        stats.sort(key=lambda x: x["total_minutes"], reverse=True)
        return stats

    # ТОП УСЛУГ (ПЛАН)
    top_services_plan = (
        Service.objects.filter(appointment__in=qs_plan)
        .annotate(bookings_count=Count("appointment", distinct=True))
        .annotate(
            estimated_revenue=ExpressionWrapper(
                F("price") * F("bookings_count"),
                output_field=IntegerField()
            )
        )
        .order_by("-bookings_count")[:10]
    )

    # ТОП УСЛУГ (ФАКТ)
    top_services_fact = (
        Service.objects.filter(appointment__in=qs_fact)
        .annotate(bookings_count=Count("appointment", distinct=True))
        .annotate(
            estimated_revenue=ExpressionWrapper(
                F("price") * F("bookings_count"),
                output_field=IntegerField()
            )
        )
        .order_by("-bookings_count")[:10]
    )

    # ЗАГРУЗКА МАСТЕРОВ
    master_stats_plan = calc_master_stats(qs_plan)
    master_stats_fact = calc_master_stats(qs_fact)

    # СТАТЫ по статусам
    counts = {
        "new": qs_all.filter(status="new").count(),
        "confirmed": qs_all.filter(status="confirmed").count(),
        "completed": qs_all.filter(status="completed").count(),
        "no_show": qs_all.filter(status="no_show").count(),
        "cancelled": qs_all.filter(status="cancelled").count(),
    }

    total_plan = qs_plan.count()
    total_fact = qs_fact.count()

    # ПРЕДОПЛАТЫ (реальные)
    total_prepayment_plan = qs_plan.aggregate(total=Sum("prepayment_amount"))["total"] or Decimal("0.00")
    total_prepayment_fact = qs_fact.aggregate(total=Sum("prepayment_amount"))["total"] or Decimal("0.00")
    prepay_count_plan = qs_plan.filter(prepayment_amount__gt=0).count()
    prepay_count_fact = qs_fact.filter(prepayment_amount__gt=0).count()

    context = {
        "date_from": date_from,
        "date_to": date_to,

        "counts": counts,
        "total_plan": total_plan,
        "total_fact": total_fact,

        "total_prepayment_plan": total_prepayment_plan,
        "total_prepayment_fact": total_prepayment_fact,

        "top_services_plan": top_services_plan,
        "top_services_fact": top_services_fact,

        "master_stats_plan": master_stats_plan,
        "master_stats_fact": master_stats_fact,

        "prepay_count_plan": prepay_count_plan,
        "prepay_count_fact": prepay_count_fact,
    }

    return render(request, "core/admin_reports.html", context)
