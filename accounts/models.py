import hashlib
from django.db import models


class User(models.Model):
    ROLE_CHOICES = [
        ('store_officer', 'Store Officer'),
        ('production_officer', 'Production Officer'),
        ('sales_manager', 'Sales Manager'),
        ('manager', 'General Manager'),
        ('md', 'Managing Director'),
    ]



    STORE_TYPE_CHOICES = [
        ('raw', 'Raw Material Store'),
        ('finished', 'Finished Goods Store'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('dismissed', 'Dismissed'),
    ]

    SALES_USER_TYPE_CHOICES = [
        ('promoter', 'Sales Promoter'),
        ('driver', 'Company Driver'),
    ]

    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=200)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)

    store_type = models.CharField(
        max_length=10, choices=STORE_TYPE_CHOICES,
        blank=True, null=True,
        help_text='Only for store_officer role: raw or finished goods store'
    )
    sales_user_type = models.CharField(
        max_length=10, choices=SALES_USER_TYPE_CHOICES,
        blank=True, null=True,
        help_text='Only for sales_user role: promoter or driver'
    )
    password_hash = models.CharField(max_length=128)
    plain_password = models.CharField(max_length=128, blank=True, null=True, help_text='Visible password for administrative reference')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'accounts_user'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"

    def set_password(self, raw_password):
        self.password_hash = hashlib.sha256(raw_password.encode()).hexdigest()

    def check_password(self, raw_password):
        return self.password_hash == hashlib.sha256(raw_password.encode()).hexdigest()

    def get_role_display_short(self):
        return dict(self.ROLE_CHOICES).get(self.role, self.role)

    # ── Login control ─────────────────────────────────────────────
    @property
    def can_login(self):
        """Sales promoters and drivers are entities, not system users."""
        if self.role == 'sales_user' and self.sales_user_type in ('promoter', 'driver'):
            return False
        return True

    # ── Basic status ──────────────────────────────────────────────
    @property
    def is_active(self):
        return self.status == 'active'

    # ── Role shortcuts ────────────────────────────────────────────
    @property
    def is_md(self):
        return self.role == 'md'

    @property
    def is_general_manager(self):
        """The `manager` role is the General Manager / Operations Manager."""
        return self.role == 'manager'

    @property
    def is_manager_or_above(self):
        return self.role in ('manager', 'md')

    @property
    def is_sales_manager(self):
        return self.role == 'sales_manager'

    @property
    def is_store_officer(self):
        return self.role == 'store_officer'

    @property
    def is_raw_store_officer(self):
        return self.role == 'store_officer' and self.store_type == 'raw'

    @property
    def is_fg_store_officer(self):
        return self.role == 'store_officer' and self.store_type == 'finished'

    @property
    def is_production_officer(self):
        return self.role == 'production_officer'

    @property
    def is_sales_user(self):
        return self.role == 'sales_user'
