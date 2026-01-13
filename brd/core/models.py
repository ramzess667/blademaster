from django.db import models
from django.contrib.auth.models import User

class Client(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='client')
    phone = models.CharField("Телефон", max_length=20, unique=True)

    def __str__(self):
        return self.phone

# Услуга
class Service(models.Model):
    name = models.CharField("Название услуги", max_length=100)
    description = models.TextField("Описание услуги", blank=True)
    price = models.DecimalField("Цена (₸)", max_digits=10, decimal_places=0)
    duration = models.IntegerField("Длительность (в минутах)", default=60)
    category = models.CharField("Категория", max_length=50, choices=[
        ('haircut', 'Стрижки'),
        ('beard', 'Бритьё и оформление бороды'),
        ('care', 'Уход'),
        ('complex', 'Комплексные процедуры'),
    ], default='haircut')

    class Meta:
        verbose_name = "Услуга"
        verbose_name_plural = "Услуги"

    def __str__(self):
        return f"{self.name} — {self.price} ₸"


# Мастер
class Master(models.Model):
    full_name = models.CharField("ФИО мастера", max_length=100)
    description = models.TextField("Описание / о себе", blank=True)
    photo = models.ImageField("Фотография мастера", upload_to='masters/', blank=True, null=True)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='master_profile')

    class Meta:
        verbose_name = "Мастер"
        verbose_name_plural = "Мастера"

    def __str__(self):
        return self.full_name
    
    def average_rating(self):
        reviews = self.appointment_set.filter(review__isnull=False).values_list('review__rating', flat=True)
        if reviews:
            from statistics import mean
            return mean(reviews)
        return 0
    
    @property
    def reviews(self):
        return Review.objects.filter(appointment__master=self)
    
    def get_reviews(self):
        return Review.objects.filter(appointment__master=self).order_by('-created_at')

    def average_rating(self):
        reviews = self.get_reviews()
        if reviews.exists():
            return round(sum(r.rating for r in reviews) / reviews.count(), 1)
        return 0.0

    def reviews_count(self):
        return self.get_reviews().count()

# Запись на услугу
class Appointment(models.Model):
    client_name = models.CharField("Имя клиента", max_length=100)
    client_phone = models.CharField("Телефон клиента", max_length=20)
    client_email = models.EmailField("Email клиента", blank=True, null=True)
    
    service = models.ManyToManyField(Service, verbose_name="Выбранные услуги")
    master = models.ForeignKey(Master, on_delete=models.CASCADE, verbose_name="Мастер")
    date = models.DateField("Дата записи")
    time = models.TimeField("Время записи")
    
    status = models.CharField("Статус записи", max_length=20, choices=[
        ('new', 'Новая'),
        ('confirmed', 'Подтверждена'),
        ('completed', 'Выполнена'),
        ('cancelled', 'Отменена'),
        ('no_show', 'Не пришёл'),
    ], default='new')
    
    created_at = models.DateTimeField("Дата и время создания записи", auto_now_add=True)
    
    prepayment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Сумма предоплаты")
    prepayment_paid = models.BooleanField(default=False, verbose_name="Предоплата оплачена")
    prepayment_method = models.CharField(max_length=50, blank=True, verbose_name="Способ предоплаты")

    class Meta:
        verbose_name = "Запись"
        verbose_name_plural = "Записи клиентов"

    def total_price(self):
        return sum(service.price for service in self.service.all())

    def __str__(self):
        return f"Запись №{self.id} — {self.client_name} ({self.date} {self.time})"
    

class Review(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE, related_name='review')
    rating = models.IntegerField("Оценка (1-5)", choices=[(1, '1'), (2, '2'), (3, '3'), (4, '4'), (5, '5')])
    comment = models.TextField("Отзыв", blank=True)
    created_at = models.DateTimeField("Дата отзыва", auto_now_add=True)

    class Meta:
        verbose_name = "Отзыв"
        verbose_name_plural = "Отзывы клиентов"

    def __str__(self):
        return f"Отзыв от {self.appointment.client_name} — {self.rating} звезд"