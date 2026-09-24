from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import json

from inventory.models import (
    SystemSettings, Branch, Category, Product, BranchStock, Customer,
    Sale, SaleItem, PaymentSplit, DebtRepayment, AuditLog
)


class MatteoWilliamsSystemTest(TestCase):
    def setUp(self):
        self.client = Client()
        
        # 1. System Settings
        self.settings = SystemSettings.get_settings()
        self.settings.general_password = "Matteo2025"
        self.settings.owner_pin = "0000"
        self.settings.owner_password = "Owner@Matteo2025"
        self.settings.save()

        # 2. Branch
        self.branch = Branch.objects.create(
            name="Main Market Hub",
            code="MW-MM01",
            location="Line 4 Sokoto Road, Onitsha",
            cashier_pin="1111",
            manager_pin="9911"
        )

        # 3. Category & Product
        self.category = Category.objects.create(name="Smart TVs", icon_name="tv")
        self.product = Product.objects.create(
            category=self.category,
            name="Samsung 55 UHD 4K Smart TV",
            sku="SAM-55-4K",
            cost_price=Decimal("400000.00"),
            selling_price=Decimal("500000.00"),
            min_selling_price=Decimal("480000.00"),
            unit="pcs"
        )
        self.stock = BranchStock.objects.create(
            branch=self.branch,
            product=self.product,
            quantity=10,
            reorder_level=3
        )

        # 4. Customer
        self.customer = Customer.objects.create(
            name="Chief Emeka Okonkwo",
            phone="08034567890",
            address="Line 2 Shop 18, Onitsha"
        )

    def test_step_1_general_gateway_login(self):
        """Test Step 1: Gateway password authentication."""
        # Wrong password
        res = self.client.post('/login/', {'general_password': 'wrongpassword'})
        self.assertFalse(self.client.session.get('general_unlocked', False))
        
        # Correct password
        res = self.client.post('/login/', {'general_password': 'Matteo2025'})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(self.client.session.get('general_unlocked', True))

    def test_step_2_branch_rate_limiting_and_lockout(self):
        """Test 3 wrong PIN attempts lock out for 24 hours."""
        session = self.client.session
        session['general_unlocked'] = True
        session.save()

        # 1st wrong attempt
        self.client.post(f'/branch/{self.branch.id}/login/', {'operator_name': 'Tester', 'pin': '0000'})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.failed_pin_attempts, 1)
        self.assertFalse(self.branch.is_locked)

        # 2nd wrong attempt
        self.client.post(f'/branch/{self.branch.id}/login/', {'operator_name': 'Tester', 'pin': '0000'})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.failed_pin_attempts, 2)
        self.assertFalse(self.branch.is_locked)

        # 3rd wrong attempt -> MUST LOCK FOR 24 HOURS
        self.client.post(f'/branch/{self.branch.id}/login/', {'operator_name': 'Tester', 'pin': '0000'})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.failed_pin_attempts, 3)
        self.assertTrue(self.branch.is_locked)
        self.assertIsNotNone(self.branch.locked_until)
        self.assertTrue(self.branch.is_currently_locked())

        # Unlock via Manager PIN
        res_unlock = self.client.post(f'/branch/{self.branch.id}/unlock/', {'override_key': '9911'})
        self.branch.refresh_from_db()
        self.assertFalse(self.branch.is_locked)
        self.assertEqual(self.branch.failed_pin_attempts, 0)

    def test_pos_split_payment_and_debt_tracking(self):
        """Test sale with split payment: Cash + Transfer + Debt."""
        session = self.client.session
        session['general_unlocked'] = True
        session['user_role'] = 'CASHIER'
        session['branch_id'] = self.branch.id
        session['actor_name'] = 'Chuka (Cashier)'
        session.save()

        # Item cost: ₦500,000.
        # Split: ₦200,000 Cash, ₦150,000 Transfer, ₦150,000 Debt.
        cart_data = [
            {'product_id': self.product.id, 'price': 500000.00, 'quantity': 1}
        ]

        post_data = {
            'cart_json': json.dumps(cart_data),
            'split_cash': '200000.00',
            'split_transfer': '150000.00',
            'transfer_ref': 'Opay #98234',
            'split_pos': '0.00',
            'split_debt': '150000.00',
            'debt_due_date': '2026-10-15',
            'customer_id': str(self.customer.id),
            'customer_name_manual': self.customer.name,
            'customer_phone_manual': self.customer.phone,
        }

        res = self.client.post('/pos/process/', post_data)
        self.assertEqual(res.status_code, 302)

        # Verify sale in database
        sale = Sale.objects.latest('id')
        self.assertEqual(sale.total_amount, Decimal('500000.00'))
        self.assertEqual(sale.amount_paid, Decimal('350000.00'))
        self.assertEqual(sale.balance_owed, Decimal('150000.00'))
        self.assertEqual(sale.payment_status, 'PARTIAL_DEBT')

        # Stock decremented from 10 to 9
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 9)

        # Splits created
        splits = sale.splits.all()
        self.assertEqual(splits.count(), 3)

        # Now test recording debt repayment against this sale!
        repay_res = self.client.post(f'/debtors/{sale.id}/repay/', {
            'repay_amount': '100000.00',
            'payment_method': 'CASH',
            'reference_note': 'Customer brought cash to Onitsha shop'
        })
        self.assertEqual(repay_res.status_code, 302)

        # Verify sale updated in real time
        sale.refresh_from_db()
        self.assertEqual(sale.amount_paid, Decimal('450000.00'))
        self.assertEqual(sale.balance_owed, Decimal('50000.00'))
        self.assertEqual(sale.payment_status, 'PARTIAL_DEBT')

        # Pay remaining ₦50,000
        self.client.post(f'/debtors/{sale.id}/repay/', {
            'repay_amount': '50000.00',
            'payment_method': 'TRANSFER',
            'reference_note': 'Final settlement transfer'
        })
        sale.refresh_from_db()
        self.assertEqual(sale.balance_owed, Decimal('0.00'))
        self.assertEqual(sale.payment_status, 'PAID_FULL')

    def test_owner_branch_creation(self):
        """Test Owner creating a 4th branch dynamically."""
        session = self.client.session
        session['general_unlocked'] = True
        session['user_role'] = 'OWNER'
        session.save()

        res = self.client.post('/owner/branches/new/', {
            'name': 'Bridge Head Electronics Hub',
            'code': 'MW-BH04',
            'location': 'Bridge Head Market, Onitsha',
            'phone': '+234 803 999 8888',
            'cashier_pin': '4444',
            'manager_pin': '9944'
        })
        self.assertEqual(res.status_code, 302)

        new_branch = Branch.objects.get(code='MW-BH04')
        self.assertEqual(new_branch.name, 'Bridge Head Electronics Hub')
        self.assertEqual(new_branch.cashier_pin, '4444')
        self.assertEqual(new_branch.manager_pin, '9944')
