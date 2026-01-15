from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('services/', views.services, name='services'),
    path('masters/', views.masters, name='masters'),
    path('book/<int:service_id>/', views.book_step1_master, name='book_service'),  # Выбор мастера
    path('book/<int:service_id>/<int:master_id>/', views.book_step2_datetime, name='book_datetime'),  # Выбор даты/времени
    path('book/confirm/', views.book_confirm, name='book_confirm'),  # Подтверждение и сохранение
    path('appointment/<int:appointment_id>/success/', views.book_success, name='book_success'),
    path('appointment/<int:appointment_id>/cancel/', views.cancel_appointment, name='cancel_appointment'),
    path('book/select-master/', views.book_select_master, name='book_select_master'),
    path('book/datetime/', views.book_datetime_multi, name='book_datetime_multi'),
    path('get-free-slots/<int:master_id>/<str:date_str>/', views.get_free_slots, name='get_free_slots'),
    path('appointment/<int:appointment_id>/invoice-pdf/', views.generate_invoice_pdf, name='generate_invoice_pdf'),
    path('appointment/<int:appointment_id>/act-pdf/', views.generate_act_pdf, name='generate_act_pdf'),  
    path('appointment/<int:appointment_id>/add-review/', views.add_review, name='add_review'),
    path('cabinet/', views.cabinet_login, name='cabinet_login'),
    path('cabinet/dashboard/', views.cabinet_dashboard, name='cabinet_dashboard'),
    path('cabinet/cancel/<int:appointment_id>/', views.cabinet_cancel_appointment, name='cabinet_cancel'),
    path('cabinet/logout/', views.cabinet_logout, name='cabinet_logout'),
    path('master/login/', views.master_login, name='master_login'),
    path('master/dashboard/', views.master_dashboard, name='master_dashboard'),
    path('master/change-status/<int:appointment_id>/<str:new_status>/', views.master_change_status, name='master_change_status'),
    path('master/logout/', views.master_logout, name='master_logout'),
    path("offer/", views.offer_view, name="offer"),
    path("offer/pdf/", views.offer_pdf, name="offer_pdf"),
    path("reports/", views.admin_reports, name="admin_reports"),


]