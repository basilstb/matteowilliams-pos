from django.db import models
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import uuid


class SystemSettings(models.Model):
    """General gateway password and overall business settings."""
    business_name = models.CharField(max_length=200, default="Matteo Williams Electronics")
    business_tagline = models.CharField(max_length=300, default="Wholesale & Retail Electronics Hub - Onitsha")
    business_phone = models.CharField(max_length=50, default="+234 803 892 4510")
    business_address = models.CharField(max_length=300, default="Onitsha Commercial Center, Anambra State")
    general_password = models.CharField(max_length=128, default="Matteo2025")
    owner_username = models.CharField(max_length=100, default="owner")
    owner_pin = models.CharField(max_length=32, default="0000")  # Master Owner PIN
    owner_password = models.CharField(max_length=128, default="Owner@Matteo2025")
    
    class Meta:
        verbose_name_plural = "System Settings"

    def __str__(self):
        return self.business_name

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj


class Branch(models.Model):
    """Electronics Branches in Onitsha with individual PINs and rate-limiting."""
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, unique=True)
    location = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True, null=True)
    
    # Secure branch PINs
    cashier_pin = models.CharField(max_length=32, default="1234", help_text="PIN for cashiers of this branch")
    manager_pin = models.CharField(max_length=32, default="7788", help_text="PIN for manager of this branch")
    
    # Rate Limiting & Lockout
    is_active = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False)
    failed_pin_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)
    locked_reason = models.CharField(max_length=255, blank=True, null=True)
    last_unlocked_at = models.DateTimeField(blank=True, null=True)
    last_unlocked_by = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def is_currently_locked(self):
        """Check if branch is locked due to 3 failed attempts, automatically expiring after 24 hrs."""
        if not self.is_locked:
            return False
        if self.locked_until and timezone.now() >= self.locked_until:
            # 24 hours have passed -> auto-unlock
            self.is_locked = False
            self.failed_pin_attempts = 0
            self.locked_until = None
            self.locked_reason = "Lock expired after 24 hours"
            self.save(update_fields=['is_locked', 'failed_pin_attempts', 'locked_until', 'locked_reason'])
            return False
        return True

    def record_failed_attempt(self):
        """Record a wrong PIN attempt; lockout for 24h on 3rd failure."""
        self.failed_pin_attempts += 1
        if self.failed_pin_attempts >= 3:
            self.is_locked = True
            self.locked_until = timezone.now() + timedelta(hours=24)
            self.locked_reason = "3 consecutive invalid PIN attempts. Locked for 24 hours."
            self.save(update_fields=['failed_pin_attempts', 'is_locked', 'locked_until', 'locked_reason'])
            return True  # just got locked
        self.save(update_fields=['failed_pin_attempts'])
        return False

    def unlock(self, unlocked_by="Owner"):
        """Unlock branch immediately by Owner or Branch Manager."""
        self.is_locked = False
        self.failed_pin_attempts = 0
        self.locked_until = None
        self.locked_reason = f"Manually unlocked by {unlocked_by}"
        self.last_unlocked_at = timezone.now()
        self.last_unlocked_by = unlocked_by
        self.save(update_fields=['is_locked', 'failed_pin_attempts', 'locked_until', 'locked_reason', 'last_unlocked_at', 'last_unlocked_by'])


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    icon_name = models.CharField(max_length=50, default="tv", help_text="Lucide icon name")

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True, null=True)
    sku = models.CharField(max_length=50, unique=True)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Naira - Hidden from Cashiers")
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Naira - Standard Selling Price")
    min_selling_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Floor price - Requires manager permission below this")
    unit = models.CharField(max_length=30, default="pcs")
    warranty_info = models.CharField(max_length=100, default="1 Year Manufacturer Warranty")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} [{self.sku}]"

    def get_stock_for_branch(self, branch):
        stock = self.branch_stocks.filter(branch=branch).first()
        return stock.quantity if stock else 0


class BranchStock(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='stocks')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='branch_stocks')
    quantity = models.IntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=5)
    last_restocked = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'product')
        ordering = ['product__name']

    def __str__(self):
        return f"{self.branch.name} - {self.product.name}: {self.quantity} {self.product.unit}"


class Customer(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=50, db_index=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    business_name = models.CharField(max_length=150, blank=True, null=True, help_text="e.g. Shop at Onitsha")
    guarantor_name = models.CharField(max_length=150, blank=True, null=True)
    guarantor_phone = models.CharField(max_length=50, blank=True, null=True)
    total_credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('500000.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def total_outstanding_debt(self):
        unpaid_sales = self.sales.filter(balance_owed__gt=Decimal('0.00'))
        return sum(s.balance_owed for s in unpaid_sales) or Decimal('0.00')


class Sale(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('PAID_FULL', 'Paid in Full'),
        ('PARTIAL_DEBT', 'Split / Partial Debt'),
        ('FULL_DEBT', '100% Credit / Total Debt'),
    ]

    invoice_number = models.CharField(max_length=60, unique=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='sales')
    cashier_name = models.CharField(max_length=100)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    customer_name_snapshot = models.CharField(max_length=150, blank=True, null=True)
    customer_phone_snapshot = models.CharField(max_length=50, blank=True, null=True)
    
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    balance_owed = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PAID_FULL')
    debt_due_date = models.DateField(blank=True, null=True, help_text="Promised debt repayment date")
    
    is_manager_approved = models.BooleanField(default=True)
    approved_by = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    
    # Exact timestamping
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.invoice_number} - {self.branch.code} - ₦{self.total_amount:,.2f}"

    def update_debt_status(self):
        """Recalculate balance owed and status after repayments."""
        if self.balance_owed <= Decimal('0.00'):
            self.balance_owed = Decimal('0.00')
            self.payment_status = 'PAID_FULL'
        elif self.amount_paid > Decimal('0.00'):
            self.payment_status = 'PARTIAL_DEBT'
        else:
            self.payment_status = 'FULL_DEBT'
        self.save(update_fields=['balance_owed', 'amount_paid', 'payment_status', 'updated_at'])


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='sale_items')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)

    def __str__(self):
        return f"{self.quantity}x {self.product.name} @ ₦{self.unit_price:,.2f}"


class PaymentSplit(models.Model):
    METHOD_CHOICES = [
        ('CASH', 'Cash Payment'),
        ('TRANSFER', 'Bank Transfer'),
        ('POS', 'POS / Card'),
        ('DEBT', 'Credit / Debt Owed'),
    ]

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='splits')
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference_note = models.CharField(max_length=255, blank=True, null=True, help_text="e.g. OPay transfer ref, Moniepoint terminal slip")
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.get_method_display()}: ₦{self.amount:,.2f} ({self.sale.invoice_number})"


class DebtRepayment(models.Model):
    """Record payment towards a specific debt sale."""
    METHOD_CHOICES = [
        ('CASH', 'Cash Payment'),
        ('TRANSFER', 'Bank Transfer'),
        ('POS', 'POS / Card'),
    ]

    receipt_number = models.CharField(max_length=60, unique=True)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='debt_repayments')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='repayments')
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='CASH')
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    received_by = models.CharField(max_length=100)
    received_by_role = models.CharField(max_length=50, default="Cashier")
    reference_note = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.receipt_number} - Paid ₦{self.amount_paid:,.2f} on {self.sale.invoice_number}"


class AuditLog(models.Model):
    """Immutable audit trail with exact timestamps for all operations."""
    ROLE_CHOICES = [
        ('OWNER', 'Owner'),
        ('MANAGER', 'Manager'),
        ('CASHIER', 'Cashier'),
        ('GATEWAY', 'General Gateway'),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    user_role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    actor_name = models.CharField(max_length=100)
    action_type = models.CharField(max_length=80)
    details = models.TextField()
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {self.user_role} - {self.action_type}"


class Expense(models.Model):
    """Records business expenses and damaged/written-off goods per branch."""
    TYPE_CHOICES = [
        ('DAMAGED_GOODS', 'Damaged / Written-Off Goods'),
        ('OPERATIONAL',   'Operational Expense'),
        ('LOGISTICS',     'Logistics & Delivery'),
        ('UTILITY',       'Utility Bill (Light / Water)'),
        ('STAFF',         'Staff Welfare / Wages'),
        ('MAINTENANCE',   'Equipment Maintenance'),
        ('OTHER',         'Other Expense'),
    ]

    reference = models.CharField(max_length=60, unique=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='expenses')
    expense_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='OPERATIONAL')
    title = models.CharField(max_length=200, help_text="Short description e.g. 'Samsung TV screen cracked during transit'")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # For damaged goods — optionally link a product
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='expense_records', help_text="Link product if it's a damaged goods write-off")
    quantity_damaged = models.PositiveIntegerField(default=0, help_text="Qty written off from stock (0 for non-goods expenses)")
    notes = models.TextField(blank=True, null=True)
    recorded_by = models.CharField(max_length=100)
    recorded_by_role = models.CharField(max_length=30, default='MANAGER')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} | {self.get_expense_type_display()} | ₦{self.amount:,.2f}"

