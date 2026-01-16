from django.contrib import admin
from .models import Service, Master, Appointment, Review
from .models import WorkingHours
from .models import BlockedSlot


@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ("start_time", "end_time")



@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'duration']
    list_filter = ['category']
    search_fields = ['name']


@admin.register(Master)
class MasterAdmin(admin.ModelAdmin):
    list_display = ['full_name']
    search_fields = ['full_name']


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'client_name', 'client_phone', 'master', 'date', 'time', 'status', 'total_price']
    list_filter = ['status', 'date', 'master']
    search_fields = ['client_name', 'client_phone', 'id']
    readonly_fields = ['created_at']
    
    def total_price(self, obj):
        return f"{obj.total_price()} ₸"
    total_price.short_description = "Сумма к оплате"



@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['appointment', 'rating', 'created_at']
    list_filter = ['rating']

@admin.register(BlockedSlot)
class BlockedSlotAdmin(admin.ModelAdmin):
    list_display = ("date", "master", "time_from", "time_to", "reason")
    list_filter = ("date", "master")
    search_fields = ("reason", "master__full_name")
